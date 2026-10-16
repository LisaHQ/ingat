"""T1: the prepare and deploy planners for fx-lite against a real daemon (run with tests/harness or scratch dt.sh on
both engines): first install, nothing to do, config-only and data-changing updates, the refusals around them, and that
planning leaves `instances/` and the Docker inventory untouched and puts no secret into a plan.

The fixture repository is a file:// repository with two commits under the scratch root's cache/fixtures/ (ADR-0027).
The test stands in for the executor where a plan needs earlier state: it writes the candidate and deployment records
an executor would write and starts the installed app with Compose. A second image built FROM the tool image with
FXLITE_SCHEMA=2 makes the data-changing update, which one test runs through the executor in this process up to a
failure past its forward point and then moves forward. The wrapper mounts the probe volume where the Docker root's
free space is measured; here a directory under the scratch root stands in for it."""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from ingat import __version__, brand
from ingat.adapters import override
from ingat.adapters.compose import Project
from ingat.adapters.docker import EffectToken
from ingat.core import approval, executor
from ingat.core.plan import Plan
from ingat.model import records
from ingat.model.errors import Refused
from ingat.model.manifest import parse_manifest
from ingat.ops import context as cx
from ingat.ops import deploy, lifecycle, status
from ingat.ops.backup import plan_backup
from ingat.ops.validate import validate
from ingat.policy import compose_text, gate
from ingat.store import state
from tests.harness import host as harness
from tests.unit.test_compose_text import BENIGN, HOSTILE

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


def token() -> EffectToken:
    return EffectToken(0, 0)  # the test stands in for the executor, the only issuer of tokens in the package


def docker(*args: str, stdin: bytes | None = None) -> str:
    return subprocess.run(["docker", *args], input=stdin, check=True, capture_output=True).stdout.decode()


def tree(path: str, skip: str = "") -> dict[str, tuple[int, str]]:
    """Mode and content hash of every entry below `path`, but the top-level `skip` tree."""
    out = {}
    for top, dirs, files, _ in os.fwalk(path):
        dirs[:] = [d for d in dirs if top != path or d != skip]
        for name in dirs + files:
            p = os.path.join(top, name)
            st = os.lstat(p)
            digest = hashlib.sha256(Path(p).read_bytes()).hexdigest() if name in files else ""
            out[os.path.relpath(p, path)] = (st.st_mode, digest)
    return out


@unittest.skipUnless(os.path.exists("/var/run/docker.sock"), "needs a scratch Docker daemon")
class PlanningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fx2 = f"tpln{os.urandom(4).hex()}-fx2:2"
        docker("build", "-q", "-t", cls.fx2, "-", stdin=f"FROM {IMAGE}\nENV FXLITE_SCHEMA=2\n".encode())
        cls.addClassCleanup(docker, "rmi", cls.fx2)

    def setUp(self) -> None:
        u = os.urandom(4).hex()
        self.base, self.name = f"/srv/tpln{u}", f"tp{u}"
        self.addCleanup(shutil.rmtree, self.base, True)
        root, backups = f"{self.base}/root", f"{self.base}/backups"
        for d in (f"{root}/cache/docker-config", backups, f"{self.base}/facts/etc", f"{self.base}/probe"):
            os.makedirs(d)
        Path(f"{self.base}/facts/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        for patch in (
            mock.patch.object(brand, "HOST_FACTS_DIR", f"{self.base}/facts"),
            mock.patch.object(brand, "PROBE_MOUNT", f"{self.base}/probe"),
            mock.patch.object(gate, "load_tested", self.engines),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.environ = {brand.env("ROOT"): root, brand.env("BACKUPS"): backups, brand.env("HOST"): "testhost"}
        self.ctx = ctx = cx.make_ctx(self.environ)
        self.lay = lay = ctx.layout
        state.write_doc_once(lay.host_json, records.new_doc("host", engine_id=ctx.info["ID"], root=root))
        cert = {"kind": "selftest", "result": "PASS", "build": cx.build_facts(ctx)}
        state.write_doc_once(f"{lay.certifications_dir}/x-selftest.json", cert)
        self.repo = f"{lay.fixtures_dir}/fx-lite"
        os.makedirs(self.repo)
        subprocess.run([*GIT, "init", "-q", self.repo], env=GIT_ENV, check=True)
        shutil.copy(FIXTURE / "ingat.toml", self.repo)
        shutil.copy(FIXTURE / "compose.yaml", self.repo)
        self.a = self.commit("a")
        compose = Path(self.repo, "compose.yaml")
        compose.write_text(
            compose.read_text().replace("      DATA_DIR: /data\n", "      DATA_DIR: /data\n      NOTE: b\n")
        )
        self.b = self.commit("b")
        self.canaries = {k: "Canary" + os.urandom(12).hex() for k in ("MAIL_USER", "MAIL_PASSWORD")}
        for k, v in self.canaries.items():
            os.makedirs(f"{lay.secrets_dir(self.name)}/env", exist_ok=True)
            Path(f"{lay.secrets_dir(self.name)}/env/{k}").write_text(v)
        self.instance(IMAGE)
        record = {"name": self.name, "app": "fx-lite", "environment": "test", "lineage": u * 4, "disposable": False}
        record |= {"state": "registered", "current_deployment": None, "previous_deployment": None, "generations": {}}
        record |= {"held_since": None, "open_op": None, "next_seq": 1, "last_op": None}
        state.write_doc_once(lay.record_json(self.name), records.new_doc("instance", **record))
        os.makedirs(lay.placeholder(self.name))
        m = parse_manifest((FIXTURE / "ingat.toml").read_bytes(), tool_version=__version__)
        # the entries `init` writes, on random ports above the lowest free ones, which another runner's selftest takes
        for param in cx.allocate_ports(ctx, self.name, m, cx.load(ctx, self.name).inst):
            entry = records.new_doc("allocation", instance=self.name, purpose="live", param=param, op=None, at="x")
            state.write_doc_once(lay.allocation("port", str(harness.free_port())), entry)

    def engines(self) -> list[dict[str, str]]:
        server = self.ctx.version["Server"]
        return [{"engine": ".".join(server["Version"].split(".")[:2]), "arch": server["Arch"]}]

    def commit(self, message: str) -> str:
        for args in (["add", "-A"], ["commit", "-q", "-m", message]):
            subprocess.run([*GIT, "-C", self.repo, *args], env=GIT_ENV, check=True)
        out = subprocess.run([*GIT, "-C", self.repo, "rev-parse", "HEAD"], env=GIT_ENV, check=True, capture_output=True)
        return out.stdout.decode().strip()

    def instance(self, image: str, params: dict[str, str] | None = None, **app_env: str) -> None:
        lines = ["instance = 1", f'name = "{self.name}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
        lines += [f'repo = "file://{self.repo}"', "[params]", f'FXLITE_IMAGE = "{image}"']
        lines += [*(f'{k} = "{v}"' for k, v in (params or {}).items()), "[app_env]"]
        lines += [f'{k} = "{v}"' for k, v in (APP_ENV | app_env).items()]
        Path(self.lay.inst_toml(self.name)).write_text("\n".join(lines) + "\n")

    def candidate(self, commit: str, image: str, **over: object) -> None:
        """What a prepare's Obtain and Record steps write."""
        image_id = self.ctx.docker.image(image)["Id"]  # type: ignore[index]
        doc = {"commit": commit, "release": commit, "export": self.lay.cache_src(commit), "manifest_sha256": "-"}
        doc |= {"images": {"app": image_id}, "refs": {"app": image}, "digests": {"app": None}, "labels_checked": []}
        doc |= over
        path = self.lay.candidates(self.name, commit, doc["refs"])
        state.write_doc_once(path, records.new_doc("candidate", **doc))

    def install(self, plan: Plan, start: bool) -> None:
        """What the executor leaves after the first install `plan`: generation, env file, deployment 1, record."""
        lay, n, record = self.lay, self.name, plan.steps[-1].args
        cv, spec = plan.inputs["variants"]["candidate"], plan.inputs["app_env"]
        gen = lay.data_gen(n, "data", "g1")
        os.makedirs(gen, 0o700)
        os.chown(gen, 10001, 10001)
        values = {k: x["value"] if "value" in x else Path(x["secret_file"]).read_text() for k, x in spec["lines"]}
        os.makedirs(lay.env_dir(n))
        Path(spec["path"]).write_bytes(cx.env_text(values))
        schema = {"expected": "1", "actual": "1", "at": "2026-10-15T00:00:00Z"}
        doc = record["doc"] | {"schema": schema, "writes_reopened_at": schema["at"], "created_at": schema["at"]}
        state.write_doc_once(lay.deployment_json(n, 1), records.new_doc("deployment", **doc))
        snap = lay.deployment_snapshot(n, 1)
        os.makedirs(snap)
        Path(snap, brand.MANIFEST_FILE).write_bytes(Path(record["manifest_path"]).read_bytes())
        Path(snap, "override.yaml").write_text(cv["override"])
        Path(snap, "compose.env").write_bytes(cx.env_text(cv["env"]))
        rec = state.read_doc(lay.record_json(n), "instance")
        rec |= {"state": "running", "current_deployment": 1, "generations": {"data": 1}, "next_seq": 2}
        state.replace_doc(lay.record_json(n), rec)
        if start:
            p = Project(n, cv["directory"], tuple(cv["files"]), f"{snap}/override.yaml", f"{snap}/compose.env")
            self.addCleanup(self.ctx.compose.down, token(), p, timeout=120)
            self.assertEqual(self.ctx.compose.up(token(), p, ["app"], timeout=120).code, 0)
            labels = {brand.label("instance"): n}
            for i in range(40):  # running, and still running a moment later (no restart loop)
                time.sleep(0.5)
                if i > 4 and all(c["State"]["Running"] for c in self.ctx.docker.containers(labels)):
                    break
            else:
                self.fail("the installed app does not keep running")

    def ghost(self, service: str, *opts: str, **labels: str) -> str:
        """A container no plan made, by default a leftover of the instance's project; `opts` go to docker run."""
        name = f"{self.name}-ghost-{os.urandom(3).hex()}"
        labels = {brand.label("instance"): self.name, "com.docker.compose.project": self.name} | labels
        marks = [
            x for k, v in ({"com.docker.compose.service": service} | labels).items() for x in ("--label", f"{k}={v}")
        ]
        docker("run", "-d", "--name", name, *marks, *opts, "--entrypoint", "sleep", IMAGE, "600")
        self.addCleanup(subprocess.run, ["docker", "rm", "-f", name], capture_output=True)
        return name

    def plan(self, kind: str, ref: str) -> Plan | None:
        """Plan with a fresh context, checking that planning wrote nothing under instances/ and touched no Docker
        object of this instance or image it names (the daemon is shared: other tests tag their own images), and
        that the plan holds no secret."""
        ctx = self.ctx = cx.make_ctx(self.environ)
        before, since = tree(self.lay.root, "cache"), f"{time.time():.6f}"
        ours = (IMAGE, self.fx2, "example.invalid/")
        try:
            plan = (deploy.plan_prepare if kind == "prepare" else deploy.plan_deploy)(ctx, self.name, ref)
        finally:
            self.assertEqual(tree(self.lay.root, "cache"), before)
            self.assertEqual([n for n in os.listdir("/dev/shm") if n.startswith(f"{brand.CLI}-plan-")], [])
            events = ctx.docker.events(since, f"{time.time() + 0.5:.6f}")
            image = [
                e
                for e in events
                if e.get("Type") == "image" and e["Actor"]["Attributes"].get("name", "").startswith(ours)
            ]
            self.assertEqual([e for e in events if self.name in json.dumps(e)] + image, [])
        if plan is not None:
            text = json.dumps(plan.doc())
            self.assertFalse([k for k, v in self.canaries.items() if v in text])
            self.assertEqual(plan.hash, Plan.from_doc(json.loads(text)).hash)
        return plan

    def check_variants(self, plan: Plan) -> None:
        """Every variant's model renders again from the plan's own data, pins its images and passes the policy."""
        m = parse_manifest(
            Path(self.lay.cache_src(plan.inputs["commit"]), "ingat.toml").read_bytes(), tool_version=__version__
        )
        self.assertEqual(m.raw_sha256, plan.inputs["manifest_sha256"])  # the bytes a deployment snapshots (F4)
        for name, v in plan.inputs["variants"].items():
            model = cx.model(self.ctx, v)
            self.assertEqual({s: x["image"] for s, x in model["services"].items()}, v["images"], name)
            self.assertEqual(records.doc_hash(model), v["model_sha256"], name)
            spec = override.live(
                model["services"], instance=self.name, ns=brand.LABEL_NS, images=v["images"], stores={}, networks=()
            )
            self.assertEqual(cx.policy_errors(m, model, spec, v["env"], v["directory"], True), [], name)
            self.assertTrue(all(b.startswith(self.lay.root + "/") for b in v["binds"]), v["binds"])

    def types(self, plan: Plan) -> list[str]:
        return [s.type for s in plan.steps]

    def exe(self, plan: Plan) -> dict[str, object]:
        """`approve` (saved) then `_exec <i> <hash> <run-id>` in this process: the run file."""
        run_id, ctx = secrets.token_hex(8), cx.make_ctx(self.environ)
        executor.execute(self.lay, ctx.docker, ctx.compose, approval.save(self.lay, plan), run_id)
        return state.read_doc(self.lay.run(run_id), "run")

    def test_prepare_and_first_install(self) -> None:
        with self.assertRaises(Refused) as cm:
            self.plan("deploy", self.a)
        self.assertEqual(
            (cm.exception.code, cm.exception.next), ("no-candidate", f"{brand.CLI} prepare {self.name} {self.a}")
        )
        plan = self.plan("prepare", self.a)
        assert plan is not None
        self.assertEqual((plan.op_kind, plan.approval, self.types(plan)), ("prepare", "B", ["Obtain", "Record"]))
        self.assertEqual(plan.steps[0].args["images"], [{"ref": IMAGE, "services": ["app"], "check_labels": {}}])
        self.assertEqual((plan.steps[1].args["kind"], plan.steps[1].args["commit"]), ("candidate", self.a))
        self.assertTrue(os.path.isfile(f"{self.lay.cache_src(self.a)}/compose.yaml"))
        self.assertEqual(os.stat(self.lay.cache_src(self.a)).st_mode & 0o777, 0o555)  # the export is read-only
        self.candidate(self.a, IMAGE)
        self.assertIsNone(self.plan("prepare", self.a))  # prepared: nothing to do
        ghost = self.ghost("app", **{brand.label("instance"): "", "com.docker.compose.oneoff": "False"})
        network = f"{self.name}_other"  # Compose would recreate both (F8: a foreign object is never touched)
        docker("network", "create", "--label", f"com.docker.compose.project={self.name}", network)
        self.addCleanup(subprocess.run, ["docker", "network", "rm", network], capture_output=True)
        for remove in (["rm", "-f", ghost], ["network", "rm", network]):
            with self.assertRaises(Refused) as cm:
                self.plan("deploy", self.a)
            self.assertEqual(cm.exception.code, "foreign")
            docker(*remove)

        plan = self.plan("deploy", self.a)
        assert plan is not None
        self.assertEqual((plan.op_kind, plan.approval), ("deploy", "C"))
        self.assertEqual(self.types(plan), ["CreateGeneration", "RunTask", "Up", "Pause", "Up", "Record"])
        gen, migrate, up, pause, check, record = plan.steps
        self.assertEqual(
            (gen.args["path"], gen.args["owner"], gen.args["mode"]),
            (self.lay.data_gen(self.name, "data", "g1"), [10001, 10001], 0o700),
        )
        self.assertEqual(
            (migrate.args["task"], migrate.args["variant"], migrate.klass, migrate.forward_point),
            ("migrate", "candidate", "forward", True),
        )
        self.assertEqual(
            (up.args["services"], up.args["wait"], up.args["reopens_writes"], up.args["schema_probe"]),
            (["app"], ["ready", "edge-live"], True, "ready"),
        )
        self.assertIn(f"ingat task {self.name} bootstrap-config", pause.args["text"])
        self.assertEqual((check.args["identity"], check.args["smoke"], check.args["services"]), (True, True, []))
        doc = record.args["doc"]
        self.assertEqual(
            (doc["seq"], doc["origin"], doc["commit"], doc["rollback_target"]), (1, "install", self.a, None)
        )
        self.assertEqual(record.args["from"]["writes_reopened_at"], 3)
        spec = plan.inputs["app_env"]
        self.assertEqual([k for k, x in spec["lines"] if "secret_file" in x], ["MAIL_USER", "MAIL_PASSWORD"])
        self.assertEqual(
            sorted(plan.inputs["redact_files"]),
            sorted(x["secret_file"] for _, x in spec["lines"] if "secret_file" in x),
        )
        self.assertEqual(spec["path"], f"{self.lay.env_dir(self.name)}/{spec['sha256']}.env")
        self.check_variants(plan)
        cv = plan.inputs["variants"]["candidate"]
        self.assertEqual(cv["probes"]["edge-live"]["port"], int(cv["env"]["FXLITE_PORT"]))
        self.assertEqual(cv["values"]["op.seq"], "1")
        self.assertEqual(cv["secret_files"], sorted(plan.inputs["redact_files"]))  # the app env's (ARCH §9.4)
        self.assertEqual((plan.inputs["warnings"], plan.inputs["forward"]), ([], None))
        failed = f"{brand.CLI} deploy {self.name} {self.a}"  # a deploy that ends frozen names its way forward
        self.assertEqual(plan.inputs["next"], {"failed-frozen": failed, "abandoned": failed})

    def test_nothing_to_do_then_config_only(self) -> None:
        self.candidate(self.a, IMAGE)
        install = self.plan("deploy", self.a)
        assert install is not None
        self.install(install, start=True)
        self.assertIsNone(self.plan("deploy", self.a))  # running config hashes equal the planned ones
        ghost = self.ghost("app", **{"com.docker.compose.oneoff": "True", "com.docker.compose.config-hash": "x"})
        self.assertIsNone(self.plan("deploy", self.a))  # a running one-off task container is no service container
        docker("rm", "-f", ghost)
        ghost = self.ghost("app", **{"com.docker.compose.config-hash": "stale"})  # a second, stale container of app
        stale = self.plan("deploy", self.a)
        assert stale is not None
        self.assertEqual((self.types(stale), stale.steps[0].args["services"]), (["Up", "Up", "Record"], ["app"]))
        docker("rm", "-f", ghost)
        ghost = self.ghost("worker")  # a service the candidate does not have: the identity check would fail on it
        with self.assertRaises(Refused) as cm:
            self.plan("deploy", self.a)
        self.assertEqual(cm.exception.code, "removed-service")
        docker("rm", "-f", ghost)
        self.candidate(self.b, IMAGE)
        plan = self.plan("deploy", self.b)
        assert plan is not None
        self.assertEqual(self.types(plan), ["Up", "Up", "Record"])
        self.assertEqual((plan.steps[0].args["services"], plan.steps[0].klass), (["app"], "reversible"))
        self.assertFalse(any(s.forward_point for s in plan.steps))
        doc, sources = plan.steps[-1].args["doc"], plan.steps[-1].args["from"]
        self.assertEqual((doc["seq"], doc["origin"], doc["rollback_target"]), (2, "config", 1))
        self.assertEqual((plan.steps[0].args["schema_probe"], sources["schema"]), ("ready", 1))  # read again
        self.assertEqual((doc["writes_reopened_at"], sources["writes_reopened_at"]), ("2026-10-15T00:00:00Z", None))
        self.assertEqual(sorted(plan.inputs["variants"]), ["candidate", "current"])
        self.check_variants(plan)
        self.instance(IMAGE, DELIVERY_MODE="smtp")  # an owner-gated key: class D (M2)
        with self.assertRaises(Refused) as cm:
            self.plan("deploy", self.b)
        self.assertEqual(cm.exception.code, "not-in-this-release")

    def test_data_changing_update(self) -> None:
        self.candidate(self.a, IMAGE)
        install = self.plan("deploy", self.a)
        assert install is not None
        self.install(install, start=False)
        self.instance(self.fx2)
        self.candidate(self.b, self.fx2)
        plan = self.plan("deploy", self.b)
        assert plan is not None
        types = ["Stop", "CaptureBundle", "RunTask", "CaptureBundle", "VerifyBundle", "Record", "RunTask", "Up", "Up"]
        self.assertEqual(self.types(plan), [*types, "Record"])
        stop, begin, backup, seal, verify, verified, migrate, up = plan.steps[:8]
        self.assertEqual((stop.args["services"], stop.args["freeze"], stop.args["variant"]), (["app"], True, "current"))
        self.assertEqual(
            (begin.args["phase"], seal.args["phase"], seal.args["class"], seal.group),
            ("begin", "seal", "pre-change", "capture"),
        )
        self.assertEqual(
            (backup.args["task"], backup.args["variant"], backup.group, backup.args["task_uid"]),
            ("backup", "current", "capture", [10001, 10001]),
        )
        self.assertEqual((seal.args["deployment"]["seq"], seal.args["schema"]), (1, {"expected": "1", "actual": "1"}))
        self.assertEqual((verify.args, verified.args["bundle_from"]), ({"bundle": None, "input_owner": None}, 5))
        self.assertEqual(
            (migrate.args["task"], migrate.args["variant"], migrate.forward_point), ("migrate", "candidate", True)
        )
        self.assertEqual(migrate.args["capacity"], {self.lay.root: cx.GIB})
        self.assertEqual((up.klass, up.args["reopens_writes"]), ("forward", True))
        doc, sources = plan.steps[-1].args["doc"], plan.steps[-1].args["from"]
        self.assertEqual((doc["origin"], doc["rollback_target"], sources["pre_change_bundle"]), ("update", 1, 4))
        variants = plan.inputs["variants"]
        self.assertNotEqual(variants["current"]["images"], variants["candidate"]["images"])
        self.assertEqual(
            variants["current"]["override"],
            Path(self.lay.deployment_snapshot(self.name, 1), "override.yaml").read_text(),
        )
        self.check_variants(plan)

    def test_an_update_that_froze_moves_forward_on_its_own_bundle(self) -> None:
        """A data-changing update that fails past its forward point (here the owner cancels it while its activation
        waits for its probes) names `deploy <i> <ref>` next; that deploy plans only the way forward (LIFECYCLE §3.6) on
        the bundle the update sealed and verified, and completes."""
        self.candidate(self.a, IMAGE)
        install = self.plan("deploy", self.a)
        assert install is not None
        self.install(install, start=True)
        self.instance(self.fx2)
        self.candidate(self.b, self.fx2)
        update, seq = self.plan("deploy", self.b), state.next_seq(self.lay, self.name)
        assert update is not None
        argv = [sys.executable, "-m", "tests.docker.helpers", self.lay.root, self.lay.backups, self.lay.docker_config]
        run_id = secrets.token_hex(8)
        proc = subprocess.Popen([*argv, approval.save(self.lay, update), run_id, "new"])  # the executor, as launched
        journal, up = Path(self.lay.op_dir(self.name, seq, "deploy"), "steps.jsonl"), [s.n for s in update.steps][-3]
        for _ in range(240):  # until the activation (after the migrate, the forward point) has started
            lines = journal.read_bytes().splitlines() if journal.exists() else []
            if any((r["step"], r["phase"]) == (up, "intent") for r in map(records.loads, lines)):
                break
            time.sleep(0.5)
        lifecycle.cancel(cx.make_ctx(self.environ), self.name)
        self.assertEqual(proc.wait(300), 3)
        run = state.read_doc(self.lay.run(run_id), "run")
        result = state.read_doc(f"{self.lay.op_dir(self.name, seq, 'deploy')}/result.json", "result")
        forward = f"{brand.CLI} deploy {self.name} {self.b}"
        self.assertEqual(
            (run["code"], result["outcome"], result["next"], run["next"]),
            ("cancelled", "failed-frozen", forward, forward),
        )
        rec = state.read_doc(self.lay.record_json(self.name), "instance")
        self.assertEqual((rec["state"], rec["current_deployment"]), ("frozen", 1))
        ctx = cx.make_ctx(self.environ)
        self.assertEqual(status.status(ctx, self.name)["next"], forward)  # the exact way forward (LIFECYCLE §3.2)
        for klass in ("manual", "scheduled"):  # its data may be past the forward point: no backup until it moves on
            with self.assertRaises(Refused) as cm:
                plan_backup(ctx, self.name, klass, None, False, scheduled=klass == "scheduled")
            self.assertEqual((cm.exception.code, cm.exception.next), ("frozen", forward))
        [bid] = [f[:-5] for f in os.listdir(self.lay.catalog_dir(self.name))]
        self.candidate(self.a, self.fx2)
        with self.assertRaises(Refused) as cm:  # another release cannot move it forward
            self.plan("deploy", self.a)
        self.assertEqual(cm.exception.code, "frozen")
        plan = self.plan("deploy", self.b)
        assert plan is not None
        self.assertEqual(self.types(plan), ["VerifyBundle", "RunTask", "Up", "Up", "Record"])
        verify, migrate, activate, _, record = plan.steps
        self.assertEqual(verify.args, {"bundle": bid, "input_owner": None})
        self.assertEqual((migrate.args["task"], migrate.forward_point, activate.klass), ("migrate", True, "forward"))
        doc = record.args["doc"]
        self.assertEqual(
            (doc["seq"], doc["origin"], doc["pre_change_bundle"], doc["rollback_target"]), (2, "update", bid, 1)
        )
        self.assertEqual(sorted(plan.inputs["variants"]), ["candidate"])
        self.assertEqual(plan.inputs["forward"]["bundle"], bid)
        self.assertIn("freeze_at", plan.inputs["variants"]["candidate"]["values"])
        run = self.exe(plan)
        self.assertEqual((run["exit"], run["code"]), (0, "completed"), run)
        rec = state.read_doc(self.lay.record_json(self.name), "instance")
        self.assertEqual((rec["state"], rec["current_deployment"], rec["previous_deployment"]), ("running", 2, 1))
        dep = state.read_doc(self.lay.deployment_json(self.name, 2), "deployment")
        self.assertEqual((dep["pre_change_bundle"], dep["rollback_target"], dep["schema"]["actual"]), (bid, 1, 2))

    def test_a_new_image_reference_makes_a_new_candidate(self) -> None:
        """Candidates are keyed by commit and the image references they were prepared for: an instance param that
        names another image leads to a fresh prepare, never a stale candidate."""
        self.candidate(self.a, IMAGE)
        self.assertIsNone(self.plan("prepare", self.a))
        self.instance(self.fx2)
        with self.assertRaises(Refused) as cm:
            self.plan("deploy", self.a)
        self.assertEqual(
            (cm.exception.code, cm.exception.next), ("no-candidate", f"{brand.CLI} prepare {self.name} {self.a}")
        )
        plan = self.plan("prepare", self.a)
        assert plan is not None
        self.assertEqual(self.types(plan), ["Obtain", "Record"])
        self.assertEqual(plan.steps[0].args["images"], [{"ref": self.fx2, "services": ["app"], "check_labels": {}}])
        self.candidate(self.a, self.fx2)
        self.assertIsNone(self.plan("prepare", self.a))
        self.instance(IMAGE)
        self.assertIsNone(self.plan("prepare", self.a))  # the first candidate still serves its references

    def test_include_and_extends_files_are_refused_before_compose_reads_them(self) -> None:
        """Compose reads include files (fetching remote ones during `config`) and extends files before the policy
        sees the merged model (ARCHITECTURE §9.5): every hostile form below is one Compose v5 reads, and each is
        refused; prepare and validate refuse a commit that uses one."""
        forms = f"{self.base}/forms"
        os.makedirs(forms)
        Path(forms, "inc.yaml").write_text("services:\n  inc:\n    image: busybox\n")
        Path(forms, "other.yaml").write_text("services:\n  base:\n    image: busybox\n    privileged: true\n")
        for what, text in {**HOSTILE, **BENIGN}.items():
            with self.subTest(what):
                Path(forms, "compose.yaml").write_bytes(text.encode())
                out = subprocess.run(
                    ["docker", "compose", "-p", "x", "-f", "compose.yaml", "config", "--format", "json"],
                    cwd=forms, capture_output=True, check=True,
                )  # fmt: skip
                services = json.loads(out.stdout)["services"]
                read = "inc" in services or services["app"].get("privileged") is True
                self.assertEqual(
                    (read, bool(compose_text.errors("compose.yaml", text.encode()))), (what in HOSTILE,) * 2
                )
        Path(self.repo, "inc.yaml").write_text("services:\n  inc:\n    image: busybox\n")
        compose = Path(self.repo, "compose.yaml")
        compose.write_text("include: [inc.yaml]\n" + compose.read_text())
        with self.assertRaises(Refused) as cm:
            self.plan("prepare", self.commit("include"))
        self.assertEqual(cm.exception.code, "unsupported-source")
        self.assertIn("compose.yaml:1: ", cm.exception.message)
        with self.assertRaises(Refused) as cm:
            validate(self.ctx, self.repo)
        self.assertEqual(cm.exception.code, "invalid-app")
        self.assertTrue([e for e in cm.exception.message.splitlines() if e.startswith("compose.yaml:1: ")])

    def test_unsound_commits_are_refused_at_prepare(self) -> None:
        """A build service that names no Compose service would skip its expect_labels check (OD-11 (b)); export-subst
        (or export-ignore) would make a deployment snapshot other manifest bytes than the plan's (F4)."""
        manifest = Path(self.repo, "ingat.toml")
        text = manifest.read_text()
        labels = 'build_services = ["App"]\nexpect_labels = { "org.opencontainers.image.revision" = "{commit}" }\n'
        manifest.write_text(text.replace('files = ["compose.yaml"]\n', f'files = ["compose.yaml"]\n{labels}'))
        with self.assertRaises(Refused) as cm:
            self.plan("prepare", self.commit("c"))
        self.assertEqual(cm.exception.code, "invalid-manifest")
        Path(self.repo, ".gitattributes").write_text("ingat.toml export-subst\n")
        manifest.write_text(text + "# $Format:%B$\n")
        with self.assertRaises(Refused) as cm:
            self.plan("prepare", self.commit("d\n\ninjected = 1"))
        self.assertEqual(cm.exception.code, "unsupported-source")

    def test_prepare_again_and_port_conflicts(self) -> None:
        lost = "sha256:" + "f" * 64  # the candidate's image is gone (for example pruned by the owner)
        self.candidate(self.a, IMAGE, images={"app": lost})
        with self.assertRaises(Refused) as cm:
            self.plan("deploy", self.a)
        self.assertEqual(cm.exception.code, "no-candidate")
        with self.assertRaises(Refused) as cm:
            self.plan("prepare", self.a)  # no digest: the recorded image cannot be pulled again
        self.assertEqual(cm.exception.code, "stale-candidate")
        digest = f"example.invalid/fx@sha256:{'e' * 64}"
        self.candidate(self.b, IMAGE, images={"app": lost}, digests={"app": digest})
        plan = self.plan("prepare", self.b)  # pull the recorded digest again; the write-once candidate stays
        assert plan is not None
        self.assertEqual(self.types(plan), ["Obtain"])
        self.assertEqual(plan.steps[0].args["images"], [{"ref": digest, "services": ["app"], "check_labels": {}}])
        port = str(29000 + int.from_bytes(os.urandom(2)) % 900)
        self.ghost(
            "web", "-p", f"127.0.0.1:{port}:3000", **{brand.label("instance"): "x", "com.docker.compose.project": "x"}
        )
        self.instance(IMAGE, {"FXLITE_PORT": port})  # set after init: no allocation entry protects it
        with self.assertRaises(Refused) as cm:
            self.plan("deploy", self.a)
        self.assertEqual(cm.exception.code, "port-conflict")

    def test_validate(self) -> None:
        validate(self.ctx, str(FIXTURE), self.lay.inst_toml(self.name))
        validate(self.ctx, str(FIXTURE.parent / "fx-web"))
        bad = f"{self.base}/bad"
        shutil.copytree(FIXTURE, bad)
        compose = Path(bad, "compose.yaml")
        text = compose.read_text().replace("RELEASE: ${FXLITE_RELEASE:?}", "RELEASE: ${UNDECLARED}")
        hostile = "    read_only: true\n    privileged: true\n    use_api_socket: true\n    network_mode: bridge\n"
        compose.write_text(text.replace("    read_only: true\n", hostile))
        manifest = Path(bad, "ingat.toml")
        labels = 'build_services = ["gone"]\nexpect_labels = { "org.opencontainers.image.revision" = "{commit}" }\n'
        manifest.write_text(
            manifest.read_text().replace('files = ["compose.yaml"]\n', f'files = ["compose.yaml"]\n{labels}')
        )
        with self.assertRaises(Refused) as cm:
            validate(self.ctx, bad)
        self.assertEqual(cm.exception.code, "invalid-app")
        errors = cm.exception.message.splitlines()[1:]
        self.assertIn("compose: variable UNDECLARED has no default and is not a declared param", errors)
        self.assertIn("params.FXLITE_RELEASE: not used by the Compose files", errors)
        self.assertIn("sample: services.app.privileged: refused", errors)
        self.assertIn("sample--t1: services.app.privileged: refused", errors)
        self.assertIn("sample: services.app.use_api_socket: refused", errors)  # Compose would bind the Docker socket
        self.assertIn("compose.build_services: unknown gone", errors)
        bridge = [e.split(":")[0] for e in errors if "services.app.network_mode" in e]
        self.assertEqual(bridge, ["sample--t1"])  # allowed live, refused in an isolated run (F13)


if __name__ == "__main__":
    unittest.main()
