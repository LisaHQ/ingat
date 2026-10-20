"""Shared harness for real-Docker core tests: a scratch tool root under /srv, an fx-lite instance, and hand-built
plans the way a planner renders them (variants, probes, task args). The fixture image is the tool image itself.

Run as a module it is a stand-in executor process for crash tests:
    python3 -m tests.docker.helpers <root> <backups> <docker-config> <plan-hash> <run-id> new|resume|abandon
"""

import hashlib
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.adapters import override
from ingat.adapters.compose import Compose, Project
from ingat.adapters.docker import Docker
from ingat.core import approval, executor
from ingat.core.plan import fingerprint, new_plan
from ingat.model import records
from ingat.store import state
from tests.harness import host as harness

IMAGE = os.environ.get("INGAT_TEST_IMAGE", "ingat:dev")
SRV = "/srv"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "fx-lite"
COMMIT = "c0ffee" + "0" * 34
RELEASE = "r1"
UID = [10001, 10001]
HOLDS = {"app": {"DELIVERY_MODE": "capture", "JOBS": "off"}}
EXIT3 = {"0": "ok", "1": "failed", "2": "refused"}


def eventually(fn: Callable[[], Any], wait: float = 60.0) -> Any:
    end = time.monotonic() + wait
    while not (value := fn()) and time.monotonic() < end:
        time.sleep(0.5)
    return value


def probe(name: str, kind: str, expect_json: dict[str, list[Any]], **kw: Any) -> dict[str, Any]:
    expect = {"status": None, "json": expect_json, "body_contains": None, "header_equals": {}, "header_contains": {}}
    p = {"name": name, "kind": kind, "service": None, "argv": [], "port": None, "path": None, "method": "GET"}
    p |= {"headers": {}, "body": None, "expect": expect | {"exit": None}, "stable": 0, "interval": 1, "timeout": 120}
    return p | kw


def task(name: str, variant: str, argv: list[str], *, effect: str, exit: dict[str, str], **kw: Any) -> dict[str, Any]:
    args = {"task": name, "variant": variant, "service": "app", "argv": argv, "env": {}, "user": None, "stdout": None}
    args |= {"stdin": None, "mounts": [], "effect": effect, "idempotent": True, "observe": None, "exit": exit}
    args |= {"expect": None, "timeout": 600, "require_ok": True, "findings_ok": False, "report": False}
    args |= {"capacity": None, "store_params": {}, "gen_paths": {}, "task_uid": UID, "inputs": {}, "args": {}}
    return args | {"max_input_bytes": None} | kw


def step(type_: str, klass: str, **kw: Any) -> dict[str, Any]:
    return {"type": type_, "klass": klass, **kw}


class Lab:
    """One instance `name` of fx-lite in a fresh root; `close()` removes everything it made."""

    def __init__(self, tag: str) -> None:
        self.name = tag + secrets.token_hex(3)
        self.base = f"{SRV}/{self.name}"
        os.makedirs(self.base)
        self.layout = state.Layout(f"{self.base}/root", f"{self.base}/backups")
        self.cfg = f"{self.base}/cfg"
        os.makedirs(self.cfg)
        self.docker = Docker(config_dir=self.cfg)
        self.compose = Compose(self.cfg)
        image = self.docker.image(IMAGE)
        assert image is not None
        self.image: str = image["Id"]
        self.port = harness.free_port()  # above the lowest free ports, which a selftest allocates
        self.secret = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
        self.export = self.layout.cache_src(COMMIT)
        shutil.copytree(FIXTURE, self.export)
        self.manifest = f"{self.export}/{brand.MANIFEST_FILE}"
        L, n = self.layout, self.name
        self.info = self.docker.info()
        host = records.new_doc("host", engine_id=self.info["ID"], root=L.root, backups=L.backups)
        state.write_doc_once(L.host_json, host | {"pools": {"isolation": harness.own_pool()}})  # one per runner
        os.makedirs(L.placeholder(n), 0o555)
        os.makedirs(L.inbox, 0o700)
        os.makedirs(f"{L.secrets_dir(n)}/env", 0o700)
        self.secret_file = f"{L.secrets_dir(n)}/env/MAIL_PASSWORD"
        Path(self.secret_file).write_text(self.secret)
        rec = records.new_doc(
            "instance", name=n, app="fx-lite", environment="test", lineage=secrets.token_hex(16), disposable=True,
            state="registered", current_deployment=None, previous_deployment=None, generations={}, held_since=None,
            open_op=None, next_seq=1, created_at=records.iso(records.utc_now()), last_op=None,
        )  # fmt: skip
        state.write_doc_once(L.record_json(n), rec)
        self.lineage = rec["lineage"]
        plain = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "a@b.invalid"}
        plain["PROXY_ADDRESS"] = "127.0.0.1"
        self.isolated_env = "".join(f"{k}='{v}'\n" for k, v in plain.items())
        text = self.isolated_env + f"MAIL_PASSWORD='{self.secret}'\n"
        sha = hashlib.sha256(text.encode()).hexdigest()
        lines: list[list[Any]] = [[k, {"value": v}] for k, v in plain.items()]
        lines.append(["MAIL_PASSWORD", {"secret_file": self.secret_file}])
        self.app_env = {"path": f"{L.env_dir(n)}/{sha}.env", "sha256": sha, "lines": lines}
        self.g1 = L.data_gen(n, "data", "g1")
        tmp = f"{self.base}/model.env"
        Path(tmp).write_text("".join(f"{k}='{v}'\n" for k, v in self.env(self.g1, self.app_env["path"]).items()))
        self.model = self.compose.config(Project(n, self.export, ("compose.yaml",), None, tmp))

    def env(self, data: str, env_file: str) -> dict[str, str]:
        return {
            "FXLITE_IMAGE": self.image, "FXLITE_RELEASE": RELEASE, "FXLITE_ENV_FILE": env_file,
            "FXLITE_DATA_DIR": data, "FXLITE_PORT": str(self.port),
        }  # fmt: skip

    def seq(self) -> int:
        return state.next_seq(self.layout, self.name)

    def op_dir(self, seq: int, kind: str) -> str:
        return self.layout.op_dir(self.name, seq, kind)

    def variant(self, *, isolated: bool = False, seq: int = 0, data: str = "", env_file: str = "") -> dict[str, Any]:
        project = f"{self.name}--t{seq}" if isolated else self.name
        kw = {"instance": self.name, "ns": brand.LABEL_NS, "images": {"app": self.image}, "stores": {}}
        kw["networks"] = list(self.model.get("networks", {}))
        spec = override.isolated(self.model["services"], op=seq, holds=HOLDS, **kw) if isolated else None
        spec = spec or override.live(self.model["services"], **kw)
        env = self.env(data or self.g1, env_file or str(self.app_env["path"]))
        if isolated:
            env["FX_SUBNET"] = "@subnet"
        ready = probe("ready", "exec", {"status": ["ready"], "data_writable": [True]}, service="app", stable=2)
        ready["argv"] = ["fx-lite", "probe", "http://127.0.0.1:3000/api/ready"]
        live = probe("edge-live", "http", {"status": ["ok"]}, port=self.port, path="/api/health")
        smoke = probe("live", "http", {"status": ["ok"]}, port=self.port, path="/api/health")
        values = {"instance": self.name, "environment": "test", "host": "h", "release": RELEASE, "commit": COMMIT}
        return {
            "project": project, "directory": self.export, "files": ["compose.yaml"], "override": override.render(spec),
            "env": env, "profiles": [], "images": {"app": self.image}, "values": values | {"op.seq": str(seq)},
            "probes": {"ready": ready, "edge-live": live}, "smoke": [smoke], "isolated": isolated,
            "binds": [data or self.g1],
        }  # fmt: skip

    def save(
        self,
        kind: str,
        steps: list[dict[str, Any]],
        variants: dict[str, Any],
        bundles: tuple[str, ...] = (),
        **extra: Any,
    ) -> str:
        seq = self.seq()
        inputs = {"seq": seq, "op_dir": self.op_dir(seq, kind), "variants": variants, "app_env": self.app_env}
        inputs |= {"writers": ["app"], "redact_files": [self.secret_file], **extra}
        fp = fingerprint(self.layout, self.docker, self.name, bundles)
        plan = new_plan(kind, self.name, "B", [brand.CLI, kind, self.name], fp, inputs, steps)
        return approval.save(self.layout, plan)

    def run(self, plan_hash: str, mode: str = "new") -> tuple[int, dict[str, Any]]:
        run_id = secrets.token_hex(8)
        code = executor.execute(
            self.layout, self.docker, self.compose, plan_hash, run_id, resume=mode == "resume",
            abandon=mode == "abandon",
        )  # fmt: skip
        return code, state.read_doc(self.layout.run(run_id), "run")

    def crash(self, plan_hash: str, at: str, mode: str = "new") -> int:
        """Run the executor in a child process that SIGKILLs itself at `at` (the journal's test hook)."""
        argv = [sys.executable, "-m", "tests.docker.helpers", self.layout.root, self.layout.backups, self.cfg]
        env = {**os.environ, brand.env("CRASH_AT"): at}
        return subprocess.run([*argv, plan_hash, secrets.token_hex(8), mode], env=env, check=False).returncode

    def spawn(self, plan_hash: str) -> tuple["subprocess.Popen[bytes]", str]:
        """The executor in a child process, as the CLI starts it (signals reach only that process)."""
        run_id = secrets.token_hex(8)
        argv = [sys.executable, "-m", "tests.docker.helpers", self.layout.root, self.layout.backups, self.cfg]
        return subprocess.Popen([*argv, plan_hash, run_id, "new"]), run_id

    def resume_plan(self, kind: str = "resume") -> str:
        fp = fingerprint(self.layout, self.docker, self.name)
        plan = new_plan(kind, self.name, "C", [brand.CLI, kind, self.name], fp, {}, [])
        return approval.save(self.layout, plan)

    def open_op(self) -> dict[str, Any] | None:
        op: dict[str, Any] | None = state.read_doc(self.layout.record_json(self.name), "instance")["open_op"]
        return op

    def result(self, seq: int, kind: str) -> dict[str, Any]:
        return state.read_doc(f"{self.op_dir(seq, kind)}/result.json", "result")

    def journal(self, seq: int, kind: str) -> list[dict[str, Any]]:
        lines = Path(f"{self.op_dir(seq, kind)}/steps.jsonl").read_bytes().splitlines()
        return [json.loads(line) for line in lines if line]

    def labelled(self, **labels: str) -> list[str]:
        """Names of containers and networks carrying all these labels (plus this instance's)."""
        want = {brand.label("instance"): self.name, **{brand.label(k): v for k, v in labels.items()}}
        found = [c["Name"].lstrip("/") for c in self.docker.containers(want)]
        return found + [n["Name"] for n in self.docker.networks(want)]

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {"PATH": os.environ["PATH"], "HOME": "/root", "DOCKER_CONFIG": self.cfg}
        return subprocess.run(["docker", *args], env=env, capture_output=True, text=True, check=False)

    def close(self) -> None:
        mine = f"label={brand.label('instance')}={self.name}"
        ids = self.cli("ps", "-aq", "--filter", mine).stdout.split()
        if ids:
            self.cli("rm", "-f", *ids)
        nets = self.cli("network", "ls", "-q", "--filter", mine).stdout.split()
        if nets:
            self.cli("network", "rm", *nets)
        shutil.rmtree(self.base, ignore_errors=True)

    # plans ------------------------------------------------------------------------------------------------
    def install_steps(self) -> list[dict[str, Any]]:
        obtain = {"images": [{"ref": self.image, "services": ["app"], "check_labels": {}}], "commit": COMMIT}
        candidate = {"kind": "candidate", "commit": COMMIT, "release": RELEASE, "export": self.export}
        candidate |= {"manifest_sha256": self.manifest_sha(), "obtain_step": 1}
        gen = {"store": "data", "gen": "g1", "path": self.g1, "owner": UID, "mode": 0o700, "purpose": "live"}
        migrate = task("migrate", "candidate", ["fx-lite", "migrate"], effect="data", exit={"0": "ok"})
        start = {"variant": "candidate", "services": ["app"], "wait": ["ready", "edge-live"], "reopens_writes": True}
        start |= {"schema_probe": "ready", "schema_paths": ["schema.expected", "schema.actual"]}
        doc = {"seq": 1, "instance": self.name, "origin": "install", "release": RELEASE, "commit": COMMIT}
        doc |= {"export": self.export, "images": {"app": self.image}, "generations": {"data": 1}}
        deployment = {"kind": "deployment", "doc": doc, "state": "running", "variant": "candidate"}
        deployment |= {"manifest_path": self.manifest, "from": {"writes_reopened_at": 5, "schema": 5}}
        return [
            step("Obtain", "scratch", interruptible=True, args=obtain),
            step("Record", "idempotent", args=candidate),
            step("CreateGeneration", "scratch", args=gen),
            step("RunTask", "forward", forward_point=True, args=migrate),
            step("Up", "reversible", args=start),
            step("Up", "scratch", args={"variant": "candidate", "services": [], "identity": True, "smoke": True}),
            step("Record", "idempotent", args=deployment | {"generations": {"data": 1}}),
        ]

    def manifest_sha(self) -> str:
        return hashlib.sha256(Path(self.manifest).read_bytes()).hexdigest()

    def backup_steps(self, argv: list[str] | None = None) -> list[dict[str, Any]]:
        dep = {"seq": 1, "release": RELEASE, "commit": COMMIT, "images": {"app": self.image}}
        dep |= {"manifest_sha256": self.manifest_sha(), "model_sha256": "0" * 64}
        tool = {"version": "0.1.0", "engine": self.info["ServerVersion"], "api": "1.43", "cli": "x", "compose": "x"}
        cap = {"class": "manual", "naming": "{bundle.stamp}-{class}", "payload": None, "stage_owner": UID}
        cap |= {
            "variant": "current",
            "schema": {"expected": 1, "actual": 1},
            "deployment": dep,
            "lineage": self.lineage,
        }
        cap |= {"meta_files": {brand.MANIFEST_FILE: self.manifest, "compose.yaml": f"{self.export}/compose.yaml"}}
        cap |= {
            "app": "fx-lite",
            "environment": "test",
            "stores": {"data": 1},
            "host": "h",
            "consistency": "online-app",
        }
        cap |= {"tool": tool | {"arch": "amd64", "os": "linux"}}
        argv = argv or ["fx-lite", "backup", "--to", "/out"]
        backup = task("backup", "current", argv, effect="app-write", exit=EXIT3)
        backup |= {"mounts": [["/out", "stage"]], "user": "10001:10001", "stdout": "json"}
        verification = {"kind": "verification", "level": "verified", "bundle_from": 4, "steps_ok": [4]}
        return [
            step("CaptureBundle", "scratch", group="capture", args=cap | {"phase": "begin"}),
            step("RunTask", "scratch", group="capture", interruptible=True, args=backup),
            step("CaptureBundle", "scratch", group="capture", args=cap | {"phase": "seal"}),
            step("VerifyBundle", "scratch", args={"bundle": None, "input_owner": None}),
            step("Record", "idempotent", args=verification),
        ]

    def backup_plan(self, argv: list[str] | None = None) -> str:
        self.fresh_second()
        return self.save("backup", self.backup_steps(argv), {"current": self.variant()})

    def fresh_second(self) -> None:
        """A bundle id carries the UTC second its backup begins and is never reused (a second backup in that second is
        refused with bundle-exists). Two backups of one lab fit in a second on a fast runner, so wait for a second that
        no catalogued, sealed or half-made bundle of this lab carries."""
        dirs = [self.layout.catalog_dir(self.name), os.path.dirname(self.layout.bundle_dir(self.name, "x"))]
        while True:
            stamp = records.stamp(records.utc_now())
            if not any(stamp in n for d in dirs if os.path.isdir(d) for n in os.listdir(d)):
                return
            time.sleep(0.1)

    def drill_plan(
        self, bundle_id: str, restore: list[str] | None = None, check: list[str] | None = None
    ) -> tuple[int, str]:
        """With `check`, the isolated app comes up inside the restore group (as the data services of `restore.start`
        do) and that check task runs after the group (as `restore.checks` do): a crash in either leaves containers that
        mount the drill generation."""
        seq = self.seq()
        t, d = self.layout.data_gen(self.name, "data", f"t{seq}"), self.op_dir(seq, "drill")
        variant = self.variant(isolated=True, seq=seq, data=t, env_file=f"{d}/env/isolated.env")
        gen = {"store": "data", "gen": f"t{seq}", "path": t, "owner": UID, "mode": 0o700, "purpose": "drill"}
        argv = restore or ["fx-lite", "restore", "--from", "/in/{bundle.payload}", "--to", "/restore"]
        restore = task("restore", "drill", argv, effect="data", exit=EXIT3, idempotent=False, user="10001:10001")
        restore |= {"mounts": [["/in", "bundle"], ["/restore", "generation:data"]], "gen_paths": {"data": t}}
        restore |= {"store_params": {"data": "FXLITE_DATA_DIR"}}
        start = {"variant": "drill", "services": ["app"], "wait": ["ready", "edge-live"], "identity": True}
        steps = [
            step("VerifyBundle", "scratch", args={"bundle": bundle_id, "input_owner": UID}),
            step("CreateGeneration", "scratch", group="restore", args=gen),
            step("RunTask", "scratch", group="restore", args=restore),
            step("Up", "scratch", interruptible=True, args=start, **({"group": "restore"} if check else {})),
        ]
        if check:
            probe_task = task("check", "drill", check, effect="read", exit={"0": "ok"})
            steps.append(step("RunTask", "scratch", args=probe_task))
        verification = {"kind": "verification", "level": "restore-tested", "bundle_from": 1}
        steps.append(step("Record", "idempotent", args=verification | {"steps_ok": list(range(3, len(steps) + 1))}))
        steps.append(step("Teardown", "scratch", always=True, args={"variant": "drill"}))
        files = {f"{d}/env/isolated.env": self.isolated_env}
        return seq, self.save("drill", steps, {"drill": variant}, (bundle_id,), files=files)


def secret_files(lab: Lab, values: list[str]) -> list[str]:
    """Files under the lab that hold a secret value, except where secrets belong: the secret files, the app env
    file, the owner's inbox and private input copies of inbox files."""
    allowed = (lab.layout.secrets_dir(lab.name), lab.layout.env_dir(lab.name), lab.layout.inbox)
    found = []
    for d, _, files in os.walk(lab.base):
        for f in files:
            path = os.path.join(d, f)
            if not path.startswith(allowed) and "/in/input-" not in path and not os.path.islink(path):
                try:
                    data = Path(path).read_bytes()
                except FileNotFoundError:  # a running app's own temporary file (SQLite -shm, -wal) went meanwhile
                    continue
                found += [path for v in values if v.encode() in data]
    return found


def allocations(lab: Lab) -> list[str]:
    d = lab.layout.allocations_dir
    return os.listdir(d) if os.path.exists(d) else []


def tree_hash(root: str) -> str:
    """Every path, mode and content under `root`, except the lock files any lock-taking command rewrites."""
    h = hashlib.sha256()
    for d, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for name in sorted(files + dirs):
            path = os.path.join(d, name)
            if name in ("lock", "lock.holder.json"):
                continue
            st = os.lstat(path)
            h.update(f"{os.path.relpath(path, root)} {st.st_mode} {st.st_size}\n".encode())
            if os.path.isfile(path):
                h.update(Path(path).read_bytes())
    return h.hexdigest()


class LabTest(unittest.TestCase):
    """One fx-lite instance per class, installed by a first-install-like plan; every test leaves no operation open
    and no secret value outside the files that hold secrets (a canary swept after each test, F12)."""

    TAG = "tc"
    lab: Lab
    install: tuple[int, dict[str, Any]]
    token: str
    token_file: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.lab = lab = Lab(cls.TAG)
        try:
            cls.install = lab.run(lab.save("deploy", lab.install_steps(), {"candidate": lab.variant()}))
        except BaseException:
            lab.close()
            raise
        cls.token = secrets.token_hex(16)  # a secret file that ends in a newline, as an owner's editor writes it
        cls.token_file = f"{lab.layout.secrets_dir(lab.name)}/token"
        Path(cls.token_file).write_text(cls.token + "\n")
        Path(lab.layout.inbox, "tok").write_text(cls.token)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.lab.close()

    def tearDown(self) -> None:
        self.assertIsNone(self.lab.open_op(), "a test left an operation open")
        self.assertEqual(secret_files(self.lab, [self.lab.secret, self.token]), [], "secret canary (F12)")


if __name__ == "__main__":
    root, backups, cfg, plan_hash, run_id, mode = sys.argv[1:7]
    sys.exit(
        executor.execute(
            state.Layout(root, backups), Docker(config_dir=cfg), Compose(cfg), plan_hash, run_id,
            resume=mode == "resume", abandon=mode == "abandon",
        )
    )  # fmt: skip
