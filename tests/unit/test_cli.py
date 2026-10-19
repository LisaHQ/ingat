"""T0: the command line without a daemon: parsing, rendering, approval and the no-trace refusals, the chaining of
prepare before deploy, scheduled jobs, and the follower against a stand-in Docker (contract §17, §21)."""

import contextlib
import dataclasses
import io
import json
import os
import shutil
import signal
import tempfile
import unittest
from typing import Any
from unittest import mock

from ingat import __version__, brand
from ingat.cli import commands, follow, render
from ingat.core.executor import Res
from ingat.core.journal import PROGRESS
from ingat.core.plan import Plan, new_plan
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.ops import context as cx
from ingat.ops import deploy
from ingat.store import state

NAME = "lite-test"
C_WORDS = "changes the app; you must type the instance name to approve"  # class C in the plan summary head
DONE = Res(0, "completed", "completed", 1, None)  # what the in-process executor answers
STALE = Res(1, "stale-plan", f"{NAME} changed since this plan was made; plan again", None, None)


def ctrl_c() -> None:
    raise KeyboardInterrupt


def plan(layout: state.Layout, kind: str = "deploy", approval: str = "C", **inputs: Any) -> Plan:
    steps = [
        {"type": "Obtain", "klass": "scratch", "args": {"images": [{"ref": "sha256:ab", "services": ["app"]}]}},
        {"type": "RunTask", "klass": "forward", "forward_point": True, "args": {"task": "migrate", "effect": "data"}},
        {"type": "Record", "klass": "idempotent", "args": {"kind": "deployment"}},
    ]
    inputs = {"seq": 1, "op_dir": layout.op_dir(NAME, 1, kind), "release": "r1"} | inputs
    command = [brand.CLI, *(["scheduled"] if kind == "backup" else []), kind, NAME]
    return new_plan(kind, NAME, approval, command, {}, inputs, steps)


class FakeDocker:
    """Launches nothing: records the launch and plays the executor (progress, run file) when `finish`."""

    def __init__(self, layout: state.Layout, *, finish: bool = True, alive: bool = False) -> None:
        self.layout, self.finish, self.alive, self.launched = layout, finish, alive, list[dict[str, Any]]()
        self.outcome = {"exit": 0, "code": "completed", "message": "completed"}  # what the run file says

    def launch_executor(self, **kw: Any) -> str:
        self.launched.append(kw)
        op_dir = self.layout.op_dir(NAME, 1, "deploy")
        os.makedirs(op_dir, exist_ok=True)
        with open(os.path.join(op_dir, PROGRESS), "ab") as f:
            f.write(b"t step 1 Obtain: started\nt step 1 Obtain: done\nt partial")
        if self.finish:
            run_id = kw["args"][3]
            doc = records.new_doc("run", run_id=run_id, **self.outcome, op=1)
            state.write_doc_once(self.layout.run(run_id), doc | {"next": None})
        return "c0ffee"

    def inspect(self, kind: str, ids: list[str]) -> list[dict[str, Any]]:
        return [{"Id": ids[0], "State": {"Running": True}, "Config": {"Cmd": []}}] if self.alive else []


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.layout = state.Layout(f"{self.tmp}/root", f"{self.tmp}/backups")
        self.docker = FakeDocker(self.layout)
        self.ctx = cx.Ctx(self.layout, self.docker, None, "sha256:" + "1" * 64, "op", "host1")  # type: ignore[arg-type]
        self.tty = False
        for patch in (
            mock.patch.object(
                commands.cx, "make_ctx", lambda environ, tty=False: dataclasses.replace(self.ctx, tty=tty)
            ),
            mock.patch.object(commands, "_tty", lambda: self.tty),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def main(self, *argv: str, typed: str = "") -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch("sys.stdin", io.StringIO(typed)),
        ):
            code = commands.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def plans(self) -> list[str]:
        return os.listdir(self.layout.plans_dir) if os.path.isdir(self.layout.plans_dir) else []


class ParseTest(unittest.TestCase):
    def parse(self, *argv: str) -> Any:
        return commands.parser().parse_args(list(argv))

    def test_commands(self) -> None:
        a = self.parse("deploy", NAME, "abc", "--json")
        self.assertEqual((a.cmd, a.instance, a.ref, a.json, a.scheduled), ("deploy", NAME, "abc", True, False))
        a = self.parse("--json", "status")
        self.assertEqual((a.cmd, a.instance, a.json), ("status", None, True))
        self.assertFalse(hasattr(self.parse("list"), "json"))
        a = self.parse("task", NAME, "queue-release-job", "--arg", "job=j1", "--input", "config=c.json")
        self.assertEqual((a.task, a.arg, a.input), ("queue-release-job", ["job=j1"], ["config=c.json"]))
        a = self.parse("scheduled", "verify", NAME, "--latest", "--restore-test")
        self.assertEqual(
            (a.cmd, a.job, a.latest, a.restore_test, a.scheduled), ("scheduled", "verify", True, True, True)
        )
        a = self.parse("backup", NAME, "--class", "manual", "--reason", "before upgrade", "--prune")
        self.assertEqual((a.klass, a.reason, a.prune), ("manual", "before upgrade", True))
        self.assertEqual(self.parse("host", "init").what, "init")
        a = self.parse("init", NAME, "--config", "/x.toml", "--ref", "main")
        self.assertEqual((a.cmd, a.config, a.ref), ("init", "/x.toml", "main"))
        a = self.parse("_exec", "--host", "h", "r")
        self.assertEqual((a.host, a.words, a.resume), (True, ["h", "r"], False))
        a = self.parse("_exec", NAME, "h", "r", "--resume")
        self.assertEqual((a.host, a.words, a.resume, a.abandon), (False, [NAME, "h", "r"], True, False))
        self.assertEqual(self.parse("stop", NAME, "app", "worker").services, ["app", "worker"])

    def test_usage_errors(self) -> None:
        for argv in (["deploy", NAME], ["selftest", "--host", "--offline"], ["prune", NAME], ["nope"], []):
            with self.assertRaises(CannotRun) as cm:
                self.parse(*argv)
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("usage", 2), argv)

    def test_every_table_command_parses(self) -> None:
        args = {"init": ["x", "--config", "c", "--ref", "r"], "logs": ["x", "app"], "validate": ["d"]}
        args |= {k: ["x", "r"] for k in ("prepare", "deploy")} | {"task": ["x", "t"], "prune": ["x", "--bundles"]}
        args |= {"scheduled": ["status"], "version": [], "list": [], "status": [], "selftest": []}
        args |= {"host init": [], "host check": []}
        for key in commands.COMMANDS:
            words = key.split() + args.get(key, ["x"])
            a = self.parse(*words)
            self.assertEqual(f"host {a.what}" if a.cmd == "host" else a.cmd, key)
            self.assertIn(key, commands.HANDLERS if key != "version" else {"version"})


class RenderTest(unittest.TestCase):
    def test_plan_summary(self) -> None:
        p = plan(state.Layout("/r", "/b"), warnings=["Engine 30.0 is not tested"])
        lines = render.plan_summary(p)
        self.assertEqual(lines[0], f"deploy {NAME} at r1: approval class C ({C_WORDS}), 3 step(s)")
        self.assertEqual(lines[1], "  1. Obtain (get the app's images) images=sha256:ab  [scratch]")
        forward = "forward point: cannot be undone after this step; if it fails, the app is kept stopped so your data "
        forward += "stays safe"
        self.assertEqual(lines[2], f"  2. RunTask (run an app task) task=migrate effect=data  [forward, {forward}]")
        self.assertEqual(lines[-1], "warning: Engine 30.0 is not tested")

    def test_plan_summary_of_a_resume_or_abandon_names_the_open_operation(self) -> None:
        inputs = {"seq": 3, "op_dir": "/r/i/ops/3-deploy", "into_op": 3, "warnings": ["w"]}
        words = {"resume": "continues unfinished", "abandon": "gives up, undoes what it can and closes unfinished"}
        for kind, what in words.items():
            p = new_plan(kind, NAME, "C", [brand.CLI, kind, NAME], {}, inputs, [])
            lines = render.plan_summary(p)
            head = f"{kind} {NAME}: approval class C ({C_WORDS}), {what} operation 3"
            self.assertEqual(lines, [head, "warning: w"])
            self.assertNotIn("0 step", "\n".join(lines))

    def test_report_and_error(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = render.report({"exit": 3, "code": "failed", "next": "x status y", "lines": ["it failed"]}, False)
        self.assertEqual((code, out.getvalue()), (3, ""))
        self.assertEqual(err.getvalue(), f"{brand.CLI}: it failed\nnext: x status y\n")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rep = {"exit": 4, "code": "paused", "next": f"x resume {NAME}", "lines": ["paused: run the bootstrap"]}
            code = render.report(rep, False)
        want = f"paused: run the bootstrap\nnext: x resume {NAME}\n"  # exit 4 kept; stdout, no `<cli>:` prefix
        self.assertEqual((code, out.getvalue(), err.getvalue()), (4, want, ""))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = render.report({"exit": 4, "code": "detached", "next": "x attach y", "lines": ["detached"]}, False)
        self.assertEqual((code, out.getvalue(), err.getvalue()), (4, "", f"{brand.CLI}: detached\nnext: x attach y\n"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = render.error(Refused("no such thing", code="unknown-instance", next="x list"), True)
        doc = json.loads(out.getvalue())
        self.assertEqual(
            (code, doc), (1, {"exit": 1, "code": "unknown-instance", "message": "no such thing", "next": "x list"})
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(render.report({"exit": 5, "code": "attention", "lines": ["held"], "data": 1}, True), 5)
        self.assertEqual(json.loads(out.getvalue()), {"exit": 5, "code": "attention", "next": None, "data": 1})


class MainTest(Base):
    def test_version(self) -> None:
        env = {brand.env("WRAPPER_VERSION"): "1.2.3", brand.env("IMAGE"): "sha256:" + "2" * 64}
        with mock.patch.dict(os.environ, env):
            code, out, _ = self.main("version", "--json")
        doc = json.loads(out)
        self.assertEqual(
            (code, doc["version"], doc["wrapper"], doc["image"]), (0, __version__, "1.2.3", env[brand.env("IMAGE")])
        )
        self.assertEqual((doc["code"], doc["next"]), ("ok", None))

    def test_help_lists_every_command_but_the_executor_entry(self) -> None:
        code, out, err = self.main("--help")
        self.assertEqual((code, err), (0, ""))
        for key in commands.COMMANDS:
            self.assertRegex(out, rf"(?m)^\s+{key.split()[0]}\s+\S", key)  # listed, with a description after it
        self.assertNotIn("_exec", out)
        self.assertNotIn("SUPPRESS", out)
        self.assertNotRegex(out, r"(?m)^\s+(\w+)\s+\1 \(class", "a lazy description")
        for words in (("host", "--help"), ("scheduled", "--help"), ("deploy", "--help")):
            code, out, _ = self.main(*words)
            self.assertEqual(code, 0, words)
            self.assertNotIn("SUPPRESS", out)

    def test_usage_error_output(self) -> None:
        code, out, err = self.main("deploy", NAME)
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith(f"{brand.CLI}: the following arguments are required: ref\n"))
        code, out, _ = self.main("deploy", "--json")
        self.assertEqual((code, json.loads(out)["code"]), (2, "usage"))
        with mock.patch.object(deploy, "plan_deploy", side_effect=KeyboardInterrupt):
            code, out, _ = self.main("deploy", NAME, "r1", "--json")
        self.assertEqual((code, json.loads(out)["code"]), (130, "cancelled"))  # not an operation's `interrupted`

    def test_class_c_without_terminal_leaves_no_trace(self) -> None:
        with (
            mock.patch.object(deploy, "plan_deploy", return_value=plan(self.layout)),
            mock.patch.object(follow, "launch_and_follow") as launch,
        ):
            code, out, err = self.main("deploy", NAME, "r1", "--json")
        self.assertEqual((code, json.loads(out)["code"]), (2, "no-tty"))
        self.assertIn("approval class C", err)  # the summary goes to stderr under --json
        self.assertEqual((self.plans(), launch.called), ([], False))

    def test_no_candidate_without_terminal_prepares_nothing(self) -> None:
        refused = Refused("no prepared candidate", code="no-candidate")
        with (
            mock.patch.object(deploy, "plan_deploy", side_effect=refused),
            mock.patch.object(deploy, "plan_prepare") as prepare,
        ):
            code, _, err = self.main("deploy", NAME, "r1")
            self.assertEqual((code, prepare.called), (2, False))
            self.assertIn(f"{brand.CLI}: deploy changes your app, so you must approve it", err)
            self.assertIn(f"next: {brand.CLI} prepare {NAME} r1\n", err)  # prepare is class B: no terminal needed
            code, out, _ = self.main("deploy", NAME, "r1", "--json")
        self.assertEqual((code, prepare.called), (2, False))
        self.assertEqual(json.loads(out)["next"], f"{brand.CLI} prepare {NAME} r1")

    def test_typed_approval(self) -> None:
        self.tty = True
        p = plan(self.layout)
        done = {"exit": 0, "code": "completed", "next": None, "lines": ["completed"], "op": 1}
        with (
            mock.patch.object(deploy, "plan_deploy", return_value=p),
            mock.patch.object(follow, "launch_and_follow", return_value=done) as launch,
        ):
            code, _, err = self.main("deploy", NAME, "r1", typed="lite-tset\n")
            self.assertEqual((code, launch.called, self.plans()), (1, False, []))
            self.assertIn("Type the instance name to approve: ", err)
            self.assertIn("not approved", err)
            code, out, _ = self.main("deploy", NAME, "r1", typed=f"{NAME}\n")
        self.assertEqual((code, launch.call_args.args[1]), (0, p))
        self.assertIn("completed", out)

    def test_deploy_prepares_first(self) -> None:
        self.tty = True
        order: list[str] = []
        prepared = plan(self.layout, "prepare", "B")
        deployed = plan(self.layout)

        def plan_deploy(ctx: Any, name: str, ref: str) -> Plan:
            order.append("plan deploy")
            if "prepare" not in order:
                raise Refused("no prepared candidate", code="no-candidate")
            return deployed

        def launch(ctx: Any, p: Plan, out: Any) -> dict[str, Any]:
            order.append(p.op_kind)
            return {"exit": 0, "code": "completed", "next": None, "lines": ["completed"], "op": 1}

        with (
            mock.patch.object(deploy, "plan_deploy", plan_deploy),
            mock.patch.object(deploy, "plan_prepare", return_value=prepared),
            mock.patch.object(follow, "launch_and_follow", launch),
        ):
            code, out, _ = self.main("deploy", NAME, "r1", typed=f"{NAME}\n")
        self.assertEqual((code, order), (0, ["plan deploy", "prepare", "plan deploy", "deploy"]))
        self.assertIn("preparing r1 first", out)

    def test_scheduled(self) -> None:
        from ingat.ops import backup

        done = {"exit": 0, "code": "completed", "next": f"{brand.CLI} status {NAME}", "lines": ["completed"], "op": 7}
        again = dict(done)  # the first run rewrites its report
        with mock.patch.object(backup, "plan_backup", return_value=plan(self.layout, "backup", "C")):
            code, out, _ = self.main("scheduled", "backup", NAME, "--json")
        self.assertEqual((code, json.loads(out)["code"]), (2, "unattended"))
        with (
            mock.patch.object(backup, "plan_backup", return_value=plan(self.layout, "backup", "B")) as planner,
            mock.patch.object(follow, "launch_and_follow", return_value=done) as launch,
        ):
            code, out, err = self.main("scheduled", "backup", NAME)
        self.assertEqual((code, out, err), (0, f"scheduled backup {NAME}: completed (operation 7)\n", ""))
        self.assertEqual(planner.call_args.kwargs, {"scheduled": True})
        self.assertIsNone(launch.call_args.args[2])  # quiet: no progress
        with (
            mock.patch.object(backup, "plan_backup", return_value=plan(self.layout, "backup", "B")),
            mock.patch.object(follow, "launch_and_follow", return_value=again),
        ):
            code, out, _ = self.main("scheduled", "backup", NAME, "--json")
        self.assertEqual((code, json.loads(out)["next"]), (0, f"{brand.CLI} status {NAME}"))  # JSON keeps `next`

    def test_scheduled_names_an_auto_abandon(self) -> None:
        from ingat.ops import backup

        d = self.layout.op_dir(NAME, 1, "backup")  # a crashed nightly backup, still open
        os.makedirs(d)

        def launch(ctx: Any, p: Plan, out: Any) -> dict[str, Any]:
            result = {"op": 1, "outcome": "abandoned-auto", "exit": 0, "code": "abandoned-auto", "message": "m"}
            state.write_doc_once(f"{d}/result.json", records.new_doc("result", **result, next="n"))
            return {"exit": 0, "code": "completed", "next": "n", "lines": ["completed"], "op": 2}

        with (
            mock.patch.object(backup, "plan_backup", return_value=plan(self.layout, "backup", "B")),
            mock.patch.object(follow, "launch_and_follow", launch),
        ):
            code, out, _ = self.main("scheduled", "backup", NAME)
        line = f"scheduled backup {NAME}: completed (operation 2); the earlier unfinished operation 1 (backup) was "
        line += "undone and closed automatically first\n"
        self.assertEqual((code, out), (0, line))

    def test_the_table_class_is_a_floor(self) -> None:
        from ingat.ops import lifecycle

        self.tty = True
        with (
            mock.patch.object(lifecycle, "plan_start", return_value=plan(self.layout, "start", "B")),
            mock.patch.object(follow, "launch_and_follow") as launch,
        ):
            code, out, _ = self.main("start", NAME, "--json")
        self.assertEqual((code, json.loads(out)["code"], launch.called, self.plans()), (1, "internal", False, []))

    def test_cli_side_class_c(self) -> None:
        from ingat.ops import host

        with mock.patch.object(host, "host_init") as init:
            code, _, err = self.main("host", "init")
            self.assertEqual((code, init.called), (2, False), err)
            self.tty = True
            init.return_value = {"exit": 0, "code": "ok", "next": None, "lines": ["host initialized"]}
            code, out, _ = self.main("host", "init", typed="host1\n")
        self.assertEqual((code, out), (0, "host initialized\n"))

    def test_terminal_task_runs_in_the_cli(self) -> None:
        from ingat.ops import lifecycle

        p = plan(self.layout, "task", "B", foreground=True)
        with (
            mock.patch.object(lifecycle, "plan_task", return_value=p),
            mock.patch.object(commands.executor, "run_in_process", return_value=DONE) as run,
            mock.patch.object(follow, "launch_and_follow") as launch,
        ):
            code, _, _ = self.main("task", NAME, "bootstrap-new-code")
        self.assertEqual((code, run.called, launch.called, self.plans()), (0, True, False, [f"{p.hash}.json"]))

    def test_terminal_task_joined_to_a_paused_install(self) -> None:
        from ingat.ops import lifecycle

        p = plan(self.layout, "task", "B", foreground=True, into_op=1)
        with (
            mock.patch.object(lifecycle, "plan_task", return_value=p),
            mock.patch.object(commands.executor, "run_in_process", return_value=DONE),
        ):
            code, out, _ = self.main("task", NAME, "bootstrap-new-code", "--json")
        self.assertEqual((code, json.loads(out)["next"]), (0, f"{brand.CLI} resume {NAME}"))

    def test_terminal_task_left_open_prints_the_executors_next_command(self) -> None:
        """A terminal task whose container could not be proved stopped, or whose operation paused or was interrupted,
        leaves no result.json: the CLI prints what the executor decided (its code, message and the exact next
        command), as the run file of the detached executor would (LIFECYCLE §3.5, F15)."""
        from ingat.ops import lifecycle

        p = plan(self.layout, "task", "B", foreground=True)
        stop = f"docker stop {NAME}-x1-1-a1"
        cases = [
            (Res(4, "task-running", "task container still runs; stop it first", 1, stop), stop),
            (Res(4, "paused", "waiting for the owner", 1, f"{brand.CLI} resume {NAME}"), f"{brand.CLI} resume {NAME}"),
            (Res(4, "interrupted", "step 1 RunTask ended unknown", 1, None), f"{brand.CLI} status {NAME}"),
        ]
        for res, nxt in cases:
            with (
                self.subTest(code=res.code),
                mock.patch.object(lifecycle, "plan_task", return_value=p),
                mock.patch.object(commands.executor, "run_in_process", return_value=res),
            ):
                code, out, _ = self.main("task", NAME, "bootstrap-new-code", "--json")
            doc = json.loads(out)
            got = (code, doc["code"], doc["message"], doc["next"], doc["op"])
            self.assertEqual(got, (4, res.code, res.message, nxt, 1))
            with (
                mock.patch.object(lifecycle, "plan_task", return_value=p),
                mock.patch.object(commands.executor, "run_in_process", return_value=res),
            ):
                code, out, err = self.main("task", NAME, "bootstrap-new-code")  # stdout holds the plan summary
            self.assertEqual((code, (res.message in out + err), f"next: {nxt}\n" in out + err), (4, True, True))

    def test_stale_terminal_task_never_reports_another_operation(self) -> None:
        from ingat.ops import lifecycle

        p, other = plan(self.layout, "task", "C", foreground=True), plan(self.layout, "task", "C", other=1)
        d = p.inputs["op_dir"]  # the same seq and kind: another task took this operation number
        os.makedirs(d)
        state.write_doc_once(f"{d}/plan.json", other.doc())
        result = {"op": 1, "outcome": "completed", "exit": 0, "code": "completed", "message": "done", "next": "n"}
        state.write_doc_once(f"{d}/result.json", records.new_doc("result", **result))
        self.tty = True
        with (
            mock.patch.object(lifecycle, "plan_task", return_value=p),
            mock.patch.object(commands.executor, "run_in_process", return_value=STALE),
        ):
            code, out, _ = self.main("task", NAME, "reset", "--json", typed=f"{NAME}\n")
        self.assertEqual((code, json.loads(out)["code"]), (1, "stale-plan"))
        os.remove(f"{d}/plan.json")  # its own operation: the result it closed with
        state.write_doc_once(f"{d}/plan.json", p.doc())
        with (
            mock.patch.object(lifecycle, "plan_task", return_value=p),
            mock.patch.object(commands.executor, "run_in_process", return_value=DONE),
        ):
            code, out, _ = self.main("task", NAME, "reset", "--json", typed=f"{NAME}\n")
        self.assertEqual((code, json.loads(out)["code"], json.loads(out)["next"]), (0, "completed", "n"))

    def test_exec_words_must_name_the_plan(self) -> None:
        from ingat.core import approval

        p = plan(self.layout)
        approval.save(self.layout, p)
        with mock.patch.object(commands.executor, "execute", return_value=0) as execute:
            for run_id, words in (("r1", ["other"]), ("r2", ["--host"]), ("r3", [NAME, "--resume"])):
                code, _, _ = self.main("_exec", *words[:1], p.hash, run_id, *words[1:])
                doc = state.read_doc(self.layout.run(run_id), "run")
                self.assertEqual((code, doc["exit"], doc["code"]), (2, 2, "usage"), words)
            self.assertFalse(execute.called)
            self.assertEqual(self.main("_exec", NAME, p.hash, "r4")[0], 0)
        self.assertEqual(execute.call_args.args[3:], (p.hash, "r4"))


class FollowTest(Base):
    def test_launch_and_follow(self) -> None:
        p = plan(self.layout)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {brand.env("WRAPPER_VERSION"): "1.2.3"}):
            os.environ.pop(brand.env("CRASH_AT"), None)
            rep = follow.launch_and_follow(self.ctx, p, out)
        self.assertEqual((rep["exit"], rep["code"], rep["lines"], rep["op"]), (0, "completed", ["completed"], 1))
        self.assertEqual(out.getvalue(), "t step 1 Obtain: started\nt step 1 Obtain: done\n")  # whole lines only
        kw = self.docker.launched[0]
        self.assertEqual((kw["name"], kw["image"]), (brand.executor_name(NAME), self.ctx.image))
        self.assertEqual(kw["args"][:3], ["_exec", NAME, p.hash])
        root, backups = self.layout.root, self.layout.backups
        sock = "/var/run/docker.sock"
        self.assertEqual(
            kw["mounts"][:4],
            [
                f"{sock}:{sock}",
                f"{root}:{root}",
                f"{backups}:{backups}",
                f"{brand.PROBE_VOLUME}:{brand.PROBE_MOUNT}:ro",
            ],
        )
        env = {brand.env(k): v for k, v in {"ROOT": root, "BACKUPS": backups, "IMAGE": self.ctx.image}.items()}
        env |= {brand.env("HOST"): "host1", brand.env("OPERATOR"): "op", brand.env("WRAPPER_VERSION"): "1.2.3"}
        self.assertEqual(kw["env"], env)
        self.assertEqual(kw["labels"], {brand.label("role"): "exec", brand.label("instance"): NAME})
        self.assertEqual(self.plans(), [f"{p.hash}.json"])

    def test_crash_hook_passes_only_when_set(self) -> None:
        with mock.patch.dict(os.environ, {brand.env("CRASH_AT"): "3:intent:after"}):
            follow.launch_and_follow(self.ctx, plan(self.layout), None)
        self.assertEqual(self.docker.launched[0]["env"][brand.env("CRASH_AT")], "3:intent:after")

    def test_resume_flag(self) -> None:
        follow.launch_and_follow(self.ctx, plan(self.layout, "resume"), None)
        self.assertEqual(self.docker.launched[0]["args"][4:], ["--resume"])

    def test_vanished_executor(self) -> None:
        self.docker.finish = False
        rep = follow.launch_and_follow(self.ctx, plan(self.layout), None)
        self.assertEqual(
            (rep["exit"], rep["code"], rep["next"]), (4, "executor-vanished", f"{brand.CLI} status {NAME}")
        )
        want = f"disappeared before it reported a result, so the operation may be unfinished. Run `{brand.CLI} status"
        self.assertIn(f"{want} {NAME}`", rep["message"])

    def test_open_operation_without_executor(self) -> None:
        d = self.layout.op_dir(NAME, 1, "deploy")
        rep = follow.follow(self.ctx, NAME, d, "gone", None, None)
        self.assertEqual((rep["exit"], rep["code"]), (4, "open-operation"))
        os.makedirs(d)
        result = {"op": 1, "outcome": "completed", "exit": 0, "code": "completed", "message": "done", "next": "n"}
        state.write_doc_once(f"{d}/result.json", records.new_doc("result", **result))
        rep = follow.follow(self.ctx, NAME, d, "gone", None, None)
        self.assertEqual((rep["exit"], rep["code"], rep["lines"], rep["next"]), (0, "completed", ["done"], "n"))
        self.assertEqual(rep["message"], "done")

    def test_json_carries_the_message_the_executor_decided(self) -> None:
        from ingat.ops import backup

        why = f"{NAME} changed since this plan was made; plan again"
        self.docker.outcome = {"exit": 1, "code": "stale-plan", "message": why}
        with mock.patch.object(backup, "plan_backup", return_value=plan(self.layout, "backup", "B")):
            code, out, _ = self.main("backup", NAME, "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["code"], doc["message"], doc["op"]), (1, "stale-plan", why, 1))

    def test_no_image(self) -> None:
        ctx = dataclasses.replace(self.ctx, image="")
        with self.assertRaises(CannotRun) as cm:
            follow.launch_and_follow(ctx, plan(self.layout), None)
        self.assertEqual((cm.exception.code, self.plans()), ("no-image", []))

    def interrupted(self, interrupt: Any, typed: str = "") -> tuple[dict[str, Any], str]:
        """Follow an operation whose executor runs on, interrupted at the first look at it."""
        calls: list[int] = []

        def inspect(kind: str, ids: list[str]) -> list[dict[str, Any]]:
            calls.append(1)
            if len(calls) == 1:
                interrupt()
            return []

        err = io.StringIO()
        with (
            mock.patch.object(self.docker, "inspect", inspect),
            mock.patch("sys.stdin", io.StringIO(typed)),
            contextlib.redirect_stderr(err),
        ):
            rep = follow.follow(self.ctx, NAME, None, "c0ffee", "r1", None)
        return rep, err.getvalue()

    def test_interrupt_detaches_without_a_terminal(self) -> None:
        for interrupt in (
            ctrl_c,
            lambda: os.kill(os.getpid(), signal.SIGTERM),
            lambda: os.kill(os.getpid(), signal.SIGHUP),
        ):
            rep, _ = self.interrupted(interrupt)
            self.assertEqual((rep["exit"], rep["code"], rep["next"]), (4, "detached", f"{brand.CLI} attach {NAME}"))
        self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)  # restored after following

    def test_interrupt_on_a_terminal_asks(self) -> None:
        from ingat.ops import lifecycle

        self.ctx = dataclasses.replace(self.ctx, tty=True)
        cancelled = {"exit": 0, "code": "cancel-requested", "next": None, "lines": ["cancel requested"]}
        with mock.patch.object(lifecycle, "cancel", return_value=cancelled) as cancel:
            rep, err = self.interrupted(ctrl_c, "c\n")
        self.assertIn("[d]etach or [c]ancel? ", err)
        self.assertEqual((cancel.call_args.args[1], rep["exit"], rep["code"]), (NAME, 4, "executor-vanished"))
        rep, _ = self.interrupted(ctrl_c, "d\n")
        self.assertEqual((rep["exit"], rep["code"]), (4, "detached"))

    def test_cancel_before_the_operation_opens_follows_on(self) -> None:
        from ingat.ops import lifecycle

        self.ctx = dataclasses.replace(self.ctx, tty=True)
        refused = Refused(f"{NAME} has no open operation", code="wrong-state")
        with mock.patch.object(lifecycle, "cancel", side_effect=refused):
            rep, err = self.interrupted(ctrl_c, "c\n")
        self.assertEqual((rep["exit"], rep["code"]), (4, "executor-vanished"))  # followed on, not exit 1
        self.assertIn("[d]etach or [c]ancel? ", err)

    def test_lost_session_while_asking_detaches(self) -> None:
        self.ctx = dataclasses.replace(self.ctx, tty=True)

        def ask(prompt: str) -> str:
            os.kill(os.getpid(), signal.SIGHUP)
            return "c\n"

        with mock.patch.object(render, "ask", ask):
            rep, _ = self.interrupted(ctrl_c)
        self.assertEqual((rep["exit"], rep["code"]), (4, "detached"))

    def test_an_exited_executor_that_stays_counts_as_gone(self) -> None:
        exited = [{"Id": "c0ffee", "State": {"Running": False, "Status": "exited"}, "Config": {"Cmd": []}}]
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            self.assertLess(len(sleeps), 3, "the follower waits for a container that will never run again")

        with (
            mock.patch.object(self.docker, "inspect", lambda kind, ids: exited),
            mock.patch.object(follow.time, "sleep", sleep),
        ):
            rep = follow.follow(self.ctx, NAME, None, "c0ffee", "r1", None)
        self.assertEqual((rep["exit"], rep["code"]), (4, "executor-vanished"))

    def test_an_unreachable_daemon_never_says_nothing_changed(self) -> None:
        def inspect(kind: str, ids: list[str]) -> list[dict[str, Any]]:
            raise CannotRun("the Docker daemon is unreachable", code="daemon-unreachable")

        with mock.patch.object(self.docker, "inspect", inspect):
            rep = follow.follow(self.ctx, NAME, None, "c0ffee", "r1", None)
        self.assertEqual(
            (rep["exit"], rep["code"], rep["next"]), (4, "executor-vanished", f"{brand.CLI} status {NAME}")
        )

    def test_interrupt_during_launch(self) -> None:
        launched: list[str] = []

        def launch(**kw: Any) -> str:
            launched.append(kw["args"][3])
            raise KeyboardInterrupt

        def inspect(kind: str, ids: list[str]) -> list[dict[str, Any]]:
            return [
                {"Id": "c0ffee", "State": {"Running": True}, "Config": {"Cmd": ["_exec", NAME, "h", *launched[:1]]}}
            ]

        with (
            mock.patch.object(self.docker, "launch_executor", launch),
            mock.patch.object(self.docker, "inspect", inspect),
        ):
            rep = follow.launch_and_follow(self.ctx, plan(self.layout), None)  # it reached the daemon: runs on
            self.assertEqual((rep["exit"], rep["code"], rep["next"]), (4, "detached", f"{brand.CLI} attach {NAME}"))
            with self.assertRaises(KeyboardInterrupt):  # no container runs this run id: nothing was launched
                follow.launch_and_follow(self.ctx, plan(self.layout, other=1), None)

    def test_attach_when_the_operation_closes_meanwhile(self) -> None:
        d, real = self.layout.op_dir(NAME, 1, "deploy"), state.open_ops
        os.makedirs(d)

        def open_ops(layout: state.Layout, name: str) -> list[tuple[int, str]]:
            found = real(layout, name)  # the executor closes the operation right after attach found it open
            if found:
                result = {"op": 1, "outcome": "completed", "exit": 0, "code": "completed", "message": "done"}
                state.write_doc_once(f"{d}/result.json", records.new_doc("result", **result, next="n"))
            return found

        with mock.patch.object(follow.cx, "load"), mock.patch.object(state, "open_ops", open_ops):
            rep = follow.attach(self.ctx, NAME, None)
        self.assertEqual((rep["exit"], rep["code"], rep["lines"]), (0, "completed", ["done"]))


if __name__ == "__main__":
    unittest.main()
