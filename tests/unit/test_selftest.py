"""`selftest` without a daemon: the offline checks over the repository's fixtures (Compose rendering is stubbed here;
tests/docker/test_selftest.py runs it for real, in the image without a daemon), the config-only change of commit B,
the refusals before anything is written, the gate waiver that only a selftest run's own marked instance gets, and the
teardown steps that only such an instance allows: `down` of its live project and the deletion of its generations."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from ingat import brand
from ingat.adapters.docker import PROJECT_LABEL, EffectToken
from ingat.adapters.runner import Result
from ingat.core import steps
from ingat.core.plan import new_plan
from ingat.model import records
from ingat.model.errors import CannotRun, Failed, Refused
from ingat.ops import context as cx
from ingat.ops import selftest
from ingat.policy import compose_policy, gate
from ingat.store import state

FIXTURES = str(Path(__file__).resolve().parents[2] / "fixtures")
SERVER: dict[str, Any] = {"Version": "29.9.0", "ApiVersion": "1.52", "Arch": "amd64", "Os": "linux"}
SERVER |= {"GitCommit": "a5b58c9", "BuildTime": "2026-10-08T20:39:33Z"}
SERVER["Components"] = [{"Name": "runc", "Version": "1.3.0"}, {"Name": "containerd", "Version": "v2.4.1"}]
INFO: dict[str, Any] = {"ID": "E1", "DockerRootDir": "/var/lib/docker", "Driver": "overlayfs", "KernelVersion": "6.6.1"}
INFO |= {"Architecture": "x86_64", "CpuCfsQuota": True, "CpuCfsPeriod": True, "MemoryLimit": True}
TESTED = [{"engine": "29.9", "arch": "amd64"}]
LITE = f"{brand.SELFTEST_PREFIX}1-lite"


class NoDocker:
    """Answers the image query only: these tests never reach Docker otherwise."""

    def __init__(self, image: dict[str, Any] | None = None) -> None:
        self.found = image

    def image(self, ref: str) -> dict[str, Any] | None:
        return self.found


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base)
        os.makedirs(f"{self.base}/facts/etc")
        Path(f"{self.base}/facts/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        self.tested: list[dict[str, str]] = list(TESTED)
        for patch in (
            mock.patch.object(brand, "HOST_FACTS_DIR", f"{self.base}/facts"),
            mock.patch.object(gate, "load_tested", lambda: self.tested),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.layout = state.Layout(f"{self.base}/root", f"{self.base}/backups")
        version = {"Client": {"Version": "29.9.0"}, "Server": dict(SERVER)}
        fields = {"layout": self.layout, "info": dict(INFO), "version": version, "image": "tool@sha256:1"}
        now = records.parse_iso("2026-10-15T10:00:00Z")
        self.ctx: Any = SimpleNamespace(**fields, operator="root", now=now, docker=NoDocker(), hostname="h")

    def marker(self, name: str, run_id: str = "r1", instance: str | None = None) -> None:
        doc = records.new_doc(steps.SELFTEST_KIND, run_id=run_id, instance=instance or name, at="t")
        state.write_doc_once(self.layout.inst(name, steps.SELFTEST_MARKER), doc)


class OfflineTest(Base):
    def run_offline(self, fixtures: str = FIXTURES, **patches: Any) -> tuple[dict[str, Any], mock.MagicMock]:
        with mock.patch.object(selftest, "validate", **patches) as validate:
            return selftest.run(self.ctx, host=False, offline=True, fixtures=fixtures), validate

    def test_the_repository_fixtures_pass(self) -> None:
        rep, validate = self.run_offline()
        self.assertEqual((rep["exit"], rep["code"], rep["result"], rep["next"]), (0, "ok", "PASS", None), rep)
        self.assertEqual(len(rep["lines"]), 8)  # three checks per fixture, the hostile services, the verdict
        self.assertTrue(all(x.startswith("PASS ") for x in rep["lines"][:-1]), rep["lines"])
        self.assertEqual(rep["lines"][-1], "selftest PASS")
        dirs = [c.args[1] for c in validate.call_args_list]
        self.assertEqual(dirs, [f"{FIXTURES}/fx-lite", f"{FIXTURES}/fx-web"])  # Compose and policy on both

    def test_a_broken_manifest_and_a_policy_refusal_fail_with_their_reasons(self) -> None:
        fixtures = f"{self.base}/fixtures"
        shutil.copytree(FIXTURES, fixtures)
        manifest = Path(fixtures, "fx-web", brand.MANIFEST_FILE)
        manifest.write_text(manifest.read_text().replace('app = "fx-web"\n', 'app = "fx-web"\nbogus = 1\n'))
        refusal = Refused("project sample is refused by the Compose policy:\nservices.app.privileged: refused")
        rep, validate = self.run_offline(fixtures, side_effect=[refusal])
        self.assertEqual((rep["exit"], rep["code"], rep["result"]), (3, "failed", "FAIL"))
        failed = [x for x in rep["lines"] if x.startswith("FAIL")]
        self.assertEqual(len(failed), 2, rep["lines"])
        self.assertIn("fx-lite: the Compose models", failed[0])
        self.assertIn("privileged", failed[0])
        self.assertTrue(failed[1].startswith("FAIL fx-web: the manifest parses") and "bogus" in failed[1])
        self.assertFalse(any(x.startswith("PASS fx-web") for x in rep["lines"]))  # skipped without a manifest
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(rep["lines"][-1], "selftest FAIL")

    def test_a_policy_that_accepts_a_hostile_service_fails(self) -> None:
        with mock.patch.object(compose_policy, "check", return_value=[]):
            rep, _ = self.run_offline()
        self.assertEqual(rep["exit"], 3)
        self.assertTrue(rep["lines"][-2].startswith("FAIL the Compose policy refuses"), rep["lines"])

    def test_each_hostile_service_alone_is_refused(self) -> None:
        pctx = compose_policy.PolicyContext("/sample", (), frozenset(), frozenset({"20000"}), True, brand.LABEL_NS)
        for snippet in selftest.HOSTILE:
            model = {"name": "x", "services": {"x": {"image": "x", **snippet}}}
            self.assertTrue(compose_policy.check(model, pctx), snippet)
        self.assertEqual(compose_policy.check({"name": "x", "services": {"x": {"image": "x"}}}, pctx), [])


class ConfigChangeTest(unittest.TestCase):
    def test_commit_b_adds_one_environment_value_at_the_mapping_indent(self) -> None:
        for fx in ("fx-lite", "fx-web"):
            text = Path(FIXTURES, fx, "compose.yaml").read_bytes()
            changed = selftest._config_change(text).decode().splitlines()
            at = changed.index("    environment:")
            self.assertEqual(changed[at + 1], '      SELFTEST_UPDATE: "B"')
            self.assertEqual([x for x in changed if x != changed[at + 1]], text.decode().splitlines())

    def test_a_compose_file_without_environment_refuses(self) -> None:
        with self.assertRaises(Failed):
            selftest._config_change(b"services:\n  app:\n    image: x\n")


class FullRefusalTest(Base):
    def setUp(self) -> None:
        super().setUp()
        os.makedirs(f"{self.base}/root", 0o700)
        state.write_doc_once(self.layout.host_json, records.new_doc("host", engine_id="E1"))

    def assert_refused(self, code: str) -> None:
        before = sorted(os.listdir(self.layout.root))
        with self.assertRaises(CannotRun) as cm:
            selftest.run(self.ctx, host=True, offline=False)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), (code, 2))
        self.assertEqual(sorted(os.listdir(self.layout.root)), before)  # nothing written, not even the host lock

    def test_an_untested_engine_refuses_before_anything_is_written(self) -> None:
        self.tested.clear()
        self.assert_refused("untested-platform")

    def test_missing_build_facts_refuse(self) -> None:
        os.remove(f"{self.base}/facts/etc/os-release")
        self.assert_refused("uncertified")

    def test_a_tool_image_missing_from_the_daemon_refuses(self) -> None:
        self.assert_refused("no-image")


class GateWaiverTest(Base):
    """Gate tier 2 without a certification refuses, except for an instance of the selftest run this process drives
    (its marker names that run); a marker alone is a file and waives nothing (ARCHITECTURE §3.6: no file widens gate
    tier 2), and an untested Engine refuses the run's instances too (F14)."""

    def gate(self, name: str | None) -> str | None:
        try:
            cx.gate(self.ctx, gate.TIER2, name)
        except CannotRun as e:
            return e.code
        return None

    def test_only_the_running_selftest_skips_the_certification_of_its_own_instances(self) -> None:
        self.assertEqual(self.gate(None), "uncertified")
        self.assertEqual(self.gate(LITE), "uncertified")  # the prefix alone proves nothing
        self.marker(LITE)
        self.assertEqual(self.gate(LITE), "uncertified")  # nor does the marker of a run no process here drives
        stale = f"{brand.SELFTEST_PREFIX}3-lite"
        self.marker(stale, run_id="r0")  # left by an earlier, killed run
        with mock.patch.object(steps, "SELFTEST_RUNS", {"r1"}):  # this process drives run r1
            self.assertIsNone(self.gate(LITE))
            self.assertEqual(self.gate(stale), "uncertified")
            self.assertEqual(self.gate(None), "uncertified")  # nothing changes for the host or other instances
            self.marker("lite-test")  # a marker on an instance without the prefix
            self.assertEqual(self.gate("lite-test"), "uncertified")
            other = f"{brand.SELFTEST_PREFIX}2-lite"
            self.marker(other, instance=LITE)  # a marker that names another instance
            self.assertEqual(self.gate(other), "uncertified")
            runs = (steps.selftest_run(self.layout, LITE), steps.selftest_run(self.layout, other))
            self.assertEqual(runs, ("r1", None))
            self.tested.clear()
            self.assertEqual(self.gate(LITE), "untested-platform")
        self.tested.extend(TESTED)
        self.assertEqual(self.gate(LITE), "uncertified")  # the run ended: its markers waive nothing any more


class StartTest(Base):
    """The run takes the first pair of names that nothing on the host carries yet, so that whatever its teardown
    finds under them later is its own (F8)."""

    def test_names_no_directory_docker_object_allocation_or_ledger_entry_carries(self) -> None:
        p, inst = brand.SELFTEST_PREFIX, brand.label("instance")
        found = SimpleNamespace(
            containers=lambda: [{"Config": {"Labels": {inst: f"{p}1-lite", PROJECT_LABEL: f"{p}1-lite--t5"}}}],
            networks=lambda: [{"Labels": {PROJECT_LABEL: f"{p}2-web"}}],
        )
        self.ctx.docker = found  # a drill container of an earlier instance 1-lite, the network of a project 2-web
        entry = records.new_doc("allocation", instance=f"{p}3-web", purpose="live", param="FXWEB_PORT", op=None, at="t")
        state.write_doc_once(self.layout.allocation("port", "20001"), entry)
        ledger = records.new_doc("ledger", image="sha256:" + "ab" * 32, pulled_by={"instance": f"{p}4-lite", "op": 2})
        state.write_doc_once(self.layout.ledger("ab" * 32, f"{p}4-lite-2"), ledger)
        os.makedirs(self.layout.bundle_dir(f"{p}5-web", "b1"))
        t = selftest._start(self.ctx)
        self.assertEqual(t.names, [f"{p}6-lite", f"{p}6-web"])
        doc = state.read_doc(os.path.join(t.dir, selftest.RUN_MARKER), steps.SELFTEST_KIND)
        self.assertEqual((doc["run_id"], doc["instances"]), (t.id, t.names))


class FakeDocker:
    def __init__(self) -> None:
        self.running: list[dict[str, Any]] = []
        self.project: list[dict[str, Any]] = []  # the containers of the live project

    def containers(self, labels: dict[str, str] | None = None, project: str | None = None) -> list[dict[str, Any]]:
        return self.project if project else [] if labels else self.running

    def networks(self, labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return []


class SelftestStepsTest(Base):
    """`Teardown` of a live project and `Delete` of a generation act only for an instance a selftest run marked."""

    def op(self, name: str) -> steps.Op:
        v = {"project": name, "directory": "/x", "files": ["compose.yaml"], "override": "", "env": {}}
        plan = new_plan("teardown", name, "B", [], {}, {"variants": {"current": v}}, [])
        self.compose = mock.Mock(**{"down.return_value": Result(0, "", "", False, False)})
        return steps.Op(self.layout, FakeDocker(), self.compose, plan, name, 3, "/op", mock.Mock(), "/op/v")  # type: ignore[arg-type]

    def generation(self, name: str, owner: str | None = None) -> str:
        path = self.layout.data_gen(name, "data", "g1")
        os.makedirs(path)
        Path(path, "app.db").write_bytes(b"x")
        doc = records.new_doc("generation", instance=owner or name, store="data", generation="g1", purpose="live", op=1)
        state.write_doc_once(path + ".json", doc)
        return path

    def run_step(self, op: steps.Op, type_: str, **args: Any) -> Any:
        step = new_plan("teardown", op.name, "B", [], {}, {}, [{"type": type_, "klass": "forward", "args": args}])
        fn = steps.teardown if type_ == "Teardown" else steps.delete
        return fn(op, step.steps[0], EffectToken(3, 1))

    def test_a_live_project_goes_down_only_for_a_marked_selftest_instance(self) -> None:
        for name in ("lite-test", LITE):
            with self.assertRaises(Refused) as cm:
                self.run_step(self.op(name), "Teardown", variant="current")
            self.assertEqual(cm.exception.code, "not-isolated")
            self.compose.down.assert_not_called()
        self.marker(LITE)
        self.assertEqual(self.run_step(self.op(LITE), "Teardown", variant="current"), {})
        self.assertEqual(self.compose.down.call_args.args[1].name, LITE)

    def test_a_live_teardown_re_proves_that_nothing_foreign_is_in_the_project(self) -> None:
        """`down` acts on the whole project: an object of it that is not the instance's, made after the plan, refuses
        the step before Compose runs (F8)."""
        self.marker(LITE)
        op = self.op(LITE)
        own = {"Name": f"/{LITE}-app-1", "Config": {"Labels": {brand.label("instance"): LITE, PROJECT_LABEL: LITE}}}
        hand = {"Name": "/hand-made", "Config": {"Labels": {PROJECT_LABEL: LITE, "com.docker.compose.service": "app"}}}
        op.docker.project = [own, hand]  # type: ignore[attr-defined]
        with self.assertRaises(Refused) as cm:
            self.run_step(op, "Teardown", variant="current")
        self.assertEqual(cm.exception.code, "foreign")
        self.assertIn("hand-made", cm.exception.message)
        self.assertNotIn(f"{LITE}-app-1", cm.exception.message)
        self.compose.down.assert_not_called()
        op.docker.project = [own]  # type: ignore[attr-defined]
        self.assertEqual(self.run_step(op, "Teardown", variant="current"), {})
        self.compose.down.assert_called_once()

    def test_a_generation_is_deleted_only_for_a_marked_selftest_instance_and_its_own_marker(self) -> None:
        item = {"kind": "generation", "store": "data", "gen": "g1"}
        kept = [self.generation("lite-test"), self.generation(LITE)]
        for name in ("lite-test", LITE):  # no selftest marker
            with self.assertRaises(Refused):
                self.run_step(self.op(name), "Delete", item=item)
        self.marker(LITE)
        other = f"{brand.SELFTEST_PREFIX}2-lite"
        self.marker(other)
        kept.append(self.generation(other, owner=LITE))  # its marker names another instance
        with self.assertRaises(Refused):
            self.run_step(self.op(other), "Delete", item=item)
        op = self.op(LITE)
        op.docker.running = [{"Name": "/x", "Mounts": [{"Source": kept[1]}]}]  # type: ignore[attr-defined]
        with self.assertRaises(Refused) as cm:
            self.run_step(op, "Delete", item=item)
        self.assertEqual(cm.exception.code, "in-use")
        self.assertTrue(all(os.path.exists(p) and os.path.exists(p + ".json") for p in kept))
        op.docker.running = []  # type: ignore[attr-defined]
        self.assertEqual(self.run_step(op, "Delete", item=item), {})
        self.assertFalse(os.path.exists(kept[1]) or os.path.exists(kept[1] + ".json"))
        self.assertEqual(self.run_step(op, "Delete", item=item), {})  # a redo finds it done
        self.assertTrue(os.path.exists(kept[0]) and os.path.exists(kept[2]))


if __name__ == "__main__":
    unittest.main()
