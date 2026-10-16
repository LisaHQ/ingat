"""Pure planning helpers of ops/context.py and ops/deploy.py: env files, params, probes, model rules, the policy wiring,
the gate's release facts, capacity, RunTask and capture steps, and the plan-time schema gate."""

import copy
import dataclasses
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

from ingat import __version__, brand
from ingat.adapters import override
from ingat.adapters.compose import Compose
from ingat.core.journal import Journal
from ingat.core.plan import new_plan
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.model.instance import Backups
from ingat.model.manifest import Activate, Manifest, parse_manifest
from ingat.model.records import new_doc
from ingat.ops import backup, deploy
from ingat.ops import context as cx
from ingat.ops import steps_build as sb
from ingat.ops.validate import validate
from ingat.store import fs, state
from ingat.store.locks import Lock
from ingat.store.state import Layout

REPO = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"
LITE: Manifest = parse_manifest((REPO / "fixtures/fx-lite/ingat.toml").read_bytes(), tool_version=__version__)
LAYOUT = Layout("/srv/r", "/srv/b")
GIVEN = {"FXLITE_IMAGE": "img:1", "FXLITE_PORT": "20080"}
TV = {"instance": "lite", "environment": "test", "host": "h", "release": "c" * 40, "commit": "c" * 40}


def env(**over: str) -> dict[str, str]:
    return cx.params(LITE, LAYOUT, "lite", GIVEN | over, TV, {"data": 3}, "/srv/r/instances/lite/env/e.env")


def model() -> dict[str, Any]:
    """A real Compose model of fx-lite rendered with the override (tests/unit/data/policy)."""
    doc: dict[str, Any] = json.loads((DATA / "policy/fx-lite.json").read_text())
    return doc


class EnvTest(unittest.TestCase):
    def test_env_text_quotes_in_order_and_refuses_unquotable_values_by_key(self) -> None:
        self.assertEqual(cx.env_text({"B": "a$b c", "A": ""}), b"B='a$b c'\nA=''\n")
        self.assertEqual(cx.env_values(cx.env_text({"B": "x#y", "A": ""})), {"B": "x#y", "A": ""})
        for bad in ("it's", "a\nb", "a\rb", "a\0b"):
            with self.assertRaises(Refused) as cm:
                cx.env_text({"OK": "1", "KEY": bad})
            self.assertEqual(cm.exception.code, "invalid-value")
            self.assertIn("KEY", cm.exception.message)
            self.assertNotIn(bad, cm.exception.message)

    def test_params_fill_paths_defaults_and_templates(self) -> None:
        e = env()
        self.assertEqual(e["FXLITE_DATA_DIR"], "/srv/r/data/lite/data/g3")
        self.assertEqual(e["FXLITE_ENV_FILE"], "/srv/r/instances/lite/env/e.env")
        self.assertEqual(e["FXLITE_RELEASE"], "c" * 40)
        self.assertEqual((e["FXLITE_IMAGE"], e["FXLITE_PORT"]), ("img:1", "20080"))
        first = cx.params(LITE, LAYOUT, "lite", GIVEN, TV, {}, "")
        self.assertEqual(first["FXLITE_DATA_DIR"], "/srv/r/data/lite/data/g1")  # first install: g1
        with self.assertRaises(Refused):
            cx.params(LITE, LAYOUT, "lite", {"FXLITE_IMAGE": "img:1"}, TV, {}, "")  # a port needs a value

    def test_probes_are_rendered_concretely(self) -> None:
        tv = TV | {f"param.{k}": v for k, v in env().items()}
        ready = cx.probe(LITE.probes["ready"], tv, env())
        self.assertEqual((ready["kind"], ready["service"], ready["port"]), ("exec", "app", None))
        self.assertEqual(ready["argv"], ["fx-lite", "probe", "http://127.0.0.1:3000/api/ready"])
        self.assertEqual(ready["expect"]["json"], {"status": ["ready"], "data_writable": [True]})
        self.assertEqual((ready["stable"], ready["interval"], ready["timeout"]), (5, 2, 120))
        live = cx.probe(LITE.smoke[0].probe, tv, env())
        self.assertEqual(
            (live["name"], live["kind"], live["port"], live["path"]), ("live", "http", 20080, "/api/health")
        )
        self.assertEqual((live["method"], live["expect"]["status"]), ("GET", 200))


class ModelTest(unittest.TestCase):
    def test_model_rules_that_need_compose(self) -> None:
        app = {"services": {"app": {"volumes": [{"type": "bind", "source": env()["FXLITE_DATA_DIR"]}]}}}
        self.assertEqual(cx.model_errors(LITE, app, env()), [])
        app["services"]["extra"] = {}
        app["services"]["ops"] = {"profiles": ["ops"]}  # task-only: needs no role
        app["secrets"] = {"tok": {"file": "/srv/r/instances/lite/secrets/tok"}}
        errs = cx.model_errors(LITE, app, env(FXLITE_DATA_DIR="/elsewhere"))
        self.assertEqual(len(errs), 3, errs)
        self.assertTrue(errs[0].startswith("services.extra:"))
        self.assertTrue(errs[1].startswith("stores.data.param:"))
        self.assertTrue(errs[2].startswith("secrets.tok:"))
        del app["services"]["app"]
        self.assertTrue(any(e.startswith("services: 'app'") for e in cx.model_errors(LITE, app, env())))
        built = dataclasses.replace(LITE, build_services=("ops", "gone"))  # OD-11 (b): labels of each are checked
        self.assertIn("compose.build_services: unknown gone", cx.model_errors(built, app, env()))
        self.assertFalse([e for e in cx.model_errors(built, app, env()) if "unknown ops" in e])

    def test_policy_wiring_allows_the_tool_paths_and_refuses_the_rest(self) -> None:
        m, root = model(), "/srv/ingat/instances/lite-test"
        e = {"FXLITE_DATA_DIR": f"{root}/data/data/g1", "FXLITE_PORT": "20080"}
        e["FXLITE_ENV_FILE"] = m["services"]["app"]["env_file"][0]["path"]
        spec = override.live(
            {"app": {}}, instance="lite-test", ns=brand.LABEL_NS, images={"app": "x"}, stores={}, networks=()
        )
        export = "/srv/ingat/cache/src/" + "0" * 40
        self.assertEqual(cx.policy_errors(LITE, m, spec, e, export, True), [])
        self.assertEqual(cx.binds(m), [f"{root}/data/data/g1"])
        hostile = copy.deepcopy(m)
        hostile["services"]["app"] |= {"privileged": True, "cpus": 0.5, "use_api_socket": True}  # Docker socket
        hostile["services"]["app"]["ports"][0]["published"] = "20081"
        found = cx.policy_errors(LITE, hostile, spec, e, export, False)
        for key in ("privileged", "ports[0]", "cpus", "use_api_socket"):
            self.assertTrue(any(f"services.app.{key}" in x for x in found), (key, found))
        self.assertTrue(cx.policy_errors(LITE, m, spec, e | {"FXLITE_DATA_DIR": f"{root}/data/data/g2"}, export, True))
        bridged = copy.deepcopy(m)
        bridged["services"]["app"]["network_mode"] = "bridge"  # would skip the internal networks of an isolated run
        self.assertEqual(cx.policy_errors(LITE, bridged, spec, e, export, True), [])
        found = cx.policy_errors(LITE, bridged, spec, e, export, True, isolated=True)  # F13
        self.assertTrue(any("services.app.network_mode" in x for x in found), found)

    def test_supported_refuses_what_m1_cannot_run(self) -> None:
        cx.supported(LITE)
        pg = parse_manifest((DATA / "fx-pg.toml").read_bytes(), tool_version=__version__)
        with self.assertRaises(Refused) as cm:
            cx.supported(pg)
        self.assertEqual(cm.exception.code, "not-in-this-release")
        for name in ("volume stores", "data services", "exec tasks"):
            self.assertIn(name, cm.exception.message)


def fake_ctx(root: str, user: str = "") -> Any:
    version = {"Client": {"Version": "29.0.0"}, "Server": {"Version": "29.0.1", "ApiVersion": "1.52", "Arch": "amd64"}}
    version["Server"] |= {"Os": "linux"}
    info = {"ClientInfo": {"Plugins": [{"Name": "compose", "Version": "v5.6.0"}]}}
    docker = SimpleNamespace(image=lambda ref: {"Id": ref, "Config": {"User": user}})
    layout = Layout(root, root + "-b")
    return SimpleNamespace(layout=layout, docker=docker, version=version, info=info, hostname="h", operator="t")


class StepsTest(unittest.TestCase):
    def test_task_steps_carry_the_task_and_its_owner(self) -> None:
        ctx, v = fake_ctx("/srv/r"), {"images": {"app": "sha256:1"}}
        step = sb.task_step(ctx, LITE, v, model(), LITE.tasks["backup"], "current", "scratch", group="capture")
        args = step["args"]
        self.assertEqual(
            (step["type"], step["klass"], step["group"], step["interruptible"]), ("RunTask", "scratch", "capture", True)
        )
        self.assertEqual(
            (args["mounts"], args["task_uid"], args["variant"]), ([["/out", "stage"]], [10001, 10001], "current")
        )
        self.assertEqual(args["exit"], {"0": "ok", "1": "failed", "2": "refused"})
        self.assertTrue(args["require_ok"])
        held = sb.task_step(ctx, LITE, v, model(), LITE.tasks["queue-held"], "current", "scratch")["args"]
        self.assertEqual((held["expect"], held["task_uid"], held["report"]), ({"outcome": ["preview"]}, None, True))
        restore = sb.task_step(ctx, LITE, v, model(), LITE.tasks["restore"], "bundle", "scratch")["args"]
        self.assertEqual(restore["store_params"], {"data": "FXLITE_DATA_DIR"})
        # no task user: the service's, else the image's; a name is refused
        t = dataclasses.replace(LITE.tasks["backup"], user=None)
        bare = {"services": {"app": {}}}
        self.assertEqual(sb.task_uid(fake_ctx("/srv/r", "1000"), v, bare, t), [1000, 1000])
        self.assertEqual(sb.task_uid(fake_ctx("/srv/r", ""), v, bare, t), [0, 0])
        with self.assertRaises(Refused) as cm:
            sb.task_uid(fake_ctx("/srv/r", "app"), v, bare, t)
        self.assertEqual(cm.exception.code, "task-user")

    def test_capture_group_then_verify_group(self) -> None:
        ctx = fake_ctx("/srv/r")
        dep = {"seq": 2, "release": "r", "commit": "c", "images": {"app": "sha256:1"}, "export": "/srv/r/cache/src/c"}
        dep |= {"manifest_sha256": "m", "model_sha256": "x", "schema": {"expected": 1, "actual": 1, "at": "t"}}
        ld = cx.Loaded(
            "lite", SimpleNamespace(environment="test"), {"lineage": "l", "generations": {"data": 1}}, dep, LITE
        )
        steps: list[Any] = [{"type": "Stop"}]
        sb.capture_steps(
            ctx, ld, {"images": {"app": "sha256:1"}}, model(), steps, "current", "pre-change", "writers-stopped"
        )
        types = [(s["type"], s.get("group"), s["args"].get("phase")) for s in steps[1:]]
        expected = [
            ("CaptureBundle", "capture", "begin"),
            ("RunTask", "capture", None),
            ("CaptureBundle", "capture", "seal"),
        ]
        self.assertEqual(types, [*expected, ("VerifyBundle", "verify", None), ("Record", None, None)])
        seal = steps[3]["args"]
        self.assertEqual(
            (seal["class"], seal["stage_owner"], seal["consistency"]), ("pre-change", [10001, 10001], "writers-stopped")
        )
        self.assertEqual(seal["schema"], {"expected": 1, "actual": 1})
        self.assertEqual(seal["deployment"]["seq"], 2)
        self.assertEqual(seal["meta_files"]["deployment.json"], "/srv/r/instances/lite/deployments/2.json")
        self.assertEqual(seal["tool"]["compose"], "v5.6.0")
        self.assertEqual(
            steps[-1]["args"], {"kind": "verification", "level": "verified", "bundle_from": 5, "steps_ok": []}
        )


def loaded(record: dict[str, Any], dep: dict[str, Any] | None, m: Manifest = LITE) -> cx.Loaded:
    return cx.Loaded("lite", SimpleNamespace(environment="test"), record, dep, m if dep else None)  # type: ignore[arg-type]


def source(m: Manifest) -> cx.Source:
    return cx.Source("d" * 40, "d" * 40, "/srv/r/cache/src/" + "d" * 40, m)


class DeployStepsTest(unittest.TestCase):
    DEP: ClassVar[dict[str, Any]] = {"seq": 1, "release": "r", "commit": "c", "export": "/srv/r/cache/src/c"}

    def update(self, m: Manifest, cm: Manifest = LITE) -> list[Any]:
        steps: list[Any] = []
        ld = loaded(
            {"lineage": "l", "generations": {"data": 1}}, self.DEP | {"images": {"app": "sha256:1"}, "schema": None}, cm
        )
        variants = {"current": {"images": {"app": "sha256:1"}}, "candidate": {"images": {"app": "sha256:2"}}}
        with mock.patch.object(cx, "payload_size", return_value=100):
            self.needs = deploy._update(fake_ctx("/srv/r"), ld, source(m), cm, variants, (model(), model()), steps)
        return steps

    def test_update_activation_is_forward_even_without_a_migrate_task(self) -> None:
        """The first start of a candidate writer may migrate at start: undoing it would restart the old release on
        changed data (LIFECYCLE §4.4 step 11 is forward)."""
        two = (Activate(("worker",), ("ready",), False), Activate(("app",), ("ready", "edge-live"), True))
        m = dataclasses.replace(LITE, deploy=dataclasses.replace(LITE.deploy, migrate=None), activate=two)
        steps = self.update(m)
        self.assertEqual([s["type"] for s in steps if s["type"] in ("Stop", "Up")], ["Stop", "Up", "Up"])
        self.assertEqual([s["klass"] for s in steps if s["type"] == "Up"], ["forward", "forward"])
        self.assertEqual(steps[-2]["args"]["services"], ["worker"])  # the first forward step: the forward point
        self.assertNotIn("forward", [s["klass"] for s in steps if s["type"] != "Up"])
        self.assertEqual(self.needs, {"/srv/r": 100, "/srv/r-b": 100})  # the stage and the published copy

    def test_migrate_reads_the_bundle_copy_only_as_its_owner(self) -> None:
        migrate = dataclasses.replace(LITE.tasks["migrate"], mounts={"/in": "bundle"}, user="1000:1000")
        m = dataclasses.replace(LITE, tasks=LITE.tasks | {"migrate": migrate})
        verify = [s for s in self.update(m) if s["type"] == "VerifyBundle"]
        self.assertEqual(verify[0]["args"]["input_owner"], [1000, 1000])
        self.assertEqual(self.needs, {"/srv/r": 200, "/srv/r-b": 100})  # plus the private input copy (§5.8)
        reader = dataclasses.replace(LITE.tasks["restore"], name="check")  # a verify task that reads the bundle
        backup = dataclasses.replace(LITE.backup, verify=("check",))
        with self.assertRaises(Refused) as cm:
            self.update(m, dataclasses.replace(LITE, tasks=LITE.tasks | {"check": reader}, backup=backup))
        self.assertEqual(cm.exception.code, "task-user")

    def test_install_keeps_the_g1_of_an_unfinished_install(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ctx = fake_ctx(d)
            cv = {"values": TV, "images": {"app": "sha256:2"}}
            gen = ctx.layout.data_gen("lite", "data", "g1")
            for marker in (False, True):
                if marker:  # left by an install that ended frozen past its forward point
                    state.write_doc_once(f"{gen}.json", new_doc("generation", instance="lite", store="data", op=1))
                steps: list[Any] = []
                deploy._install(ctx, loaded({"generations": {}}, None), source(LITE), cv, model(), {}, steps)
                types = ["RunTask", "Up", "Pause"]
                self.assertEqual([s["type"] for s in steps], types if marker else ["CreateGeneration", *types])
                self.assertEqual(steps[-3]["args"]["gen_paths"], {"data": gen})  # generation:<store> mounts

    def test_the_check_reads_a_probe_schema_no_earlier_up_read(self) -> None:
        self.assertEqual(deploy._check(LITE, [])["args"]["wait"], ["ready"])
        self.assertEqual(deploy._check(LITE, [])["args"]["schema_probe"], "ready")
        read = deploy._up(LITE, "candidate", ["app"], ["ready"], klass="reversible")
        check = deploy._check(LITE, [read])["args"]
        self.assertEqual((check["wait"], check["identity"], check["smoke"], check["services"]), ([], True, True, []))

    def test_data_changing_counts_the_writers_of_both_releases(self) -> None:
        old, new = {"app": "sha256:1", "ops": "sha256:3"}, {"app": "sha256:2", "ops": "sha256:3"}
        services = dataclasses.replace(LITE.services, writers=(), stateless=("app",))
        stateless = dataclasses.replace(LITE, services=services, schema=None)
        self.assertTrue(deploy.data_changing(LITE, LITE, old, new))
        self.assertTrue(deploy.data_changing(stateless, LITE, old, new))  # app was a writer of the running release
        self.assertFalse(deploy.data_changing(stateless, stateless, old, new))
        self.assertFalse(deploy.data_changing(LITE, LITE, old, old))
        self.assertTrue(deploy.data_changing(dataclasses.replace(stateless, schema=LITE.schema), stateless, old, new))


class SecretsTest(unittest.TestCase):
    def test_app_env_refers_to_secrets_by_file_and_refuses_an_empty_one(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ctx = fake_ctx(d)
            ld = cx.Loaded("lite", SimpleNamespace(app_env={"BASE_URL": "http://x"}), {}, None, None)  # type: ignore[arg-type]
            secret = Path(ctx.layout.secrets_dir("lite"), "env", "MAIL_PASSWORD")
            secret.parent.mkdir(parents=True)
            secret.write_text("")  # ARCHITECTURE §9.4: a regular, non-empty file
            with self.assertRaises(Refused) as cm:
                cx.app_env(ctx, ld, LITE)
            self.assertEqual((cm.exception.code, "MAIL_PASSWORD" in cm.exception.message), ("missing-secret", True))
            secret.write_text("Canary-s3cret")
            spec, content = cx.app_env(ctx, ld, LITE)
            assert spec is not None
            self.assertIn(b"MAIL_PASSWORD='Canary-s3cret'", content)
            self.assertNotIn("Canary-s3cret", json.dumps(spec))
            self.assertEqual(dict(spec["lines"])["MAIL_PASSWORD"], {"secret_file": str(secret)})

    def test_deploy_redacts_the_secrets_of_both_releases_and_needs_its_bound_secret_files(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ctx = fake_ctx(d)
            sdir = Path(ctx.layout.secrets_dir("lite"))
            (sdir / "env").mkdir(parents=True)
            (sdir / "env" / "MAIL_PASSWORD").write_text("p")
            (sdir / "tok").write_text("")
            current = SimpleNamespace(secrets={"tok": None}, app_env=None)  # a secret the candidate dropped
            ld = cx.Loaded("lite", None, {}, {}, current)  # type: ignore[arg-type]
            models = [{"secrets": {"tok": {"name": "lite_tok", "file": str(sdir / "tok")}}}]
            for content in (None, ""):  # missing, then empty
                if content is None:
                    (sdir / "tok").unlink()
                else:
                    (sdir / "tok").write_text(content)
                with self.assertRaises(Refused) as cm:
                    deploy._secrets(ctx, ld, LITE, models)
                self.assertEqual(cm.exception.code, "missing-secret")
            (sdir / "tok").write_text("t")
            self.assertEqual(
                deploy._secrets(ctx, ld, LITE, models), [str(sdir / "env/MAIL_PASSWORD"), str(sdir / "tok")]
            )


class ExportTest(unittest.TestCase):
    def test_a_concurrent_export_is_never_removed_and_a_dead_one_is(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ctx, commit = fake_ctx(d), "c" * 40
            dest = ctx.layout.cache_src(commit)
            other = Path(os.path.dirname(dest), f".{commit}.tmp-other")  # another planner is still filling it
            other.mkdir(parents=True)
            (other / "compose.yaml").write_text("services: {}")
            lock = os.path.join(os.path.dirname(dest), f".{commit}.lock")

            def archive(bare: str, c: str, tmp: str) -> None:
                Path(tmp, "compose.yaml").write_text("services: {}")

            with mock.patch.object(cx.git, "archive", side_effect=archive):
                with Lock(lock, {"op": "export"}):
                    with self.assertRaises(CannotRun) as cm:
                        cx._export(ctx, "/bare", commit)
                    self.assertEqual(cm.exception.code, "lock-busy")
                    self.assertTrue((other / "compose.yaml").exists())
                    self.assertFalse(os.path.exists(dest))
                self.assertEqual(cx._export(ctx, "/bare", commit), dest)  # its planner died: the leftover goes
            self.assertFalse(other.exists())
            self.assertEqual((os.stat(dest).st_mode & 0o777, os.listdir(dest)), (0o555, ["compose.yaml"]))
            self.assertEqual(os.stat(f"{dest}/compose.yaml").st_mode & 0o777, 0o444)

    def test_compose_settings_never_reach_the_env_file(self) -> None:
        """COMPOSE_* and DOCKER_* params would set Compose's own options (ARCHITECTURE §9.5): refused before Compose
        runs."""
        ctx = SimpleNamespace(compose=Compose("/nonexistent"))
        for name in ("COMPOSE_PROFILES", "DOCKER_HOST"):
            with self.assertRaises(Refused) as cm:
                cx.config(ctx, "lite", "/srv/r/cache/src/x", ["compose.yaml"], {"A": "1", name: "x"})  # type: ignore[arg-type]
            self.assertEqual(cm.exception.code, "policy")
            self.assertIn(name, cm.exception.message)


class SourceTest(unittest.TestCase):
    def test_an_invalid_instance_name_is_a_usage_error(self) -> None:
        with self.assertRaises(CannotRun) as cm:  # exit 2 (LIFECYCLE §6), before any file is read
            cx.load(fake_ctx("/nonexistent"), "Not a name")
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("usage", 2))

    def test_validate_names_a_missing_directory_or_file_as_a_usage_error(self) -> None:
        ctx: Any = SimpleNamespace()  # refused before any Compose call
        with tempfile.TemporaryDirectory() as d:
            for args in ((f"{d}/nosuch",), (d, f"{d}/nosuch.toml")):
                with self.assertRaises(CannotRun) as cm:
                    validate(ctx, *args)
                self.assertEqual((cm.exception.code, cm.exception.exit_code), ("usage", 2))
            with self.assertRaises(Refused) as cm2:  # no manifest: not an app repository
                validate(ctx, d)
            self.assertEqual(cm2.exception.code, "invalid-app")

    def test_refusals_before_any_fetch(self) -> None:
        ctx = fake_ctx("/srv/r")
        inst = SimpleNamespace(source_kind="git", repo="file:///srv/r/cache/fixturesx/app", accept=None, key=None)
        ld = cx.Loaded("lite", inst, {}, None, None)  # type: ignore[arg-type]
        with mock.patch.object(cx.git, "fetch") as fetch:
            for repo, accept, code in (
                ("file:///srv/r/cache/fixturesx/app", None, "invalid-instance"),  # ADR-0027: under cache/fixtures/
                ("file:///srv/other/app", None, "invalid-instance"),
                ("ssh://git@example.invalid/app.git", "v[0-9]+", "ref-not-accepted"),
            ):
                inst.repo, inst.accept = repo, accept
                with self.assertRaises(Refused) as cm:
                    cx.source(ctx, ld, "main")
                self.assertEqual(cm.exception.code, code)
            inst.source_kind = "image"
            with self.assertRaises(Refused) as cm:
                cx.source(ctx, ld, "main")
            self.assertEqual(cm.exception.code, "not-in-this-release")
        fetch.assert_not_called()


class HostTest(unittest.TestCase):
    def test_release_files_keep_release_and_build_keys_only(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(f"{d}/etc.defaults")
            os.makedirs(f"{d}/etc")
            Path(f"{d}/etc/os-release").write_text('NAME="Debian"\nVERSION_ID="13"\nHOME_URL="x"\n# c\n')
            Path(f"{d}/etc.defaults/VERSION").write_text('majorversion="7"\nbuildnumber="72806"\nunique="a_model"\n')
            with mock.patch.object(brand, "HOST_FACTS_DIR", d):
                facts = cx.release_files()
        self.assertEqual(facts["etc/os-release"], {"NAME": "Debian", "VERSION_ID": "13"})
        self.assertEqual(facts["etc.defaults/VERSION"], {"majorversion": "7", "buildnumber": "72806"})

    def test_capacity_sums_needs_per_filesystem_with_a_floor(self) -> None:
        with tempfile.TemporaryDirectory() as d, mock.patch.object(brand, "PROBE_MOUNT", f"{d}/probe"):
            for x in ("r", "r-b", "probe"):
                os.makedirs(f"{d}/{x}")
            ctx = fake_ctx(f"{d}/r")
            free = {f"{d}/r": cx.GIB * 2, f"{d}/r-b": cx.GIB * 2, f"{d}/probe": cx.GIB * 9}
            devs = {f"{d}/r": 1, f"{d}/r-b": 1, f"{d}/probe": 2}
            with mock.patch.object(cx.fs, "statvfs", side_effect=lambda p: (devs[p], free[p])):  # both roots on one
                cx.capacity(ctx, {f"{d}/r": cx.GIB // 2, f"{d}/r-b": cx.GIB // 2})
                with self.assertRaises(Refused) as cm:
                    cx.capacity(ctx, {f"{d}/r": cx.GIB // 2, f"{d}/r-b": cx.GIB // 2 + 1})
                self.assertEqual(cm.exception.code, "capacity")
            with mock.patch.object(cx.fs, "statvfs", side_effect=lambda p: (len(p), free[p])):  # three filesystems
                cx.capacity(ctx, {f"{d}/r": cx.GIB, f"{d}/r-b": cx.GIB})

    def test_capacity_never_skips_a_path_it_cannot_measure(self) -> None:
        """A missing root or probe mount would leave its filesystem unchecked (LIFECYCLE §5.8): nothing runs."""
        with tempfile.TemporaryDirectory() as d, mock.patch.object(brand, "PROBE_MOUNT", f"{d}/probe"):
            ctx = fake_ctx(f"{d}/r")
            for x in ("r", "r-b", "probe"):
                with self.assertRaises(CannotRun) as cm:
                    cx.capacity(ctx, {})
                self.assertEqual((cm.exception.code, cm.exception.exit_code), ("cannot-measure", 2))
                self.assertIn(f"{d}/{x}", cm.exception.message)
                os.makedirs(f"{d}/{x}")
            cx.capacity(ctx, {})


class SchemaGateTest(unittest.TestCase):
    def test_order(self) -> None:
        self.assertTrue(deploy.older("2", "10"))
        self.assertFalse(deploy.older(10, 2))
        self.assertTrue(deploy.older("a1", "b0"))

    def test_an_older_release_on_newer_data_is_refused_with_its_restore(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ctx = fake_ctx(d)
            docs = [
                {"seq": 1, "commit": "a", "release": "a", "schema": {"expected": "1", "actual": "1"}},
                {"seq": 2, "commit": "b", "release": "b", "schema": {"expected": "2", "actual": "2"}},
            ]
            docs[1] |= {"rollback_target": 1, "pre_change_bundle": "B1"}
            for doc in docs:
                state.write_doc_once(ctx.layout.deployment_json("lite", doc["seq"]), new_doc("deployment", **doc))
            ld = cx.Loaded("lite", None, {}, docs[1], LITE)  # type: ignore[arg-type]
            with self.assertRaises(Refused) as cm:
                deploy._schema_gate(ctx, ld, "a")
            self.assertEqual(
                (cm.exception.code, cm.exception.next),
                ("schema-gate", f"{brand.CLI} restore lite --bundle B1 --reason <text>"),
            )
            deploy._schema_gate(ctx, ld, "b")  # the current release
            deploy._schema_gate(ctx, ld, "new")  # never deployed here: the app guards it
            ld = cx.Loaded("lite", None, {}, docs[1] | {"schema": {"expected": "1", "actual": "1"}}, LITE)  # type: ignore[arg-type]
            deploy._schema_gate(ctx, ld, "a")  # same schema: a code-only move


class ComposeFilesTest(unittest.TestCase):
    def test_runtime_and_build_files_are_read_as_text_before_compose(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            Path(d, "compose.yaml").write_text("include: [inc.yaml]\nservices: {}\n")
            Path(d, "compose.build.yaml").write_text("services:\n  app:\n    extends: {file: x.yaml, service: a}\n")
            m = dataclasses.replace(LITE, build_files=("compose.yaml", "compose.build.yaml", "gone.yaml"))
            found = cx.compose_files(d, m)
            self.assertEqual([e.split(":")[:2] for e in found], [["compose.yaml", "1"], ["compose.build.yaml", "3"]])
            Path(d, "compose.yaml").write_text("services: {}\n")
            self.assertEqual(len(cx.compose_files(d, LITE)), 0)


B1, H1 = "pre-1", "h" * 64
COMMIT = "d" * 40


class ForwardTest(unittest.TestCase):
    """The way forward from a frozen update (LIFECYCLE §3.6): only the candidate that froze the instance, past its
    forward point, after its pre-change bundle was sealed and verified."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ctx = fake_ctx(tmp.name)
        self.lay: Layout = self.ctx.layout
        catalog = {"bundle_id": B1, "bundle_hash": H1, "class": "pre-change", "size": 42}
        catalog["created_at"] = "2026-10-01T00:00:00Z"
        state.write_doc_once(self.lay.catalog("lite", B1), new_doc("catalog", **catalog))
        self.verified(True)
        self.update(3)

    def verified(self, ok: bool) -> None:
        line = new_doc("verification", bundle_id=B1, bundle_hash=H1, level="verified", ok=ok, op=3, at="t")
        fs.append_line(self.lay.verification("lite", B1), records.dumps(line))

    def update(self, seq: int, outcome: str = "failed-frozen", sealed: bool = True, **inputs: Any) -> None:
        """Deploy `seq` of COMMIT over deployment 1 that ended `outcome` at its activation."""

        def step(type_: str, klass: str, **args: Any) -> dict[str, Any]:
            return {"type": type_, "klass": klass, "args": args}

        steps = [step("Stop", "reversible", freeze=True), step("CaptureBundle", "scratch", phase="begin")]
        steps += [step("CaptureBundle", "scratch", phase="seal"), step("VerifyBundle", "scratch", bundle=None)]
        steps += [step("Record", "idempotent", kind="verification"), step("RunTask", "forward"), step("Up", "forward")]
        steps += [step("Record", "idempotent", kind="deployment", doc={"rollback_target": 1})]
        if inputs.get("forward"):  # a way forward holds no capture
            steps = [step("VerifyBundle", "scratch", bundle=B1), *steps[5:]]
        d = self.lay.op_dir("lite", seq, "deploy")
        variants = {"candidate": {"images": {"app": "sha256:2"}}}
        plan = new_plan("deploy", "lite", "C", ["deploy"], {}, {"commit": COMMIT, "variants": variants} | inputs, steps)
        state.write_doc_once(f"{d}/plan.json", plan.doc())
        state.write_doc_once(f"{d}/result.json", new_doc("result", outcome=outcome))
        evidence = {
            1: {"freeze_at": "F", "values": {"freeze_at": "F"}},
            2: {"bundle_id": B1, "values": {"bundle.id": B1, "bundle.stamp": "S"}},
            3: {"bundle_id": B1, "bundle_hash": H1},
            4: {"bundle_id": B1, "values": {"bundle.id": B1, "bundle.payload": "p"}, "input_dir": None},
        }
        journal = Journal(d, seq)
        for n in range(1, len(steps)):
            journal.intent(n, 1)
            if not sealed and n == 3:
                return
            journal.close_step(n, "failed" if n == len(steps) - 1 else "done", evidence.get(n, {}))

    def forward(self, commit: str = COMMIT, image: str = "sha256:2", m: Manifest = LITE) -> Any:
        record = {"state": "frozen", "last_op": {"seq": 3, "kind": "deploy", "outcome": "failed-frozen"}}
        ld = cx.Loaded("lite", SimpleNamespace(environment="test"), record, {"seq": 1}, LITE)  # type: ignore[arg-type]
        return deploy._forward(self.ctx, ld, cx.Source(commit, commit, "/x", m), {"images": {"app": image}})

    def refused(self, **kw: Any) -> None:
        with self.assertRaises(Refused) as cm:
            self.forward(**kw)
        self.assertEqual(cm.exception.code, "frozen")
        self.assertIn("restore", cm.exception.message)

    def test_the_candidate_that_froze_the_instance_moves_forward(self) -> None:
        found = self.forward()
        values = {"freeze_at": "F", "bundle.id": B1, "bundle.stamp": "S", "bundle.payload": "p"}
        self.assertEqual(found, {"bundle": B1, "hash": H1, "values": values, "size": 42})
        state.write_doc_once(f"{self.lay.op_dir('lite', 4, 'backup')}/result.json", new_doc("result"))
        self.assertEqual(self.forward(), found)  # a nightly backup since keeps the data and the way forward
        self.update(5, "failed-unchanged", forward=found)  # a way forward that changed nothing
        self.assertEqual(self.forward(), found)
        self.update(6, forward=found)  # ... or froze the instance again: the same bundle carries on
        self.assertEqual(self.forward(), found)

    def test_an_update_abandoned_past_its_forward_point_moves_forward(self) -> None:
        forward = f"{brand.CLI} deploy lite {COMMIT}"  # its next command, which status and backup name too
        self.update(4, "abandoned", next=dict.fromkeys(deploy.FROZEN, forward))
        self.assertEqual((self.forward()["bundle"], deploy.way_forward(self.lay, "lite")), (B1, forward))
        self.verified(False)  # a later verify found the bundle broken: no way forward in this release
        self.assertIsNone(deploy.way_forward(self.lay, "lite"))

    def test_any_other_frozen_instance_refuses_naming_restore(self) -> None:
        self.refused(commit="e" * 40)  # another release
        self.refused(image="sha256:3")  # the same commit prepared for other image references
        migrate = dataclasses.replace(LITE.tasks["migrate"], idempotent=False, observe="schema")
        self.refused(m=dataclasses.replace(LITE, tasks={**LITE.tasks, "migrate": migrate}))  # never repeated blind
        self.verified(False)  # a later verify found the bundle broken
        self.refused()
        self.verified(True)
        self.forward()
        tomb = new_doc("tombstone", bundle_id=B1, op=7, at="t")  # pruned: its catalog entry stays
        state.write_doc_once(self.lay.catalog("lite", f"{B1}.pruned"), tomb)
        self.refused()

    def test_retention_keeps_the_bundle_while_the_instance_is_frozen(self) -> None:
        """The only copy of the data before the update: its way forward and its restore (M2) need it, so retention
        keeps it past pin_pre_change_days while the instance is frozen (LIFECYCLE §5.6)."""
        newer = {
            "bundle_id": "b2",
            "bundle_hash": H1,
            "class": "manual",
            "size": 1,
            "created_at": "2026-10-02T00:00:00Z",
        }
        state.write_doc_once(self.lay.catalog("lite", "b2"), new_doc("catalog", **newer))
        line = new_doc("verification", bundle_id="b2", bundle_hash=H1, level="verified", ok=True, op=4, at="t")
        fs.append_line(self.lay.verification("lite", "b2"), records.dumps(line))
        ctx = SimpleNamespace(layout=self.lay, now=records.parse_iso("2026-10-03T00:00:00Z"))
        rules = SimpleNamespace(backups=Backups(keep_daily=0, keep_weekly=0, keep_monthly=0, pin_pre_change_days=0))
        for st, kept in (("running", {"b2"}), ("frozen", {"b2", B1})):
            ld = SimpleNamespace(name="lite", record={"state": st}, inst=rules)
            self.assertEqual(set(backup._retention(ctx, ld)[0]), kept)  # type: ignore[arg-type]

    def test_an_update_that_failed_unchanged_or_froze_before_its_seal_refuses(self) -> None:
        self.update(4, "failed-unchanged")
        self.refused()
        self.update(5, sealed=False)
        self.refused()


if __name__ == "__main__":
    unittest.main()
