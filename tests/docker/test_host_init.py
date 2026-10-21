"""T1: `host init`, `host check` and `init` against a real daemon (run with tests/harness or scratch dt.sh on both
engines). The scratch roots live under /srv; the fx-lite fixture repository is a file:// repository under the scratch
root's cache/fixtures/ (ADR-0027), its manifest extended with two generated file secrets. The refusals use a foreign
Compose project of the instance's name created with plain `docker compose`, and a port another container publishes;
each must leave `instances/` and the allocation entries untouched."""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from ingat import brand
from ingat.model import records
from ingat.model.errors import Refused
from ingat.ops import context as cx
from ingat.ops import host, instance
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
SECRETS = '\n[secrets.alpha]\ngenerate = "alnum32"\nmode = "0444"\n[secrets.beta]\ngenerate = "alnum32"\n'
APP_ENV = ["[app_env]", 'ALLOWED_ORIGINS = "x"', 'BASE_URL = "x"', 'MAIL_SENDER = "x"', 'PROXY_ADDRESS = "x"']


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout


def tree(path: str) -> dict[str, tuple[int, str]]:
    out = {}
    for top, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(top, n)
            digest = hashlib.sha256(Path(p).read_bytes()).hexdigest() if n in files else ""
            out[os.path.relpath(p, path)] = (os.lstat(p).st_mode, digest)
    return out


@unittest.skipUnless(os.path.exists("/var/run/docker.sock"), "needs a scratch Docker daemon")
class HostInitTest(unittest.TestCase):
    def setUp(self) -> None:
        u = os.urandom(4).hex()
        self.base, self.name = f"/srv/thi{u}", f"hi{u}"
        self.addCleanup(shutil.rmtree, self.base, True)
        root, backups = f"{self.base}/root", f"{self.base}/backups"
        for d in (root, backups):
            os.makedirs(d, 0o700)
        os.makedirs(f"{self.base}/facts/etc")
        Path(f"{self.base}/facts/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        for patch in (
            mock.patch.object(brand, "HOST_FACTS_DIR", f"{self.base}/facts"),
            mock.patch.object(gate, "load_tested", self.engines),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.environ = {brand.env("ROOT"): root, brand.env("BACKUPS"): backups, brand.env("IMAGE"): IMAGE}
        self.ctx = cx.make_ctx(self.environ)
        self.lay = self.ctx.layout

    def engines(self) -> list[dict[str, str]]:
        server = self.ctx.version["Server"]
        return [{"engine": ".".join(server["Version"].split(".")[:2]), "arch": server["Arch"]}]

    def test_host_init_and_host_check(self) -> None:
        os.chmod(self.lay.root, 0o755)
        with self.assertRaises(Refused) as cm:
            host.host_init(self.ctx)
        self.assertEqual(cm.exception.code, "roots")
        self.assertEqual(os.listdir(self.lay.root), [])
        os.chmod(self.lay.root, 0o700)
        report = host.host_init(self.ctx)
        self.assertEqual((report["exit"], report["next"]), (0, f"{brand.CLI} selftest --host"))
        info = json.loads(docker("info", "--format", "{{json .}}"))
        doc = state.read_doc(self.lay.host_json, "host")
        self.assertEqual((doc["engine_id"], doc["docker_root_dir"]), (info["ID"], info["DockerRootDir"]))
        store = "containerd" if ["driver-type", "io.containerd.snapshotter.v1"] in info["DriverStatus"] else "classic"
        self.assertEqual((doc["facts"]["image_store"], doc["facts"]["storage_driver"]), (store, info["Driver"]))
        self.assertEqual(doc["versions"]["engine"], info["ServerVersion"])
        self.assertEqual(gate.platform_build(doc), cx.build_facts(self.ctx))
        self.assertEqual(doc["pools"], {"isolation": "10.250.0.0/20", "ports": "20000-29999"})
        for d in (self.lay.docker_config, self.lay.plans_dir, self.lay.inbox, f"{self.lay.root}/host"):
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700, d)
        self.assertEqual(os.listdir(self.lay.docker_config), [])
        self.ctx = cx.make_ctx(self.environ)  # a later run on the same engine refreshes the facts
        host.host_init(self.ctx)
        self.assertEqual(state.read_doc(self.lay.host_json, "host")["initialized_at"], doc["initialized_at"])

        check = host.host_check(self.ctx)
        self.assertEqual((check["exit"], check["result"], check["failed"], check["missing"]), (0, "PASS", [], []))
        cert = records.loads(Path(check["path"]).read_bytes())
        self.assertEqual((cert["kind"], cert["result"]), ("host-check", "PASS"))
        self.assertEqual(cert["build"], cx.build_facts(self.ctx))
        runc = tuple(int(x) for x in doc["versions"]["runc"].lstrip("v").split("-")[0].split(".")[:3])
        self.assertEqual(any("runc" in r for r in check["risks"]), runc < (1, 1, 12))
        seccomp = any("name=seccomp" in o for o in info.get("SecurityOptions") or ())
        self.assertEqual(any("seccomp" in r for r in check["risks"]), not seccomp)

    def test_init_of_fx_lite(self) -> None:
        host.host_init(self.ctx)
        cert = {"kind": "selftest", "result": "PASS", "build": cx.build_facts(self.ctx)}
        state.write_doc_once(f"{self.lay.certifications_dir}/x-selftest.json", cert)
        repo = f"{self.lay.fixtures_dir}/fx-lite"
        os.makedirs(repo)
        subprocess.run([*GIT, "init", "-q", repo], env=GIT_ENV, check=True)
        shutil.copy(FIXTURE / "compose.yaml", repo)
        Path(repo, brand.MANIFEST_FILE).write_text((FIXTURE / brand.MANIFEST_FILE).read_text() + SECRETS)
        for args in (["add", "-A"], ["commit", "-q", "-m", "a"]):
            subprocess.run([*GIT, "-C", repo, *args], env=GIT_ENV, check=True)
        config = f"{self.lay.inbox}/{self.name}.toml"

        def write(**params: str) -> None:
            lines = ["instance = 1", f'name = "{self.name}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
            lines += [f'repo = "file://{repo}"', "[params]", f'FXLITE_IMAGE = "{IMAGE}"']
            Path(config).write_text("\n".join([*lines, *(f'{k} = "{v}"' for k, v in params.items()), *APP_ENV]) + "\n")

        def refused(code: str) -> None:
            before = tree(self.lay.instances_dir), tree(self.lay.allocations_dir)
            with self.assertRaises(Refused) as cm:
                instance.init(cx.make_ctx(self.environ), self.name, config, "main")
            self.assertEqual(cm.exception.code, code)
            self.assertEqual((tree(self.lay.instances_dir), tree(self.lay.allocations_dir)), before)

        # A foreign Compose project of the same name, made with plain `docker compose`.
        foreign = f"{self.base}/foreign.yaml"
        Path(foreign).write_text(f'services:\n  x:\n    image: "{IMAGE}"\n    command: ["true"]\n')
        compose = ["compose", "-p", self.name, "-f", foreign]
        self.addCleanup(subprocess.run, ["docker", *compose, "down"], capture_output=True, check=False)
        docker(*compose, "create")
        write()
        refused("foreign")
        docker(*compose, "down")

        # A port another container publishes on the daemon.
        port = str(harness.free_port())  # held by this runner: no other runner's instance publishes or draws it
        cid = docker("create", "-p", f"127.0.0.1:{port}:3000", IMAGE, "true").strip()
        self.addCleanup(subprocess.run, ["docker", "rm", cid], capture_output=True, check=False)
        write(FXLITE_PORT=port)
        refused("port-conflict")

        write()
        report = instance.init(cx.make_ctx(self.environ), self.name, config, "main")
        self.assertEqual((report["exit"], report["next"]), (0, f"{brand.CLI} deploy {self.name} main"))
        record = state.read_doc(self.lay.record_json(self.name), "instance")
        self.assertEqual((record["state"], record["next_seq"], record["generations"]), ("registered", 1, {}))
        self.assertRegex(record["lineage"], "^[0-9a-f]{32}$")
        entries = {k: e for k, e in cx.allocations(self.ctx).items() if e["instance"] == self.name}
        self.assertEqual(
            [(k[0], e["param"], e["purpose"]) for k, e in entries.items()], [("port", "FXLITE_PORT", "live")]
        )
        self.assertEqual(report["params"]["FXLITE_PORT"], next(iter(entries))[1])
        sdir = self.lay.secrets_dir(self.name)
        values = [Path(sdir, k).read_text() for k in ("alpha", "beta")]
        self.assertEqual(len(set(values)), 2)
        self.assertTrue(all(len(v) == 32 and v.isascii() and v.isalnum() for v in values))
        modes = [stat.S_IMODE(os.stat(p).st_mode) for p in (f"{sdir}/alpha", f"{sdir}/beta", sdir, f"{sdir}/env")]
        self.assertEqual(modes, [0o444, 0o400, 0o700, 0o700])
        self.assertEqual(stat.S_IMODE(os.stat(self.lay.placeholder(self.name)).st_mode), 0o555)
        self.assertEqual(Path(self.lay.inst_toml(self.name)).read_bytes(), Path(config).read_bytes())
        self.assertFalse([v for v in values if v in json.dumps(report)])
        label = f"label={brand.label('instance')}={self.name}"  # init changed nothing in Docker
        self.assertEqual(docker("ps", "-aq", "--filter", label) + docker("network", "ls", "-q", "--filter", label), "")
        refused("exists")


if __name__ == "__main__":
    unittest.main()
