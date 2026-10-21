"""The capture's begin (core/tasks.py, LIFECYCLE §5.4): the bundle id renders from the class's naming template and the
UTC second; an id taken in this second waits once, under a second, for the next second instead of refusing."""

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest import mock

from ingat.core import tasks
from ingat.core.steps import Op
from ingat.model import records
from ingat.model.errors import Refused
from ingat.store import fs
from ingat.store.state import Layout

NAMING = "{bundle.stamp}-{class}"
BEGIN = {"phase": "begin", "class": "manual", "naming": NAMING, "payload": None, "stage_owner": None}


class BeginTest(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.lay = Layout(f"{d.name}/root", f"{d.name}/backups")
        op_dir = self.lay.op_dir("i", 1, "backup")
        os.makedirs(op_dir)
        plan, unused = SimpleNamespace(inputs={"variants": {}}), None  # the begin reads no daemon and no journal
        self.op = Op(self.lay, unused, unused, plan, "i", 1, op_dir, unused, op_dir)  # type: ignore[arg-type]
        self.t0 = records.utc_now()
        self.t1 = self.t0 + records.SECOND
        self.sleep = mock.patch.object(tasks.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)

    def begin(self, naming: str = NAMING) -> dict[str, Any]:
        """The begin step with a clock that reads t0 first and t1 after a wait."""
        step: Any = SimpleNamespace(args=BEGIN | {"naming": naming})
        with mock.patch.object(records, "utc_now", side_effect=[self.t0, self.t1]):
            return tasks.capture(self.op, step, None)  # type: ignore[arg-type]

    def take(self, kind: str, at: datetime | None = None, bid: str = "") -> str:
        """A catalogued, sealed or half-made bundle named `bid`, or the default name for the second `at`."""
        path: str = getattr(self.lay, kind)("i", bid or f"{records.stamp(at or self.t0)}-manual")
        if kind == "catalog":
            fs.write_once(path, b"{}")
        else:
            os.makedirs(path)
        return path

    def assert_begun(self, ev: dict[str, Any], at: datetime) -> None:
        bid = f"{records.stamp(at)}-manual"
        self.assertEqual((ev["bundle_id"], ev["created_at"]), (bid, records.iso(at)))
        self.assertEqual(ev["values"], {"bundle.id": bid, "bundle.stamp": records.stamp(at)})
        self.assertTrue(os.path.isdir(self.op.path("stage")))

    def test_a_free_id_is_used_at_once(self) -> None:
        self.assert_begun(self.begin(), self.t0)
        self.sleep.assert_not_called()

    def test_an_id_taken_in_this_second_waits_once_for_the_next(self) -> None:
        for kind in ("catalog", "bundle_dir", "incoming_dir"):
            with self.subTest(kind):
                self.sleep.reset_mock()
                taken = self.take(kind)
                self.assert_begun(self.begin(), self.t1)
                self.assertEqual(self.sleep.call_count, 1)
                left = self.sleep.call_args.args[0]
                self.assertTrue(0 <= left <= 1, left)  # until t1 starts: never longer than a second
                self.assertTrue(os.path.exists(taken))  # an existing bundle is never touched
                shutil.rmtree(self.op.path("stage"))
                if kind == "catalog":
                    os.remove(taken)
                else:
                    os.rmdir(taken)

    def test_an_id_that_does_not_change_with_the_second_refuses_without_waiting(self) -> None:
        self.take("catalog", bid="nightly-manual")
        with self.assertRaises(Refused) as cm:
            self.begin("nightly-{class}")
        self.assertEqual(cm.exception.code, "bundle-exists")
        self.sleep.assert_not_called()
        self.assertFalse(os.path.exists(self.op.path("stage")))

    def test_an_id_taken_in_the_next_second_too_refuses_after_one_wait(self) -> None:
        self.take("catalog")
        self.take("catalog", self.t1)
        with self.assertRaises(Refused) as cm:
            self.begin()
        self.assertEqual((cm.exception.code, self.sleep.call_count), ("bundle-exists", 1))
        self.assertIn("never overwritten", cm.exception.message)
        self.assertFalse(os.path.exists(self.op.path("stage")))


if __name__ == "__main__":
    unittest.main()
