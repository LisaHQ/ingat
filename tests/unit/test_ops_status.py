"""Diagnostics on synthetic records and a fake daemon: attention codes and their priority, bundle and verification
ages, open operations, live drift, scheduled status's change detection, log redaction and the doctor checks; and that
none of them but scheduled status writes anything."""

import hashlib
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from ingat import brand
from ingat.adapters.docker import PROJECT_LABEL
from ingat.adapters.runner import Redactor, Result
from ingat.core.journal import Journal
from ingat.core.steps import SELFTEST_KIND, SELFTEST_MARKER
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.ops import context as cx
from ingat.ops import status as st
from ingat.store import fs, state
from ingat.store.state import Layout

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
CLI, NAME, IMAGE = brand.CLI, "lite", "sha256:" + "1" * 64
INSTANCE = """instance = 1
name = "lite"
app = "fx-lite"
environment = "test"
[source]
repo = "ssh://git@example.invalid/fx-lite.git"
[params]
FXLITE_IMAGE = "img:1"
[app_env]
ALLOWED_ORIGINS = "http://127.0.0.1"
BASE_URL = "http://127.0.0.1"
MAIL_SENDER = "a@example.invalid"
PROXY_ADDRESS = "127.0.0.1"
"""


def ago(**kw: float) -> str:
    return records.iso(NOW - timedelta(**kw))


def labels(name: str, service: str, **extra: str) -> dict[str, str]:
    out = {PROJECT_LABEL: name, cx.SERVICE: service, cx.CONFIG_HASH: "h1"}
    return out | {brand.label("instance"): name} | extra


def container(name: str, lab: dict[str, str], running: bool = True, image: str = IMAGE) -> dict[str, Any]:
    status = {"Status": "running" if running else "exited", "Running": running}
    host = {"PortBindings": {}}
    return {"Id": name + "-id", "Name": "/" + name, "Image": image, "Config": {"Labels": lab}, "State": status} | {
        "HostConfig": host,
        "RestartCount": 0,
    }


class FakeDocker:
    def __init__(self) -> None:
        self.box: list[dict[str, Any]] = []
        own = {PROJECT_LABEL: NAME, brand.label("instance"): NAME}
        self.nets: list[dict[str, Any]] = [{"Name": f"{NAME}_default", "Labels": own, "IPAM": {"Config": []}}]
        self.down, self.engine = False, "E1"

    def info(self) -> dict[str, Any]:
        if self.down:
            raise CannotRun("the Docker daemon is unreachable", code="daemon-unreachable")
        return {"ID": self.engine, "Architecture": "x86_64"}

    def containers(self, labels: dict[str, str] | None = None, project: str | None = None) -> list[dict[str, Any]]:
        self.info()  # every call fails on an unreachable daemon
        want = {**(labels or {}), **({PROJECT_LABEL: project} if project else {})}
        return [c for c in self.box if all(c["Config"]["Labels"].get(k) == v for k, v in want.items())]

    def inspect(self, kind: str, ids: list[str]) -> list[dict[str, Any]]:
        objs = self.box if kind == "container" else self.nets
        return [o for o in objs if o["Name"].lstrip("/") in ids or o.get("Id") in ids]

    def networks(self, labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return [n for n in self.nets if all(n["Labels"].get(k) == v for k, v in (labels or {}).items())]


class FakeCompose:
    hashes: ClassVar[dict[str, str]] = {"app": "h1"}

    def __init__(self, config_dir: str, redactor: Redactor | None = None) -> None:
        pass

    def config_hashes(self, p: object, services: list[str]) -> dict[str, str]:
        return dict(self.hashes)

    def config(self, p: object) -> dict[str, Any]:
        return {"services": {"app": {"networks": {"default": None}}}, "networks": {"default": {"name": "lite_default"}}}


def tree(root: str) -> dict[str, bytes]:
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            out[os.path.join(d, f)] = Path(d, f).read_bytes()
    return out


class StatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base)
        self.lay = lay = Layout(f"{self.base}/root", f"{self.base}/backups")
        for d in (lay.root, lay.backups, lay.docker_config):
            os.makedirs(d, 0o700, exist_ok=True)
        state.write_doc_once(lay.host_json, records.new_doc("host", engine_id="E1"))
        os.makedirs(f"{lay.secrets_dir(NAME)}/env", 0o700)
        os.chmod(lay.secrets_dir(NAME), 0o700)
        self.register(NAME)
        self.docker = FakeDocker()
        self.ctx = cx.Ctx(lay, self.docker, None, "", "root", "h", now=NOW)  # type: ignore[arg-type]
        patches = [mock.patch.object(cx, "gate", return_value=[]), mock.patch.object(st, "Compose", FakeCompose)]
        if os.geteuid() != 0:  # the roots check wants root-owned roots; test_ops_host covers it, as root
            patches.append(mock.patch.object(st, "roots", return_value=[]))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def register(self, name: str) -> None:
        """An instance as init leaves it: its instance.toml and record."""
        os.makedirs(self.lay.inst(name), 0o700, exist_ok=True)
        Path(self.lay.inst_toml(name)).write_text(INSTANCE.replace(f'name = "{NAME}"', f'name = "{name}"'))
        rec = {"name": name, "app": "fx-lite", "environment": "test", "lineage": "0" * 32, "disposable": False}
        rec |= {"state": "registered", "current_deployment": None, "previous_deployment": None, "generations": {}}
        rec |= {"held_since": None, "open_op": None, "next_seq": 1, "created_at": ago(days=30), "last_op": None}
        state.write_doc_once(self.lay.record_json(name), records.new_doc("instance", **rec))

    def update(self, **fields: Any) -> None:
        rec = state.read_doc(self.lay.record_json(NAME), "instance")
        state.replace_doc(self.lay.record_json(NAME), rec | fields)

    def deploy(self) -> None:
        """What a first install leaves: deployment 1, its snapshot, generation g1, the running service and a fresh
        verified and restore-tested bundle."""
        lay = self.lay
        doc = {"seq": 1, "instance": NAME, "op": 1, "release": "r1", "commit": "c" * 40, "origin": "install"}
        doc |= {"export": f"{lay.root}/cache/src/{'c' * 40}", "images": {"app": IMAGE}, "generations": {"data": 1}}
        doc |= {"params": {"FXLITE_PORT": "20001"}, "created_at": ago(days=2), "schema": None}
        state.write_doc_once(lay.deployment_json(NAME, 1), records.new_doc("deployment", **doc))
        os.makedirs(lay.deployment_snapshot(NAME, 1))
        shutil.copy(REPO / "fixtures/fx-lite/ingat.toml", f"{lay.deployment_snapshot(NAME, 1)}/{brand.MANIFEST_FILE}")
        os.makedirs(lay.data_gen(NAME, "data", "g1"))
        self.update(state="running", current_deployment=1, generations={"data": 1}, next_seq=2)
        self.docker.box.append(container("lite-app-1", labels(NAME, "app")))
        self.bundle("b1", ago(hours=3), verified=True, restore_tested=True)

    def bundle(self, bid: str, created: str, **levels: bool) -> str:
        digest = hashlib.sha256(bid.encode()).hexdigest()
        entry = {"bundle_id": bid, "bundle_hash": digest, "class": "manual", "size": 10, "created_at": created}
        state.write_doc_once(self.lay.catalog(NAME, bid), records.new_doc("catalog", **entry))
        for level, ok in levels.items():
            v = {"bundle_id": bid, "bundle_hash": digest, "level": level.replace("_", "-"), "ok": ok, "op": 1}
            line = records.dumps(records.new_doc("verification", **v, at=created, evidence={}))
            fs.append_line(self.lay.verification(NAME, bid), line)
        return digest

    def status(self) -> dict[str, Any]:
        return st.status(self.ctx, NAME)

    def codes(self) -> list[str]:
        return sorted(self.status()["attention"])

    def test_registered_and_deployed_instances_are_clean(self) -> None:
        rep = self.status()
        self.assertEqual((rep["exit"], rep["code"], rep["next"], rep["attention"]), (0, "ok", None, {}))
        self.assertEqual(rep["lines"][:2], ["lite: registered", "bundles: 0, verified never, restore-test never"])
        self.deploy()
        rep = self.status()
        self.assertEqual((rep["exit"], rep["attention"]), (0, {}), rep["lines"])
        self.assertEqual(rep["instance"]["deployment"]["release"], "r1")
        self.assertEqual(rep["instance"]["services"][0]["state"], "running")
        self.assertEqual(rep["host"]["gate_tier"], 2)
        every = st.status(self.ctx, None)
        self.assertEqual((every["exit"], every["instances"][0]["attention"]), (0, []))

    def test_backup_and_restore_test_ages(self) -> None:
        self.deploy()
        os.remove(self.lay.catalog(NAME, "b1"))
        rep = self.status()
        self.assertEqual(sorted(rep["attention"]), ["backup-old", "restore-test-old"])
        self.assertEqual((rep["exit"], rep["next"]), (5, f"{CLI} backup {NAME}"))
        self.bundle("b2", ago(hours=30), verified=True)
        self.bundle("b3", ago(days=9), restore_tested=True)
        rep = self.status()
        self.assertEqual(rep["attention"]["backup-old"], ["newest verified bundle b2; the limit is 26h"])
        self.assertEqual(rep["attention"]["restore-test-old"], ["last restore-test 9d ago; the limit is 8d"])
        self.bundle("b4", ago(hours=1), verified=True, restore_tested=False)  # a failed drill counts against b4
        rep = self.status()
        self.assertEqual(sorted(rep["attention"]), ["backup-old", "restore-test-old", "unverified-bundle"])
        self.assertEqual(rep["attention"]["unverified-bundle"], ["bundle b4: restore-tested failed"])
        self.bundle("b5", ago(hours=1), verified=True)
        self.assertEqual(self.codes(), ["restore-test-old", "unverified-bundle"])

    def test_unverified_tombstoned_and_rebound_bundles(self) -> None:
        self.deploy()
        self.bundle("b2", ago(hours=1), verified=False)
        self.bundle("b3", ago(hours=2))
        rep = self.status()
        self.assertEqual(rep["attention"]["unverified-bundle"], ["bundle b2: verified failed", "bundle b3: unverified"])
        self.assertEqual(rep["next"], f"{CLI} verify {NAME} b2")
        state.write_doc_once(self.lay.catalog(NAME, "b2.pruned"), records.new_doc("tombstone", bundle_id="b2"))
        self.assertEqual([b["id"] for b in st.bundles(self.ctx, NAME)["bundles"]], ["b3", "b1"])
        os.makedirs(self.lay.op_dir(NAME, 2, "backup"))  # b3 may be the open backup's own bundle
        self.assertEqual(self.codes(), ["open-operation"])
        cat = state.read_doc(self.lay.catalog(NAME, "b1"), "catalog")  # records bound to another hash prove nothing
        os.remove(self.lay.catalog(NAME, "b1"))
        state.write_doc_once(self.lay.catalog(NAME, "b1"), cat | {"bundle_hash": "0" * 64})
        self.assertIn("backup-old", self.codes())

    def test_a_torn_verification_line_was_never_written(self) -> None:
        """A power loss during the append leaves a partial last line until the executor's next write heals it; the
        diagnostics read the complete lines only."""
        self.deploy()
        digest = self.bundle("b2", ago(hours=1), verified=True)
        torn = records.dumps(records.new_doc("verification", bundle_id="b2", bundle_hash=digest, level="verified"))
        with open(self.lay.verification(NAME, "b2"), "ab") as f:
            f.write(torn[:20])
        self.assertEqual((self.status()["exit"], st.bundles(self.ctx, NAME)["bundles"][0]["id"]), (0, "b2"))
        self.assertEqual(st.scheduled_status(self.ctx)["exit"], 0)

    def test_failed_drill_points_at_a_new_drill_and_tombstones_are_records(self) -> None:
        self.deploy()
        self.bundle("b2", ago(hours=1), verified=True, restore_tested=False)
        rep = self.status()
        self.assertEqual(rep["attention"]["unverified-bundle"], ["bundle b2: restore-tested failed"])
        self.assertEqual(rep["next"], f"{CLI} verify {NAME} b2 --restore-test")  # a plain verify cannot clear it
        self.bundle("b3.pruned", ago(hours=2), verified=True)  # a bundle id may end in .pruned (bundle.ID_RE)
        self.assertEqual([b["id"] for b in st.bundles(self.ctx, NAME)["bundles"]], ["b2", "b3.pruned", "b1"])
        state.write_doc_once(
            self.lay.catalog(NAME, "b3.pruned.pruned"), records.new_doc("tombstone", bundle_id="b3.pruned")
        )
        self.assertEqual([b["id"] for b in st.bundles(self.ctx, NAME)["bundles"]], ["b2", "b1"])

    def test_open_operations(self) -> None:
        self.deploy()
        d = self.lay.op_dir(NAME, 2, "deploy")
        steps = [{"n": 1, "type": "Up"}, {"n": 2, "type": "Pause"}, {"n": 3, "type": "Up"}]
        state.write_doc_once(f"{d}/plan.json", records.new_doc("plan", steps=steps))
        j = Journal(d, 2)
        j.intent(1, 1)
        j.close_step(1, "done")
        j.intent(2, 1)
        rep = self.status()
        self.assertEqual(rep["attention"], {"open-operation": ["operation 2 (deploy) is paused"]})
        self.assertEqual(rep["instance"]["operations"][0]["last_step"]["type"], "Pause")
        self.assertEqual(rep["next"], f"{CLI} resume {NAME}")
        os.remove(f"{d}/plan.json")
        self.assertEqual(self.status()["attention"]["open-operation"], ["operation 2 (deploy) is interrupted"])
        self.assertEqual(st.history(self.ctx, NAME)["operations"][0]["state"], "interrupted")
        executor = {brand.label("role"): "exec", brand.label("instance"): NAME}  # as the CLI launches it
        self.docker.box.append(container(brand.executor_name(NAME), executor))
        rep = self.status()
        self.assertEqual((rep["exit"], rep["instance"]["operations"][0]["state"]), (0, "running"))
        self.assertEqual(st.history(self.ctx, NAME)["operations"], [{"seq": 2, "kind": "deploy", "outcome": "open"}
                                                                   | {"state": "running"}])  # fmt: skip
        self.docker.down = True  # history then tells from the records alone
        self.assertEqual(st.history(self.ctx, NAME)["operations"][0]["state"], "interrupted")

    def test_operations_run_in_the_host_executor_or_a_terminal_task(self) -> None:
        """The host executor runs a selftest instance's operations, and a terminal task runs in the CLI: their open
        operation is running while that executor runs, or while a task container of it does as the CLI has a step in
        flight, never stuck. A task container that outlived its executor, or whose step closed, runs no operation."""
        role, own, op, step = brand.label("role"), brand.label("instance"), brand.label("op"), brand.label("step")
        d, task = self.lay.op_dir(NAME, 2, "task"), {"n": 1, "type": "RunTask", "klass": "forward", "args": {}}

        def plan(foreground: bool) -> None:
            if os.path.exists(f"{d}/plan.json"):
                os.remove(f"{d}/plan.json")
            doc = records.new_doc("plan", steps=[task], inputs={"foreground": foreground})
            state.write_doc_once(f"{d}/plan.json", doc)

        plan(False)  # the detached executor runs it
        Journal(d, 2).intent(1, 2)
        orphan = container("lite-x2-1-a2", {own: NAME, op: "2", step: "1", role: "task"})  # its executor is gone
        self.docker.box += [
            container(brand.executor_name(None), {role: "exec"}),  # it never runs a plain instance's operation
            container(brand.executor_name("other"), {role: "exec", own: "other"}),
            container("lite-x3-1-a1", {own: NAME, op: "3", step: "1", role: "task"}),  # another operation's
            container("lite-x2-1-a1", {own: NAME, op: "2", step: "1", role: "task"}, running=False),  # an exited one
            orphan,
        ]
        self.assertEqual((self.codes(), st.history(self.ctx, NAME)["operations"][0]["state"]),
                         (["open-operation"], "interrupted"))  # fmt: skip
        self.assertEqual(self.status()["next"], "docker stop lite-x2-1-a2")  # every other command refuses (F15)
        plan(True)  # the CLI runs it
        self.docker.box.remove(orphan)
        self.assertEqual(self.codes(), ["open-operation"])
        self.docker.box.append(orphan)
        rep = self.status()
        self.assertEqual((rep["exit"], rep["instance"]["operations"][0]["state"]), (0, "running"))
        self.assertEqual(st.history(self.ctx, NAME)["operations"][0]["state"], "running")
        Journal(d, 2).close_step(1, "unknown", {"code": "task-running"})  # the CLI could not stop it and is gone
        self.assertEqual((self.codes(), st.history(self.ctx, NAME)["operations"][0]["state"]),
                         (["open-operation"], "interrupted"))  # fmt: skip
        name = brand.SELFTEST_PREFIX + "lite-a"
        self.register(name)
        os.makedirs(self.lay.op_dir(name, 1, "deploy"))
        self.assertEqual(
            st.status(self.ctx, name)["attention"], {"open-operation": ["operation 1 (deploy) is interrupted"]}
        )
        marker = records.new_doc(SELFTEST_KIND, run_id="r1", instance=name, at=ago(minutes=1))
        state.write_doc_once(self.lay.inst(name, SELFTEST_MARKER), marker)  # selftest made it: its executor runs it
        rep = st.status(self.ctx, name)
        self.assertEqual((rep["exit"], rep["instance"]["operations"][0]["state"]), (0, "running"))
        self.assertEqual(st.history(self.ctx, name)["operations"][0]["state"], "running")

    def test_one_broken_instance_config_is_reported_and_the_others_go_on(self) -> None:
        self.deploy()
        self.register("other")
        Path(self.lay.inst_toml("other")).write_text("instance = 1\nname = [\n")
        rep = st.status(self.ctx, None)
        rows = [(r["name"], r["state"], r["release"], r["attention"]) for r in rep["instances"]]
        self.assertEqual(rows, [(NAME, "running", "r1", []), ("other", None, None, ["invalid-config"])])
        self.assertEqual(
            (rep["exit"], rep["next"], rep["lines"][1]), (5, f"{CLI} status other", "other: unknown, invalid-config")
        )
        with self.assertRaises(Refused) as cm:  # its own status names the errors
            st.status(self.ctx, "other")
        self.assertEqual(cm.exception.code, "invalid-instance")
        rep = st.scheduled_status(self.ctx)
        self.assertEqual((rep["exit"], rep["codes"]), (5, {"other": ["invalid-config"]}))
        os.remove(self.lay.inst_toml("other"))
        self.assertEqual(st.status(self.ctx, None)["instances"][1]["attention"], ["invalid-config"])
        self.assertEqual(st.scheduled_status(self.ctx)["exit"], 0)
        os.makedirs(self.lay.inst("Bad"))  # a name no init gives, a usage error (exit 2): reported all the same
        Path(self.lay.record_json("Bad")).write_bytes(Path(self.lay.record_json("other")).read_bytes())
        rows = [(r["name"], r["attention"]) for r in st.status(self.ctx, None)["instances"]]
        self.assertEqual(rows[0], ("Bad", ["invalid-config"]))

    def test_a_partial_stop_is_no_change_outside(self) -> None:
        """`stop <i> <service>` leaves the instance running: a container that last stopped within a completed stop of
        its service is stopped as the owner asked, also after later operations; one stopped at another time, or
        within an operation of another kind or outcome, is changed-outside."""
        self.deploy()
        d = self.lay.op_dir(NAME, 2, "stop")
        stop = {"n": 1, "type": "Stop", "klass": "reversible", "args": {"services": ["app"]}}
        state.write_doc_once(f"{d}/plan.json", records.new_doc("plan", steps=[stop]))
        span = {"started_at": ago(minutes=10), "finished_at": ago(minutes=9)}
        state.write_doc_once(f"{d}/result.json", records.new_doc("result", outcome="completed", **span))
        later = self.lay.op_dir(NAME, 3, "backup")
        state.write_doc_once(f"{later}/result.json", records.new_doc("result", outcome="completed"))
        self.update(last_op={"seq": 3, "kind": "backup", "outcome": "completed", "at": ago(minutes=1)})
        app = self.docker.box[0]
        app["State"] = {"Status": "exited", "Running": False, "FinishedAt": ago(minutes=9)[:-1] + ".987654321Z"}
        rep = self.status()
        self.assertEqual((rep["exit"], rep["instance"]["services"][0]["state"]), (0, "exited"), rep["lines"])
        app["State"]["FinishedAt"] = ago(minutes=5)[:-1] + ".1Z"  # started and stopped again outside
        self.assertEqual(self.status()["attention"], {"changed-outside": ["service app is not running"]})
        app["State"]["FinishedAt"] = ago(minutes=9, seconds=30)[:-1] + ".1Z"
        self.assertEqual(self.status()["exit"], 0)
        os.rename(d, self.lay.op_dir(NAME, 2, "restart"))
        self.assertEqual(self.codes(), ["changed-outside"])
        os.rename(self.lay.op_dir(NAME, 2, "restart"), d)
        os.remove(f"{d}/result.json")
        state.write_doc_once(f"{d}/result.json", records.new_doc("result", outcome="failed-unchanged", **span))
        self.assertEqual(self.codes(), ["changed-outside"])

    def test_a_task_that_may_have_run_points_at_abandon(self) -> None:
        """A forward task that is not idempotent and may have run is never repeated blind: `resume` refuses it until
        the owner decides (LIFECYCLE §3.4), so `next` is `abandon`, never a resume that sends the owner back here."""
        self.deploy()
        d = self.lay.op_dir(NAME, 2, "deploy")
        task = {"n": 2, "type": "RunTask", "klass": "forward", "args": {"effect": "data", "idempotent": False}}
        steps = [{"n": 1, "type": "Stop", "klass": "reversible", "args": {}}, task]
        state.write_doc_once(f"{d}/plan.json", records.new_doc("plan", steps=steps))
        j = Journal(d, 2)
        j.intent(1, 1)
        j.close_step(1, "done")
        self.assertEqual(self.status()["next"], f"{CLI} resume {NAME}")
        j.intent(2, 1)
        j.close_step(2, "unknown")
        self.assertEqual(self.status()["next"], f"{CLI} abandon {NAME}")
        for change in ({"klass": "scratch"}, {"klass": "forward", "args": {"effect": "data", "idempotent": True}}):
            task |= change  # scratch is discarded and redone; an idempotent task is re-run
            os.remove(f"{d}/plan.json")
            state.write_doc_once(f"{d}/plan.json", records.new_doc("plan", steps=steps))
            self.assertEqual(self.status()["next"], f"{CLI} resume {NAME}")

    def test_record_codes_follow_priority(self) -> None:
        self.deploy()
        last = {"seq": 4, "kind": "deploy", "outcome": "failed-frozen", "at": ago(hours=1)}
        self.update(state="frozen", last_op=last, held_since=ago(hours=2))
        rep = self.status()
        self.assertEqual(sorted(rep["attention"]), ["frozen", "held", "last-op-failed"])
        self.assertEqual(rep["next"], f"{CLI} history {NAME}")  # no update froze it with a way forward
        self.update(state="running", last_op=last | {"outcome": "failed-unchanged"})
        d = self.lay.op_dir(NAME, 4, "deploy")
        for nxt, want in ((f"{CLI} status {NAME}", f"{CLI} history {NAME}"), (f"{CLI} backup {NAME}",) * 2):
            state.write_doc_once(f"{d}/result.json", records.new_doc("result", outcome="failed-unchanged", next=nxt))
            self.assertEqual(self.status()["next"], want)  # the next command its result printed, unless `status`
            shutil.rmtree(d)
        self.update(state="running", last_op=last | {"outcome": "needs-review"})
        rep = self.status()
        self.assertEqual((sorted(rep["attention"]), rep["next"]), (["held", "needs-review"], f"{CLI} history {NAME}"))
        self.update(last_op=None)
        self.assertEqual(self.status()["next"], f"{CLI} task {NAME} queue-resume")

    def test_live_changes(self) -> None:
        self.deploy()
        app = self.docker.box[0]
        app["State"] = {"Status": "exited", "Running": False}
        rep = self.status()
        self.assertEqual((rep["attention"], rep["next"]), ({"changed-outside": ["service app is not running"]},
                                                           f"{CLI} restart {NAME}"))  # fmt: skip
        self.update(state="stopped")
        self.assertEqual(self.status()["exit"], 0)
        app["Image"] = "sha256:" + "2" * 64
        app["Config"]["Labels"][cx.CONFIG_HASH] = "h2"
        self.docker.box.append(container("intruder", {PROJECT_LABEL: NAME, cx.SERVICE: "app"}))
        self.docker.box.append(container("lite-app-run-1", labels(NAME, "app", **{st.ONEOFF: "True"}), image="x"))
        self.docker.nets[0]["Labels"] = {PROJECT_LABEL: NAME}  # Compose would use it for the project
        rep = self.status()
        self.assertEqual(
            rep["attention"]["foreign"],
            ["container intruder is in project lite but not labelled as its own",
             "network lite_default is in project lite but not labelled as its own"],
        )  # fmt: skip
        self.docker.nets.clear()
        rep = self.status()
        self.assertEqual(sorted(rep["attention"]), ["changed-outside", "drift", "foreign"])
        self.assertEqual(
            rep["attention"]["changed-outside"],
            [f"service app runs sha256:{'2' * 64}, not {IMAGE}", "network lite_default is missing"],
        )
        os.rmdir(self.lay.data_gen(NAME, "data", "g1"))
        rep = self.status()
        self.assertEqual(rep["attention"]["changed-outside"][0], "generation g1 of store data is missing")
        self.assertEqual(rep["next"], f"{CLI} bundles {NAME}")
        names = [r["name"] for r in st.ps(self.ctx, NAME)["containers"] if not r["owned"]]
        self.assertEqual(names, ["intruder"])

    def test_a_stopped_instance_started_outside_is_changed_outside(self) -> None:
        self.deploy()
        self.update(state="stopped")
        rep = self.status()
        self.assertEqual(rep["attention"], {"changed-outside": ["service app runs while the instance is stopped"]})
        self.assertEqual((rep["exit"], rep["next"]), (5, f"{CLI} stop {NAME}"))

    def test_daemon_unreachable_engine_mismatch_and_uncertified(self) -> None:
        self.deploy()
        os.remove(self.lay.catalog(NAME, "b1"))
        self.docker.down = True
        rep = self.status()
        self.assertEqual(sorted(rep["attention"]), ["backup-old", "daemon-unreachable", "restore-test-old"])
        self.assertEqual((rep["exit"], rep["next"], rep["instance"]["services"]), (5, None, None))
        self.docker.down, self.docker.engine = False, "E2"
        self.assertIn("engine-mismatch", self.codes())
        self.docker.engine = "E1"
        del self.ctx.info  # the context caches what the daemon reported

        def gate(ctx: object, tier: int) -> list[str]:
            if tier == 2:
                raise CannotRun("no host certification for this platform build", code="uncertified")
            return []

        with mock.patch.object(cx, "gate", gate):
            rep = self.status()
        self.assertEqual(rep["attention"]["uncertified"], ["no host certification for this platform build"])
        self.assertEqual(rep["host"]["gate_tier"], 1)

        def untested(ctx: object, tier: int) -> list[str]:
            if tier == 2:
                raise CannotRun(
                    "Engine 99.0 on amd64 is not a tested combination of this release", code="untested-platform"
                )
            return []

        self.bundle("b2", ago(hours=1), verified=True, restore_tested=True)
        with mock.patch.object(cx, "gate", untested):
            rep = self.status()
        self.assertEqual((sorted(rep["attention"]), rep["next"]), (["uncertified"], None))  # selftest cannot help

    def test_doctor_on_an_instance_never_deployed(self) -> None:
        """init's secret files are no finding before the first deploy: only a deployed manifest says which belong."""
        Path(self.lay.secrets_dir(NAME), "env", "MAIL_PASSWORD").write_text("x" * 32)
        os.chmod(Path(self.lay.secrets_dir(NAME), "env", "MAIL_PASSWORD"), 0o600)
        rep = st.doctor(self.ctx, NAME)
        self.assertEqual((rep["exit"], {k: v for k, v in rep["checks"].items() if v}), (0, {}), rep["lines"])
        Path(self.lay.secrets_dir(NAME), "empty").write_text("")
        self.assertEqual(st.doctor(self.ctx, NAME)["checks"]["secrets"], ["empty: not a regular non-empty file"])
        self.docker.engine = "E2"
        del self.ctx.info  # the context caches what the daemon reported
        rep = st.doctor(self.ctx, NAME)
        self.assertEqual(rep["checks"]["gate"], ["not checked: the Docker engine ID differs from host.json"])

    def test_scheduled_status_reports_changes_once(self) -> None:
        self.deploy()
        before = tree(self.lay.root)
        rep = st.scheduled_status(self.ctx)
        self.assertEqual((rep["exit"], rep["lines"]), (0, []))
        self.assertEqual(tree(self.lay.root), before)
        os.remove(self.lay.catalog(NAME, "b1"))
        rep = st.scheduled_status(self.ctx)
        self.assertEqual((rep["exit"], rep["lines"]), (5, [f"new: {NAME} backup-old", f"new: {NAME} restore-test-old"]))
        written = tree(self.lay.root)
        self.assertEqual(set(written) - set(before) | {self.lay.attention_json}, {self.lay.attention_json})
        self.assertEqual(state.read_doc(self.lay.attention_json, "attention")["codes"], {NAME: rep["codes"][NAME]})
        self.assertEqual((st.scheduled_status(self.ctx)["exit"], tree(self.lay.root)), (0, written))
        self.bundle("b2", ago(hours=1), verified=True, restore_tested=True)
        rep = st.scheduled_status(self.ctx)
        self.assertEqual((rep["exit"], rep["lines"][0]), (5, f"cleared: {NAME} backup-old"))
        self.assertEqual(st.scheduled_status(self.ctx)["exit"], 0)

    def test_diagnostics_write_nothing(self) -> None:
        self.deploy()
        os.makedirs(self.lay.op_dir(NAME, 2, "backup"))
        state.write_doc_once(
            f"{self.lay.op_dir(NAME, 1, 'deploy')}/result.json",
            records.new_doc("result", outcome="completed", exit=0, message="done", finished_at=ago(days=2)),
        )
        before = tree(self.base)
        with mock.patch.object(cx, "current"):
            for rep in (self.status(), st.doctor(self.ctx, NAME), st.list_(self.ctx), st.ps(self.ctx, NAME)):
                self.assertIn("next", rep)
        hist = st.history(self.ctx, NAME)
        self.assertEqual([(r["seq"], r["outcome"]) for r in hist["operations"]], [(1, "completed"), (2, "open")])
        self.assertEqual(st.list_(self.ctx)["instances"][0]["release"], "r1")
        st.bundles(self.ctx, NAME)
        self.assertEqual(tree(self.base), before)

    def test_logs_redact_the_instance_secrets(self) -> None:
        self.deploy()
        secret, other = "Canary" + os.urandom(8).hex(), "Other" + os.urandom(8).hex()
        Path(self.lay.secrets_dir(NAME), "env", "MAIL_PASSWORD").write_text(secret)
        Path(self.lay.secrets_dir(NAME), "token").write_text(other)
        seen: list[Redactor] = []

        class Logs:
            def __init__(self, *, config_dir: str, redactor: Redactor) -> None:
                seen.append(redactor)

            def logs(self, name: str, *, since: str | None, tail: int) -> Result:
                text = f"login with {secret} and {other}\n"
                return Result(0, seen[0].redact(text), "", False, False)

        with mock.patch.object(st, "Docker", Logs):
            rep = st.logs(self.ctx, NAME, "app", since="10m")
        self.assertEqual(rep["lines"], ["lite-app-1 | login with *** and ***"])
        for bad in ("-1", "10m --x", "a"):
            with self.assertRaises(CannotRun) as usage:  # a usage error exits 2 (LIFECYCLE §6)
                st.logs(self.ctx, NAME, "app", since=bad)
            self.assertEqual((usage.exception.code, usage.exception.exit_code), ("usage", 2))
        with self.assertRaises(Refused) as cm:
            st.logs(self.ctx, NAME, "nope")
        self.assertEqual(cm.exception.code, "no-container")

    def test_doctor_checks(self) -> None:
        self.deploy()
        with mock.patch.object(cx, "current"):
            rep = st.doctor(self.ctx, NAME)
        self.assertEqual((rep["exit"], {k: v for k, v in rep["checks"].items() if v}), (0, {}), rep["lines"])
        self.assertIn("backup: online", rep["notes"])
        secret = Path(self.lay.secrets_dir(NAME), "env", "MAIL_PASSWORD")
        secret.write_text("x" * 32)
        secret.chmod(0o644)
        Path(self.lay.secrets_dir(NAME), "stray").write_text("")
        os.rmdir(self.lay.docker_config)
        entry = records.new_doc("allocation", instance="other", purpose="live", param="P", op=None, at=ago(days=1))
        state.write_doc_once(self.lay.allocation("port", "20001"), entry)
        intruder = container("web", {})
        intruder["HostConfig"]["PortBindings"] = {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "20001"}]}
        self.docker.box.append(intruder)
        failed = mock.Mock(side_effect=Refused("project lite is refused by the Compose policy:\nservices.app.x"))
        with mock.patch.object(cx, "current", failed), mock.patch.dict(os.environ, {brand.env("CRASH_AT"): "1:task"}):
            rep = st.doctor(self.ctx, NAME)
        checks = {k: v for k, v in rep["checks"].items() if v}
        self.assertEqual((rep["exit"], rep["code"]), (5, "findings"))
        self.assertEqual(
            checks["secrets"],
            ["env/MAIL_PASSWORD: mode 0644, the manifest says 0600", "stray: not a regular non-empty file"],
        )
        self.assertEqual(checks["policy"][1], "services.app.x")
        self.assertEqual(
            checks["collisions"], ["port 20001 is allocated to other", "port 20001 is published by container web"]
        )
        self.assertEqual(sorted(checks), ["collisions", "crash-hook", "docker-config", "policy", "secrets"])


if __name__ == "__main__":
    unittest.main()
