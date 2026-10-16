"""T1: start, stop, restart, tasks, resume, abandon and cancel of an fx-lite instance, planned by ops/lifecycle (and
ops/deploy for the install) and run in-process by the executor as `_exec` would (both engines, dt.sh).

The first install runs in setUpClass through the real prepare and deploy plans: it pauses at the fixture's install
pause, the allowed terminal task joins the paused operation (run in this process, as the CLI runs it), and resume
completes it. The fixture repository is a file:// repository under the scratch root's cache/fixtures/ (ADR-0027); the
test adds three tasks to its manifest (a read preview, a slow read task and a slow, non-idempotent write task). The
fixture image is the tool image, named by ID so that prepare finds it without a pull."""

import hashlib
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from ingat import brand
from ingat.core import approval, executor
from ingat.core.plan import Plan
from ingat.model import records
from ingat.model.errors import CannotRun, IngatError, Refused
from ingat.ops import context as cx
from ingat.ops import deploy, lifecycle
from ingat.policy import gate
from ingat.store import state
from tests.harness import host as harness

IMAGE = os.environ.get("INGAT_TEST_IMAGE", "ingat:dev")
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "fx-lite"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main"]
GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
TASKS = """
[tasks.peek]
service = "app"
mode = "run"
argv = ["fx-lite", "queue", "resume"]
effect = "read"
stdout = "json"
expect = { json = { outcome = "preview" } }
exit = { 2 = "ok" }
timeout = "2m"

[tasks.slow]
service = "app"
mode = "run"
argv = ["sh", "-c", "trap 'exit 143' TERM; sleep 60 & wait"]
effect = "read"
timeout = "5m"

[tasks.slow-write]
service = "app"
mode = "run"
argv = ["sh", "-c", "sleep 8; exit 7"]
effect = "app-write"
timeout = "5m"
"""
SKIP = not os.path.exists("/var/run/docker.sock")


def eventually(fn: Callable[[], Any], wait: float = 60.0) -> Any:
    end = time.monotonic() + wait
    while not (value := fn()) and time.monotonic() < end:
        time.sleep(0.5)
    return value


def tree(path: str) -> dict[str, str]:
    out = {}
    for top, dirs, files in os.walk(path):
        for name in dirs + files:
            p = os.path.join(top, name)
            data = Path(p).read_bytes() if name in files else b""
            out[os.path.relpath(p, path)] = f"{os.lstat(p).st_mode} {hashlib.sha256(data).hexdigest()}"
    return out


@unittest.skipIf(SKIP, "needs a scratch Docker daemon")
class LifecycleTest(unittest.TestCase):
    environ: dict[str, str]
    lay: state.Layout
    name: str
    base: str
    port: int
    install: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        u = secrets.token_hex(4)
        cls.base, cls.name, cls.port = f"/srv/tlc{u}", f"tl{u}", harness.free_port()
        root, backups = f"{cls.base}/root", f"{cls.base}/backups"
        for d in (
            f"{root}/cache/docker-config",
            backups,
            f"{cls.base}/facts/etc",
            f"{root}/inbox",
            f"{cls.base}/probe",
        ):
            os.makedirs(d)
        cls.addClassCleanup(cls.close)
        Path(f"{cls.base}/facts/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        for patch in (
            mock.patch.object(brand, "HOST_FACTS_DIR", f"{cls.base}/facts"),
            mock.patch.object(brand, "PROBE_MOUNT", f"{cls.base}/probe"),  # where the wrapper mounts the probe volume
            mock.patch.object(gate, "load_tested", cls.engines),
        ):
            patch.start()
            cls.addClassCleanup(patch.stop)
        cls.environ = {brand.env("ROOT"): root, brand.env("BACKUPS"): backups, brand.env("HOST"): "testhost"}
        ctx = cls.ctx()
        cls.lay = lay = ctx.layout
        state.write_doc_once(lay.host_json, records.new_doc("host", engine_id=ctx.info["ID"], root=root))
        cert = {"kind": "selftest", "result": "PASS", "build": cx.build_facts(ctx)}
        state.write_doc_once(f"{lay.certifications_dir}/x-selftest.json", cert)
        repo = f"{lay.fixtures_dir}/fx-lite"
        os.makedirs(repo)
        subprocess.run([*GIT, "init", "-q", repo], env=GIT_ENV, check=True)
        Path(repo, brand.MANIFEST_FILE).write_text((FIXTURE / "ingat.toml").read_text() + TASKS)
        shutil.copy(FIXTURE / "compose.yaml", repo)
        for args in (["add", "-A"], ["commit", "-q", "-m", "a"]):
            subprocess.run([*GIT, "-C", repo, *args], env=GIT_ENV, check=True)
        commit = subprocess.run([*GIT, "-C", repo, "rev-parse", "HEAD"], env=GIT_ENV, check=True, capture_output=True)
        cls.canary = "Canary" + secrets.token_hex(12)
        os.makedirs(f"{lay.secrets_dir(cls.name)}/env")
        Path(f"{lay.secrets_dir(cls.name)}/env/MAIL_PASSWORD").write_text(cls.canary)
        image = ctx.docker.image(IMAGE)["Id"]  # type: ignore[index]
        lines = ["instance = 1", f'name = "{cls.name}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
        lines += [f'repo = "file://{repo}"', "[params]", f'FXLITE_IMAGE = "{image}"', f'FXLITE_PORT = "{cls.port}"']
        lines += ["[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items())]
        Path(lay.inst_toml(cls.name)).write_text("\n".join(lines) + "\n")
        record = {"name": cls.name, "app": "fx-lite", "environment": "test", "lineage": u * 8, "disposable": False}
        record |= {"state": "registered", "current_deployment": None, "previous_deployment": None, "generations": {}}
        record |= {"held_since": None, "open_op": None, "next_seq": 1, "last_op": None}
        state.write_doc_once(lay.record_json(cls.name), records.new_doc("instance", **record))
        os.makedirs(lay.placeholder(cls.name), 0o555)
        cls.install = cls.first_install(commit.stdout.decode().strip())

    @classmethod
    def first_install(cls, ref: str) -> dict[str, Any]:
        """prepare, then deploy up to the install pause; there start, an unlisted task and a cancel (no executor runs
        a paused operation) are refused and the allowed terminal task joins; resume completes the install."""
        out: dict[str, Any] = {"prepare": cls.exe(cls.plan(deploy.plan_prepare, ref))}
        seq = state.next_seq(cls.lay, cls.name)
        out["deploy"] = cls.exe(cls.plan(deploy.plan_deploy, ref))
        out["refusals"] = []
        for planner, args in ((lifecycle.plan_start, ([],)), (lifecycle.plan_task, ("peek", {}, {}, False))):
            try:
                cls.plan(planner, *args)
            except IngatError as e:
                out["refusals"].append((e.code, e.next))
        try:
            lifecycle.cancel(cls.ctx(), cls.name)
        except Refused as e:
            out["cancel"] = (e.code, e.next, os.path.exists(f"{cls.lay.op_dir(cls.name, seq, 'deploy')}/cancel"))
        Path(cls.lay.inbox, "boot.json").write_text('{"admin": "owner"}\n')
        join = cls.plan(lifecycle.plan_task, "bootstrap-config", {}, {"config": "boot.json"}, False)
        out["join"] = join
        with tempfile.TemporaryFile() as tty:  # stands in for the CLI's terminal: the output is shown, never captured
            sys.stdout.flush()
            saved = os.dup(1)
            os.dup2(tty.fileno(), 1)
            try:
                ctx = cls.ctx()
                out["joined"] = executor.run_in_process(cls.lay, ctx.docker, ctx.compose, join, tty=False)
            finally:
                os.dup2(saved, 1)
                os.close(saved)
            tty.seek(0)
            out["printed"] = tty.read().decode()
        out["journal"] = cls.journal(seq, "deploy")
        out["resume"] = cls.exe(cls.plan(lifecycle.plan_resume), "resume")
        out["seq"] = seq
        return out

    @classmethod
    def close(cls) -> None:
        env = {"PATH": os.environ["PATH"], "HOME": "/root", "DOCKER_CONFIG": f"{cls.base}/root/cache/docker-config"}
        mine = f"label={brand.label('instance')}={cls.name}"
        for kind in ("container", "network"):
            ids = subprocess.run(["docker", kind, "ls", "-aq" if kind == "container" else "-q", "--filter", mine],
                                 env=env, capture_output=True, text=True, check=False).stdout.split()  # fmt: skip
            if ids:
                subprocess.run(["docker", kind, "rm", *(["-f"] if kind == "container" else []), *ids], env=env,
                               capture_output=True, check=False)  # fmt: skip
        shutil.rmtree(cls.base, ignore_errors=True)

    @classmethod
    def engines(cls) -> list[dict[str, str]]:
        server = cls.ctx().version["Server"]
        return [{"engine": ".".join(server["Version"].split(".")[:2]), "arch": server["Arch"]}]

    @classmethod
    def ctx(cls) -> cx.Ctx:
        """A fresh context per command, as the CLI makes one."""
        return cx.make_ctx(cls.environ)

    @classmethod
    def plan(cls, planner: Callable[..., Plan | None], *args: Any) -> Any:
        """Plan the way the CLI does, checking that planning wrote nothing under instances/ and held no secret."""
        before = tree(cls.lay.instances_dir)
        try:
            plan = planner(cls.ctx(), cls.name, *args)
        finally:
            assert tree(cls.lay.instances_dir) == before, "planning wrote under instances/"
        assert plan is None or cls.canary not in str(plan.doc()), "a secret in a plan"
        return plan

    @classmethod
    def exe(cls, plan: Plan, mode: str = "new") -> tuple[int, dict[str, Any]]:
        """`approve` (saved) then `_exec <i> <hash> <run-id> [--resume|--abandon]` in this process."""
        run_id, ctx = secrets.token_hex(8), cls.ctx()
        code = executor.execute(cls.lay, ctx.docker, ctx.compose, approval.save(cls.lay, plan), run_id,
                                resume=mode == "resume", abandon=mode == "abandon")  # fmt: skip
        return code, state.read_doc(cls.lay.run(run_id), "run")

    @classmethod
    def journal(cls, seq: int, kind: str) -> list[dict[str, Any]]:
        lines = Path(cls.lay.op_dir(cls.name, seq, kind), "steps.jsonl").read_bytes().splitlines()
        return [records.loads(line) for line in lines if line]

    def record(self) -> dict[str, Any]:
        return state.read_doc(self.lay.record_json(self.name), "instance")

    def result(self, seq: int, kind: str) -> dict[str, Any]:
        return state.read_doc(f"{self.lay.op_dir(self.name, seq, kind)}/result.json", "result")

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/health", timeout=5) as r:
                return int(r.status) == 200
        except OSError:
            return False

    def app(self) -> dict[str, Any]:
        [c] = self.ctx().docker.containers(labels={brand.label("instance"): self.name}, project=self.name)
        return c

    def tasks(self, seq: int) -> list[str]:
        labels = {brand.label("instance"): self.name, brand.label("op"): str(seq), brand.label("role"): "task"}
        return [c["Name"] for c in self.ctx().docker.containers(labels)]

    def tearDown(self) -> None:
        rec = self.record()
        self.assertEqual((rec["open_op"], rec["state"]), (None, "running"), "a test left the instance changed")

    def test_first_install_pauses_joins_the_allowed_task_and_resumes(self) -> None:
        i, seq = self.install, self.install["seq"]
        self.assertEqual((i["prepare"][0], i["deploy"][0], i["deploy"][1]["code"]), (0, 4, "paused"), i)
        resume = f"{brand.CLI} resume {self.name}  or  {brand.CLI} abandon {self.name}"
        self.assertEqual(i["refusals"], [("open-operation", resume)] * 2)  # start, and a task the pause does not allow
        self.assertEqual(i.get("cancel"), ("wrong-state", resume, False))  # it would end the joined task and resume
        join = i["join"]
        self.assertEqual(
            (join.op_kind, join.approval, join.inputs["into_op"], join.inputs["seq"]), ("task", "C", seq, seq)
        )
        self.assertTrue(join.inputs["foreground"])
        self.assertEqual(join.steps[0].args["inputs"], {"config": f"{self.lay.inbox}/boot.json"})
        self.assertEqual(i["joined"], 0)
        joined = {r["step"]: r for r in i["journal"] if r["phase"] == "done" and r["step"] > 1000}
        self.assertEqual((sorted(joined), joined[1001]["evidence"]["outcome"]), ([1001, 1002], "ok"))
        code = i["printed"].strip().splitlines()[-1].encode()  # the single-use code reached the terminal only
        self.assertGreater(len(code), 10)
        files = [p for p in Path(self.base).rglob("*") if p.is_file() and not p.is_symlink()]
        self.assertEqual([p for p in files if code in p.read_bytes()], [])
        self.assertEqual((i["resume"][0], i["resume"][1]["code"]), (0, "completed"), i["resume"])
        self.assertEqual(self.result(seq, "deploy")["outcome"], "completed")
        rec = self.record()
        self.assertEqual((rec["current_deployment"], rec["generations"]), (1, {"data": 1}))
        self.assertTrue(self.health())

    def test_stop_start_restart(self) -> None:
        plan = self.plan(lifecycle.plan_stop, [])
        self.assertEqual(([s.type for s in plan.steps], plan.approval), (["Stop", "Record"], "C"))
        self.assertEqual(self.exe(plan)[0], 0)
        self.assertEqual(self.record()["state"], "stopped")
        self.assertFalse(self.app()["State"]["Running"])
        self.assertIsNone(self.plan(lifecycle.plan_stop, []))  # already stopped: nothing to do
        plan = self.plan(lifecycle.plan_start, [])
        self.assertEqual([s.type for s in plan.steps], ["Up", "Up", "Record"])
        up, check = plan.steps[0].args, plan.steps[1].args
        self.assertEqual((up["services"], up["wait"]), (["app"], ["ready", "edge-live"]))
        self.assertEqual((check["services"], check["identity"], check["smoke"]), ([], True, True))
        self.assertEqual(plan.inputs["variants"]["current"]["images"], {"app": self.app()["Image"]})  # pinned (F4)
        code, run = self.exe(plan)
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertTrue(self.app()["State"]["Running"] and self.health())
        self.assertIsNone(self.plan(lifecycle.plan_start, []))  # already running the recorded images
        started = self.app()["State"]["StartedAt"]
        plan = self.plan(lifecycle.plan_restart, ["app"])
        self.assertEqual([s.type for s in plan.steps], ["Stop", "Up", "Up", "Record"])
        code, run = self.exe(plan)
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        self.assertNotEqual(self.app()["State"]["StartedAt"], started)
        self.assertTrue(self.health())
        with self.assertRaises(CannotRun) as cm:
            self.plan(lifecycle.plan_start, ["nosuch"])
        self.assertEqual(cm.exception.code, "usage")

    def test_a_foreign_container_in_the_project_refuses_stop_and_restart(self) -> None:
        """Compose stops and starts every container of a service in the project: one that is not the instance's own
        refuses the plan and is never touched (F8)."""
        ghost = f"{self.name}-hand"
        labels = [f"--label=com.docker.compose.project={self.name}", "--label=com.docker.compose.service=app"]
        run = ["docker", "run", "-d", "--name", ghost, *labels, "--entrypoint", "sleep", IMAGE, "600"]
        subprocess.run(run, check=True, capture_output=True)
        self.addCleanup(subprocess.run, ["docker", "rm", "-f", ghost], capture_output=True)
        for planner, services in ((lifecycle.plan_stop, []), (lifecycle.plan_restart, ["app"])):
            with self.subTest(planner=planner.__name__), self.assertRaises(Refused) as cm:
                self.plan(planner, services)
            self.assertEqual((cm.exception.code, f"container {ghost}" in cm.exception.message), ("foreign", True))
        inspect = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", ghost], capture_output=True, text=True
        )
        self.assertEqual(inspect.stdout.strip(), "true")

    def test_read_task_is_class_b(self) -> None:
        seq = state.next_seq(self.lay, self.name)
        plan = self.plan(lifecycle.plan_task, "peek", {}, {}, False)
        step = plan.steps[0]
        self.assertEqual(
            (plan.approval, step.klass, step.interruptible, plan.inputs["foreground"]), ("B", "scratch", True, False)
        )
        self.assertEqual(step.args["variant"], "current")
        code, run = self.exe(plan)
        self.assertEqual((code, run["code"]), (0, "completed"), run)
        done = next(r for r in self.journal(seq, "task") if r["step"] == 1 and r["phase"] == "done")
        self.assertIn('"preview"', Path(done["evidence"]["artifact"]).read_text())
        self.assertEqual(self.plan(lifecycle.plan_task, "peek", {}, {}, True).approval, "B")  # scheduled may run it

    def test_write_tasks_are_class_c_clear_the_hold_and_never_freeze_on_a_refusal(self) -> None:
        rec = self.record() | {"held_since": "2026-10-15T00:00:00Z"}  # the hold a live restore leaves
        state.replace_doc(self.lay.record_json(self.name), rec)
        plan = self.plan(lifecycle.plan_task, "queue-resume", {}, {}, False)
        self.assertEqual((plan.approval, plan.steps[0].klass, plan.steps[0].forward_point), ("C", "forward", False))
        self.assertEqual(plan.steps[1].args, {"kind": "task", "task": "queue-resume", "clears_hold": True, "step": 1})
        self.assertEqual(self.exe(plan)[0], 0)
        self.assertIsNone(self.record()["held_since"])
        seq = state.next_seq(self.lay, self.name)
        plan = self.plan(lifecycle.plan_task, "queue-release-job", {"job": "nosuch"}, {}, False)
        self.assertEqual(plan.steps[0].args["args"], {"job": "nosuch"})
        code, run = self.exe(plan)  # the app refuses: nothing changed, the instance is not frozen
        self.assertEqual((code, run["code"]), (3, "task-refused"), run)
        self.assertEqual(self.result(seq, "task")["outcome"], "failed-unchanged")
        self.assertTrue(self.app()["State"]["Running"] and self.health())

    def test_task_refusals_leave_no_trace(self) -> None:
        big = Path(self.lay.inbox, "big.json")
        big.write_bytes(b"x" * 262145)
        os.symlink("/etc/hostname", f"{self.lay.inbox}/link.json")
        cases: list[tuple[tuple[Any, ...], type[IngatError], str]] = [
            (("nosuch", {}, {}, False), Refused, "unknown-task"),
            (("migrate", {}, {}, False), Refused, "not-operator"),  # operator = false
            (("backup", {}, {}, False), Refused, "not-operator"),  # operator = false, and it mounts a stage
            (("queue-release-job", {}, {}, False), CannotRun, "usage"),
            (("queue-release-job", {"job": "bad job"}, {}, False), Refused, "invalid-arg"),
            (("queue-release-job", {"job": "j", "x": "1"}, {}, False), CannotRun, "usage"),
            (("bootstrap-config", {}, {}, False), CannotRun, "usage"),
            (("bootstrap-config", {}, {"config": "/etc/hostname"}, False), Refused, "unsafe-path"),
            (("bootstrap-config", {}, {"config": "../host.json"}, False), Refused, "unsafe-path"),
            (("bootstrap-config", {}, {"config": "missing.json"}, False), Refused, "missing-input"),
            (("bootstrap-config", {}, {"config": "big.json"}, False), Refused, "too-large"),
            (("bootstrap-config", {}, {"config": "link.json"}, False), Refused, "unsafe-path"),
            (("queue-status", {}, {}, True), CannotRun, "unattended"),  # class C
            (("bootstrap-new-code", {}, {}, True), CannotRun, "unattended"),  # terminal
        ]
        for args, error, code in cases:
            with self.subTest(args=args), self.assertRaises(error) as cm:
                self.plan(lifecycle.plan_task, *args)
            self.assertEqual(cm.exception.code, code, cm.exception.message)
        for planner in (lifecycle.plan_resume, lifecycle.plan_abandon, lifecycle.cancel):
            with self.subTest(planner=planner.__name__), self.assertRaises(Refused) as cm:
                self.plan(planner)
            self.assertEqual(cm.exception.code, "wrong-state")

    def test_cancel_stops_the_open_operation(self) -> None:
        seq, ctx = state.next_seq(self.lay, self.name), self.ctx()
        plan = self.plan(lifecycle.plan_task, "slow", {}, {}, False)
        argv = [sys.executable, "-m", "tests.docker.helpers", self.lay.root, self.lay.backups, self.lay.docker_config]
        run_id = secrets.token_hex(8)
        proc = subprocess.Popen([*argv, approval.save(self.lay, plan), run_id, "new"])  # the executor, as launched
        self.assertTrue(eventually(lambda: self.tasks(seq)))
        report = lifecycle.cancel(ctx, self.name)
        self.assertEqual((report["exit"], report["code"], report["op"]), (0, "cancel-requested", seq))
        self.assertTrue(os.path.exists(f"{self.lay.op_dir(self.name, seq, 'task')}/cancel"))
        self.assertEqual(lifecycle.cancel(ctx, self.name)["op"], seq)  # asking again changes nothing
        self.assertEqual(proc.wait(120), 3)
        run = state.read_doc(self.lay.run(run_id), "run")
        self.assertEqual((run["code"], self.result(seq, "task")["outcome"]), ("cancelled", "failed-unchanged"))
        self.assertTrue(eventually(lambda: not self.tasks(seq)))

    def crash(self, seq: int) -> None:
        """Run the non-idempotent `slow-write` task and SIGKILL the executor while its container runs."""
        plan = self.plan(lifecycle.plan_task, "slow-write", {}, {}, False)
        self.assertEqual((plan.steps[0].klass, plan.steps[0].forward_point), ("forward", False))
        argv = [sys.executable, "-m", "tests.docker.helpers", self.lay.root, self.lay.backups, self.lay.docker_config]
        env = {**os.environ, brand.env("CRASH_AT"): "1:task"}
        done = subprocess.run([*argv, approval.save(self.lay, plan), secrets.token_hex(8), "new"], env=env, check=False)
        self.assertEqual(done.returncode, -signal.SIGKILL)
        for planner in (lifecycle.plan_resume, lifecycle.plan_abandon):
            with self.subTest(planner=planner.__name__), self.assertRaises(CannotRun) as cm:
                self.plan(planner)  # the task container still runs (F15)
            self.assertEqual(cm.exception.code, "task-running")
        self.assertTrue(eventually(lambda: not self.tasks(seq)))  # exited and removed: no evidence of its outcome

    def test_a_crashed_write_task_abandons_or_closes_needs_review_never_repeated(self) -> None:
        seq = state.next_seq(self.lay, self.name)
        self.crash(seq)
        code, run = self.exe(self.plan(lifecycle.plan_abandon), "abandon")
        self.assertEqual((code, run["code"]), (0, "abandoned"), run)
        self.assertEqual(self.result(seq, "task")["outcome"], "abandoned")
        self.assertEqual(self.record()["state"], "running")  # an app-write task never freezes (LIFECYCLE §3.5)
        seq += 1
        self.crash(seq)
        code, run = self.exe(self.plan(lifecycle.plan_resume), "resume")
        self.assertEqual((code, run["code"]), (4, "needs-review"), run)  # closed, the instance not blocked (§3.5)
        self.assertEqual(self.result(seq, "task")["outcome"], "needs-review")
        intents = [r for r in self.journal(seq, "task") if r["step"] == 1 and r["phase"] == "intent"]
        self.assertEqual(len(intents), 1)  # never repeated blind (F5)
        self.assertTrue(self.health())


if __name__ == "__main__":
    unittest.main()
