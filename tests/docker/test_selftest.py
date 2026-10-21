"""T1: `selftest` against a real daemon (both engines, dt.sh). The full run goes in-process, as the host executor runs
it, on a scratch root that `host init` set up and that holds no certification: it must pass there, write the
certification of this platform build with `--host`, and leave nothing of its instances behind, while a pre-existing
instance of the same root (records, data, a bundle, allocation and ledger entries, a running container) stays
untouched. A failure injected at the drill, or an install left open at its pause, still tears everything down and
certifies nothing. `--offline` runs as the install runs it: the tool image without the socket, the roots or network."""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest import mock

from ingat import __version__, brand
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.ops import backup, lifecycle, selftest
from ingat.ops import context as cx
from ingat.ops import host as hostops
from ingat.policy import gate
from ingat.store import state
from tests.harness import host as harness

IMAGE = os.environ.get("INGAT_TEST_IMAGE", "ingat:dev")
REPO = Path(__file__).resolve().parents[2]
PKG = "/usr/local/lib/python3.13/site-packages/ingat"
SOCK = "/var/run/docker.sock"
ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/root"}


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, env=ENV, check=check)


def tree(path: str) -> dict[str, tuple[int, str]]:
    out = {}
    for top, dirs, files in os.walk(path):
        for name in dirs + files:
            p = os.path.join(top, name)
            digest = hashlib.sha256(Path(p).read_bytes()).hexdigest() if name in files else ""
            out[os.path.relpath(p, path)] = (os.lstat(p).st_mode, digest)
    return out


def listing(path: str) -> list[str]:
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


@unittest.skipUnless(os.path.exists(SOCK), "needs a scratch Docker daemon")
class SelftestTest(unittest.TestCase):
    def setUp(self) -> None:
        # The daemon-wide lock `certify` of the integration harness holds, until close() has run (cleanups run last in,
        # first out): every selftest takes the lowest free names and ports of the daemon, so another runner's selftest
        # would reuse self.names while assert_nothing_left and close() still look them up by label.
        self.enterContext(harness.daemon_lock("host-executor"))
        u = secrets.token_hex(4)
        self.base, self.other = f"/srv/tst{u}", f"to{u}"
        root, backups = f"{self.base}/root", f"{self.base}/backups"
        for d in (root, backups, f"{self.base}/facts/etc", f"{self.base}/probe"):
            os.makedirs(d, 0o700)
            os.chmod(d, 0o700)
        self.addCleanup(self.close)
        Path(f"{self.base}/facts/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        server = json.loads(docker("version", "--format", "{{json .Server}}").stdout)
        tested = [{"engine": ".".join(server["Version"].split(".")[:2]), "arch": server["Arch"]}]
        for patch in (
            mock.patch.object(brand, "HOST_FACTS_DIR", f"{self.base}/facts"),
            mock.patch.object(brand, "PROBE_MOUNT", f"{self.base}/probe"),  # the host executor mounts the probe volume
            mock.patch.object(gate, "load_tested", return_value=tested),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        if docker("volume", "inspect", brand.PROBE_VOLUME, check=False).returncode:  # as install.sh makes it
            docker("volume", "create", "--label", f"{brand.label('role')}=probe", brand.PROBE_VOLUME)
        self.environ = {brand.env("ROOT"): root, brand.env("BACKUPS"): backups, brand.env("HOST"): "testhost"}
        self.environ[brand.env("IMAGE")] = IMAGE
        self.assertEqual(hostops.host_init(self.ctx())["exit"], 0)
        self.lay = self.ctx().layout
        self.image_hex = self.ctx().docker.image(IMAGE)["Id"].removeprefix("sha256:")  # type: ignore[index]
        self.names: list[str] = []
        self.make_other()

    def ctx(self) -> cx.Ctx:
        return cx.make_ctx(self.environ)

    def close(self) -> None:
        """Only a failed run leaves anything; the other instance's container always goes."""
        docker("rm", "-f", f"{self.other}-app", f"{self.other}-hand", check=False)
        left = [n for n in listing(f"{self.base}/root/instances") if n.startswith(brand.SELFTEST_PREFIX)]
        for name in {*self.names, *left}:
            for kind in ("container", "network"):
                found = docker(kind, "ls", "-q", *(["-a"] if kind == "container" else []), "--filter",
                               f"label={brand.label('instance')}={name}", check=False).stdout.split()  # fmt: skip
                if found:
                    docker(kind, "rm", *(["-f"] if kind == "container" else []), *found, check=False)
        shutil.rmtree(self.base, ignore_errors=True)

    def make_other(self) -> None:
        """An instance of this root that is not the selftest's: records, a generation, a bundle, a port allocation, a
        ledger entry of the tool image, and a running container in its own project."""
        lay, o = self.lay, self.other
        record = {"name": o, "app": "fx-lite", "environment": "test", "lineage": "a" * 32, "disposable": False}
        record |= {"state": "running", "current_deployment": None, "generations": {"data": 1}, "open_op": None}
        state.write_doc_once(lay.record_json(o), records.new_doc("instance", **record, next_seq=2))
        Path(lay.inst_toml(o)).write_text(f'instance = 1\nname = "{o}"\napp = "fx-lite"\nenvironment = "test"\n')
        gen = lay.data_gen(o, "data", "g1")
        os.makedirs(gen)
        Path(gen, "app.db").write_bytes(b"data")
        marker = records.new_doc("generation", instance=o, store="data", generation="g1", purpose="live", op=1)
        state.write_doc_once(gen + ".json", marker)
        os.makedirs(lay.bundle_dir(o, "b1"))
        Path(lay.bundle_dir(o, "b1"), "SHA256SUMS").write_text("x\n")
        entry = records.new_doc("allocation", instance=o, purpose="live", param="FXLITE_PORT", op=None, at="t")
        state.write_doc_once(lay.allocation("port", "29999"), entry)
        ledger = records.new_doc("ledger", image="sha256:" + self.image_hex, refs=[IMAGE], pulled_by={"instance": o})
        state.write_doc_once(lay.ledger(self.image_hex, f"{o}-1"), ledger)
        labels = [f"--label={brand.label('instance')}={o}", f"--label=com.docker.compose.project={o}"]
        docker("run", "-d", "--name", f"{o}-app", *labels, "--entrypoint", "sleep", IMAGE, "600")

    def other_state(self) -> dict[str, Any]:
        lay, o = self.lay, self.other
        trees = {p: tree(p) for p in (lay.inst(o), os.path.dirname(os.path.dirname(lay.data_gen(o, "s", "g"))))}
        trees[os.path.dirname(lay.bundle_dir(o, "b"))] = tree(os.path.dirname(lay.bundle_dir(o, "b")))
        files = [lay.allocation("port", "29999"), lay.ledger(self.image_hex, f"{o}-1")]
        [c] = json.loads(docker("inspect", f"{self.other}-app").stdout)
        return {
            "trees": trees,
            "files": {p: Path(p).read_bytes() for p in files},
            "app": (c["Id"], c["State"]["Status"]),
        }

    def run_selftest(self) -> dict[str, Any]:
        """Under the daemon-wide lock setUp took (never taken again here: flock belongs to the open file, so a second
        open of the lock file in this process would wait on itself)."""
        rep = selftest.run(self.ctx(), host=True, offline=False, fixtures=str(REPO / "fixtures"))
        self.names = rep["instances"]
        return rep

    def certification(self) -> dict[str, Any]:
        [name] = [f for f in listing(self.lay.certifications_dir) if f.endswith("-selftest.json")]
        return state.read_doc(f"{self.lay.certifications_dir}/{name}", "selftest")

    def assert_nothing_left(self) -> None:
        lay, o = self.lay, self.other
        for name in self.names:
            for kind in ("container", "network"):
                found = docker(kind, "ls", "-q", *(["-a"] if kind == "container" else []), "--filter",
                               f"label={brand.label('instance')}={name}").stdout.split()  # fmt: skip
                self.assertEqual(found, [], f"{kind} of {name} left")
        self.assertEqual(listing(lay.instances_dir), [o])
        self.assertEqual(listing(f"{lay.root}/data"), [o])
        self.assertEqual(listing(lay.backups), [o])
        self.assertEqual(listing(lay.allocations_dir), ["port-29999.json"])
        self.assertEqual(listing(f"{lay.root}/host/images"), [self.image_hex])
        self.assertEqual(listing(f"{lay.root}/host/images/{self.image_hex}"), [f"{o}-1.json"])
        for folder in (lay.plans_dir, lay.runs_dir, lay.fixtures_dir, f"{lay.root}/cache/src", f"{lay.root}/cache/git"):
            self.assertEqual(listing(folder), [], folder)

    def test_full_run_passes_certifies_and_leaves_nothing(self) -> None:
        with self.assertRaises(CannotRun):  # uncertified before
            cx.gate(self.ctx(), gate.TIER2)
        before = self.other_state()
        rep = self.run_selftest()
        self.assertEqual((rep["exit"], rep["result"]), (0, "PASS"), "\n".join(rep["lines"]))
        self.assertTrue(all(x.startswith("PASS ") for x in rep["lines"][:-1]))
        names = rep["instances"]
        n = names[0].removeprefix(brand.SELFTEST_PREFIX).removesuffix("-lite")  # the smallest free number
        self.assertEqual(names, [f"{brand.SELFTEST_PREFIX}{n}-lite", f"{brand.SELFTEST_PREFIX}{n}-web"])
        self.assertTrue(n.isdigit())
        for step in ("resume the install", "backup", "verify the bundle", "drill the bundle", "deploy B"):
            self.assertTrue(any(x.startswith(f"PASS {names[0]}: {step}") for x in rep["lines"]), step)
        self.assertTrue(any(x.startswith(f"PASS {names[1]}: deploy B") for x in rep["lines"]))
        cert = self.certification()
        self.assertEqual((cert["result"], cert["tool_version"]), ("PASS", __version__))
        ctx = self.ctx()
        self.assertEqual(cert["build"], cx.build_facts(ctx))
        self.assertEqual(cert["facts"]["engine_id"], ctx.info["ID"])
        self.assertEqual(cert["checks"], rep["lines"][:-1])
        self.assertTrue(rep["lines"][-1].endswith(rep["certification"]))
        self.assertEqual(cx.gate(ctx, gate.TIER2), [])  # the platform build is certified now
        self.assert_nothing_left()
        self.assertEqual(self.other_state(), before)
        self.assertEqual(before["app"][1], "running")

    def fail_at(self, module: Any, planner: str, when: Callable[..., bool], check: str) -> mock.MagicMock:
        """Run with `planner` refusing when `when(args)`: the check fails, later ones are skipped, the teardown
        removes everything all the same (abandoning an open operation first) and the run certifies nothing."""
        real = getattr(module, planner)

        def refusing(ctx: cx.Ctx, *args: Any, **kw: Any) -> Any:
            if when(*args):
                raise Refused("injected by the test", code="test")
            return real(ctx, *args, **kw)

        before = self.other_state()
        with (
            mock.patch.object(module, planner, refusing),
            mock.patch.object(lifecycle, "plan_abandon", wraps=lifecycle.plan_abandon) as abandon,
        ):
            rep = self.run_selftest()
        self.assertEqual((rep["exit"], rep["result"], rep["next"]), (3, "FAIL", f"{brand.CLI} status"), rep["lines"])
        failed = [x for x in rep["lines"] if x.startswith("FAIL")]
        self.assertEqual(failed, [f"FAIL {self.names[0]}: {check}: injected by the test"])
        self.assertFalse(any(self.names[1] in x for x in rep["lines"] if "teardown" not in x))  # skipped
        self.assertTrue(rep["lines"][-2].startswith("PASS nothing of the run remains"))
        self.assertEqual(self.certification()["result"], "FAIL")
        with self.assertRaises(CannotRun):  # a FAIL certifies nothing
            cx.gate(self.ctx(), gate.TIER2)
        self.assert_nothing_left()
        self.assertEqual(self.other_state(), before)
        return abandon

    def test_a_failed_drill_still_tears_down_and_certifies_nothing(self) -> None:
        abandon = self.fail_at(backup, "plan_verify", lambda name, bundle, latest, drill: drill, "drill the bundle")
        self.assertEqual(abandon.call_count, 0)  # no operation was left open

    def test_an_install_left_at_its_pause_is_abandoned_and_torn_down(self) -> None:
        abandon = self.fail_at(lifecycle, "plan_resume", lambda name: True, "resume the install")
        self.assertEqual([c.args[1] for c in abandon.call_args_list], [self.names[0]])

    def test_a_foreign_container_joining_a_selftest_project_is_never_touched(self) -> None:
        """A hand-made container joins the live project of the fx-lite instance after its deletion plan was made: the
        teardown re-proves the project right before `down` and refuses, so the container is neither stopped nor
        removed (F8); the fx-web instance is still torn down, the run fails, and the fx-lite instance it leaves gets
        no gate waiver from its marker once the run has ended (F14)."""
        real, made = selftest._deletions, dict[str, Any]()

        def deletions(ctx: cx.Ctx, name: str) -> Any:
            plan = real(ctx, name)
            if name.endswith("-lite"):  # every Compose label of the instance's own container, not its instance label
                [own] = json.loads(docker("inspect", f"{name}-app-1").stdout)
                tags = [f"--label={k}={v}" for k, v in own["Config"]["Labels"].items() if k.startswith("com.docker.")]
                docker("run", "-d", "--name", f"{self.other}-hand", *tags, "--entrypoint", "sleep", IMAGE, "600")
                [made["before"]] = json.loads(docker("inspect", f"{self.other}-hand").stdout)
            return plan

        before = self.other_state()
        with mock.patch.object(selftest, "_deletions", deletions):
            rep = self.run_selftest()
        lite, web = self.names
        self.assertEqual((rep["exit"], rep["result"]), (3, "FAIL"), rep["lines"])
        failed = [x for x in rep["lines"] if x.startswith("FAIL")]
        self.assertTrue(failed[0].startswith(f"FAIL {lite}: teardown"), failed)
        self.assertIn(f"{self.other}-hand", failed[0])
        self.assertIn(f"PASS {web}: teardown", rep["lines"])
        [after] = json.loads(docker("inspect", f"{self.other}-hand").stdout)
        for key in ("Id", "Created"):
            self.assertEqual(after[key], made["before"][key])
        state_keys = ("Status", "StartedAt", "FinishedAt")
        self.assertEqual([after["State"][k] for k in state_keys], [made["before"]["State"][k] for k in state_keys])
        self.assertEqual(after["State"]["Status"], "running")
        self.assertEqual(self.certification()["result"], "FAIL")
        self.assertTrue(os.path.exists(self.lay.inst(lite, "selftest.json")))  # the marker is left with the instance
        with self.assertRaises(CannotRun) as cm:  # and widens gate tier 2 for nobody once the run has ended
            cx.gate(self.ctx(), gate.TIER2, lite)
        self.assertEqual(cm.exception.code, "uncertified")
        self.assertEqual(listing(self.lay.instances_dir), sorted([self.other, lite]))
        self.assertEqual(self.other_state(), before)

    def test_offline_in_the_image_without_socket_roots_or_network(self) -> None:
        mounts = ["-v", f"{REPO}/src/ingat:{PKG}:ro", "-v", f"{REPO}/fixtures:/opt/fixtures:ro"]
        res = docker("run", "--rm", "--network", "none", *mounts, IMAGE, "selftest", "--offline", "--json", check=False)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        doc = json.loads(res.stdout)
        self.assertEqual((doc["exit"], doc["code"], doc["result"], doc["next"]), (0, "ok", "PASS", None))


if __name__ == "__main__":
    unittest.main()
