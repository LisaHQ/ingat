"""Suite 4, session loss (ARCHITECTURE §4.2 step 5, §4.4, §4.5, §10.3; LIFECYCLE F5, F15), on a scratch host installed
by the release's install.sh and driven through the real wrapper, the CLI on a pty when it needs typed approval.

fx-lite-slow (tests/data/fx-lite-slow) is fx-lite with a backup task that first waits 12 seconds and three operator
tasks that only wait, so a signal lands while a step is in flight:

- losing the follower never stops the executor: SIGHUP, SIGTERM, SIGINT and SIGKILL of the CLI during a backup (no
  terminal, as a scheduler runs it) and a hung-up terminal, SIGTERM and SIGKILL during a deploy (on a terminal). The
  executor gets no signal and completes the operation; a follower that could react detaches (exit 4, `next: attach`),
  and `attach` follows the operation again;
- real SIGINT, SIGTERM, SIGHUP and SIGQUIT sent to the executor container (`docker kill -s`) each act as a cancel
  request: the operation closes at the next boundary (no later step starts), an interruptible step is stopped,
  reversible steps are undone, and the executor exits by itself; `docker stop` of the executor waits out an atomic
  step well within the executor's two minutes;
- the `cancel` command (refusals leave no trace; a paused install is refused), an atomic step that a cancel request
  does not stop, and Ctrl-C on the follower's terminal: `c` cancels; `d`, a second Ctrl-C or a lost terminal while it
  asks detaches;
- no task container survives the lock: each one died before the operation's result was written, the CLI's own lock
  of a terminal task included; and when the executor is killed outright (`docker kill`, the documented last resort)
  its live task container blocks resume, abandon and every other operation until it is stopped, after which `abandon`
  converges."""

import json
import os
import secrets
import signal
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.store import state
from tests.harness import background, host

CLI = brand.CLI
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
DETACHED = "detached; the operation runs on"
CHOICE = "[d]etach or [c]ancel? "
H: host.ScratchHost
NAME = f"its{secrets.token_hex(3)}"
EXEC = brand.executor_name(NAME)
A = ""  # the one commit of the fixture repository


def setUpModule() -> None:
    global H, A
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    H = host.ScratchHost("sess")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()
    [A] = H.fixture_repo("fx-lite-slow", [{}], base="fx-lite")


def jdoc(text: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(text)
    return doc


class SessionLoss(unittest.TestCase):
    maxDiff = None

    # the instance's files ----------------------------------------------------------------------------------
    def op(self, seq: int, kind: str, *parts: str) -> str:
        return os.path.join(H.layout.op_dir(NAME, seq, kind), *parts)

    def result(self, seq: int, kind: str) -> dict[str, Any] | None:
        path = self.op(seq, kind, "result.json")
        return state.read_doc(path, "result") if os.path.exists(path) else None

    def journal(self, seq: int, kind: str) -> list[dict[str, Any]]:
        return [json.loads(x) for x in Path(self.op(seq, kind, "steps.jsonl")).read_text().splitlines()]

    def step_no(self, seq: int, kind: str, type_: str) -> int:
        steps = state.read_doc(self.op(seq, kind, "plan.json"), "plan")["steps"]
        found: int = next(s["n"] for s in steps if s["type"] == type_)
        return found

    def started(self, seq: int, kind: str, n: int, type_: str) -> bool:
        path = self.op(seq, kind, "progress.log")
        return os.path.exists(path) and f"step {n} {type_}: started" in Path(path).read_text()

    def listing(self, path: str) -> list[str]:
        return sorted(os.listdir(path)) if os.path.isdir(path) else []

    def bundles(self) -> list[str]:
        """The instance's catalog entries."""
        return self.listing(H.layout.catalog_dir(NAME))

    def published(self) -> list[str]:
        """Everything under the instance's directory of the backups root: bundles and partial copies."""
        return self.listing(os.path.dirname(H.layout.bundle_dir(NAME, "x")))

    def set_hours(self, value: str) -> None:
        """The owner's edit of a plain app_env value: the next deploy is a config-only change (LIFECYCLE §4.5)."""
        path = H.layout.inst_toml(NAME)
        lines = [x for x in Path(path).read_text().splitlines() if not x.startswith("SESSION_HOURS")]
        Path(path).write_text("\n".join([*lines, f'SESSION_HOURS = "{value}"']) + "\n")

    # Docker ------------------------------------------------------------------------------------------------
    def app(self) -> dict[str, Any]:
        [c] = host.inspect("container", [f"{NAME}-app-1"])
        return c

    def running(self, container: str) -> bool:
        return any(c["State"]["Running"] for c in host.inspect("container", [container]))

    def task_container(self, seq: int, n: int) -> str:
        return f"{NAME}-x{seq}-{n}-a1"

    def cli_containers(self) -> list[str]:
        """The CLI containers (role cli) of this host's wrapper."""
        ids = host.docker("ps", "-aq", "--no-trunc", "--filter", f"label={brand.label('role')}=cli").split()
        root = f"{brand.env('ROOT')}={H.root}"
        return [c["Id"] for c in host.inspect("container", ids) if root in (c["Config"].get("Env") or [])]

    def op_containers(self, seq: int) -> list[str]:
        own, op = f"label={brand.label('instance')}={NAME}", f"label={brand.label('op')}={seq}"
        return host.docker("ps", "-aq", "--filter", own, "--filter", op).split()

    def watch(self) -> background.EventStream:
        """The container events from now on, once the executor of an earlier command is gone: it may still be exiting
        after its follower read the run file (slower on a busy daemon), and its `die` would land in the new window."""
        self.assertTrue(host.wait_gone(EXEC, 240))
        w = background.EventStream()
        self.addCleanup(w.close)
        return w

    def events_of(self, who: str, w: background.EventStream) -> list[dict[str, Any]]:
        """The container events of `who` (a name or a full ID) that `w` saw."""
        evs = [e for e in w.events() if e.get("Type") == "container"]
        return [e for e in evs if who in (e["Actor"].get("ID"), e["Actor"]["Attributes"].get("name"))]

    # processes ---------------------------------------------------------------------------------------------
    def spawn(self, *args: str, tty: bool = False) -> background.Proc:
        p = background.Proc(["sh", H.wrapper, *args], tty=tty, answer=NAME if tty else None)
        self.addCleanup(p.close)
        return p

    def until(
        self, pred: Callable[[], bool], what: str, p: background.Proc | None = None, timeout: float = 240
    ) -> None:
        end = time.monotonic() + timeout
        while not pred():
            out = f"\n{p.text()}{p.err.decode(errors='replace')}" if p else ""
            if time.monotonic() > end:
                self.fail(f"timed out waiting for {what}{out}")
            if p is None:
                time.sleep(0.2)
            elif p.poll() is not None:
                self.fail(f"the command ended (exit {p.code}) before {what}{out}")
            else:
                p.drain(0.2)

    def in_task(self, p: background.Proc, seq: int, kind: str) -> tuple[int, str]:
        """(step, container) once the operation's first task step runs its container."""
        self.until(lambda: os.path.exists(self.op(seq, kind, "plan.json")), f"operation {seq}", p)
        n = self.step_no(seq, kind, "RunTask")
        name = self.task_container(seq, n)
        self.until(lambda: self.running(name), f"task container {name}", p)
        return n, name

    def in_step(self, p: background.Proc, seq: int, kind: str, n: int, type_: str) -> None:
        self.until(lambda: self.started(seq, kind, n, type_), f"step {n} {type_} of operation {seq}", p)

    # outcomes ----------------------------------------------------------------------------------------------
    def follower_lost(self, p: background.Proc, seq: int, kind: str) -> host.Result:
        """The follower ended; its operation runs on, under its executor."""
        res = p.wait(60)
        self.assertTrue(self.running(EXEC), f"the executor stopped with its follower: {res}")
        self.assertIsNone(self.result(seq, kind), res)
        return res

    def completed(self, seq: int, kind: str, w: background.EventStream, who: str = EXEC) -> None:
        """The operation completed; its executor (`who`) got no signal and exited 0; nothing of it is left."""
        self.assertTrue(host.wait_gone(who, 240))
        res = self.result(seq, kind)
        self.assertEqual((res or {}).get("outcome"), "completed", res)
        evs = self.events_of(who, w)
        self.assertEqual([e for e in evs if e["Action"] == "kill"], [])
        self.assertEqual([e["Actor"]["Attributes"]["exitCode"] for e in evs if e["Action"] == "die"], ["0"])
        self.left_nothing(seq)

    def cancelled(
        self,
        seq: int,
        kind: str,
        last: int,
        phase: str,
        w: background.EventStream,
        sigs: tuple[int, ...] = (),
        who: str = EXEC,
    ) -> None:
        """Closed at the next boundary after the cancel request: step `last` ended `phase` and no later step started;
        the executor (`who`; signalled `sigs` and by nothing else) exited by itself, after every container
        of the operation had died; the instance is back where it was and its lock is free."""
        self.assertTrue(host.wait_gone(who, 240))
        res = self.result(seq, kind)
        self.assertEqual(
            {k: (res or {}).get(k) for k in ("outcome", "exit", "code")},
            {"outcome": "failed-unchanged", "exit": 3, "code": "cancelled"},
            res,
        )
        lines = self.journal(seq, kind)
        self.assertEqual(sorted({x["step"] for x in lines if x["phase"] == "intent"}), list(range(1, last + 1)), lines)
        self.assertEqual([x["phase"] for x in lines if x["step"] == last][-1], phase, lines)
        steps = state.read_doc(self.op(seq, kind, "plan.json"), "plan")["steps"]
        if phase == "cancelled" and next(s for s in steps if s["n"] == last)["type"] == "RunTask":
            evs = self.events_of(self.task_container(seq, last), w)  # an interruptible task: stopped (SIGTERM)
            self.assertIn("15", [e["Actor"]["Attributes"].get("signal") for e in evs if e["Action"] == "kill"], evs)
            self.assertEqual([e["Actor"]["Attributes"]["exitCode"] for e in evs if e["Action"] == "die"], ["143"])
        evs = self.events_of(who, w)
        kills = [e["Actor"]["Attributes"].get("signal") for e in evs if e["Action"] == "kill"]
        self.assertEqual(kills, [str(int(s)) for s in sigs], evs)
        self.assertEqual([e["Actor"]["Attributes"]["exitCode"] for e in evs if e["Action"] == "die"], ["3"], evs)
        closed = os.stat(self.op(seq, kind, "result.json")).st_mtime_ns
        for e in w.events():
            attrs = e.get("Actor", {}).get("Attributes", {})
            if e.get("Type") == "container" and e["Action"] == "die" and attrs.get(brand.label("op")) == str(seq):
                self.assertLessEqual(int(e["timeNano"]), closed, f"{attrs.get('name')} died after the close")
        self.left_nothing(seq)
        rec = H.record(NAME)
        self.assertEqual((rec["open_op"], rec["state"], rec["last_op"]["seq"]), (None, "running", seq), rec)

    def ran_out(self, task: str, w: background.EventStream, seconds: int) -> None:
        """Task container `task` was neither stopped nor killed: it ran its `seconds` and exited 0 (an atomic step)."""
        evs = self.events_of(task, w)
        self.assertEqual([e for e in evs if e["Action"] in ("kill", "stop")], [], evs)
        start = next(int(e["timeNano"]) for e in evs if e["Action"] == "start")
        die = next(e for e in evs if e["Action"] == "die")
        self.assertEqual(die["Actor"]["Attributes"]["exitCode"], "0", die)
        self.assertGreaterEqual(int(die["timeNano"]) - start, (seconds - 1) * 10**9)

    def left_nothing(self, seq: int) -> None:
        """No container of operation `seq` and no CLI container of this host is left."""
        self.until(lambda: not self.op_containers(seq), f"the containers of operation {seq} to go", timeout=30)
        self.until(lambda: not self.cli_containers(), "the CLI containers to go", timeout=60)

    def no_trace(self, *args: str, code: int, why: str) -> dict[str, Any]:
        """A refused command: its exit and code; nothing under instances/ and no Docker object of the instance
        changed (an executor it started has gone)."""
        tree, inv = host.tree_hash(H.layout.instances_dir), host.inventory(NAME)
        res = H.cli(*args, "--json")
        self.assertTrue(host.wait_gone(EXEC))
        doc = jdoc(res[1])
        self.assertEqual((res[0], doc["code"]), (code, why), res)
        self.assertEqual((host.tree_hash(H.layout.instances_dir), host.inventory(NAME)), (tree, inv))
        return doc

    def run_tty(self, *args: str, code: int = 0) -> str:
        res = H.cli(*args, tty=True, answer=NAME)
        self.assertEqual(res[0], code, res[1])
        return res[1]

    def attention(self) -> dict[str, Any]:
        doc: dict[str, Any] = jdoc(H.cli("status", NAME, "--json")[1])["attention"]
        return doc

    # the suite ---------------------------------------------------------------------------------------------
    def test_0_install(self) -> None:
        """The instance every later test uses; a cancel request never reaches a paused install."""
        lines = ["instance = 1", f'name = "{NAME}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
        lines += [f'repo = "{H.repo_url("fx-lite-slow")}"', "[params]", f'FXLITE_IMAGE = "{H.image}"']
        lines += [f'FXLITE_PORT = "{host.free_port()}"', "[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items())]
        cfg = H.inbox(f"{NAME}.toml", "\n".join(lines) + "\n")
        self.run_tty("init", NAME, "--config", cfg, "--ref", A)
        out = self.run_tty("deploy", NAME, A, code=4)
        self.assertIn(f"next: {CLI} resume {NAME}", out)
        doc = self.no_trace("cancel", NAME, code=1, why="wrong-state")  # it would end the resume too
        self.assertEqual(doc["next"], f"{CLI} resume {NAME}  or  {CLI} abandon {NAME}")
        self.assertIn("open-operation", self.attention())
        self.run_tty("resume", NAME)
        self.assertEqual((H.record(NAME)["state"], H.record(NAME)["open_op"]), ("running", None))

    def test_1_follower_lost_during_backup(self) -> None:
        """No terminal, as a scheduler runs it: SIGHUP, SIGTERM and SIGINT of the wrapper's process reach the
        follower, which detaches (ARCHITECTURE §4.4); SIGKILL of the CLI container kills the follower outright. The
        backup completes either way."""
        for how in ("SIGHUP", "SIGTERM", "SIGINT", "SIGKILL"):
            with self.subTest(how=how):
                seq, w, count = state.next_seq(H.layout, NAME), self.watch(), len(self.bundles())
                p = self.spawn("backup", NAME, "--json")
                self.in_task(p, seq, "backup")
                if how == "SIGKILL":
                    [cli] = self.cli_containers()
                    host.docker("kill", cli)
                else:
                    p.kill(getattr(signal, how))
                code, out, err = self.follower_lost(p, seq, "backup")
                if how == "SIGKILL":
                    self.assertEqual(code, 137, (out, err))
                else:
                    doc = jdoc(out)
                    self.assertEqual((code, doc["code"], doc["next"]), (4, "detached", f"{CLI} attach {NAME}"), out)
                if how == "SIGTERM":  # `attach` follows the operation again, to its end
                    res = H.cli("attach", NAME)
                    self.assertEqual(res[0], 0, res)
                    self.assertIn("operation completed", res[1])
                self.completed(seq, "backup", w)
                self.assertEqual(len(self.bundles()), count + 1)

    def test_2_follower_lost_during_deploy(self) -> None:
        """On a terminal: the terminal hangs up (a lost SSH session), or the wrapper's process gets SIGTERM or
        SIGKILL, while a config-only deploy waits for its probes. The executor completes the deploy."""
        for value, how in (("11", "hangup"), ("12", "SIGTERM"), ("13", "SIGKILL")):
            with self.subTest(how=how):
                self.set_hours(value)
                seq, w, before = state.next_seq(H.layout, NAME), self.watch(), self.app()["Id"]
                current = H.record(NAME)["current_deployment"]
                p = self.spawn("deploy", NAME, A, tty=True)
                self.in_step(p, seq, "deploy", 1, "Up")
                if how == "hangup":
                    p.hangup()
                else:
                    p.kill(getattr(signal, how))
                code, out, _ = self.follower_lost(p, seq, "deploy")
                if how == "SIGKILL":
                    self.assertEqual(code, -signal.SIGKILL, out)
                else:  # the wrapper's docker client passes the signal on: the follower detaches
                    self.assertEqual(code, 4, out)
                if how == "SIGTERM":  # a hung-up terminal shows nothing more
                    self.assertIn(f"{DETACHED}\nnext: {CLI} attach {NAME}", out)
                self.completed(seq, "deploy", w)
                rec = H.record(NAME)
                dep = state.read_doc(H.layout.deployment_json(NAME, rec["current_deployment"]), "deployment")
                self.assertEqual((rec["current_deployment"], dep["origin"], dep["op"]), (current + 1, "config", seq))
                app = self.app()
                self.assertNotEqual(app["Id"], before)
                self.assertIn(f"SESSION_HOURS={value}", app["Config"]["Env"])
                self.assertTrue(app["State"]["Running"])

    def test_3_executor_signals(self) -> None:
        """Each real signal to the executor is a cancel request, honoured at the next boundary."""
        # SIGINT during a backup task (scratch, interruptible): the task container is stopped, nothing is published
        seq, w, app = state.next_seq(H.layout, NAME), self.watch(), self.app()
        bundles = self.published()
        p = self.spawn("backup", NAME, "--json")
        n, _ = self.in_task(p, seq, "backup")
        host.docker("kill", "-s", "INT", EXEC)
        code, out, _ = p.wait(120)
        self.assertEqual((code, jdoc(out)["code"]), (3, "cancelled"), out)
        self.cancelled(seq, "backup", n, "cancelled", w, (signal.SIGINT,))
        self.assertEqual(self.published(), bundles)  # no bundle, no partial copy
        self.assertEqual((self.app()["Id"], self.app()["State"]["StartedAt"]), (app["Id"], app["State"]["StartedAt"]))
        self.assertIn("last-op-failed", self.attention())

        # SIGTERM while a config-only deploy waits for its probes (reversible): undone, the recorded config runs
        self.set_hours("21")
        seq, w, app = state.next_seq(H.layout, NAME), self.watch(), self.app()
        current = H.record(NAME)["current_deployment"]
        p = self.spawn("deploy", NAME, A, tty=True)
        self.in_step(p, seq, "deploy", 1, "Up")
        host.docker("kill", "-s", "TERM", EXEC)
        self.assertEqual(p.wait(240)[0], 3, p.text())
        self.cancelled(seq, "deploy", 1, "cancelled", w, (signal.SIGTERM,))
        self.assertEqual(H.record(NAME)["current_deployment"], current)
        self.assertFalse(os.path.exists(H.layout.deployment_json(NAME, current + 1)))
        now = self.app()
        hash_key = "com.docker.compose.config-hash"
        self.assertEqual(now["Config"]["Labels"][hash_key], app["Config"]["Labels"][hash_key])
        self.assertNotIn("SESSION_HOURS=21", now["Config"]["Env"])
        self.assertTrue(now["State"]["Running"])

        # SIGHUP during a read task (scratch, interruptible): stopped at once, not after its 300 seconds
        seq, w = state.next_seq(H.layout, NAME), self.watch()
        p = self.spawn("task", NAME, "slow-read", "--arg", "seconds=300", "--json")
        n, _ = self.in_task(p, seq, "task")
        host.docker("kill", "-s", "HUP", EXEC)
        code, out, _ = p.wait(120)
        self.assertEqual((code, jdoc(out)["code"]), (3, "cancelled"), out)
        self.cancelled(seq, "task", n, "cancelled", w, (signal.SIGHUP,))

        # SIGQUIT while a restart waits for its probes: both steps are undone and the recorded deployment runs
        seq, w, app = state.next_seq(H.layout, NAME), self.watch(), self.app()
        p = self.spawn("restart", NAME, tty=True)
        self.in_step(p, seq, "restart", 2, "Up")
        host.docker("kill", "-s", "QUIT", EXEC)
        self.assertEqual(p.wait(240)[0], 3, p.text())
        self.cancelled(seq, "restart", 2, "cancelled", w, (signal.SIGQUIT,))
        now = self.app()
        self.assertEqual(now["Config"]["Labels"][hash_key], app["Config"]["Labels"][hash_key])
        self.assertTrue(now["State"]["Running"])

        # `docker stop` (SIGTERM, then SIGKILL once its two minutes are up) while an atomic step runs: the step runs
        # to its end, the operation closes at the next boundary, and the executor exits well within the two minutes
        seq, w = state.next_seq(H.layout, NAME), self.watch()
        p = self.spawn("task", NAME, "slow-write", "--arg", "seconds=10", tty=True)
        n, task = self.in_task(p, seq, "task")
        begun = time.monotonic()
        host.docker("stop", EXEC)  # returns once the executor has exited
        self.assertLess(time.monotonic() - begun, 60)
        self.assertEqual(p.wait(60)[0], 3, p.text())
        self.cancelled(seq, "task", n, "done", w, (signal.SIGTERM,))
        self.ran_out(task, w, 10)

    def test_4_cancel(self) -> None:
        """`cancel` and Ctrl-C on the follower's terminal."""
        self.no_trace("cancel", NAME, code=1, why="wrong-state")  # no open operation
        self.no_trace("cancel", "Not_A_Name", code=2, why="usage")
        self.no_trace("cancel", f"its{secrets.token_hex(4)}", code=1, why="unknown-instance")

        # `cancel` writes the operation's cancel file; the running backup task is stopped
        seq, w = state.next_seq(H.layout, NAME), self.watch()
        p = self.spawn("backup", NAME, "--json")
        n, _ = self.in_task(p, seq, "backup")
        res = H.cli("cancel", NAME, "--json")
        doc = jdoc(res[1])
        self.assertEqual(
            (res[0], doc["code"], doc["op"], doc["next"]), (0, "cancel-requested", seq, f"{CLI} attach {NAME}")
        )
        self.assertTrue(os.path.exists(self.op(seq, "backup", "cancel")))
        code, out, _ = p.wait(120)
        self.assertEqual((code, jdoc(out)["code"]), (3, "cancelled"), out)
        self.cancelled(seq, "backup", n, "cancelled", w)

        # an atomic step (an app-write task) runs until its child returns; the operation then stops before the next
        seq, w = state.next_seq(H.layout, NAME), self.watch()
        p = self.spawn("task", NAME, "slow-write", "--arg", "seconds=10", tty=True)
        n, task = self.in_task(p, seq, "task")
        self.assertEqual(H.cli("cancel", NAME, "--json")[0], 0)
        self.assertEqual(p.wait(120)[0], 3, p.text())
        self.cancelled(seq, "task", n, "done", w)
        self.ran_out(task, w, 10)

        # Ctrl-C on the terminal, then `c`: a cancel request; the follower follows on to the close
        seq, w = state.next_seq(H.layout, NAME), self.watch()
        p = self.spawn("backup", NAME, tty=True)
        n, _ = self.in_task(p, seq, "backup")
        p.type("\x03")
        p.wait_for(CHOICE)
        p.type("c\r")
        p.wait_for(f"cancel requested for operation {seq} (backup)")
        self.assertEqual(p.wait(120)[0], 3, p.text())
        self.assertTrue(os.path.exists(self.op(seq, "backup", "cancel")))
        self.cancelled(seq, "backup", n, "cancelled", w)

        # Ctrl-C, then `d`: the follower detaches; the backup completes and `attach` follows it again
        seq, w = state.next_seq(H.layout, NAME), self.watch()
        p = self.spawn("backup", NAME, tty=True)
        self.in_task(p, seq, "backup")
        p.type("\x03")
        p.wait_for(CHOICE)
        p.type("d\r")
        code, out, _ = self.follower_lost(p, seq, "backup")
        self.assertEqual(code, 4, out)
        self.assertIn(DETACHED, out)
        self.assertIn(f"next: {CLI} attach {NAME}", out)
        self.assertFalse(os.path.exists(self.op(seq, "backup", "cancel")))
        res = H.cli("attach", NAME)
        self.assertEqual(res[0], 0, res)
        self.assertIn("operation completed", res[1])
        self.completed(seq, "backup", w)
        self.assertNotIn("last-op-failed", self.attention())

        # while it asks, a second Ctrl-C detaches, and so does a lost terminal; the operation runs on, uncancelled
        seq, w = state.next_seq(H.layout, NAME), self.watch()
        p = self.spawn("task", NAME, "slow-read", "--arg", "seconds=120", tty=True)
        n, _ = self.in_task(p, seq, "task")
        for how in ("Ctrl-C", "hangup"):
            p.type("\x03")
            p.wait_for(CHOICE)
            if how == "hangup":
                p.hangup()
            else:
                p.type("\x03")
            code, out, _ = self.follower_lost(p, seq, "task")
            self.assertEqual(code, 4, out)
            if how == "Ctrl-C":
                self.assertIn(f"{DETACHED}\nnext: {CLI} attach {NAME}", out)
                p = self.spawn("attach", NAME, tty=True)
                p.wait_for(f"step {n} RunTask: started")  # attach prints the operation's progress from its start
        self.assertFalse(os.path.exists(self.op(seq, "task", "cancel")))
        self.assertEqual(H.cli("cancel", NAME)[0], 0)
        self.cancelled(seq, "task", n, "cancelled", w)
        self.no_trace("attach", f"its{secrets.token_hex(4)}", code=1, why="unknown-instance")
        doc = self.no_trace("attach", NAME, code=0, why="no-open-operation")
        self.assertEqual(doc["next"], f"{CLI} status {NAME}")

    def test_5_executor_killed(self) -> None:
        """`docker kill` of the executor (the last resort): the lock goes with it while its task container runs on,
        and that container blocks every operation of the instance until it is stopped (F15)."""
        seq = state.next_seq(H.layout, NAME)
        p = self.spawn("task", NAME, "slow-read", "--arg", "seconds=600", "--json")
        n, task = self.in_task(p, seq, "task")
        host.docker("kill", EXEC)
        code, out, _ = p.wait(60)
        doc = jdoc(out)
        self.assertEqual((code, doc["code"], doc["next"]), (4, "executor-vanished", f"{CLI} status {NAME}"), out)
        self.assertTrue(self.running(task))
        res = H.cli("status", NAME, "--json")
        doc = jdoc(res[1])
        ops = [(o["seq"], o["state"]) for o in doc["instance"]["operations"]]
        self.assertEqual((res[0], ops), (5, [(seq, "interrupted")]), res)
        self.assertIn("open-operation", doc["attention"])
        status_next = doc["next"]  # checked last, so that a wrong one does not hide the rest

        stop = f"docker stop {task}"
        self.assertEqual(self.no_trace("resume", NAME, code=2, why="task-running")["next"], stop)
        self.assertEqual(self.no_trace("abandon", NAME, code=2, why="task-running")["next"], stop)
        self.no_trace("task", NAME, "slow-read", "--arg", "seconds=1", code=2, why="open-operation")
        self.no_trace("backup", NAME, code=2, why="open-operation")
        self.assertTrue(self.running(task))
        last = self.journal(seq, "task")[-1]
        self.assertEqual((last["step"], last["phase"]), (n, "intent"))

        host.docker("stop", task)  # the command the refusals print
        out = self.run_tty("abandon", NAME)
        closed = self.result(seq, "task")
        self.assertEqual((closed or {}).get("outcome"), "abandoned", out)
        self.left_nothing(seq)
        self.assertEqual(H.record(NAME)["open_op"], None)
        self.assertNotIn("open-operation", self.attention())
        # status names the exact command that goes on from that state (LIFECYCLE §3.2, §4.15): while the task
        # container runs, every other command refuses and prints this one (ARCHITECTURE §4.5)
        self.assertEqual(status_next, stop, "status printed a next command that refuses while the task runs")

    def test_6_terminal_task(self) -> None:
        """A terminal task runs in the CLI, which holds the lock itself (ARCHITECTURE §4.1, §4.3). A hung-up terminal
        is a cancel request: the atomic task runs to its end and the CLI closes the operation before its next step.
        A killed wrapper process leaves the CLI container to finish and record the task. Either way the task container
        died before the operation closed and the lock was released."""
        for how in ("hangup", "SIGKILL"):
            with self.subTest(how=how):
                seq, w = state.next_seq(H.layout, NAME), self.watch()
                p = self.spawn("task", NAME, "slow-terminal", "--arg", "seconds=10", tty=True)
                n, task = self.in_task(p, seq, "task")
                p.wait_for("waiting")  # the task's own output, on this terminal
                [cli] = self.cli_containers()
                if how == "hangup":
                    p.hangup()
                else:
                    p.kill(signal.SIGKILL)
                p.wait(60)
                if how == "hangup":  # the kernel hangs up the session: SIGHUP and SIGCONT, passed on to the CLI
                    self.cancelled(seq, "task", n, "done", w, (signal.SIGHUP, signal.SIGCONT), who=cli)
                else:
                    self.completed(seq, "task", w, who=cli)
                self.ran_out(task, w, 10)

    def test_7_terminal_task_cli_killed(self) -> None:
        """The CLI that runs a terminal task is killed: the kernel releases its lock while the task container runs on,
        which blocks resume and abandon until it ends (ARCHITECTURE §4.3, §4.5). Then `status` names the command that
        goes on, and that command converges (LIFECYCLE §3.2, §3.4)."""
        seq = state.next_seq(H.layout, NAME)
        p = self.spawn("task", NAME, "slow-terminal", "--arg", "seconds=15", tty=True)
        _, task = self.in_task(p, seq, "task")
        p.wait_for("waiting")
        [cli] = self.cli_containers()
        host.docker("kill", cli)
        self.assertEqual(p.wait(60)[0], 137, p.text())
        self.assertTrue(self.running(task))
        stop = f"docker stop {task}"
        self.assertEqual(self.no_trace("resume", NAME, code=2, why="task-running")["next"], stop)
        self.assertEqual(self.no_trace("abandon", NAME, code=2, why="task-running")["next"], stop)

        self.until(lambda: not host.present("container", task), f"task container {task} to end", timeout=60)
        res = H.cli("status", NAME, "--json")
        doc = jdoc(res[1])
        ops = [(o["seq"], o["state"]) for o in doc["instance"]["operations"]]
        self.assertEqual((res[0], ops, doc["next"]), (5, [(seq, "interrupted")], f"{CLI} resume {NAME}"), res)
        out = H.cli("resume", NAME, tty=True, answer=NAME)
        closed = self.result(seq, "task")
        self.assertIsNotNone(closed, out[1])
        self.left_nothing(seq)
        self.assertEqual(H.record(NAME)["open_op"], None)
        # the command status printed succeeds: the idempotent terminal task runs again, on this terminal (§4.3)
        self.assertEqual((out[0], (closed or {}).get("outcome")), (0, "completed"), out[1])


if __name__ == "__main__":
    unittest.main()
