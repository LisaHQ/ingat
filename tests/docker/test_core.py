"""T1: the executor and the M1 steps against a real daemon with the fx-lite fixture (both engines, dt.sh).

One instance is installed per class through a first-install-like plan; every test then runs its own operations on
it and leaves no operation open. Plans are hand-built by tests.docker.helpers the way a planner renders them."""

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
import urllib.request
from pathlib import Path

from ingat import brand
from ingat.adapters.docker import EffectToken
from ingat.core import steps
from ingat.core.journal import Journal
from ingat.core.plan import PROJECT_LABEL, Step, new_plan
from ingat.core.steps import Op
from ingat.model import records
from ingat.model.errors import Refused
from ingat.ops.backup import levels
from ingat.store import state
from tests.docker.helpers import IMAGE, UID, Lab, LabTest, eventually, probe, step, task, tree_hash

SKIP = not os.path.exists("/var/run/docker.sock")


@unittest.skipIf(SKIP, "needs a scratch Docker daemon")
class CoreTest(LabTest):
    def health(self) -> int:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.lab.port}/api/health", timeout=5) as r:
            return int(r.status)

    def healthy(self) -> bool:
        try:
            return self.health() == 200
        except OSError:
            return False

    def assert_unchanged(self, seq: int, kind: str) -> None:
        """Closed failed-unchanged: the instance is not frozen and its app runs again."""
        self.assertEqual(self.lab.result(seq, kind)["outcome"], "failed-unchanged")
        self.assertEqual(state.read_doc(self.lab.layout.record_json(self.lab.name), "instance")["state"], "running")
        self.assertTrue(eventually(self.healthy))

    def backup(self) -> tuple[int, str]:
        seq = self.lab.seq()
        code, run = self.lab.run(self.lab.backup_plan())
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        seal = next(r for r in self.lab.journal(seq, "backup") if r["step"] == 3 and r["phase"] == "done")
        return seq, seal["evidence"]["bundle_id"]

    def test_install(self) -> None:
        lab, (code, run) = self.lab, self.install
        self.assertEqual((code, run["code"], run["op"]), (0, "completed", 1), run)
        rec = state.read_doc(lab.layout.record_json(lab.name), "instance")
        self.assertEqual((rec["state"], rec["current_deployment"], rec["generations"]), ("running", 1, {"data": 1}))
        dep = state.read_doc(lab.layout.deployment_json(lab.name, 1), "deployment")
        self.assertEqual((dep["schema"]["expected"], dep["schema"]["actual"], dep["op"]), (1, 1, 1))
        self.assertTrue(dep["writes_reopened_at"])
        snap = lab.layout.deployment_snapshot(lab.name, 1)
        self.assertEqual(sorted(os.listdir(snap)), sorted([brand.MANIFEST_FILE, "compose.env", "override.yaml"]))
        cand = state.read_doc(lab.layout.candidates(lab.name, dep["commit"], {"app": lab.image}), "candidate")
        self.assertEqual(cand["images"], {"app": lab.image})
        self.assertTrue(os.path.exists(lab.layout.ledger(lab.image.removeprefix("sha256:"), f"{lab.name}-1")))
        self.assertEqual(self.health(), 200)
        [c] = lab.docker.containers(project=lab.name)
        self.assertEqual(c["Image"], lab.image)
        result = lab.result(1, "deploy")
        self.assertEqual((result["outcome"], result["exit"]), ("completed", 0))
        probes = next(r for r in lab.journal(1, "deploy") if r["step"] == 5 and r["phase"] == "done")["evidence"]
        self.assertEqual(probes["probes"], {"ready": "pass", "edge-live": "pass"})
        for d, _, files in os.walk(lab.layout.root):  # secret canary: only the secret file and the app env hold it
            for f in files:
                path = os.path.join(d, f)
                if not path.startswith((lab.layout.secrets_dir(lab.name), lab.layout.env_dir(lab.name))):
                    try:
                        data = Path(path).read_bytes()
                    except FileNotFoundError:  # a running app's own temporary file (SQLite -shm, -wal) went meanwhile
                        continue
                    self.assertNotIn(lab.secret.encode(), data, path)

    def test_backup_seals_and_verifies(self) -> None:
        lab = self.lab
        seq, bid = self.backup()
        d = lab.layout.bundle_dir(lab.name, bid)
        sums = Path(d, "SHA256SUMS").read_text()
        self.assertIn("  bundle.json\n", sums)
        check = subprocess.run(["sha256sum", "--strict", "-c", "SHA256SUMS"], cwd=d, capture_output=True, check=False)
        self.assertEqual(check.returncode, 0, check.stdout)
        cat = state.read_doc(lab.layout.catalog(lab.name, bid), "catalog")
        self.assertEqual(cat["bundle_hash"], hashlib.sha256(sums.encode()).hexdigest())
        [ver] = [line for line in Path(lab.layout.verification(lab.name, bid)).read_text().splitlines() if line]
        self.assertIn('"level":"verified"', ver)
        self.assertIn('"ok":true', ver)
        self.assertFalse(os.path.exists(f"{lab.op_dir(seq, 'backup')}/stage"))
        self.assertEqual(sorted(os.listdir(d)), ["SHA256SUMS", "bundle.json", "meta", "payload"])
        self.assertEqual([x for x in os.listdir(os.path.dirname(d)) if x.startswith(".")], [])

    def test_drill_runs_isolated_and_tears_down(self) -> None:
        lab = self.lab
        _, bid = self.backup()
        seq, plan = lab.drill_plan(bid)
        code, run = lab.run(plan)
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        lines = Path(lab.layout.verification(lab.name, bid)).read_text().splitlines()
        self.assertTrue(any('"level":"restore-tested"' in line and '"ok":true' in line for line in lines))
        up = next(r for r in lab.journal(seq, "drill") if r["step"] == 4 and r["phase"] == "done")["evidence"]
        self.assertEqual(up["probes"], {"ready": "pass", "edge-live": "n/a"})
        self.assertEqual(lab.labelled(op=str(seq)), [])
        self.assertFalse(os.path.exists(lab.layout.data_gen(lab.name, "data", f"t{seq}")))
        self.assertFalse(os.path.exists(lab.layout.data_gen(lab.name, "data", f"t{seq}") + ".json"))
        self.assertEqual(os.listdir(lab.layout.allocations_dir), [])  # the subnet entry is gone again
        self.assertFalse(os.path.exists(f"{lab.op_dir(seq, 'drill')}/in"))  # the private bundle copy is gone
        self.assertEqual(self.health(), 200)

    def test_crash_at_an_intent_then_resume_redoes_the_capture_group(self) -> None:
        lab = self.lab
        seq = lab.seq()
        self.assertEqual(lab.crash(lab.backup_plan(), "3:intent:after"), -signal.SIGKILL)
        self.assertEqual(lab.open_op()["seq"], seq)  # type: ignore[index]
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        intents = [r["attempt"] for r in lab.journal(seq, "backup") if r["phase"] == "intent" and r["step"] == 1]
        self.assertEqual(intents, [1, 2])
        self.assertEqual(lab.result(seq, "backup")["outcome"], "completed")

    def test_crash_while_a_task_runs_then_resume(self) -> None:
        lab = self.lab
        seq = lab.seq()
        slow = ["sh", "-c", "sleep 3 && exec fx-lite backup --to /out"]  # long enough for the hook's tick to see it
        self.assertEqual(lab.crash(lab.backup_plan(slow), "2:task"), -signal.SIGKILL)
        self.assertTrue(lab.labelled(op=str(seq), role="task"))  # the daemon keeps running it (spike S14)
        self.assertTrue(eventually(lambda: not lab.labelled(op=str(seq))))  # --rm removes it once it exits
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        tasks = [r for r in lab.journal(seq, "backup") if r["step"] == 2 and r["phase"] == "done"]
        self.assertEqual(tasks[-1]["evidence"]["container"], f"{lab.name}-x{seq}-2-a2")

    def test_orphan_running_refuses_exited_is_evidence(self) -> None:
        lab = self.lab
        seq = lab.seq()
        self.assertEqual(lab.crash(lab.backup_plan(), "2:intent:after"), -signal.SIGKILL)
        name = f"{lab.name}-x{seq}-2-a1"
        labels = {"instance": lab.name, "op": str(seq), "step": "2", "role": "task"}
        flags = [x for k, v in labels.items() for x in ("--label", f"{brand.label(k)}={v}")]
        flags += ["--label", f"{PROJECT_LABEL}={lab.name}"]  # as `compose run` labels it: owned (ARCHITECTURE §7.5)
        made = lab.cli("run", "-d", "--name", name, *flags, "--entrypoint", "sleep", IMAGE, "300")
        self.assertEqual(made.returncode, 0, made.stderr)
        before = tree_hash(lab.layout.inst(lab.name))
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (2, "task-running"), run)
        self.assertIn(f"docker stop {name}", run["message"])
        self.assertEqual(tree_hash(lab.layout.inst(lab.name)), before)
        self.assertEqual(lab.cli("stop", "-t", "1", name).returncode, 0)
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertEqual(lab.docker.inspect("container", [name]), [])
        [orphan] = [r for r in lab.journal(seq, "backup") if "orphan" in r.get("evidence", {})]
        self.assertEqual((orphan["step"], orphan["phase"]), (2, "unknown"))
        self.assertEqual(orphan["evidence"]["orphan"]["container"], name)
        self.assertNotEqual(orphan["evidence"]["orphan"]["exit_code"], 0)

    def test_stale_plan_is_refused_without_a_trace(self) -> None:
        lab = self.lab
        stale = lab.backup_plan()
        other = lab.save("start", [step("Record", "idempotent", args={"kind": "state", "state": "running"})], {})
        self.assertEqual(lab.run(other)[0], 0)
        before = tree_hash(lab.layout.inst(lab.name))
        code, run = lab.run(stale)
        self.assertEqual((code, run["code"], run["op"]), (1, "stale-plan", None), run)
        self.assertEqual(tree_hash(lab.layout.inst(lab.name)), before)
        later = lab.save("deploy", [step("SnapshotLogs", "scratch", args={"services": ["app"]})], {})
        code, run = lab.run(later)
        self.assertEqual((code, run["code"]), (1, "not-in-this-release"), run)
        self.assertEqual(tree_hash(lab.layout.inst(lab.name)), before)

    def test_cancel_file_before_a_step_closes_abandoned(self) -> None:
        lab = self.lab
        seq = lab.seq()
        pause = step("Pause", "operator", args={"text": "waiting", "allow_tasks": []})
        record = step("Record", "idempotent", args={"kind": "state", "state": "running"})
        code, run = lab.run(lab.save("deploy", [pause, record], {}))
        self.assertEqual((code, run["code"]), (4, "paused"), run)
        Path(lab.op_dir(seq, "deploy"), "cancel").write_text("")
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (130, "cancelled"), run)
        self.assertEqual(lab.result(seq, "deploy")["outcome"], "abandoned")
        self.assertNotIn(2, [r["step"] for r in lab.journal(seq, "deploy")])

    def test_allowed_task_joins_a_paused_operation(self) -> None:
        lab = self.lab
        seq = lab.seq()
        pause = step("Pause", "operator", args={"text": "bootstrap now", "allow_tasks": ["health"]})
        record = step("Record", "idempotent", args={"kind": "state", "state": "running"})
        self.assertEqual(lab.run(lab.save("deploy", [pause, record], {}))[0], 4)
        argv = ["fx-lite", "probe", "http://app:3000/api/health"]
        health = task("health", "current", argv, effect="read", exit={"0": "ok"}, stdout="json")
        health["expect"] = {"status": ["ok"]}
        bad = lab.variant() | {"env": {"X": "it's"}}  # refused before the join writes anything into the paused op
        before = tree_hash(lab.layout.inst(lab.name))
        code, run = lab.run(lab.save("task", [step("RunTask", "scratch", args=health)], {"current": bad}))
        self.assertEqual((code, run["code"], tree_hash(lab.layout.inst(lab.name))), (1, "unsafe-value", before), run)
        leftover = Path(lab.op_dir(seq, "deploy"), "v1000")  # an earlier join killed before its intent
        leftover.mkdir()
        (leftover / "current.yaml").write_text("partial")
        joined = lab.save("task", [step("RunTask", "scratch", args=health)], {"current": lab.variant()})
        code, run = lab.run(joined)
        self.assertEqual((code, run["op"]), (0, seq), run)
        self.assertEqual(lab.open_op()["seq"], seq)  # type: ignore[index]
        done = [r for r in lab.journal(seq, "deploy") if r["step"] == 1001 and r["phase"] == "done"]
        self.assertEqual(done[0]["evidence"]["outcome"], "ok")
        self.assertEqual(lab.run(lab.resume_plan(), "resume")[0], 0)
        self.assertEqual(lab.result(seq, "deploy")["outcome"], "completed")

    def test_open_backup_is_auto_abandoned_by_the_next_plan(self) -> None:
        lab = self.lab
        seq = lab.seq()
        self.assertEqual(lab.crash(lab.backup_plan(), "3:intent:after"), -signal.SIGKILL)
        self.assertTrue(os.path.exists(f"{lab.op_dir(seq, 'backup')}/stage"))
        code, run = lab.run(lab.backup_plan())
        self.assertEqual((code, run["code"], run["op"]), (0, "completed", seq + 1), run)
        self.assertEqual(lab.result(seq, "backup")["outcome"], "abandoned-auto")
        self.assertFalse(os.path.exists(f"{lab.op_dir(seq, 'backup')}/stage"))

    def test_signal_cancels_an_interruptible_task(self) -> None:
        lab = self.lab
        seq = lab.seq()
        slow = ["sh", "-c", "trap 'exit 143' TERM; sleep 60 & wait"]
        proc, run_id = lab.spawn(lab.backup_plan(slow))
        self.assertTrue(eventually(lambda: lab.labelled(op=str(seq), role="task")))
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(120), 3)
        run = state.read_doc(lab.layout.run(run_id), "run")
        self.assertEqual(run["code"], "cancelled", run)
        self.assertEqual(lab.result(seq, "backup")["outcome"], "failed-unchanged")
        [task_step] = [r for r in lab.journal(seq, "backup") if r["step"] == 2 and r["phase"] != "intent"]
        self.assertEqual(task_step["phase"], "cancelled")
        self.assertTrue(eventually(lambda: not lab.labelled(op=str(seq))))
        self.assertFalse(os.path.exists(f"{lab.op_dir(seq, 'backup')}/stage"))

    def test_failed_drill_still_tears_down(self) -> None:
        lab = self.lab
        _, bid = self.backup()
        seq, plan = lab.drill_plan(bid, restore=["sh", "-c", "exit 1"])
        code, run = lab.run(plan)
        self.assertEqual((code, run["code"]), (3, "task-failed"), run)
        result = lab.result(seq, "drill")
        self.assertEqual((result["outcome"], result["warnings"]), ("failed-unchanged", []))
        self.assertEqual(lab.labelled(op=str(seq)), [])
        self.assertFalse(os.path.exists(lab.layout.data_gen(lab.name, "data", f"t{seq}")))
        self.assertEqual(os.listdir(lab.layout.allocations_dir), [])
        teardown = [r for r in lab.journal(seq, "drill") if r["step"] == 6]
        self.assertEqual([r["phase"] for r in teardown], ["intent", "done"])
        digest = state.read_doc(lab.layout.catalog(lab.name, bid), "catalog")["bundle_hash"]  # F10, LIFECYCLE §5.5
        self.assertEqual(levels(lab.layout, lab.name, bid, digest), {"verified": True, "restore-tested": False})
        last = json.loads(Path(lab.layout.verification(lab.name, bid)).read_text().splitlines()[-1])
        self.assertEqual((last["op"], last["ok"], last["evidence"]["3"]["code"]), (seq, False, "task-failed"))

    def verify_plan(self, bid: str, argv: list[str] | None) -> str:
        """VerifyBundle of `bid`, a verify task reading its private copy when `argv` is given, the `verified` record."""
        todo = [step("VerifyBundle", "scratch", group="verify", args={"bundle": bid, "input_owner": argv and UID})]
        if argv:
            verify = task("verify", "current", argv, effect="read", exit={"0": "ok"}, mounts=[["/in", "bundle"]])
            todo.append(step("RunTask", "scratch", group="verify", args=verify))
        done = {
            "kind": "verification",
            "level": "verified",
            "bundle_from": 1,
            "steps_ok": list(range(2, len(todo) + 1)),
        }
        return self.lab.save(
            "verify", [*todo, step("Record", "idempotent", args=done)], {"current": self.lab.variant()}
        )

    def test_a_failed_verification_is_recorded_not_ok(self) -> None:
        """F10 (LIFECYCLE §5.5): a verify task that fails, and a bundle that no longer matches its catalog entry, each
        append `ok: false` for the level; the newest record per level decides, as status reads it."""
        lab = self.lab
        _, bid = self.backup()
        digest = state.read_doc(lab.layout.catalog(lab.name, bid), "catalog")["bundle_hash"]
        for argv, code in ((["sh", "-c", "exit 1"], "task-failed"), (None, "completed")):
            self.assertEqual(lab.run(self.verify_plan(bid, argv))[1]["code"], code)
            self.assertEqual(levels(lab.layout, lab.name, bid, digest), {"verified": code == "completed"})
        [payload] = [p for p in Path(lab.layout.bundle_dir(lab.name, bid), "payload").rglob("*") if p.is_file()][:1]
        payload.chmod(0o644)
        payload.write_bytes(payload.read_bytes() + b"tampered")
        self.assertEqual(lab.run(self.verify_plan(bid, None))[1]["code"], "bundle-hash")
        self.assertEqual(levels(lab.layout, lab.name, bid, digest), {"verified": False})
        last = json.loads(Path(lab.layout.verification(lab.name, bid)).read_text().splitlines()[-1])
        self.assertEqual(
            (last["ok"], last["bundle_hash"], last["evidence"]["1"]["code"]), (False, digest, "bundle-hash")
        )

    def test_plan_warnings_reach_the_result_and_scratch_leftovers_go(self) -> None:
        """The planner's warnings are repeated in result.json and the run file; the close removes the private input
        copies and an empty stage, and keeps the artifacts."""
        lab = self.lab
        seq = lab.seq()
        argv = ["sh", "-c", "cat /in/tok >/dev/null && echo '{}'"]
        peek = task("peek", "current", argv, effect="read", exit={"0": "ok"}, stdout="json")
        peek |= {"mounts": [["/out", "stage"], ["/in", "input:tok"]], "inputs": {"tok": f"{lab.layout.inbox}/tok"}}
        warned = ["tier 1: this platform build has no host certification"]
        plan = lab.save("task", [step("RunTask", "scratch", args=peek)], {"current": lab.variant()}, warnings=warned)
        code, run = lab.run(plan)
        self.assertEqual((code, run["code"], run["warnings"]), (0, "completed", warned), run)
        self.assertEqual(lab.result(seq, "task")["warnings"], warned)
        left, d = os.listdir(lab.op_dir(seq, "task")), lab.op_dir(seq, "task")
        self.assertEqual(
            ("in" in left, "stage" in left, os.listdir(f"{d}/artifacts")), (False, False, ["1-a1-peek.out"])
        )

    def test_failure_before_the_forward_point_undoes_a_stop(self) -> None:
        lab = self.lab
        seq = lab.seq()
        stop = step("Stop", "reversible", args={"variant": "current", "services": ["app"], "freeze": True})
        failing = task("check", "current", ["sh", "-c", "exit 1"], effect="read", exit={"0": "ok"})
        plan = lab.save("restart", [stop, step("RunTask", "scratch", args=failing)], {"current": lab.variant()})
        code, run = lab.run(plan)
        self.assertEqual((code, run["code"]), (3, "task-failed"), run)
        self.assertEqual(lab.result(seq, "restart")["outcome"], "failed-unchanged")
        [c] = lab.docker.containers(project=lab.name)
        self.assertTrue(c["State"]["Running"])
        self.assertTrue(eventually(self.healthy))  # the restarted app may refuse connections for a moment

    def test_one_step_write_task_with_failed_expect_needs_review(self) -> None:
        lab = self.lab
        seq = lab.seq()
        status = task("queue-status", "current", ["fx-lite", "queue", "resume"], effect="app-write", exit={"2": "ok"})
        status |= {"stdout": "record", "expect": {"outcome": ["something-else"]}}
        code, run = lab.run(lab.save("task", [step("RunTask", "forward", args=status)], {"current": lab.variant()}))
        self.assertEqual((code, run["code"]), (4, "needs-review"), run)
        self.assertEqual(lab.result(seq, "task")["outcome"], "needs-review")
        rec = state.read_doc(lab.layout.record_json(lab.name), "instance")
        self.assertEqual(rec["state"], "running")
        self.assertTrue(any(f.startswith(f"{seq}-1-a1-") for f in os.listdir(lab.layout.reports_dir(lab.name))))

    def test_delete_reproves_and_removes_a_bundle_and_a_container(self) -> None:
        lab = self.lab
        _, bid = self.backup()
        digest = state.read_doc(lab.layout.catalog(lab.name, bid), "catalog")["bundle_hash"]
        name, owned = f"{lab.name}-leftover", ["--label", f"{PROJECT_LABEL}={lab.name}"]
        made = lab.cli("create", "--name", name, "--label", f"{brand.label('instance')}={lab.name}", *owned, IMAGE)
        self.assertEqual(made.returncode, 0, made.stderr)
        [c] = lab.docker.inspect("container", [name])
        items = [{"kind": "bundle", "id": bid, "hash": digest}]
        items.append({"kind": "container", "id": c["Id"], "name": name, "created": c["Created"]})
        steps = [step("Delete", "forward", args={"item": item}) for item in items]
        code, run = lab.run(lab.save("prune", steps, {}, (bid,)))
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertFalse(os.path.exists(lab.layout.bundle_dir(lab.name, bid)))
        self.assertEqual([x for x in os.listdir(f"{lab.layout.backups}/{lab.name}") if x.startswith(".")], [])
        self.assertTrue(os.path.exists(lab.layout.catalog(lab.name, f"{bid}.pruned")))
        self.assertEqual(lab.docker.inspect("container", [name]), [])

    def test_an_abandon_whose_undo_fails_needs_review_and_refuses_the_next_operation(self) -> None:
        """LIFECYCLE §3.4, §3.5: an abandon, or the auto-abandon the next command makes, whose undo did not complete
        (here: the writers' start is refused) closes `needs-review` (exit 4), never a clean `abandoned`, and the
        command that auto-abandoned it is refused (`needs-review`, exit 2) instead of running on with the writers
        stopped while the record says running."""
        lab = self.lab
        empty = Path(lab.base, "empty-secret")  # fault injection: the undo's Compose call refuses an empty secret
        empty.write_text("")
        bad = lab.variant() | {"secret_files": [str(empty)]}
        stop = step("Stop", "reversible", args={"variant": "current", "services": ["app"], "freeze": True})
        check = task("check", "current", ["true"], effect="read", exit={"0": "ok"})
        seq = lab.seq()
        self.assertEqual(
            lab.crash(
                lab.save("backup", [stop, step("RunTask", "scratch", args=check)], {"current": bad}), "2:intent:after"
            ),
            -signal.SIGKILL,
        )
        code, run = lab.run(lab.backup_plan())  # finds the open backup, auto-abandons it: the undo of the Stop fails
        self.assertEqual((code, run["code"], run["next"]), (2, "needs-review", f"{brand.CLI} status {lab.name}"), run)
        result = lab.result(seq, "backup")
        self.assertEqual((result["outcome"], result["exit"], result["code"]), ("needs-review", 4, "needs-review"))
        self.assertTrue([w for w in result["warnings"] if w.startswith("undo step 1")], result["warnings"])
        self.assertEqual((lab.open_op(), os.path.exists(lab.op_dir(seq + 1, "backup"))), (None, False))
        [c] = lab.docker.containers(project=lab.name)
        self.assertFalse(c["State"]["Running"])  # as the warning says; the record still says running
        self.assertEqual(state.read_doc(lab.layout.record_json(lab.name), "instance")["state"], "running")
        seq = lab.seq()
        self.assertEqual(
            lab.crash(
                lab.save("backup", [stop, step("RunTask", "scratch", args=check)], {"current": bad}), "2:intent:after"
            ),
            -signal.SIGKILL,
        )
        code, run = lab.run(lab.resume_plan("abandon"), "abandon")  # `abandon` closes the same way
        self.assertEqual((code, run["code"]), (4, "needs-review"), run)
        self.assertEqual(lab.result(seq, "backup")["outcome"], "needs-review")
        up = step("Up", "reversible", args={"variant": "current", "services": ["app"], "wait": ["ready"]})
        code, run = lab.run(lab.save("start", [up], {"current": lab.variant()}))  # the review: start the app again
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertTrue(eventually(self.healthy))

    def test_abandon_discards_partial_outputs(self) -> None:
        lab = self.lab
        seq = lab.seq()
        self.assertEqual(lab.crash(lab.backup_plan(), "3:intent:after"), -signal.SIGKILL)
        code, run = lab.run(lab.resume_plan("abandon"), "abandon")
        self.assertEqual((code, run["code"]), (0, "abandoned"), run)
        self.assertEqual(lab.result(seq, "backup")["outcome"], "abandoned")
        self.assertFalse(os.path.exists(f"{lab.op_dir(seq, 'backup')}/stage"))

    # crash matrix: closing, forward-point and resume rules --------------------------------------------------------
    def unwind_plan(self, flag: Path) -> tuple[int, str]:
        """Stop writers, a check that reads `flag`, then a sentinel Record that never runs once the check failed."""
        lab = self.lab
        stop = step("Stop", "reversible", args={"variant": "current", "services": ["app"], "freeze": True})
        check = task("check", "current", ["sh", "-c", "grep -q pass /in/flag"], effect="read", exit={"0": "ok"})
        check |= {"mounts": [["/in", "input:flag"]], "inputs": {"flag": str(flag)}}
        sentinel = step("Record", "idempotent", args={"kind": "state", "state": "stopped"})
        seq = lab.seq()
        return seq, lab.save(
            "restart", [stop, step("RunTask", "scratch", args=check), sentinel], {"current": lab.variant()}
        )

    def assert_closed_once(self, seq: int) -> None:
        code, run = self.lab.run(self.lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (3, "task-failed"), run)
        self.assertNotIn(3, [r["step"] for r in self.lab.journal(seq, "restart")])  # never resumed past the undo
        self.assertEqual(
            [r["attempt"] for r in self.lab.journal(seq, "restart") if r["step"] == 2 and "attempt" in r], [1]
        )
        self.assert_unchanged(seq, "restart")

    def test_a_crash_while_closing_finishes_the_same_close(self) -> None:
        lab = self.lab
        flag = Path(lab.layout.inbox, "flag")
        flag.write_text("fail")
        seq, plan = self.unwind_plan(flag)
        self.assertEqual(lab.crash(plan, "0:done:after"), -signal.SIGKILL)  # decided failed-unchanged, nothing undone
        flag.write_text("pass")  # a resume that redid the check would now pass it and run on with writers running
        self.assert_closed_once(seq)
        flag.write_text("fail")
        seq, plan = self.unwind_plan(flag)
        self.assertEqual(lab.run(plan)[0], 3)
        os.remove(f"{lab.op_dir(seq, 'restart')}/result.json")  # killed after the unwind, before the close was whole
        flag.write_text("pass")
        self.assert_closed_once(seq)

    def test_a_refused_forward_task_changes_nothing(self) -> None:
        lab = self.lab
        seq = lab.seq()
        stop = step("Stop", "reversible", args={"variant": "current", "services": ["app"], "freeze": True})
        migrate = task("migrate", "current", ["sh", "-c", "exit 3"], effect="data", exit={"0": "ok", "3": "refused"})
        steps = [stop, step("RunTask", "forward", forward_point=True, args=migrate)]
        code, run = lab.run(lab.save("deploy", steps, {"current": lab.variant()}))
        self.assertEqual((code, run["code"]), (3, "task-refused"), run)
        self.assert_unchanged(seq, "deploy")

    def test_a_one_step_write_task_never_freezes(self) -> None:
        lab = self.lab
        seq = lab.seq()
        release = task(
            "release", "current", ["sh", "-c", "exit 1"], effect="app-write", exit={"0": "ok", "1": "failed"}
        )
        code, run = lab.run(lab.save("task", [step("RunTask", "forward", args=release)], {"current": lab.variant()}))
        self.assertEqual((code, run["code"]), (3, "task-failed"), run)
        self.assert_unchanged(seq, "task")

    def test_a_failed_deletion_never_freezes(self) -> None:
        lab = self.lab
        seq, name = lab.seq(), f"{lab.name}-kept"
        made = lab.cli("create", "--name", name, "--label", f"{brand.label('instance')}={lab.name}", IMAGE)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.addCleanup(lab.cli, "rm", name)
        [c] = lab.docker.inspect("container", [name])
        item = {"kind": "container", "id": c["Id"], "name": name, "created": "2000-01-01T00:00:00Z"}  # not re-proved
        code, run = lab.run(
            lab.save("prune", [step("Delete", "forward", args={"item": item})], {"current": lab.variant()})
        )
        self.assertEqual((code, run["code"]), (3, "not-owned"), run)
        self.assertTrue(lab.docker.inspect("container", [name]))
        self.assert_unchanged(seq, "prune")

    def test_resume_after_a_crash_in_a_forward_up(self) -> None:
        lab = self.lab
        seq = lab.seq()
        migrate = task("migrate", "current", ["fx-lite", "migrate"], effect="data", exit={"0": "ok"})
        up = {"variant": "current", "services": ["app"], "wait": ["ready"]}
        steps = [step("RunTask", "forward", forward_point=True, args=migrate), step("Up", "forward", args=up)]
        self.assertEqual(lab.crash(lab.save("deploy", steps, {"current": lab.variant()}), "2:intent:after"), -9)
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertEqual(lab.result(seq, "deploy")["outcome"], "completed")

    def test_resume_writes_a_missing_app_env_file_again(self) -> None:
        lab = self.lab
        self.assertEqual(lab.crash(lab.backup_plan(), "1:intent:after"), -signal.SIGKILL)
        os.remove(lab.app_env["path"])  # the open was killed before it wrote the file
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertEqual(hashlib.sha256(Path(lab.app_env["path"]).read_bytes()).hexdigest(), lab.app_env["sha256"])

    def test_an_exited_orphan_decides_its_step_for_later_steps(self) -> None:
        lab = self.lab
        path = lab.layout.record_json(lab.name)
        state.replace_doc(path, state.read_doc(path, "instance") | {"held_since": "2026-01-01T00:00:00Z"})
        seq = lab.seq()
        release = task("release", "current", ["true"], effect="app-write", exit={"0": "ok"})
        record = {"kind": "task", "task": "release", "clears_hold": True, "step": 1}
        steps = [step("RunTask", "forward", args=release), step("Record", "idempotent", args=record)]
        self.assertEqual(lab.crash(lab.save("task", steps, {"current": lab.variant()}), "1:intent:after"), -9)
        name = f"{lab.name}-x{seq}-1-a1"  # the attempt's container, exited 0 and not removed
        labels = {"instance": lab.name, "op": str(seq), "step": "1", "role": "task"}
        flags = [x for k, v in labels.items() for x in ("--label", f"{brand.label(k)}={v}")]
        flags += ["--label", f"{PROJECT_LABEL}={lab.name}"]  # as `compose run` labels it: owned (ARCHITECTURE §7.5)
        self.assertEqual(lab.cli("run", "--name", name, *flags, "--entrypoint", "true", IMAGE).returncode, 0)
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertEqual(lab.docker.inspect("container", [name]), [])
        self.assertIsNone(state.read_doc(path, "instance")["held_since"])
        [done] = [r for r in lab.journal(seq, "task") if r["step"] == 1 and r["phase"] == "done"]
        self.assertEqual(done["evidence"]["orphan"]["exit_code"], 0)

    def test_an_orphan_outside_the_compose_project_is_neither_evidence_nor_removed(self) -> None:
        lab = self.lab
        seq = lab.seq()
        work = task("work", "current", ["true"], effect="read", exit={"0": "ok"})
        plan = lab.save("task", [step("RunTask", "scratch", args=work)], {"current": lab.variant()})
        self.assertEqual(lab.crash(plan, "1:intent:after"), -signal.SIGKILL)
        name = f"{lab.name}-x{seq}-1-a1"  # the op's labels, but no Compose project label: not owned
        labels = {"instance": lab.name, "op": str(seq), "step": "1", "role": "task"}
        flags = [x for k, v in labels.items() for x in ("--label", f"{brand.label(k)}={v}")]
        self.assertEqual(lab.cli("run", "--name", name, *flags, "--entrypoint", "false", IMAGE).returncode, 1)
        self.addCleanup(lab.cli, "rm", name)
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertTrue(lab.docker.inspect("container", [name]))
        [done] = [r for r in lab.journal(seq, "task") if r["step"] == 1 and r["phase"] == "done"]
        self.assertEqual(done["evidence"]["container"], f"{lab.name}-x{seq}-1-a2")

    def test_a_created_but_never_started_orphan_is_no_evidence(self) -> None:
        lab = self.lab
        seq = lab.seq()
        work = task("work", "current", ["sh", "-c", "echo '{\"ran\": true}'"], effect="data", exit={"0": "ok"})
        work |= {"stdout": "json", "expect": {"ran": [True]}}
        plan = lab.save("task", [step("RunTask", "forward", args=work)], {"current": lab.variant()})
        self.assertEqual(lab.crash(plan, "1:intent:after"), -signal.SIGKILL)
        name = f"{lab.name}-x{seq}-1-a1"  # killed between Compose's create and start: state created, ExitCode 0
        labels = {"instance": lab.name, "op": str(seq), "step": "1", "role": "task"}
        flags = [x for k, v in labels.items() for x in ("--label", f"{brand.label(k)}={v}")]
        flags += ["--label", f"{PROJECT_LABEL}={lab.name}"]  # as `compose run` labels it: owned (ARCHITECTURE §7.5)
        self.assertEqual(lab.cli("create", "--name", name, *flags, "--entrypoint", "true", IMAGE).returncode, 0)
        code, run = lab.run(lab.resume_plan(), "resume")
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertEqual(lab.docker.inspect("container", [name]), [])
        [done] = [r for r in lab.journal(seq, "task") if r["step"] == 1 and r["phase"] == "done"]
        self.assertEqual(done["evidence"]["container"], f"{lab.name}-x{seq}-1-a2")  # it really ran, as attempt 2


@unittest.skipIf(SKIP, "needs a scratch Docker daemon")
class FrozenTest(unittest.TestCase):
    def test_failure_after_the_forward_point_freezes(self) -> None:
        lab = Lab("tf")
        self.addCleanup(lab.close)
        self.assertEqual(lab.run(lab.save("deploy", lab.install_steps(), {"candidate": lab.variant()}))[0], 0)
        seq = lab.seq()
        current = lab.variant()
        current["probes"]["never"] = probe("never", "exec", {}, service="app", argv=["false"], timeout=3)
        migrate = task("migrate", "current", ["fx-lite", "migrate"], effect="data", exit={"0": "ok"})
        start = {"variant": "current", "services": ["app"], "wait": ["never"]}
        steps = [step("RunTask", "forward", forward_point=True, args=migrate), step("Up", "forward", args=start)]
        code, run = lab.run(lab.save("deploy", steps, {"current": current}))
        self.assertEqual((code, run["code"]), (3, "probe"), run)
        self.assertEqual(lab.result(seq, "deploy")["outcome"], "failed-frozen")
        rec = state.read_doc(lab.layout.record_json(lab.name), "instance")
        self.assertEqual((rec["state"], rec["open_op"]), ("frozen", None))
        [c] = lab.docker.containers(project=lab.name)
        self.assertFalse(c["State"]["Running"])


class GenerationTest(unittest.TestCase):
    """CreateGeneration without a daemon: a redo replaces its own partial directory; an unmarked one is foreign."""

    def test_redo_replaces_a_partial_directory_and_an_unmarked_one_is_refused(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        layout = state.Layout(f"{tmp.name}/root", f"{tmp.name}/backups")
        plan = new_plan("drill", "gx", "B", [], {}, {}, [])
        op = Op(layout, None, None, plan, "gx", 5, f"{tmp.name}/op", Journal(f"{tmp.name}/op", 5), "")  # type: ignore[arg-type]
        path = layout.data_gen("gx", "data", "t5")
        args = {"store": "data", "gen": "t5", "path": path, "owner": [10001, 10001], "mode": 0o750, "purpose": "drill"}
        gen = Step(1, "CreateGeneration", "scratch", args)
        os.makedirs(path)
        Path(path, "keep").write_text("not ours")
        with self.assertRaises(Refused):
            steps.create_generation(op, gen, EffectToken(5, 1))
        self.assertTrue(os.path.exists(f"{path}/keep"))
        self.assertFalse(os.path.exists(f"{path}.json"))  # no marker claims it, so no undo can delete it
        shutil.rmtree(path)
        steps.create_generation(op, gen, EffectToken(5, 1))
        os.chown(path, 0, 0)  # an attempt killed between mkdir and chown left a root-owned 0700 directory
        os.chmod(path, 0o700)
        steps.create_generation(op, gen, EffectToken(5, 1))
        st = os.stat(path)
        self.assertEqual((st.st_uid, st.st_mode & 0o777, os.listdir(path)), (10001, 0o750, []))


class DeploymentRecordTest(unittest.TestCase):
    """Record{deployment} without a daemon: a field `from` names takes that step's evidence; every other keeps the
    plan's value (a config-only change keeps the write window and the schema it follows)."""

    def test_fields_from_does_not_name_keep_the_plans_values(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        layout, d = state.Layout(f"{tmp.name}/root", f"{tmp.name}/backups"), f"{tmp.name}/op"
        rec = records.new_doc("instance", name="dx", state="running", current_deployment=1, generations={"data": 1})
        state.write_doc_once(layout.record_json("dx"), rec)
        Path(f"{tmp.name}/manifest").write_text("")
        os.makedirs(f"{d}/v")
        Path(f"{d}/v/candidate.env").write_text("")
        kept = {"writes_reopened_at": "2026-01-01T00:00:00Z", "schema": {"expected": 1}, "pre_change_bundle": "b1"}
        args = {"kind": "deployment", "doc": {"seq": 2, **kept}, "state": "running", "variant": "candidate"}
        args |= {"manifest_path": f"{tmp.name}/manifest", "from": {"writes_reopened_at": None, "schema": 3}}
        plan = new_plan("deploy", "dx", "C", [], {}, {"variants": {"candidate": {"override": ""}}}, [])
        op = Op(layout, None, None, plan, "dx", 7, d, Journal(d, 7), f"{d}/v")  # type: ignore[arg-type]
        op.evidence[3] = {"schema": {"expected": 2, "actual": 2}}
        steps.record(op, Step(4, "Record", "idempotent", args), EffectToken(7, 4))
        dep = state.read_doc(layout.deployment_json("dx", 2), "deployment")
        got = (dep["writes_reopened_at"], dep["schema"], dep["pre_change_bundle"])
        self.assertEqual(got, (kept["writes_reopened_at"], {"expected": 2, "actual": 2}, "b1"))


if __name__ == "__main__":
    unittest.main()
