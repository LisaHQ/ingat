"""T1: the core's safety floors against a real daemon with the fx-lite fixture (both engines, dt.sh): no secret in
any file the executor writes (F12), terminal output streamed only, task containers never left running behind a
closed operation (F15), owned-only deletion and probing (F8), isolation (F13), bind sources without links, and no
trace of a refusal (F2). Plans are hand-built by tests.docker.helpers the way a planner renders them."""

import os
import signal
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from ingat import brand
from ingat.core import approval, executor, steps
from ingat.core.plan import PROJECT_LABEL
from ingat.model.errors import Failed
from tests.docker.helpers import IMAGE, LabTest, allocations, eventually, secret_files, step, task, tree_hash

SKIP = not os.path.exists("/var/run/docker.sock")


@unittest.skipIf(SKIP, "needs a scratch Docker daemon")
class FloorTest(LabTest):
    TAG = "tg"

    def test_captured_output_never_holds_a_secret(self) -> None:
        """A failing task prints the app env secret and a file secret (stored with a final newline) to stdout and
        stderr; the report, artifact, journal, result and run file hold neither (tearDown sweeps every file)."""
        lab = self.lab
        seq = lab.seq()
        script = 'v=$(cat /in/tok); printf \'{"t": "%s", "p": "%s"}\' "$v" "$MAIL_PASSWORD"; echo "$v" >&2; exit 1'
        leak = task("leak", "current", ["sh", "-c", script], effect="read", exit={"0": "ok"}, stdout="record")
        leak |= {"mounts": [["/in", "input:tok"]], "inputs": {"tok": f"{lab.layout.inbox}/tok"}}
        files = [lab.secret_file, self.token_file]
        plan = lab.save("task", [step("RunTask", "scratch", args=leak)], {"current": lab.variant()}, redact_files=files)
        code, run = lab.run(plan)
        self.assertEqual((code, run["code"]), (3, "task-failed"), run)
        [report] = [f for f in os.listdir(lab.layout.reports_dir(lab.name)) if f.startswith(f"{seq}-1-")]
        self.assertEqual(Path(lab.layout.reports_dir(lab.name), report).read_text(), '{"t": "***", "p": "***"}')
        self.assertTrue(run["message"].endswith("***"), run)

    def test_terminal_output_is_streamed_only(self) -> None:
        """A foreground `stdout = "terminal"` task: its output reaches the terminal, no file, and no logging driver."""
        lab = self.lab
        seq = lab.seq()
        argv = ["sh", "-c", "sleep 3; od -An -N16 -tx1 /dev/urandom | tr -d ' \\n'; echo"]
        show = task("show", "current", argv, effect="read", exit={"0": "ok"}, stdout="terminal")
        saved = lab.save("task", [step("RunTask", "scratch", args=show)], {"current": lab.variant()}, foreground=True)
        plan = approval.load(lab.layout, saved)
        drivers: list[str] = []

        def watch() -> None:
            labels = {brand.label("instance"): lab.name, brand.label("op"): str(seq)}
            found = eventually(lambda: lab.docker.containers(labels), 30)
            drivers.extend(c["HostConfig"]["LogConfig"]["Type"] for c in found or [])

        watcher = threading.Thread(target=watch)
        watcher.start()
        with tempfile.TemporaryFile() as tty:  # stands in for the CLI's terminal
            sys.stdout.flush()
            fd = os.dup(1)
            os.dup2(tty.fileno(), 1)
            try:
                code = executor.run_in_process(lab.layout, lab.docker, lab.compose, plan, tty=False)
            finally:
                os.dup2(fd, 1)
                os.close(fd)
            tty.seek(0)
            printed = tty.read().decode().split()
        watcher.join()
        self.assertEqual((code, drivers), (0, ["none"]))
        self.assertEqual(len(printed[-1]), 32, printed)
        self.assertEqual(secret_files(lab, [printed[-1]]), [])

    def cancel_once_running(self, seq: int) -> None:
        if eventually(lambda: self.lab.labelled(op=str(seq))):
            Path(self.lab.op_dir(seq, "task"), "cancel").touch()

    def test_a_task_container_that_cannot_be_stopped_keeps_the_operation_open(self) -> None:
        """F15: when `docker stop` fails after a timeout or a cancel, the lock may go but the operation stays open,
        so the next command's orphan check sees the container; it never closes as if the task were over."""
        lab = self.lab
        for how in ("timeout", "cancel"):
            seq = lab.seq()
            slow = task("slow", "current", ["sleep", "300"], effect="read", exit={"0": "ok"})
            slow["timeout"] = 3 if how == "timeout" else 600
            only = [step("RunTask", "scratch", interruptible=True, args=slow)]
            plan = lab.save("task", only, {"current": lab.variant()})
            name = f"{lab.name}-x{seq}-1-a1"
            if how == "cancel":
                threading.Thread(target=self.cancel_once_running, args=(seq,)).start()
            with mock.patch.object(lab.docker, "stop", side_effect=Failed("docker stop failed: busy", code="docker")):
                code, run = lab.run(plan)
            self.assertEqual((code, run["code"], run["next"]), (4, "task-running", f"docker stop {name}"), run)
            self.assertEqual(lab.open_op()["seq"], seq)  # type: ignore[index]
            self.assertTrue(lab.docker.inspect("container", [name])[0]["State"]["Running"])
            code, run = lab.run(lab.resume_plan("abandon"), "abandon")  # the orphan check refuses while it runs
            self.assertEqual((code, run["code"], run["next"]), (2, "task-running", f"docker stop {name}"), run)
            self.assertEqual(lab.cli("stop", "-t", "1", name).returncode, 0)
            self.assertTrue(eventually(lambda: not lab.docker.inspect("container", [name])))  # noqa: B023
            code, run = lab.run(lab.resume_plan("abandon"), "abandon")
            self.assertEqual((code, run["code"]), (0, "abandoned"), run)

    def bundle(self) -> str:
        seq = self.lab.seq()
        self.assertEqual(self.lab.run(self.lab.backup_plan())[0], 0)
        seal = next(r for r in self.lab.journal(seq, "backup") if r["step"] == 3 and r["phase"] == "done")
        return str(seal["evidence"]["bundle_id"])

    def test_resume_or_abandon_of_a_drill_whose_isolated_app_runs(self) -> None:
        """F13, LIFECYCLE §3.4: a drill killed while its isolated app runs on the drill generation, in the restore
        group's Up or in a check after the group. Resume takes the isolated project down and redoes from the restore
        group (the generation it discards is in use until then; the check needs the app again); abandon tears down."""
        lab = self.lab
        bid = self.bundle()
        for mode, at in (("resume", "4:done:before"), ("resume", "5:intent:after"), ("abandon", "5:intent:after")):
            seq, plan = lab.drill_plan(bid, check=["fx-lite", "probe", "http://app:3000/api/health"])
            self.assertEqual(lab.crash(plan, at), -signal.SIGKILL)
            self.assertTrue(lab.labelled(op=str(seq)))
            code, run = lab.run(lab.resume_plan(mode), mode)
            self.assertEqual((code, run["code"]), (0, "completed" if mode == "resume" else "abandoned"), (at, run))
            self.assertEqual(lab.labelled(op=str(seq)), [])
            self.assertFalse(os.path.exists(lab.layout.data_gen(lab.name, "data", f"t{seq}")))
            self.assertEqual(allocations(lab), [])
            restores = [r["attempt"] for r in lab.journal(seq, "drill") if r["phase"] == "intent" and r["step"] == 2]
            self.assertEqual(restores, [1, 2] if mode == "resume" else [1], at)  # a resume restores into a fresh one
            lines = Path(lab.layout.verification(lab.name, bid)).read_text().splitlines()
            self.assertEqual(any(f'"op":{seq}' in x and '"ok":true' in x for x in lines), mode == "resume", at)

    def test_a_drill_teardown_never_takes_a_foreign_container_down(self) -> None:
        """F8: `down` acts on the whole isolated project, so right before it every container in it must carry this
        operation's labels; a foreign one posing as its service is neither stopped nor removed, and the close needs
        review (the refused teardown leaves the drill's subnet entry, removed here by hand)."""
        lab = self.lab
        bid = self.bundle()
        seq, name = lab.seq(), f"{lab.name}-intruder"
        flags = ["--label", f"{PROJECT_LABEL}={lab.name}--t{seq}", "--label", f"{steps.SERVICE_LABEL}=app"]
        made = lab.cli("run", "-d", "--name", name, *flags, "--entrypoint", "sleep", IMAGE, "300")
        self.assertEqual(made.returncode, 0, made.stderr)
        self.addCleanup(lab.cli, "rm", "-f", name)
        code, run = lab.run(lab.drill_plan(bid, restore=["sh", "-c", "exit 1"])[1])
        self.assertEqual((code, run["code"], lab.result(seq, "drill")["outcome"]), (4, "task-failed", "needs-review"))
        self.assertTrue(lab.docker.inspect("container", [name])[0]["State"]["Running"])
        self.assertFalse(os.path.exists(lab.layout.data_gen(lab.name, "data", f"t{seq}")))  # undone all the same
        for entry in allocations(lab):  # the refused teardown keeps its subnet entry for the review
            os.remove(os.path.join(lab.layout.allocations_dir, entry))

    def test_teardown_never_takes_down_a_live_project(self) -> None:
        lab = self.lab
        teardown = step("Teardown", "scratch", always=True, args={"variant": "current"})
        code, run = lab.run(lab.save("drill", [teardown], {"current": lab.variant()}))
        self.assertEqual((code, run["code"]), (4, "not-isolated"), run)  # its retry in the unwind refused too: review
        [c] = lab.docker.containers(project=lab.name)
        self.assertTrue(c["State"]["Running"])

    def test_a_container_outside_its_compose_project_is_not_deleted(self) -> None:
        lab = self.lab
        name = f"{lab.name}-stray"  # the instance label alone does not make it owned (ARCHITECTURE §7.5)
        made = lab.cli("create", "--name", name, "--label", f"{brand.label('instance')}={lab.name}", IMAGE)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.addCleanup(lab.cli, "rm", name)
        [c] = lab.docker.inspect("container", [name])
        item = {"kind": "container", "id": c["Id"], "name": name, "created": c["Created"]}
        code, run = lab.run(lab.save("prune", [step("Delete", "forward", args={"item": item})], {}))
        self.assertEqual((code, run["code"]), (3, "not-owned"), run)
        self.assertTrue(lab.docker.inspect("container", [name]))

    def test_probes_never_exec_into_a_foreign_container(self) -> None:
        """A container that carries only the instance's Compose project and service labels is foreign (F8)."""
        lab = self.lab
        name = f"{lab.name}-foreign"
        flags = ["--label", f"{PROJECT_LABEL}={lab.name}", "--label", f"{steps.SERVICE_LABEL}=app"]
        made = lab.cli("run", "-d", "--name", name, *flags, "--entrypoint", "sleep", IMAGE, "300")
        self.assertEqual(made.returncode, 0, made.stderr)
        self.addCleanup(lab.cli, "rm", "-f", name)
        current = lab.variant()
        current["probes"]["ready"]["timeout"] = 20
        check = {"variant": "current", "services": [], "wait": ["ready"], "identity": True}
        code, run = lab.run(lab.save("start", [step("Up", "scratch", args=check)], {"current": current}))
        self.assertEqual((code, run["code"]), (0, "completed"), run)

    def test_a_restart_on_undo_checks_the_bind_sources_first(self) -> None:
        """Undo brings stopped writers back with `compose up`, so it checks every bind source for links like Up. The
        undo that did not happen leaves the writers stopped while the record says running: the close needs review."""
        lab = self.lab
        seq = lab.seq()
        link = f"{lab.base}/sock"  # an app that swapped a bind source in its own data for a link to the socket
        os.symlink("/var/run/docker.sock", link)
        self.addCleanup(os.remove, link)
        start = step("Up", "reversible", args={"variant": "plain", "services": ["app"], "wait": ["ready"]})
        self.addCleanup(lambda: lab.run(lab.save("start", [start], {"plain": lab.variant()})))  # back for the others
        bad = lab.variant()
        bad["binds"].append(link)
        stop = step("Stop", "reversible", args={"variant": "current", "services": ["app"], "freeze": True})
        failing = step("RunTask", "scratch", args=task("check", "plain", ["false"], effect="read", exit={"0": "ok"}))
        code, run = lab.run(lab.save("restart", [stop, failing], {"current": bad, "plain": lab.variant()}))
        self.assertEqual((code, run["code"], lab.result(seq, "restart")["outcome"]), (4, "task-failed", "needs-review"))
        warnings = lab.result(seq, "restart")["warnings"]
        self.assertTrue(any("is a symbolic link" in w for w in warnings), warnings)
        [c] = lab.docker.containers(project=lab.name)
        self.assertFalse(c["State"]["Running"])

    def test_secret_files_are_checked_before_a_container_is_made(self) -> None:
        """ARCHITECTURE §9.4: right before a Compose call that creates a container, each secret file the variant uses
        must be a regular, non-empty file, never followed; otherwise the step refuses before it runs anything."""
        lab = self.lab
        base = f"{lab.base}/secretcheck"
        os.makedirs(f"{base}/dir")
        Path(f"{base}/empty").touch()
        os.symlink(self.token_file, f"{base}/link")  # its target is a good secret file
        work = step("RunTask", "scratch", args=task("work", "current", ["true"], effect="read", exit={"0": "ok"}))
        for bad in ("dir", "empty", "link", "missing", None):
            seq, v = lab.seq(), lab.variant() | {"secret_files": [self.token_file, *([f"{base}/{bad}"] if bad else [])]}
            code, run = lab.run(lab.save("task", [work], {"current": v}))
            self.assertEqual((code, run["code"]), (3, "secret-file") if bad else (0, "completed"), run)
            [ev] = [
                r.get("evidence", {}) for r in lab.journal(seq, "task") if r["step"] == 1 and r["phase"] != "intent"
            ]
            self.assertEqual("container" in ev, bad is None)  # a refused attempt made no task container
        up = step("Up", "reversible", args={"variant": "bad", "services": ["app"], "wait": ["ready"]})
        bad_v = lab.variant() | {"secret_files": [f"{base}/dir"]}
        code, run = lab.run(lab.save("start", [up], {"bad": bad_v, "current": lab.variant()}))
        self.assertEqual((code, run["code"]), (3, "secret-file"), run)
        self.assertTrue(eventually(lambda: lab.docker.containers(project=lab.name)[0]["State"]["Running"]))

    def test_up_recreates_a_container_that_runs_without_its_published_port(self) -> None:
        """A start that failed on a port conflict leaves a container `up` only starts again once the port is free,
        which Engine 29.9.0 then runs without the port it binds: the Up step recreates it, so its probes reach the app.
        A container that publishes its ports is never recreated."""
        lab, blocker = self.lab, f"{self.lab.name}-blocker"
        [app] = lab.docker.containers(project=lab.name)
        self.addCleanup(lab.cli, "rm", "-f", blocker)
        self.assertEqual(lab.cli("stop", app["Id"]).returncode, 0)
        port = ["-p", f"127.0.0.1:{lab.port}:9"]
        hold = lab.cli("run", "-d", "--name", blocker, *port, "--entrypoint", "sleep", IMAGE, "600")
        self.assertEqual(hold.returncode, 0, hold.stderr)
        start = lab.cli("start", app["Id"])
        self.assertIn("already allocated", start.stderr)
        self.assertEqual(lab.cli("rm", "-f", blocker).returncode, 0)
        up = step("Up", "reversible", args={"variant": "current", "services": ["app"], "wait": ["edge-live"]})
        published = []
        for _ in range(2):
            code, run = lab.run(lab.save("start", [up], {"current": lab.variant()}))
            self.assertEqual((code, run["code"]), (0, "completed"), run)
            [c] = lab.docker.containers(project=lab.name)
            self.assertEqual(c["NetworkSettings"]["Ports"]["3000/tcp"][0]["HostPort"], str(lab.port))
            published.append(c["Id"])
        self.assertEqual(published[0], published[1])  # running and published: left as it is

    def test_a_refusal_while_opening_leaves_no_trace(self) -> None:
        """F2: a refusal found while the operation directory is being written, after its subnet was allocated, and a
        Compose env value that cannot be single-quoted: nothing stays under instances/ and no allocation stays."""
        lab = self.lab
        seq = lab.seq()
        drill = lab.variant(isolated=True, seq=seq)
        record = step("Record", "idempotent", args={"kind": "state", "state": "running"})
        outside = {f"{lab.base}/elsewhere.env": "A='b'\n"}  # inputs.files must lie inside the operation directory
        bad = drill | {"env": {"X": "it's"}}
        plans = [(lab.save("drill", [record], {"drill": drill}, files=outside), "internal")]
        plans.append((lab.save("drill", [record], {"drill": bad}), "unsafe-value"))
        for plan, code in plans:
            before = tree_hash(lab.layout.inst(lab.name))
            self.assertEqual(lab.run(plan)[1]["code"], code)
            self.assertEqual((tree_hash(lab.layout.inst(lab.name)), allocations(lab)), (before, []))
            self.assertFalse(os.path.exists(f"{lab.base}/elsewhere.env"))


if __name__ == "__main__":
    unittest.main()
