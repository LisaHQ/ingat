"""T1: the backup, verify, drill and prune planners for fx-lite against a real daemon (scratch dt.sh on both engines):
step lists and classes, the gate tiers, retention, the drill's isolation (internal networks, no ports, op label, holds,
its own generation, env file and secrets), no secret in any plan, and no trace of planning.

The scratch root, the file:// fixture repository and the installed instance come from tests/docker/test_planning.py
(its setUp, candidate and install stand in for prepare and the first install). Bundles are written as the executor
seals them: payload, bundle.json, SHA256SUMS that lists it, a catalog entry and a verification record."""

import json
import os
import subprocess
import time
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

from ingat import brand
from ingat.core.plan import Plan
from ingat.model import records
from ingat.model.bundle import bundle_doc, bundle_hash, sums_text
from ingat.model.errors import CannotRun, Refused
from ingat.ops import backup
from ingat.ops import context as cx
from ingat.policy import gate
from ingat.store import fs, state
from tests.docker import test_planning as tp


@unittest.skipUnless(os.path.exists("/var/run/docker.sock"), "needs a scratch Docker daemon")
class BackupPlanningTest(unittest.TestCase):
    setUp = tp.PlanningTest.setUp
    engines, commit, instance = tp.PlanningTest.engines, tp.PlanningTest.commit, tp.PlanningTest.instance
    candidate, install, plan = tp.PlanningTest.candidate, tp.PlanningTest.install, tp.PlanningTest.plan
    fx2 = tp.IMAGE  # PlanningTest.plan watches the update image its setUpClass builds; these tests build none

    def deployed(self, backups: str = "") -> None:
        """Deployment 1 of commit a recorded as running (nothing started: planning needs no container)."""
        self.candidate(self.a, tp.IMAGE)
        plan = self.plan("deploy", self.a)
        assert plan is not None
        self.install(plan, start=False)
        if backups:
            with open(self.lay.inst_toml(self.name), "a") as f:
                f.write(f"[backups]\n{backups}\n")

    def bundle(self, bid: str, days: int, klass: str = "scheduled", verified: bool = True) -> str:
        """A sealed bundle of deployment 1 made `days` ago; returns its hash."""
        lay, n = self.lay, self.name
        dep = state.read_doc(lay.deployment_json(n, 1), "deployment")
        d, created = lay.bundle_dir(n, bid), records.iso(records.utc_now() - timedelta(days=days))
        os.makedirs(f"{d}/payload/{bid}")
        Path(f"{d}/payload/{bid}/db").write_text(bid)
        files = [(f"payload/{bid}/db", records.sha256_hex(bid.encode()), len(bid))]
        tool = dict.fromkeys(("version", "engine", "api", "cli", "compose", "arch", "os"), "x")
        doc = bundle_doc(
            bundle_id=bid, klass=klass, instance=n, app="fx-lite", environment="test", lineage="l", created_at=created,
            freeze_at=None, consistency="online-app", deployment=dep, schema=dep["schema"], stores={"data": 1},
            entry=bid, files=files, meta=[], tool=tool, host="h",
        )  # fmt: skip
        Path(f"{d}/bundle.json").write_bytes(records.pretty(doc))
        sums = sums_text([(p, h) for p, h, _ in files] + [("bundle.json", records.sha256_hex(records.pretty(doc)))])
        Path(f"{d}/SHA256SUMS").write_bytes(sums)
        entry = {"bundle_id": bid, "bundle_hash": bundle_hash(sums), "class": klass, "size": 4096}
        entry |= {"created_at": created, "path": d, "imported": False}
        state.write_doc_once(lay.catalog(n, bid), records.new_doc("catalog", **entry))
        if verified:
            ok = {"bundle_id": bid, "bundle_hash": entry["bundle_hash"], "level": "verified", "ok": True, "op": 1}
            fs.append_line(lay.verification(n, bid), records.dumps(records.new_doc("verification", **ok, at=created)))
        return str(entry["bundle_hash"])

    def planned(self, fn: Any, *args: Any, **kw: Any) -> Any:
        """Plan with a fresh context: nothing written under instances/ or the backups root, no Docker event of this
        instance, no secret in the plan, and the plan survives its own JSON form."""
        ctx = self.ctx = cx.make_ctx(self.environ)
        before, since = (tp.tree(self.lay.instances_dir), tp.tree(self.lay.backups)), f"{time.time():.6f}"
        try:
            plan = fn(ctx, self.name, *args, **kw)
        finally:
            self.assertEqual((tp.tree(self.lay.instances_dir), tp.tree(self.lay.backups)), before)
            events = ctx.docker.events(since, f"{time.time() + 0.5:.6f}")
            self.assertEqual([e for e in events if self.name in json.dumps(e)], [])
        if isinstance(plan, Plan):
            text = json.dumps(plan.doc())
            self.assertFalse([k for k, v in self.canaries.items() if v in text])
            self.assertEqual(plan.hash, Plan.from_doc(json.loads(text)).hash)
            # auto-abandon: no forward point; the only forward steps are deletions, which never freeze
            self.assertFalse(
                [s.n for s in plan.steps if s.forward_point or (s.klass == "forward" and s.type != "Delete")]
            )
            self.assertEqual((plan.approval, plan.inputs["seq"]), ("B", 2))
        return plan

    def shape(self, plan: Plan) -> list[tuple[str, str]]:
        return [(s.type, s.klass) for s in plan.steps]

    def test_backup_online_offline_and_scheduled_retention(self) -> None:
        self.deployed("keep_daily = 1\nkeep_weekly = 0")
        plan = self.planned(backup.plan_backup, "manual", "before the upgrade", False)
        capture = [("CaptureBundle", "scratch"), ("RunTask", "scratch"), ("CaptureBundle", "scratch")]
        verified = [("VerifyBundle", "scratch"), ("Record", "idempotent")]
        self.assertEqual((plan.op_kind, self.shape(plan)), ("backup", capture + verified))  # online: writers stay up
        _, task, seal, check, record = plan.steps
        self.assertEqual(
            (seal.args["class"], seal.args["consistency"], seal.group), ("manual", "online-app", "capture")
        )
        self.assertEqual(
            (task.args["task"], task.args["variant"], task.args["task_uid"]), ("backup", "current", [10001] * 2)
        )
        self.assertEqual(
            (check.args, record.args["bundle_from"], record.args["level"]),
            ({"bundle": None, "input_owner": None}, 4, "verified"),
        )
        v = plan.inputs["variants"]["current"]
        self.assertEqual(
            (v["project"], v["isolated"], v["env"]["FXLITE_DATA_DIR"]),
            (self.name, False, self.lay.data_gen(self.name, "data", "g1")),
        )
        self.assertEqual(
            (v["values"]["op.seq"], v["values"]["reason"], v["values"]["schema.expected"]),
            ("2", "before the upgrade", "1"),
        )
        self.assertEqual(
            plan.command, [brand.CLI, "backup", self.name, "--class", "manual", "--reason", "before the upgrade"]
        )
        self.assertEqual(plan.inputs["warnings"], [])
        self.assertEqual(
            sorted(plan.inputs["redact_files"]),
            sorted(f"{self.lay.secrets_dir(self.name)}/env/{k}" for k in self.canaries),
        )

        plan = self.planned(backup.plan_backup, "pre-change", None, False)  # writers stop, then start again
        stop, up = plan.steps[0], plan.steps[-1]
        self.assertEqual(self.shape(plan), [("Stop", "reversible"), *capture, *verified, ("Up", "reversible")])
        self.assertEqual((stop.args["services"], stop.args["freeze"], stop.args["variant"]), (["app"], True, "current"))
        self.assertEqual(
            (up.args["services"], up.args["wait"], up.args["variant"]), (["app"], ["ready", "edge-live"], "current")
        )
        self.assertEqual(plan.steps[3].args["consistency"], "writers-stopped")

        with mock.patch.object(
            gate, "load_tested", return_value=[]
        ):  # an untested Engine: tier 1 warns, tier 2 refuses
            warned = self.planned(backup.plan_backup, "manual", None, False)
            self.assertEqual(len(warned.inputs["warnings"]), 1)
            with self.assertRaises(CannotRun) as cm:
                self.planned(backup.plan_backup, "pre-change", None, False)
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("untested-platform", 2))

        hashes = {b: self.bundle(b, days) for b, days in (("old", 3), ("mid", 2), ("new", 1))}
        self.bundle("unverified", 2, verified=False)
        plan = self.planned(backup.plan_backup, "scheduled", None, False, scheduled=True)
        deletes = [s for s in plan.steps if s.type == "Delete"]
        self.assertEqual(plan.steps[-2:], tuple(deletes))  # retention last, after the new bundle verified
        self.assertEqual(
            [s.args["item"] for s in deletes], [{"kind": "bundle", "id": b, "hash": hashes[b]} for b in ("mid", "old")]
        )
        self.assertEqual({s.klass for s in deletes}, {"forward"})
        self.assertEqual(sorted(plan.fingerprint["bundles"]), ["mid", "new", "old", "unverified"])
        self.assertEqual(
            (plan.command, plan.inputs["variants"]["current"]["values"]["reason"]),
            ([brand.CLI, "scheduled", "backup", self.name], "scheduled scheduled backup"),  # MANIFEST_SPEC §3
        )
        report = self.planned(backup.plan_prune)  # the dry run lists the same decision and writes nothing
        self.assertEqual((report["exit"], report["keep"], report["delete"]), (0, ["new", "unverified"], ["mid", "old"]))
        self.assertEqual(report["next"], f"{brand.CLI} prune {self.name} --bundles --apply")
        plan = self.planned(backup.plan_prune, True)
        self.assertEqual((plan.op_kind, self.shape(plan)), ("prune", [("Delete", "forward")] * 2))

        os.remove(f"{self.lay.certifications_dir}/x-selftest.json")  # a platform update: gate tier 2 refuses
        plan = self.planned(backup.plan_backup, "scheduled", None, False, scheduled=True)  # the backup goes on
        self.assertEqual((self.shape(plan), plan.fingerprint["bundles"]), (capture + verified, {}))
        self.assertEqual([w.split(":")[0] for w in plan.inputs["warnings"]], ["retention skipped"])
        with self.assertRaises(CannotRun) as cm:  # an explicit prune is gate tier 2, as `prune --bundles --apply` is
            self.planned(backup.plan_backup, "manual", None, True)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("uncertified", 2))
        with self.assertRaises(CannotRun):
            self.planned(backup.plan_prune, True)

    def test_verify_and_drill(self) -> None:
        self.deployed()
        self.bundle("b1", 2)
        digest = self.bundle("b2", 1)
        plan = self.planned(backup.plan_verify, "b1", False, False)  # fx-lite verifies by hash only
        self.assertEqual(
            (plan.op_kind, self.shape(plan), plan.inputs["variants"]),
            ("verify", [("VerifyBundle", "scratch"), ("Record", "idempotent")], {}),
        )
        self.assertEqual(
            (plan.steps[0].args, plan.steps[1].args["bundle_from"]), ({"bundle": "b1", "input_owner": None}, 1)
        )
        with self.assertRaises(Refused) as cm:
            self.planned(backup.plan_verify, "nope", False, False)
        self.assertEqual(cm.exception.code, "no-bundle")

        plan = self.planned(backup.plan_verify, None, True, True, scheduled=True)  # the latest bundle: b2
        t2, op_dir = self.lay.data_gen(self.name, "data", "t2"), self.lay.op_dir(self.name, 2, "drill")
        self.assertEqual(
            (plan.op_kind, plan.command[-3:], plan.fingerprint["bundles"]),
            ("drill", [self.name, "b2", "--restore-test"], {"b2": digest}),
        )
        types = ["VerifyBundle", "CreateGeneration", "RunTask", "Up", "Record", "Teardown"]
        self.assertEqual([s.type for s in plan.steps], types)
        self.assertEqual({s.klass for s in plan.steps if s.type != "Record"}, {"scratch"})
        check, gen, restore, up, record, down = plan.steps
        self.assertEqual(check.args, {"bundle": "b2", "input_owner": [10001, 10001]})
        self.assertEqual(
            (gen.args["gen"], gen.args["path"], gen.args["purpose"], gen.args["owner"], gen.group),
            ("t2", t2, "drill", [10001, 10001], "restore"),
        )
        self.assertEqual(
            (restore.args["task"], restore.args["variant"], restore.args["mounts"]),
            ("restore", "drill", [["/in", "bundle"], ["/restore", "generation:data"]]),
        )
        self.assertEqual(
            (restore.args["gen_paths"], restore.args["store_params"]), ({"data": t2}, {"data": "FXLITE_DATA_DIR"})
        )
        self.assertEqual(
            (up.args["services"], up.args["wait"], up.args["identity"]), (["app"], ["ready", "edge-live"], True)
        )
        self.assertEqual(
            (record.args["level"], record.args["bundle_from"], record.args["steps_ok"]), ("restore-tested", 1, [3, 4])
        )
        self.assertEqual((down.always, down.args), (True, {"variant": "drill"}))

        v = plan.inputs["variants"]["drill"]
        self.assertEqual(
            (v["project"], v["isolated"], v["images"]),
            (f"{self.name}--t2", True, state.read_doc(self.lay.deployment_json(self.name, 1), "deployment")["images"]),
        )
        env_file = f"{op_dir}/env/isolated.env"
        self.assertEqual((v["env"]["FXLITE_DATA_DIR"], v["env"]["FXLITE_ENV_FILE"], v["binds"]), (t2, env_file, [t2]))
        text = plan.inputs["files"][env_file]
        self.assertIn("BASE_URL='http://127.0.0.1'", text)
        self.assertFalse([k for k in ("MAIL_USER", "MAIL_PASSWORD", "DELIVERY_MODE", "JOBS") if k in text])  # dropped
        self.assertEqual(
            (plan.inputs["app_env"], plan.inputs["redact_files"], plan.inputs["throwaway_secrets"]), (None, [], {})
        )
        live = json.dumps(v)
        self.assertNotIn(self.lay.secrets_dir(self.name), live)
        self.assertNotIn(self.lay.data_gen(self.name, "data", "g1"), live)
        model = cx.model(self.ctx, v)  # rendered again from the plan's own data
        self.assertEqual(records.doc_hash(model), v["model_sha256"])
        self.assertTrue(
            model["networks"] and all(x.get("internal") for x in model["networks"].values()), model["networks"]
        )
        app = model["services"]["app"]
        self.assertFalse(app.get("ports"))
        self.assertEqual(app["labels"][brand.label("op")], "2")
        self.assertEqual((app["environment"]["DELIVERY_MODE"], app["environment"]["JOBS"]), ("capture", "off"))
        self.assertEqual(app["env_file"][0]["path"], env_file)

        with mock.patch.object(gate, "load_tested", return_value=[]):  # drills are gate tier 2; verify is tier 1
            with self.assertRaises(CannotRun) as cm:
                self.planned(backup.plan_verify, "b2", False, True)
            self.assertEqual(cm.exception.code, "untested-platform")
            self.assertEqual(len(self.planned(backup.plan_verify, "b2", False, False).inputs["warnings"]), 1)
        meminfo = f"{self.base}/meminfo"
        Path(meminfo).write_text("MemAvailable: 1024 kB\n")
        with mock.patch.object(backup, "MEMINFO", meminfo), self.assertRaises(Refused) as cm:
            self.planned(backup.plan_verify, "b2", False, True)  # [drill] min_free_memory = 512m
        self.assertEqual(cm.exception.code, "memory")
        bundle_json = f"{self.lay.bundle_dir(self.name, 'b2')}/bundle.json"
        Path(bundle_json).write_bytes(Path(bundle_json).read_bytes().replace(b'"online-app"', b'"external"'))
        with self.assertRaises(Refused) as cm:
            self.planned(backup.plan_verify, "b2", False, True)
        self.assertEqual(cm.exception.code, "bundle-hash")

        snapshot = f"{self.lay.deployment_snapshot(self.name, 1)}/{brand.MANIFEST_FILE}"
        text = Path(snapshot).read_text().replace("checks = []\nrecord = []", 'checks = ["peek"]\nrecord = []')
        peek = ["[tasks.peek]", 'service = "app"', 'mode = "run"', 'argv = ["ls", "/in"]', 'user = "0:0"']
        peek += ['mounts = { "/in" = "bundle" }', 'effect = "read"', 'timeout = "1m"']
        os.chmod(snapshot, 0o600)
        Path(snapshot).write_text(text + "\n".join(peek) + "\n")
        with self.assertRaises(Refused) as cm:  # root and uid 10001 cannot both own the one private bundle copy
            self.planned(backup.plan_verify, "b1", False, True)
        self.assertEqual(cm.exception.code, "task-user")

    def test_offline_backup_refuses_foreign_objects_of_the_project(self) -> None:
        """Writers stop and start again: Compose would stop and start a container of the writer service that is not
        the instance's own (F8). An online backup runs no Compose stop or start."""
        self.deployed()
        ghost = f"{self.name}-hand"
        labels = [f"--label=com.docker.compose.project={self.name}", "--label=com.docker.compose.service=app"]
        tp.docker("run", "-d", "--name", ghost, *labels, "--entrypoint", "sleep", tp.IMAGE, "600")
        self.addCleanup(subprocess.run, ["docker", "rm", "-f", ghost], capture_output=True)
        with self.assertRaises(Refused) as cm:
            self.planned(backup.plan_backup, "pre-change", None, False)
        self.assertEqual(cm.exception.code, "foreign")
        self.assertIn(f"container {ghost}", cm.exception.message)
        self.assertEqual(
            self.shape(self.planned(backup.plan_backup, "manual", None, False))[0], ("CaptureBundle", "scratch")
        )
        self.assertEqual(json.loads(tp.docker("inspect", ghost))[0]["State"]["Status"], "running")

    def test_drill_isolation_policy_secrets_dir_and_warnings(self) -> None:
        """The drill's model is checked as an isolated one (F13); its throwaway secrets directory exists for a
        secrets_dir param even when no [secrets.*] makes it (LIFECYCLE §4.9); every plan carries its warnings."""
        self.deployed()
        self.bundle("b1", 1)
        drill = self.planned(backup.plan_verify, "b1", False, True)
        self.assertEqual((drill.inputs["warnings"], drill.inputs["variants"]["drill"]["secret_files"]), ([], []))
        self.assertEqual(self.planned(backup.plan_prune, True), None)  # nothing to delete: no plan
        snapshot = f"{self.lay.deployment_snapshot(self.name, 1)}/{brand.MANIFEST_FILE}"
        os.chmod(snapshot, 0o600)
        text = Path(snapshot).read_text()
        param = 'FXLITE_PORT     = { kind = "port" }\n'
        Path(snapshot).write_text(text.replace(param, param + 'FXLITE_SECRETS  = { kind = "secrets_dir" }\n'))
        drill = self.planned(backup.plan_verify, "b1", False, True)
        secrets = f"{self.lay.op_dir(self.name, 2, 'drill')}/secrets"
        self.assertEqual(drill.inputs["variants"]["drill"]["env"]["FXLITE_SECRETS"], secrets)
        self.assertEqual((drill.inputs["files"][f"{secrets}/.keep"], drill.inputs["throwaway_secrets"]), ("", {}))
        Path(snapshot).write_text(
            text.replace(param, param + 'FXLITE_SECRETS  = { kind = "secrets_dir" }\n')
            + '[secrets.tok]\ngenerate = "alnum32"\n'
        )
        drill = self.planned(backup.plan_verify, "b1", False, True)
        self.assertEqual(drill.inputs["throwaway_secrets"], {f"{secrets}/tok": 0o400})
        self.assertNotIn(f"{secrets}/.keep", drill.inputs["files"])
        Path(snapshot).write_text(text)
        export = state.read_doc(self.lay.deployment_json(self.name, 1), "deployment")["export"]
        compose = Path(export, "compose.yaml")
        os.chmod(compose, 0o644)
        compose.write_text(
            compose.read_text().replace("    read_only: true\n", "    read_only: true\n    network_mode: bridge\n")
        )
        self.planned(backup.plan_backup, "manual", None, False)  # a live run may use the default bridge
        with self.assertRaises(Refused) as cm:  # an isolated run would leave its internal networks
            self.planned(backup.plan_verify, "b1", False, True)
        self.assertEqual(cm.exception.code, "policy")
        self.assertIn("services.app.network_mode", cm.exception.message)

    def test_not_applicable_and_wrong_state(self) -> None:
        with self.assertRaises(Refused) as cm:
            self.planned(backup.plan_backup, "manual", None, False)
        self.assertEqual(cm.exception.code, "wrong-state")  # never deployed
        self.deployed()
        snapshot = f"{self.lay.deployment_snapshot(self.name, 1)}/{brand.MANIFEST_FILE}"
        os.chmod(snapshot, 0o600)
        Path(snapshot).write_bytes((tp.FIXTURE.parent / "fx-web" / brand.MANIFEST_FILE).read_bytes())  # strategy none
        for fn, args in ((backup.plan_backup, ("manual", None, False)), (backup.plan_verify, (None, True, True))):
            with self.assertRaises(Refused) as cm:
                self.planned(fn, *args)
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("not-applicable", 1))


if __name__ == "__main__":
    unittest.main()
