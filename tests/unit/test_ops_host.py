"""`host init`, `host check` and `init` without a daemon (POSIX; run as root in a Linux container, as tests/ut.sh
does): host facts and risks, root checks, the records they write, init's checks that leave no trace, its writes, the
completion of an interrupted init and a lost allocation race. A fake Docker serves the queries; the git source is
stubbed (tests/docker/test_host_init.py covers both for real)."""

import hashlib
import itertools
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from ingat import __version__, brand
from ingat.adapters.docker import PROJECT_LABEL
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.model.manifest import parse_manifest
from ingat.ops import context as cx
from ingat.ops import host, instance
from ingat.policy import gate
from ingat.store import state

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "fx-lite" / "ingat.toml"
EXTRA = """
[secrets.alpha]
generate = "alnum32"
mode = "0444"
[secrets.beta]
generate = "alnum32"
[secrets.gamma]
"""
SERVER = {"Version": "29.9.0", "ApiVersion": "1.52", "Arch": "amd64", "Os": "linux", "GitCommit": "a5b58c9"}
SERVER |= {"BuildTime": "2026-10-08T20:39:33Z", "Components": [{"Name": "runc", "Version": "1.1.7"}]}
SERVER["Components"].append({"Name": "containerd", "Version": "v2.4.1"})
INFO = {"ID": "E1", "DockerRootDir": "/var/lib/docker", "Driver": "overlayfs", "KernelVersion": "6.6.1"}
INFO |= {"Architecture": "x86_64", "CpuCfsQuota": True, "CpuCfsPeriod": True, "MemoryLimit": True}
INFO |= {"LoggingDriver": "json-file", "CgroupVersion": "2", "OperatingSystem": "Test", "SecurityOptions": []}
INFO["DriverStatus"] = [["driver-type", "io.containerd.snapshotter.v1"]]


def manifest_text(**extra: str) -> str:
    """fx-lite with [secrets.*], a subnet and a second port param, and `exclusive_environments`."""
    text = FIXTURE.read_text() + EXTRA
    params = 'FXLITE_PORT     = { kind = "port" }\n'
    text = text.replace(params, params + 'ADMIN_PORT = { kind = "port" }\nNET = { kind = "subnet" }\n')
    return text.replace(
        'requires_ingat = ">=0.1,<1"\n', 'requires_ingat = ">=0.1,<1"\nexclusive_environments = ["production"]\n'
    )


class FakeDocker:
    def __init__(self) -> None:
        self.objects: dict[str, list[dict[str, Any]]] = {"container": [], "network": [], "volume": []}

    def _find(self, kind: str, labels: dict[str, str]) -> list[dict[str, Any]]:
        def have(d: dict[str, Any]) -> dict[str, str]:
            return d.get("Labels") or d.get("Config", {}).get("Labels") or {}

        return [d for d in self.objects[kind] if all(have(d).get(k) == v for k, v in labels.items())]

    def containers(self, labels: dict[str, str] | None = None, project: str | None = None) -> list[dict[str, Any]]:
        return self._find("container", {**(labels or {}), **({PROJECT_LABEL: project} if project else {})})

    def networks(self, labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return self._find("network", labels or {})

    def volumes(self, labels: dict[str, str]) -> list[dict[str, Any]]:
        return self._find("volume", labels)


def tree(path: str) -> dict[str, tuple[int, str]]:
    out = {}
    for top, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(top, n)
            digest = hashlib.sha256(Path(p).read_bytes()).hexdigest() if n in files else ""
            out[os.path.relpath(p, path)] = (os.lstat(p).st_mode, digest)
    return out


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.base = tempfile.mkdtemp()  # 0700, owned by the test's user (root in the container)
        self.addCleanup(shutil.rmtree, self.base)
        os.makedirs(f"{self.base}/root", 0o700)
        os.makedirs(f"{self.base}/backups", 0o700)
        os.makedirs(f"{self.base}/facts/etc")
        Path(f"{self.base}/facts/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        patch = mock.patch.object(brand, "HOST_FACTS_DIR", f"{self.base}/facts")
        patch.start()
        self.addCleanup(patch.stop)
        self.layout = state.Layout(f"{self.base}/root", f"{self.base}/backups")
        version = {"Client": {"Version": "29.9.0"}, "Server": dict(SERVER)}
        now = records.parse_iso("2026-10-15T10:00:00Z")
        fields = {"layout": self.layout, "info": dict(INFO), "version": version, "image": "tool@sha256:1"}
        self.ctx: Any = SimpleNamespace(**fields, operator="root", now=now, docker=FakeDocker(), hostname="h")


@unittest.skipUnless(os.geteuid() == 0, "needs root: the roots must be root-owned")
class HostTest(Base):
    def test_facts_and_risks(self) -> None:
        f = host.facts(self.ctx)
        self.assertEqual(
            (f["engine_id"], f["facts"]["image_store"], f["facts"]["storage_driver"]), ("E1", "containerd", "overlayfs")
        )
        self.assertEqual(f["versions"]["runc"], "1.1.7")
        self.assertEqual(gate.platform_build(f), cx.build_facts(self.ctx))  # host.json holds the certification key
        self.assertEqual(f["capabilities"], {"cpu_cfs_quota": True, "cpu_cfs_period": True, "memory_limit": True})
        self.assertEqual([r.split()[0] for r in host.risks(f)], ["the", "Docker"])
        self.assertIn("runc", host.risks(f)[0])
        f["versions"]["runc"], f["facts"]["security_options"] = "1.1.12", ["name=seccomp,profile=builtin"]
        self.assertEqual(host.risks(f), [])
        f["versions"]["runc"] = None
        self.assertIn("unknown", host.risks(f)[0])
        self.ctx.info["DriverStatus"] = [["Backing Filesystem", "extfs"]]
        self.assertEqual(host.facts(self.ctx)["facts"]["image_store"], "classic")

    def test_roots(self) -> None:
        self.assertEqual(host.roots(self.layout), [])
        os.chmod(self.layout.backups, 0o750)  # group may read: no other account writes
        self.assertEqual(host.roots(self.layout), [])
        os.chmod(self.layout.root, 0o755)
        os.chmod(self.layout.backups, 0o770)
        found = host.roots(self.layout)
        self.assertEqual(len(found), 2)
        want = "a folder owned by root and private to root (root:root, permissions 0700)"
        self.assertIn(f"{self.layout.root} must be {want}; found owner 0:0 and permissions 0755", found)
        shutil.rmtree(self.layout.backups)
        self.assertIn("does not exist", host.roots(self.layout)[1])

    def test_host_init_records_refreshes_and_refuses(self) -> None:
        report = host.host_init(self.ctx)
        self.assertEqual((report["exit"], report["code"], report["next"]), (0, "ok", None))  # untested: no next
        doc = state.read_doc(self.layout.host_json, "host")
        self.assertEqual((doc["engine_id"], doc["root"], doc["backups"]), ("E1", self.layout.root, self.layout.backups))
        self.assertEqual(doc["pools"], {"isolation": "10.250.0.0/20", "ports": "20000-29999"})
        self.assertEqual(doc["tool_image"], {"current": "tool@sha256:1", "previous": None})
        self.assertEqual(doc["label_namespace"], brand.LABEL_NS)
        for d in (self.layout.docker_config, self.layout.plans_dir, self.layout.inbox, f"{self.layout.root}/host"):
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700, d)
        state.replace_doc(self.layout.host_json, doc | {"extra": 1})  # a field of a later tool version
        self.ctx.image, self.ctx.now = "tool@sha256:2", records.parse_iso("2026-10-16T10:00:00Z")
        self.ctx.info["Driver"] = "overlay2"
        with mock.patch.object(gate, "load_tested", return_value=[{"engine": "29.9", "arch": "amd64"}]):
            self.assertEqual(host.host_init(self.ctx)["next"], f"{brand.CLI} selftest --host")
        again = state.read_doc(self.layout.host_json, "host")
        self.assertEqual((again["extra"], again["initialized_at"]), (1, doc["initialized_at"]))
        self.assertEqual(
            (again["facts"]["storage_driver"], again["tool_image"]["previous"]), ("overlay2", "tool@sha256:1")
        )
        before = Path(self.layout.host_json).read_bytes()
        self.ctx.info["ID"] = "E2"
        with self.assertRaises(CannotRun) as cm:
            host.host_init(self.ctx)
        self.assertEqual(cm.exception.code, "engine-mismatch")
        os.chmod(self.layout.root, 0o750)
        with self.assertRaises(Refused) as cm2:
            host.host_init(self.ctx)
        self.assertEqual(cm2.exception.code, "roots")
        self.assertEqual(Path(self.layout.host_json).read_bytes(), before)

    def test_host_check_writes_a_certification(self) -> None:
        host.host_init(self.ctx)
        self.ctx.info["Driver"] = "overlay2"  # a new platform build since host init
        report = host.host_check(self.ctx)
        self.assertEqual(
            (report["exit"], report["result"], report["changed_since_host_init"]), (0, "PASS", ["storage_driver"])
        )
        doc = records.loads(Path(report["path"]).read_bytes())
        self.assertEqual((doc["kind"], doc["state_schema"], doc["tool_version"]), ("host-check", 1, __version__))
        self.assertEqual(doc["build"], cx.build_facts(self.ctx))
        self.assertEqual(len(doc["risks"]), 2)
        os.chmod(self.layout.backups, 0o777)
        second = host.host_check(self.ctx)  # the same second: a numbered sibling
        self.assertEqual((second["exit"], second["code"], second["result"]), (5, "findings", "FAIL"))
        self.assertTrue(second["path"].endswith("-host-check-2.json"))
        shutil.rmtree(f"{self.base}/facts")
        os.chmod(self.layout.backups, 0o700)
        self.assertEqual(host.host_check(self.ctx)["missing"], ["os_release"])


@unittest.skipUnless(os.geteuid() == 0, "needs root: the roots must be root-owned")
class InitTest(Base):
    def setUp(self) -> None:
        super().setUp()
        host.host_init(self.ctx)
        self.text = manifest_text()
        self.name = "lite"
        self.config = self.instance()

    def instance(self, name: str = "lite", environment: str = "test", **params: str) -> bytes:
        """An instance.toml; NET defaults to 10.50.0.0/24 and an empty value leaves a param unset."""
        lines = ["instance = 1", f'name = "{name}"', 'app = "fx-lite"', f'environment = "{environment}"', "[source]"]
        lines += [f'repo = "file://{self.layout.fixtures_dir}/fx-lite"', "[params]", 'FXLITE_IMAGE = "img:1"']
        lines += [f'{k} = "{v}"' for k, v in ({"NET": "10.50.0.0/24"} | params).items() if v]
        lines += ["[app_env]", 'ALLOWED_ORIGINS = "x"', 'BASE_URL = "x"', 'MAIL_SENDER = "x"', 'PROXY_ADDRESS = "x"']
        return ("\n".join(lines) + "\n").encode()

    def create(self, data: bytes | None = None, name: str = "lite") -> dict[str, Any]:
        m = parse_manifest(self.text.encode(), tool_version=__version__)
        src = cx.Source("c" * 40, "c" * 40, "/x", m)
        with mock.patch.object(cx, "source", return_value=src):
            return instance.create(self.ctx, name, self.config if data is None else data, "main")

    def snapshot(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return tree(self.layout.instances_dir), tree(self.layout.allocations_dir)

    def entries(self) -> dict[tuple[str, str], dict[str, Any]]:
        return cx.allocations(self.ctx)

    def test_init_writes_the_instance_and_refuses_a_second(self) -> None:
        report = self.create()
        self.assertEqual((report["exit"], report["next"]), (0, f"{brand.CLI} deploy lite main"))
        self.assertEqual(report["params"], {"FXLITE_PORT": "20000", "ADMIN_PORT": "20001", "NET": "10.50.0.0/24"})
        rec = state.read_doc(self.layout.record_json("lite"), "instance")
        self.assertEqual(
            (rec["state"], rec["next_seq"], rec["disposable"], rec["app"]), ("registered", 1, False, "fx-lite")
        )
        self.assertRegex(rec["lineage"], "^[0-9a-f]{32}$")
        self.assertEqual(
            {k: (e["param"], e["purpose"]) for k, e in self.entries().items()},
            {
                ("port", "20000"): ("FXLITE_PORT", "live"),
                ("port", "20001"): ("ADMIN_PORT", "live"),
                ("subnet", "10.50.0.0/24"): ("NET", "live"),
            },
        )
        sdir = self.layout.secrets_dir("lite")
        values = {k: Path(sdir, k).read_text() for k in ("alpha", "beta")}
        self.assertNotEqual(values["alpha"], values["beta"])
        self.assertTrue(all(len(v) == 32 and v.isalnum() and v.isascii() for v in values.values()))
        modes = {k: stat.S_IMODE(os.stat(f"{sdir}/{k}").st_mode) for k in ("alpha", "beta", "env", ".")}
        self.assertEqual(modes, {"alpha": 0o444, "beta": 0o400, "env": 0o700, ".": 0o700})
        self.assertFalse(os.path.exists(f"{sdir}/gamma"))  # no `generate`: set later
        self.assertEqual(stat.S_IMODE(os.stat(self.layout.placeholder("lite")).st_mode), 0o555)
        self.assertEqual(os.listdir(self.layout.placeholder("lite")), [])
        self.assertEqual(Path(self.layout.inst_toml("lite")).read_bytes(), self.config)
        self.assertEqual(stat.S_IMODE(os.stat(self.layout.inst_toml("lite")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.layout.inst("lite")).st_mode), 0o700)
        self.assertTrue(os.path.isfile(self.layout.lock("lite")))
        self.assertFalse([line for line in report["lines"] if any(v in line for v in values.values())])
        with self.assertRaises(Refused) as cm:
            self.create()
        self.assertEqual(cm.exception.code, "exists")

    def test_refusals_leave_no_trace(self) -> None:
        other = records.new_doc("allocation", instance="web", purpose="live", param="P", op=None, at="x")
        state.write_doc_once(self.layout.allocation("port", "20090"), other)
        state.write_doc_once(self.layout.allocation("subnet", "10.9.0.0/24"), other)
        docker = self.ctx.docker
        container = {
            "Name": "/c1",
            "Config": {"Labels": {}},
            "HostConfig": {"PortBindings": {"80/tcp": [{"HostPort": "20091"}]}},
        }
        docker.objects["container"].append(container)
        docker.objects["network"].append({"Name": "n1", "Labels": {}, "IPAM": {"Config": [{"Subnet": "10.8.0.0/16"}]}})
        docker.objects["network"].append({"Name": "n2", "Labels": {}, "IPAM": {"Config": [{"Gateway": "10.7.0.1"}]}})
        before = self.snapshot()
        cases = [
            ("BAD", self.config, "usage"),
            ("other", self.config, "invalid-instance"),
            ("lite", self.instance(FXLITE_PORT="20090"), "port-conflict"),  # another instance's allocation
            ("lite", self.instance(FXLITE_PORT="20091"), "port-conflict"),  # published on the daemon
            ("lite", self.instance(FXLITE_PORT="20092", ADMIN_PORT="20092"), "port-conflict"),
            ("lite", self.instance(NET="10.9.0.0/25"), "subnet-conflict"),
            ("lite", self.instance(NET="10.8.1.0/24"), "subnet-conflict"),  # a daemon network
            ("lite", self.instance(NET="10.250.8.0/24"), "subnet-conflict"),  # the isolation pool
            ("lite", self.instance(NET=""), "not-in-this-release"),  # a live subnet is not allocated in M1
        ]
        for name, data, code in cases:
            with self.subTest(code=code, name=name), self.assertRaises((Refused, CannotRun)) as cm:
                self.create(data, name)
            self.assertEqual((cm.exception.code, cm.exception.exit_code), (code, 2 if code == "usage" else 1))
        self.text += '[tasks.peek]\nservice = "app"\nmode = "exec"\nargv = ["true"]\neffect = "read"\ntimeout = "1m"\n'
        with self.assertRaises(Refused) as cm:  # an app this release cannot deploy (exec tasks arrive in M2)
            self.create()
        self.assertEqual(cm.exception.code, "not-in-this-release")
        self.text = manifest_text()
        docker.objects["volume"].append({"Name": "lite_data", "Labels": {PROJECT_LABEL: "lite"}})  # plain Compose
        with self.assertRaises(Refused) as cm:
            self.create()
        self.assertEqual(cm.exception.code, "foreign")
        self.assertIn("volume lite_data", cm.exception.message)
        self.assertEqual(self.snapshot(), before)

    def test_exclusive_environments_both_ways(self) -> None:
        self.create(self.instance("prod", "production", NET="10.51.0.0/24"), "prod")
        with self.assertRaises(Refused) as cm:
            self.create()  # another instance beside a listed one
        self.assertEqual(cm.exception.code, "exclusive")
        shutil.rmtree(self.layout.inst("prod"))
        self.create()
        with self.assertRaises(Refused) as cm:  # a listed one beside another
            self.create(self.instance("prod2", "production", NET="10.52.0.0/24"), "prod2")
        self.assertEqual(cm.exception.code, "exclusive")
        self.assertNotIn("prod2", os.listdir(self.layout.instances_dir))

    def test_an_interrupted_init_is_completed(self) -> None:
        stale = records.new_doc("allocation", instance="lite", purpose="live", param="FXLITE_PORT", op=None, at="x")
        state.write_doc_once(self.layout.allocation("port", "20005"), stale)
        sdir = self.layout.secrets_dir("lite")
        os.makedirs(f"{sdir}/env", 0o700)
        Path(f"{sdir}/alpha").write_text("kept-value")
        os.chmod(f"{sdir}/alpha", 0o600)
        Path(self.layout.inst_toml("lite")).write_bytes(self.config)
        os.makedirs(self.layout.placeholder("lite"), 0o700)
        Path(self.layout.inst("lite", ".record.json.0a1b2c3d4e5f.tmp")).write_text("{")  # killed while publishing
        report = self.create()
        self.assertEqual(sorted(self.entries()), [("port", "20000"), ("port", "20001"), ("subnet", "10.50.0.0/24")])
        self.assertEqual(
            (Path(f"{sdir}/alpha").read_text(), stat.S_IMODE(os.stat(f"{sdir}/alpha").st_mode)), ("kept-value", 0o444)
        )
        self.assertIn("secrets.alpha: kept", report["lines"])
        self.assertEqual(stat.S_IMODE(os.stat(self.layout.placeholder("lite")).st_mode), 0o555)
        os.remove(self.layout.record_json("lite"))
        Path(self.layout.inst_toml("lite")).write_bytes(self.config + b"# edited\n")
        with self.assertRaises(Refused) as cm:
            self.create()
        self.assertEqual(cm.exception.code, "exists")

    def test_records_of_an_earlier_instance_are_never_taken_over(self) -> None:
        os.makedirs(self.layout.catalog_dir("lite"))  # record.json lost, records of another lineage left
        Path(self.layout.catalog("lite", "b1")).write_text("{}")
        Path(self.layout.inst_toml("lite")).write_bytes(self.config)
        before = self.snapshot()
        with self.assertRaises(Refused) as cm:
            self.create()
        self.assertEqual(cm.exception.code, "exists")
        self.assertIn("catalog", cm.exception.message)
        self.assertEqual(self.snapshot(), before)
        shutil.rmtree(self.layout.catalog_dir("lite"))
        os.makedirs(self.layout.data_gen("lite", "data", "g1"))  # the instance directory removed by hand, data left
        with self.assertRaises(Refused) as cm:
            self.create()
        self.assertEqual((cm.exception.code, os.listdir(self.layout.inst("lite"))), ("exists", ["instance.toml"]))
        self.assertEqual(self.entries(), {})

    def test_init_runs_only_on_a_certified_platform(self) -> None:
        Path(f"{self.base}/lite.toml").write_bytes(self.config)
        tested = [{"engine": "29.9", "arch": "amd64"}]
        with mock.patch.object(gate, "load_tested", return_value=tested), self.assertRaises(CannotRun) as cm:
            instance.init(self.ctx, "lite", f"{self.base}/lite.toml", "main")
        self.assertEqual((cm.exception.code, cm.exception.next), ("uncertified", f"{brand.CLI} selftest --host"))
        self.assertFalse(os.path.exists(self.layout.instances_dir))

    def test_a_missing_config_file_is_a_usage_error(self) -> None:
        with (
            mock.patch.object(cx, "gate", return_value=[]),
            self.assertRaises(CannotRun) as cm,
        ):  # exit 2 (LIFECYCLE §6)
            instance.init(self.ctx, "lite", f"{self.base}/missing.toml", "main")
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("usage", 2))
        self.assertFalse(os.path.exists(self.layout.instances_dir))

    def test_generated_secrets_are_pairwise_distinct(self) -> None:
        chars = itertools.chain("a" * 32, "a" * 32, "b" * 32)
        with mock.patch.object(instance.secrets, "choice", side_effect=lambda _: next(chars)):
            self.create()
        sdir = self.layout.secrets_dir("lite")
        self.assertEqual((Path(sdir, "alpha").read_text(), Path(sdir, "beta").read_text()), ("a" * 32, "b" * 32))

    def test_a_lost_allocation_race_refuses_cleanly(self) -> None:
        theirs = records.new_doc("allocation", instance="web", purpose="live", param="P", op=None, at="x")
        before = self.snapshot()
        ports = {"FXLITE_PORT": "20000", "ADMIN_PORT": "20001"}

        def race(*args: Any) -> dict[str, str]:
            state.write_doc_once(self.layout.allocation("port", "20001"), theirs)  # taken after the check
            return ports

        with mock.patch.object(cx, "allocate_ports", side_effect=race), self.assertRaises(Refused) as cm:
            self.create()
        self.assertEqual(cm.exception.code, "port-conflict")
        self.assertEqual(self.snapshot()[0], before[0])
        self.assertEqual([e["instance"] for e in self.entries().values()], ["web"])


if __name__ == "__main__":
    unittest.main()
