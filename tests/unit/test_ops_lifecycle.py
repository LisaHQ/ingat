"""ops/lifecycle.py without a daemon: step order of stop and start, typed task arguments and inbox inputs, the class and
step class of a task, the refusals around frozen instances, open operations and unattended runs, joining a paused
install, resume and abandon plans, and cancel (refused for a paused operation)."""

import dataclasses
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from ingat import __version__, brand
from ingat.core.journal import Journal
from ingat.core.plan import new_plan
from ingat.model.errors import CannotRun, IngatError, Refused
from ingat.model.manifest import Activate, Manifest, parse_manifest
from ingat.model.records import new_doc
from ingat.ops import context as cx
from ingat.ops import lifecycle as lc
from ingat.store import state
from ingat.store.state import Layout

REPO = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"
LITE_BYTES = (REPO / "fixtures/fx-lite/ingat.toml").read_bytes()
LITE: Manifest = parse_manifest(LITE_BYTES, tool_version=__version__)
PG: Manifest = parse_manifest((DATA / "fx-pg.toml").read_bytes(), tool_version=__version__)
NAME = "lite"


def services(steps: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    return [(s["type"], s["args"].get("services", [])) for s in steps]


class StepOrderTest(unittest.TestCase):
    def test_stop_writers_first_then_reverse_activation(self) -> None:
        steps = lc.stops(PG, ["db", "backend", "web"])
        self.assertEqual(services(steps), [("Stop", ["backend"]), ("Stop", ["web"]), ("Stop", ["db"])])
        self.assertEqual({(s["klass"], s["args"]["freeze"]) for s in steps}, {("reversible", False)})
        self.assertEqual(services(lc.stops(PG, ["web", "db"])), [("Stop", ["web"]), ("Stop", ["db"])])

    def test_start_in_activation_order_with_the_waits_of_what_starts(self) -> None:
        steps = lc.starts(PG, ["db", "backend", "web"], check=True)
        self.assertEqual(services(steps), [("Up", ["db"]), ("Up", ["backend"]), ("Up", ["web"]), ("Up", [])])
        self.assertEqual(
            [s["args"]["wait"] for s in steps], [["db-ready"], ["backend-ready"], ["web-healthy", "edge-ready"], []]
        )
        self.assertEqual([s["args"]["identity"] for s in steps], [False, False, False, True])
        self.assertEqual({s["klass"] for s in steps[:3]} | {steps[3]["klass"]}, {"reversible", "scratch"})
        both = Activate(
            services=("backend", "web"), wait=("backend-ready", "web-healthy", "edge-ready"), reopens_writes=True
        )
        m = dataclasses.replace(PG, activate=(PG.activate[0], both))
        [up] = lc.starts(m, ["web"], check=False)  # part of a group: only the waits on what it starts
        self.assertEqual((up["args"]["services"], up["args"]["wait"]), (["web"], ["web-healthy"]))
        self.assertFalse(up["args"]["reopens_writes"])


class Fixture(unittest.TestCase):
    """A scratch root with instance `lite` (fx-lite, deployment 1) and planners whose daemon calls are faked."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lay = Layout(f"{tmp.name}/root", f"{tmp.name}/backups")
        os.makedirs(self.lay.inbox, 0o700)
        self.containers: list[dict[str, Any]] = []
        self.networks: list[dict[str, Any]] = []
        docker = SimpleNamespace(
            containers=lambda labels=None, project=None: self.containers,
            networks=lambda labels=None: self.networks,
            volumes=lambda labels=None: [],
            image=lambda ref: {"Id": ref, "Config": {"User": ""}},
        )
        self.ctx = SimpleNamespace(layout=self.lay, docker=docker, tty=False)
        self.gate_warnings: list[str] = []
        rec = {"name": NAME, "state": "running", "current_deployment": 1, "generations": {"data": 1}}
        rec |= {"held_since": None, "open_op": None, "next_seq": 3}
        self.write_record(rec)
        self.manifest = LITE
        for target, value in (
            ("require_host", None),
            ("gate", lambda *args: self.gate_warnings),
            ("load", self.loaded),
            ("current", self.current),
            ("model", lambda ctx, v: {"services": {"app": {}}}),
        ):
            patch = mock.patch.object(cx, target, value if callable(value) else mock.Mock(return_value=value))
            patch.start()
            self.addCleanup(patch.stop)

    def write_record(self, rec: dict[str, Any]) -> None:
        state.replace_doc(self.lay.record_json(NAME), new_doc("instance") | rec)

    def loaded(self, ctx: Any, name: str) -> cx.Loaded:
        rec = state.read_doc(self.lay.record_json(name), "instance")
        return cx.Loaded(name, SimpleNamespace(environment="test"), rec, {"seq": 1}, self.manifest)  # type: ignore[arg-type]

    def current(self, ctx: Any, ld: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        images = {s: "sha256:1" for g in self.manifest.activate for s in g.services}
        return {"images": images, "values": {}, "env": {}}, {"services": {"app": {}}}

    def app(self, running: bool, image: str = "sha256:1") -> None:
        labels = {cx.SERVICE: "app", brand.label("instance"): NAME, "com.docker.compose.project": NAME}
        state_ = {"Running": running, "Status": "running" if running else "exited"}
        self.containers = [{"Name": f"/{NAME}-app-1", "Id": "c1", "Image": image, "Config": {"Labels": labels}}]
        self.containers[0]["State"] = state_

    def open_op(
        self, kind: str, steps: list[dict[str, Any]], phases: dict[int, str], seq: int = 2, **inputs: Any
    ) -> str:
        """An operation left open with this plan and journal."""
        d = self.lay.op_dir(NAME, seq, kind)
        plan = new_plan(kind, NAME, "C", [kind], {}, {"seq": seq, "op_dir": d, **inputs}, steps)
        state.write_doc_once(f"{d}/plan.json", plan.doc())
        journal = Journal(d, seq)
        for n, phase in phases.items():
            journal.intent(n, 1)
            if phase != "intent":
                journal.close_step(n, phase)
        return d

    def raises(self, error: type[IngatError], code: str, fn: Any, *args: Any) -> IngatError:
        with self.assertRaises(error) as cm:
            fn(self.ctx, NAME, *args)
        self.assertEqual(cm.exception.code, code, cm.exception.message)
        return cm.exception


class CycleTest(Fixture):
    def test_stop_start_restart_plans(self) -> None:
        self.app(running=True)
        plan = lc.plan_stop(self.ctx, NAME, [])
        assert plan is not None
        self.assertEqual([s.type for s in plan.steps], ["Stop", "Record"])
        self.assertEqual(plan.steps[-1].args, {"kind": "state", "state": "stopped"})
        self.assertEqual((plan.op_kind, plan.approval, plan.inputs["seq"]), ("stop", "C", 3))
        self.assertEqual(plan.inputs["op_dir"], self.lay.op_dir(NAME, 3, "stop"))
        self.assertIsNone(lc.plan_start(self.ctx, NAME, []))  # running the recorded image: nothing to do
        self.app(running=True, image="sha256:other")
        start = lc.plan_start(self.ctx, NAME, ["app"])
        assert start is not None
        self.assertEqual([s.type for s in start.steps], ["Up", "Up", "Record"])
        self.assertEqual(start.inputs["variants"]["current"]["values"]["op.seq"], "3")
        restart = lc.plan_restart(self.ctx, NAME, [])
        assert restart is not None
        self.assertEqual([s.type for s in restart.steps], ["Stop", "Up", "Up", "Record"])
        self.app(running=False)
        self.write_record(state.read_doc(self.lay.record_json(NAME), "instance") | {"state": "stopped"})
        self.assertIsNone(lc.plan_stop(self.ctx, NAME, []))
        self.raises(CannotRun, "usage", lc.plan_start, ["db"])

    def test_a_foreign_object_in_the_project_refuses_start_stop_and_restart(self) -> None:
        """Compose stops, starts and recreates what its project holds: a container or network of the project that
        is not the instance's own is never touched (F8)."""
        self.app(running=True, image="sha256:other")  # something to do for each planner
        for planner in (lc.plan_start, lc.plan_stop, lc.plan_restart):
            self.assertIsNotNone(planner(self.ctx, NAME, []))
        labels = {"com.docker.compose.project": NAME, cx.SERVICE: "app"}
        hand = {"Name": "/hand", "Id": "c2", "Image": "x", "Config": {"Labels": labels}, "State": {"Running": True}}
        self.containers.append(hand)
        for planner in (lc.plan_start, lc.plan_stop, lc.plan_restart):
            e = self.raises(Refused, "foreign", planner, [])
            self.assertIn("container hand", e.message)
        self.containers.pop()
        self.networks.append({"Name": f"{NAME}_default", "Labels": {"com.docker.compose.project": NAME}})
        self.raises(Refused, "foreign", lc.plan_stop, [])

    def test_every_plan_carries_the_gate_warnings(self) -> None:
        self.app(running=True, image="sha256:other")
        self.gate_warnings = ["Engine 99.0 on amd64 is not a tested combination of this release"]
        for plan in (lc.plan_start(self.ctx, NAME, []), lc.plan_task(self.ctx, NAME, "queue-held", {}, {}, False)):
            assert plan is not None
            self.assertEqual(plan.inputs["warnings"], self.gate_warnings)

    def test_partial_stop_keeps_the_state_and_partial_start_skips_the_identity_check(self) -> None:
        self.manifest = dataclasses.replace(PG, schema=None)  # a task-based schema check is M2
        stop = lc.plan_stop(self.ctx, NAME, ["web"])
        assert stop is not None
        self.assertEqual([s.type for s in stop.steps], ["Stop"])  # still running in part
        start = lc.plan_start(self.ctx, NAME, ["web"])
        assert start is not None
        self.assertEqual([(s.type, s.args.get("identity")) for s in start.steps], [("Up", False), ("Record", None)])

    def test_frozen_and_open_operations_refuse(self) -> None:
        self.write_record(state.read_doc(self.lay.record_json(NAME), "instance") | {"state": "frozen"})
        for planner in (lc.plan_start, lc.plan_stop, lc.plan_restart):
            self.raises(Refused, "frozen", planner, [])
        self.write_record(state.read_doc(self.lay.record_json(NAME), "instance") | {"state": "stopped"})
        self.open_op("backup", [{"type": "Record", "klass": "idempotent", "args": {}}], {1: "intent"})
        self.assertIsNotNone(lc.plan_start(self.ctx, NAME, []))  # the executor abandons it first (LIFECYCLE §3.4)
        self.open_op("deploy", [{"type": "Record", "klass": "idempotent", "args": {}}], {1: "intent"})
        e = self.raises(CannotRun, "open-operation", lc.plan_start, [])
        self.assertEqual(e.next, f"{brand.CLI} resume {NAME}  or  {brand.CLI} abandon {NAME}")

    def test_a_task_based_schema_check_is_not_in_this_release(self) -> None:
        assert LITE.schema is not None
        self.manifest = dataclasses.replace(
            LITE, schema=dataclasses.replace(LITE.schema, task="queue-held", probe=None)
        )
        self.raises(Refused, "not-in-this-release", lc.plan_start, [])
        self.assertIsNotNone(lc.plan_stop(self.ctx, NAME, []))


class TaskTest(Fixture):
    def test_typed_arguments(self) -> None:
        t = LITE.tasks["queue-release-job"]
        self.assertEqual(lc.task_args(t, {"job": "a-1"}), {"job": "a-1"})
        for given, error, code in (
            ({}, CannotRun, "usage"),  # exit 2 (LIFECYCLE §6)
            ({"job": "a", "x": "1"}, CannotRun, "usage"),
            ({"job": "a b"}, Refused, "invalid-arg"),
        ):
            with self.subTest(given=given), self.assertRaises(error) as cm:
                lc.task_args(t, given)
            self.assertEqual(cm.exception.code, code)
            self.assertNotIn("a b", cm.exception.message)

    def test_inputs_come_from_the_inbox_only(self) -> None:
        t, inbox = LITE.tasks["bootstrap-config"], self.lay.inbox
        Path(inbox, "c.json").write_text("{}")
        Path(inbox, "big").write_bytes(b"x" * (262144 + 1))
        os.symlink(f"{inbox}/c.json", f"{inbox}/link")
        os.mkdir(f"{inbox}/dir")
        self.assertEqual(lc.task_inputs(self.ctx, t, {"config": "c.json"}), {"config": f"{inbox}/c.json"})
        self.assertEqual(lc.task_inputs(self.ctx, t, {"config": f"{inbox}/c.json"}), {"config": f"{inbox}/c.json"})
        for given, error, code in (
            ({}, CannotRun, "usage"),
            ({"config": "c.json", "other": "c.json"}, CannotRun, "usage"),
            ({"config": "missing"}, Refused, "missing-input"),
            ({"config": "big"}, Refused, "too-large"),
            ({"config": "link"}, Refused, "unsafe-path"),
            ({"config": "dir"}, Refused, "unsafe-path"),
            ({"config": "../host.json"}, Refused, "unsafe-path"),
            ({"config": "dir/x"}, Refused, "unsafe-path"),
            ({"config": "/etc/hostname"}, Refused, "unsafe-path"),
        ):
            with self.subTest(given=given), self.assertRaises(error) as cm:
                lc.task_inputs(self.ctx, t, given)
            self.assertEqual(cm.exception.code, code)

    def test_class_and_step_class_by_effect(self) -> None:
        fix = dataclasses.replace(LITE.tasks["queue-resume"], name="fix", effect="data", idempotent=True)
        self.manifest = dataclasses.replace(LITE, tasks={**LITE.tasks, "fix": fix})
        got = {}
        for task in ("queue-held", "queue-resume", "fix"):
            plan = lc.plan_task(self.ctx, NAME, task, {}, {}, False)
            s = plan.steps[0]
            got[task] = (plan.approval, s.klass, s.interruptible, s.forward_point, s.args["findings_ok"])
            self.assertEqual(plan.steps[1].args["kind"], "task")
            self.assertEqual((plan.inputs["into_op"], plan.inputs["foreground"]), (None, False))
        read = dataclasses.replace(LITE.tasks["queue-held"], name="peek", effect="read")
        self.manifest = dataclasses.replace(LITE, tasks={**LITE.tasks, "peek": read})
        got["peek"] = lc.plan_task(self.ctx, NAME, "peek", {}, {}, False).approval
        self.assertEqual(
            got,
            {
                # app-write: a forward step (the executor never repeats it blind) but no forward point: never freezes
                "queue-held": ("C", "forward", False, False, True),
                "queue-resume": ("C", "forward", False, False, True),
                "fix": ("C", "forward", False, True, True),  # data: the forward point
                "peek": "B",
            },
        )

    def test_a_task_that_mounts_a_bundle_a_new_generation_or_a_stage_runs_only_inside_its_operations(self) -> None:
        base = LITE.tasks["queue-held"]
        for source in ("bundle", "generation:data", "stage"):  # the stage: the bundle being built (ARCH §7.1)
            t = dataclasses.replace(base, name="x", mounts={"/m": source}, user="10001:10001")
            self.manifest = dataclasses.replace(LITE, tasks={**LITE.tasks, "x": t})
            with self.subTest(source=source):
                e = self.raises(Refused, "not-operator", lc.plan_task, "x", {}, {}, False)
                self.assertIn(source, e.message)
        self.manifest = LITE
        self.raises(Refused, "not-operator", lc.plan_task, "backup", {}, {}, False)  # it leaves no data copy behind

    def test_refusals(self) -> None:
        pw = dataclasses.replace(LITE.tasks["bootstrap-new-code"], name="pw", stdin="terminal")
        self.manifest = dataclasses.replace(LITE, tasks={**LITE.tasks, "pw": pw})
        self.raises(Refused, "unknown-task", lc.plan_task, "nosuch", {}, {}, False)
        self.raises(Refused, "not-operator", lc.plan_task, "migrate", {}, {}, False)
        self.raises(CannotRun, "unattended", lc.plan_task, "queue-resume", {}, {}, True)  # class C
        self.raises(CannotRun, "unattended", lc.plan_task, "bootstrap-new-code", {}, {}, True)  # terminal
        self.raises(CannotRun, "no-tty", lc.plan_task, "pw", {}, {}, False)
        self.ctx.tty = True
        self.assertTrue(lc.plan_task(self.ctx, NAME, "pw", {}, {}, False).inputs["foreground"])
        self.write_record(state.read_doc(self.lay.record_json(NAME), "instance") | {"state": "frozen"})
        self.raises(Refused, "frozen", lc.plan_task, "queue-resume", {}, {}, False)
        read = dataclasses.replace(LITE.tasks["queue-held"], name="peek", effect="read")
        self.manifest = dataclasses.replace(LITE, tasks={**LITE.tasks, "peek": read})
        self.assertEqual(lc.plan_task(self.ctx, NAME, "peek", {}, {}, False).approval, "B")  # reading stays allowed

    def test_an_allowed_task_joins_the_paused_install(self) -> None:
        manifest = f"{self.lay.root}/cache/src/c/{brand.MANIFEST_FILE}"
        os.makedirs(os.path.dirname(manifest))
        Path(manifest).write_bytes(LITE_BYTES)
        candidate = {"images": {"app": "sha256:2"}, "values": {"op.seq": "2"}, "env": {}}
        steps = [
            {"type": "Pause", "klass": "operator", "args": {"text": "t", "allow_tasks": ["bootstrap-config"]}},
            {"type": "Record", "klass": "idempotent", "args": {"kind": "deployment", "manifest_path": manifest}},
        ]
        d = self.open_op(
            "deploy", steps, {1: "intent"}, variants={"candidate": candidate}, manifest_sha256=LITE.raw_sha256
        )
        Path(self.lay.inbox, "c.json").write_text("{}")
        self.manifest = None  # type: ignore[assignment]  # a first install: no deployment yet
        plan = lc.plan_task(self.ctx, NAME, "bootstrap-config", {}, {"config": "c.json"}, False)
        self.assertEqual((plan.inputs["into_op"], plan.inputs["seq"], plan.inputs["op_dir"]), (2, 2, d))
        self.assertEqual(
            (plan.steps[0].args["variant"], plan.inputs["variants"]["candidate"]["values"]),
            ("candidate", {"op.seq": "2"}),
        )
        self.assertEqual((plan.approval, plan.inputs["foreground"]), ("C", True))
        self.raises(CannotRun, "open-operation", lc.plan_task, "queue-resume", {}, {}, False)  # not allowed
        Path(manifest).write_bytes(LITE_BYTES + b"\n# changed\n")
        self.raises(Refused, "stale-plan", lc.plan_task, "bootstrap-config", {}, {"config": "c.json"}, False)
        Path(manifest).write_bytes(LITE_BYTES)
        Journal(d, 2).close_step(0, "done", {"outcome": "abandoned"})  # its close decided, then a crash
        e = self.raises(CannotRun, "open-operation", lc.plan_task, "bootstrap-config", {}, {"config": "c.json"}, False)
        self.assertEqual(e.next, f"{brand.CLI} resume {NAME}  or  {brand.CLI} abandon {NAME}")  # finishes the close
        self.assertEqual(lc.cancel(self.ctx, NAME)["code"], "cancel-requested")  # no longer paused


class ReenterTest(Fixture):
    def write_task(self, **args: Any) -> dict[str, Any]:
        a = {"task": "t", "effect": "app-write", "idempotent": False, "exit": {"0": "ok"}, "require_ok": True} | args
        return {"type": "RunTask", "klass": "forward", "args": a}

    def test_resume_and_abandon_reenter_the_open_operation(self) -> None:
        self.raises(Refused, "wrong-state", lc.plan_resume)
        self.raises(Refused, "wrong-state", lc.plan_abandon)
        d = self.open_op("deploy", [{"type": "Pause", "klass": "operator", "args": {}}], {1: "intent"})
        for planner, kind in ((lc.plan_resume, "resume"), (lc.plan_abandon, "abandon")):
            plan = planner(self.ctx, NAME)
            self.assertEqual((plan.op_kind, plan.approval, plan.steps), (kind, "C", ()))
            self.assertEqual(plan.inputs, {"seq": 2, "op_dir": d, "into_op": 2, "warnings": [], "foreground": False})
        task = self.open_op("task", [self.write_task(stdout="terminal")], {1: "intent"}, seq=3, foreground=True)
        resume, abandon = lc.plan_resume(self.ctx, NAME), lc.plan_abandon(self.ctx, NAME)
        found = (resume.inputs["op_dir"], resume.inputs["foreground"], abandon.inputs["foreground"])
        self.assertEqual(found, (task, True, False))  # a terminal task resumes in the CLI, on its terminal (ARCH §4.3)
        shutil.rmtree(task)
        running = {"Name": "/lite-x2-1-a1", "State": {"Status": "running"}, "Config": {"Labels": {}}}
        self.containers = [running]
        e = self.raises(CannotRun, "task-running", lc.plan_resume)
        self.assertEqual(e.next, "docker stop lite-x2-1-a1")

    def test_an_unknown_write_task_is_left_to_the_executor(self) -> None:
        """Its resume closes needs-review without repeating it (LIFECYCLE §3.5, F5), so planning never blocks it."""
        steps = [self.write_task(), {"type": "Record", "klass": "idempotent", "args": {}}]
        self.open_op("task", steps, {1: "intent"})
        self.assertEqual(lc.plan_resume(self.ctx, NAME).inputs["seq"], 2)
        self.assertEqual(lc.plan_abandon(self.ctx, NAME).inputs["seq"], 2)


class CancelTest(Fixture):
    def test_cancel_writes_only_the_cancel_file_of_the_open_operation(self) -> None:
        self.raises(Refused, "wrong-state", lc.cancel)
        d = self.open_op("backup", [{"type": "Record", "klass": "idempotent", "args": {}}], {})
        before = sorted(os.listdir(d))
        report = lc.cancel(self.ctx, NAME)
        self.assertEqual((report["exit"], report["code"], report["op"]), (0, "cancel-requested", 2))
        self.assertEqual(report["next"], f"{brand.CLI} attach {NAME}")
        self.assertEqual(sorted(os.listdir(d)), sorted([*before, "cancel"]))
        self.assertEqual(lc.cancel(self.ctx, NAME)["op"], 2)  # asked again: nothing more
        self.assertEqual(sorted(os.listdir(d)), sorted([*before, "cancel"]))

    def test_cancel_needs_no_valid_instance_file(self) -> None:
        """An instance.toml edited for the next deploy must not keep a running operation from stopping."""
        d = self.open_op("backup", [{"type": "Record", "klass": "idempotent", "args": {}}], {})
        broken = Refused("instance.toml: invalid", code="invalid-instance")
        with mock.patch.object(cx, "load", side_effect=broken):
            self.assertEqual(lc.cancel(self.ctx, NAME)["code"], "cancel-requested")
            self.assertTrue(os.path.exists(f"{d}/cancel"))
            for name, error, code in (
                ("nosuch", Refused, "unknown-instance"),
                ("../lite", CannotRun, "usage"),  # exit 2, as for every command that loads an instance
                ("Lite", CannotRun, "usage"),
            ):
                with self.subTest(name=name), self.assertRaises(error) as cm:
                    lc.cancel(self.ctx, name)
                self.assertEqual(cm.exception.code, code)

    def test_a_paused_operation_is_not_cancelled(self) -> None:
        """No executor runs it: a cancel file would end every task its pause allows and its resume."""
        pause = {"type": "Pause", "klass": "operator", "args": {"text": "t", "allow_tasks": []}}
        d = self.open_op("deploy", [pause, {"type": "Record", "klass": "idempotent", "args": {}}], {1: "intent"})
        before = sorted(os.listdir(d))
        e = self.raises(Refused, "wrong-state", lc.cancel)
        self.assertEqual(e.next, f"{brand.CLI} resume {NAME}  or  {brand.CLI} abandon {NAME}")
        self.assertEqual(sorted(os.listdir(d)), before)


if __name__ == "__main__":
    unittest.main()
