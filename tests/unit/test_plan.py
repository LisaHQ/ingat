"""Plans: numbering, canonical hash, round trip, the fingerprint, and loading saved plans (F3, F4)."""

import os
import tempfile
import unittest
from datetime import timedelta
from typing import Any
from unittest import mock

from ingat import brand
from ingat.core import approval
from ingat.core.plan import CONFIG_HASH_LABEL, PROJECT_LABEL, Plan, fingerprint, new_plan
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.store import state


class FakeDocker:
    def __init__(self, containers: list[dict[str, Any]]) -> None:
        self.found = containers
        self.asked: list[dict[str, str]] = []

    def containers(self, labels: dict[str, str]) -> list[dict[str, Any]]:
        self.asked.append(labels)
        return self.found


def container(name: str, cid: str, labels: dict[str, str], status: str = "running") -> dict[str, Any]:
    return {"Name": "/" + name, "Id": cid, "Image": "sha256:" + "a" * 64, "Config": {"Labels": labels},
            "State": {"Status": status}}  # fmt: skip


STEPS = [{"type": "Obtain", "klass": "scratch", "args": {"images": []}}, {"type": "Record", "klass": "idempotent"}]


class PlanTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.layout = state.Layout(f"{tmp.name}/root", f"{tmp.name}/backups")
        rec = records.new_doc("instance", name="site", state="running", current_deployment=2, generations={"d": 1},
                              held_since=None, open_op=None, next_seq=4)  # fmt: skip
        state.write_doc_once(self.layout.record_json("site"), rec)

    def plan(self, **inputs: Any) -> Plan:
        return new_plan("backup", "site", "B", [brand.CLI, "backup", "site"], {"x": 1}, inputs, STEPS)

    def test_steps_are_numbered_and_checked(self) -> None:
        plan = self.plan()
        self.assertEqual([(s.n, s.type) for s in plan.steps], [(1, "Obtain"), (2, "Record")])
        self.assertEqual(records.parse_iso(plan.expires_at) - records.parse_iso(plan.created_at), timedelta(hours=24))
        for bad in ({"type": "Build", "klass": "scratch"}, {"type": "Up", "klass": "maybe"}):
            with self.assertRaises(Refused):
                new_plan("backup", "site", "B", [], {}, {}, [bad])

    def test_hash_is_canonical_and_survives_a_round_trip(self) -> None:
        plan = self.plan(b=1, a=[1, 2])
        again = Plan.from_doc(records.loads(records.pretty(plan.doc())))
        self.assertEqual(again, plan)
        self.assertEqual(again.hash, plan.hash)
        self.assertNotEqual(self.plan(b=2, a=[1, 2]).hash, plan.hash)

    def test_fingerprint_covers_record_containers_and_bundles(self) -> None:
        ns = {brand.label("instance"): "site"}
        found = [
            container("site-web-1", "b" * 64, {**ns, PROJECT_LABEL: "site", CONFIG_HASH_LABEL: "h1"}),
            container("site-app-1", "c" * 64, {**ns, PROJECT_LABEL: "site"}, "exited"),
            container("odd", "d" * 64, ns),  # not a Compose container: not part of any deployment
        ]
        state.write_doc_once(self.layout.catalog("site", "b1"), records.new_doc("catalog", bundle_hash="f" * 64))
        os.makedirs(self.layout.op_dir("site", 7, "backup"))
        docker = FakeDocker(found)
        fp = fingerprint(self.layout, docker, "site", ["b1", "gone"])  # type: ignore[arg-type]
        self.assertEqual(docker.asked, [ns])
        self.assertEqual(
            fp["record"],
            {"state": "running", "current_deployment": 2, "generations": {"d": 1}, "held_since": None, "open_op": None},
        )
        self.assertEqual(fp["next_seq"], 8)  # above every operation directory
        self.assertEqual([c[0] for c in fp["containers"]], ["site-app-1", "site-web-1"])
        self.assertEqual(fp["containers"][1][3:], ["h1", "running"])
        self.assertEqual(fp["bundles"], {"b1": "f" * 64, "gone": None})

    def test_load_checks_presence_hash_and_age(self) -> None:
        plan = self.plan()
        with self.assertRaises(CannotRun) as cm:
            approval.load(self.layout, plan.hash)
        self.assertEqual(cm.exception.code, "no-plan")
        self.assertEqual(approval.load(self.layout, approval.save(self.layout, plan)), plan)
        other = self.plan(z=1)
        with open(self.layout.plan(plan.hash), "rb") as f:
            data = f.read()
        state.write_doc_once(self.layout.plan("0" * 64), records.loads(data) | {"command": ["x"]})
        with self.assertRaises(Refused):
            approval.load(self.layout, "0" * 64)
        late = records.utc_now() + timedelta(hours=25)
        with mock.patch.object(records, "utc_now", return_value=late), self.assertRaises(CannotRun) as cm:
            approval.load(self.layout, approval.save(self.layout, other))
        self.assertEqual(cm.exception.code, "plan-expired")


if __name__ == "__main__":
    unittest.main()
