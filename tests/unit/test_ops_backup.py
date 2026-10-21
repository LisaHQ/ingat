"""Retention input of ops/backup.py (LIFECYCLE §5.6): catalogued bundles minus tombstones, verification levels from
the JSON Lines records (newest per level, bound to the bundle hash), pins from deployments and open operations; plus
the plan-time bundle id check, the drill's memory reading and the usage refusals."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.model.instance import Backups
from ingat.ops import backup
from ingat.store import fs, state
from ingat.store.state import Layout

H = {b: (b * 64)[:64] for b in "abcdef"}  # bundle id -> a fake bundle hash


def at(day: int, hour: int = 1) -> str:
    return f"2026-10-{day:02d}T{hour:02d}:00:00Z"


class RetentionInputTest(unittest.TestCase):
    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.lay = Layout(f"{d.name}/root", f"{d.name}/backups")

    def catalog(self, bid: str, created: str, klass: str = "scheduled") -> None:
        doc = {"bundle_id": bid, "bundle_hash": H[bid], "class": klass, "size": 10, "created_at": created}
        state.write_doc_once(self.lay.catalog("i", bid), records.new_doc("catalog", **doc, path="/x", imported=False))

    def verification(self, bid: str, level: str, ok: bool, digest: str | None = None) -> None:
        doc = {"bundle_id": bid, "bundle_hash": digest or H[bid], "level": level, "ok": ok, "op": 1, "at": "t"}
        fs.append_line(self.lay.verification("i", bid), records.dumps(records.new_doc("verification", **doc)))

    def deployment(self, seq: int, bundle: str | None) -> None:
        doc = records.new_doc("deployment", seq=seq, pre_change_bundle=bundle)
        state.write_doc_once(self.lay.deployment_json("i", seq), doc)

    def test_catalogued_leaves_out_tombstoned_bundles(self) -> None:
        for bid, day in (("a", 1), ("b", 2), ("c", 3)):
            self.catalog(bid, at(day))
        tomb = records.new_doc("tombstone", bundle_id="b", op=4, at=at(4))
        state.write_doc_once(self.lay.catalog("i", "b.pruned"), tomb)
        self.assertEqual(sorted(backup.catalogued(self.lay, "i")), ["a", "c"])
        self.assertEqual(backup.catalogued(self.lay, "other"), {})

    def test_levels_newest_record_per_level_bound_to_the_hash(self) -> None:
        self.verification("a", "verified", False)
        self.verification("a", "verified", True)  # a later pass wins
        self.verification("a", "restore-tested", True)
        self.verification("a", "restore-tested", False)  # a later failure wins
        self.verification("a", "verified", False, digest="f" * 64)  # another hash: never this bundle's evidence
        with open(self.lay.verification("i", "a"), "ab") as f:  # a torn last line was never written
            f.write(b'{"level": "verified", "ok": fal')
        self.assertEqual(backup.levels(self.lay, "i", "a", H["a"]), {"verified": True, "restore-tested": False})
        self.assertEqual(backup.levels(self.lay, "i", "b", H["b"]), {})

    def test_bundle_infos_pins_paired_and_referenced_bundles(self) -> None:
        for bid, day, klass in (("a", 1, "pre-change"), ("b", 2, "pre-change"), ("c", 3, "manual"), ("d", 4, "x")):
            self.catalog(bid, at(day), klass)
        self.verification("a", "verified", True)
        self.verification("c", "verified", True)
        self.verification("c", "restore-tested", True)
        self.deployment(2, "a")
        self.deployment(3, "b")
        record = {"current_deployment": 3, "previous_deployment": 2}
        cat = backup.catalogued(self.lay, "i")
        infos = {b.id: b for b in backup.bundle_infos(self.lay, "i", record, cat, {"d"})}
        self.assertEqual(sorted(infos), ["a", "b", "c", "d"])
        self.assertEqual({b for b, x in infos.items() if x.pinned}, {"a", "b", "d"})
        self.assertEqual({b for b, x in infos.items() if x.verified}, {"a", "c"})
        self.assertEqual({b for b, x in infos.items() if x.restore_tested}, {"c"})
        self.assertEqual((infos["c"].klass, infos["c"].created_at), ("manual", datetime.fromisoformat(at(3))))
        self.assertFalse(backup.bundle_infos(self.lay, "i", {"current_deployment": None}, cat, set())[0].pinned)

    def test_referenced_reads_open_operations_only(self) -> None:
        open_dir, closed = self.lay.op_dir("i", 5, "drill"), self.lay.op_dir("i", 4, "verify")
        steps = [{"type": "VerifyBundle", "args": {"bundle": "b"}}, {"type": "Record", "args": {"kind": "x"}}]
        plan = records.new_doc("plan", fingerprint={"bundles": {"a": H["a"]}}, steps=steps)
        state.write_doc_once(f"{open_dir}/plan.json", plan)
        for rec in ({"step": 1, "phase": "intent"}, {"step": 1, "phase": "done", "evidence": {"bundle_id": "c"}}):
            fs.append_line(f"{open_dir}/steps.jsonl", records.dumps({"seq": 5, "at": "t", **rec}))
        state.write_doc_once(
            f"{closed}/plan.json", records.new_doc("plan", fingerprint={"bundles": {"d": "x"}}, steps=[])
        )
        state.write_doc_once(f"{closed}/result.json", records.new_doc("result", outcome="completed"))
        self.assertEqual(backup.referenced(self.lay, "i"), {"a", "b", "c"})

    def test_retention_keeps_the_rules_and_deletes_the_rest(self) -> None:
        for bid, day in (("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)):
            self.catalog(bid, at(day), "pre-change" if bid == "b" else "scheduled")
            if bid != "c":
                self.verification(bid, "verified", True)
        self.deployment(1, "b")
        ctx = SimpleNamespace(layout=self.lay, now=datetime.fromisoformat(at(6)))
        inst = SimpleNamespace(backups=Backups(keep_daily=1, keep_weekly=0, keep_monthly=0, pin_pre_change_days=0))
        ld = SimpleNamespace(name="i", record={"current_deployment": 1}, inst=inst)
        keep, delete, cat = backup._retention(ctx, ld)  # type: ignore[arg-type]
        # e: newest (and newest verified, the one daily); b: paired with deployment 1; c: unverified, never deleted
        self.assertEqual((keep, delete), (["e", "c", "b"], ["d", "a"]))
        self.assertEqual(backup._deletes(cat, delete)[0]["args"]["item"], {"kind": "bundle", "id": "d", "hash": H["d"]})
        self.assertEqual(backup._deletes(cat, delete)[0]["klass"], "forward")  # LIFECYCLE §3.3: no undo
        self.catalog("f", at(7))  # dated after the clock: the whole run is refused
        with self.assertRaises(Refused) as cm:
            backup._retention(ctx, ld)  # type: ignore[arg-type]
        self.assertEqual(cm.exception.code, "clock")


class NamingTest(unittest.TestCase):
    """Plan time (LIFECYCLE §5.4): an id taken in this second is fine while the next second's id is free, which the
    executor waits for; refused when that one is taken too or when the id does not change with the second."""

    def setUp(self) -> None:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.lay = Layout(f"{d.name}/root", f"{d.name}/backups")
        self.now = datetime.fromisoformat("2026-10-20T01:02:03Z")

    def naming(self, template: str, *taken: str) -> None:
        for bid in taken:
            fs.write_once(self.lay.catalog("i", bid), b"{}")
        ctx = SimpleNamespace(layout=self.lay, now=self.now)
        m = SimpleNamespace(backup=SimpleNamespace(naming={"manual": template}, payload=None))
        backup._naming(ctx, "i", m, {}, "manual")  # type: ignore[arg-type]

    def test_an_id_taken_only_in_this_second_plans(self) -> None:
        self.naming("{bundle.stamp}-{class}")
        self.naming("{bundle.stamp}-{class}", "20261020T010203Z-manual")

    def test_an_id_that_waiting_would_not_free_is_refused(self) -> None:
        for template, taken in (
            ("{bundle.stamp}-{class}", ("20261020T010203Z-manual", "20261020T010204Z-manual")),
            ("nightly-{class}", ("nightly-manual",)),
        ):
            with self.subTest(template), self.assertRaises(Refused) as cm:
                self.naming(template, *taken)
            self.assertEqual(cm.exception.code, "bundle-exists")
            self.assertIn("never overwritten", cm.exception.message)


class HelperTest(unittest.TestCase):
    def test_memory_reads_mem_available_in_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            Path(f"{d}/meminfo").write_text("MemTotal:  4000 kB\nMemAvailable:    2048 kB\n")
            Path(f"{d}/none").write_text("MemTotal:  4000 kB\n")
            with mock.patch.object(backup, "MEMINFO", f"{d}/meminfo"):
                self.assertEqual(backup._memory(), 2048 * 1024)
            with mock.patch.object(backup, "MEMINFO", f"{d}/none"), self.assertRaises(Refused) as cm:
                backup._memory()
            self.assertEqual(cm.exception.code, "memory")

    def test_usage_errors_exit_2_before_any_observation(self) -> None:
        ctx: Any = SimpleNamespace()  # nothing is observed: no host, no daemon
        calls = (
            lambda: backup.plan_backup(ctx, "i", "weekly", None, False),
            lambda: backup.plan_backup(ctx, "i", "manual", "two\nlines", False),
            lambda: backup.plan_verify(ctx, "i", "b1", True, False),
            lambda: backup.plan_verify(ctx, "i", None, False, True),
        )
        for call in calls:
            with self.assertRaises(CannotRun) as cm:
                call()
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("usage", 2))  # LIFECYCLE §6


if __name__ == "__main__":
    unittest.main()
