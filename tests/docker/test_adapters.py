"""T1: the Docker and Compose adapters against a real daemon (run with tests/harness or scratch dt.sh on both engines).

Every object is uniquely named and labelled and removed again. Bind sources live under /srv, which the test container
shares with the daemon's host at the same path. The tool image itself is the service image, so nothing is pulled."""

import hashlib
import json
import os
import shutil
import tempfile
import time
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock

from ingat import brand
from ingat.adapters import docker as docker_mod
from ingat.adapters.compose import Compose, Project
from ingat.adapters.docker import PROJECT_LABEL, Docker, EffectToken
from ingat.adapters.runner import Redactor
from ingat.model.errors import CannotRun, Failed, Refused

IMAGE = os.environ.get("INGAT_TEST_IMAGE", "ingat:dev")
SRV = "/srv"
SECRET = "Sx9Lq2Vb7TwKp4Rz"
MAIN = "/usr/local/lib/python3.13/site-packages/ingat/__main__.py"  # the tool image's entry module
COMPOSE = """services:
  app:
    image: ${APP_IMAGE}
    init: true
    entrypoint: ["python3", "-c"]
    command: ["import os, time; print('greeting=' + os.environ['GREETING'], flush=True); time.sleep(600)"]
    environment:
      GREETING: ${GREETING:-hello}
    env_file: [app.env]
"""
FAKE_MAIN = "import os, sys, time\ntime.sleep(float(sys.argv[1]))\nprint(os.environ.get('PROBE_ENV'), flush=True)\n"


def token() -> EffectToken:
    """The tests stand in for the executor, the only issuer of tokens in the package."""
    return EffectToken(0, 0)


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def eventually(fn: Callable[[], Any], wait: float = 15.0) -> Any:
    end = time.monotonic() + wait
    while not (value := fn()) and time.monotonic() < end:
        time.sleep(0.25)
    return value


@unittest.skipUnless(os.path.exists("/var/run/docker.sock"), "needs a scratch Docker daemon")
class AdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.u = "tadp" + os.urandom(4).hex()
        self.root = os.path.join(SRV, self.u)
        os.makedirs(self.root)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.cfg = cfg = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg, True)
        self.d = Docker(config_dir=cfg, redactor=Redactor([SECRET]))
        self.c = Compose(cfg, Redactor([SECRET]))
        write(f"{self.root}/app/compose.yaml", COMPOSE)
        write(f"{self.root}/app/app.env", f"TOKEN={SECRET}\n")
        write(f"{self.root}/compose.env", f"APP_IMAGE='{IMAGE}'\nGREETING='hi-there'\n")
        labels = {brand.label("instance"): self.u, brand.label("role"): "app"}
        write(f"{self.root}/override.yaml", json.dumps({"services": {"app": {"labels": labels}}}))
        self.p = Project(
            self.u, f"{self.root}/app", ("compose.yaml",), f"{self.root}/override.yaml", f"{self.root}/compose.env"
        )
        self.addCleanup(self.c.down, token(), self.p, timeout=120)
        self.ilabel = {brand.label("instance"): self.u}

    def test_queries(self) -> None:
        self.assertTrue(self.d.version()["Server"]["ApiVersion"])
        info = self.d.info()
        self.assertTrue(info["ID"])
        self.assertIn("CpuCfsQuota", info)
        image = self.d.image(IMAGE)
        assert image is not None
        self.assertTrue(image["Id"].startswith("sha256:"))
        self.assertIsNone(self.d.image("example.invalid/none:0"))
        for kind in ("container", "volume", "network"):
            self.assertEqual(self.d.inspect(kind, [self.u + "-none"]), [])
        vol, label = f"{self.u}-vol", f"{brand.label('instance')}={self.u}"
        docker_mod.check(docker_mod.cli(["volume", "create", "--label", label, vol], self.cfg, None), "create")
        self.addCleanup(docker_mod.cli, ["volume", "rm", vol], self.cfg, None)
        self.assertEqual([v["Name"] for v in self.d.volumes(self.ilabel)], [vol])

    def test_model_variables_and_hashes(self) -> None:
        model = self.c.config(self.p)
        app = model["services"]["app"]
        self.assertEqual(model["name"], self.u)
        self.assertEqual([e["path"] for e in app["env_file"]], [f"{self.root}/app/app.env"])
        self.assertEqual(app["labels"][brand.label("instance")], self.u)
        self.assertNotIn(SECRET, json.dumps(model))
        self.assertEqual(self.c.variables(self.p), {"APP_IMAGE": False, "GREETING": True})
        self.assertRegex(self.c.config_hashes(self.p, ["app"])["app"], "^[0-9a-f]{64}$")

    def test_config_failure_is_refused_and_redacted(self) -> None:
        write(f"{self.root}/app/bad.yaml", COMPOSE.replace("    init: true", f"    bogus{SECRET}: 1"))
        bad = Project(self.u, self.p.directory, ("bad.yaml",), None, self.p.env_file)
        for call in (lambda: self.c.config(bad), lambda: self.c.config_hashes(bad, ["app"])):
            with self.assertRaises(Refused) as cm:
                call()
            self.assertEqual(cm.exception.code, "compose-config")
            self.assertIn("***", cm.exception.message)
            self.assertNotIn(SECRET, cm.exception.message)

    def test_service_lifecycle(self) -> None:
        r = self.c.up(token(), self.p, ["app"], timeout=120)
        self.assertEqual(r.code, 0, r.err)
        [ps] = self.c.ps(self.p)
        self.assertEqual((ps["Service"], ps["State"]), ("app", "running"))
        [c] = self.d.containers(project=self.u)
        name, image = c["Name"].lstrip("/"), self.d.image(IMAGE)
        assert image is not None
        hashes = self.c.config_hashes(self.p, ["app"])
        self.assertEqual(c["Config"]["Labels"]["com.docker.compose.config-hash"], hashes["app"])
        self.assertEqual(c["Image"], image["Id"])
        self.assertEqual([x["Id"] for x in self.d.containers(self.ilabel)], [c["Id"]])
        self.assertEqual(len(self.d.networks({PROJECT_LABEL: self.u})), 1)
        probe = self.d.probe_exec(name, ["python3", "-c", "import os; print('probe', os.environ['TOKEN'])"], 30)
        self.assertEqual((probe.code, probe.out), (0, "probe ***\n"))
        self.assertEqual(self.d.probe_exec(name, ["python3", "-c", "raise SystemExit(5)"], 30).code, 5)
        self.assertTrue(eventually(lambda: "greeting=hi-there" in self.d.logs(name, tail=5).out))

        # The stop's own events, the newest of the window: a replay of the daemon's buffer (its newest few hundred
        # events, shared with the parallel suites) may have lost the start by now. `stop` is logged before the stop
        # call returns, `die` under the container's lock, which the inspect waits for.
        since = f"{time.time() - 1:.6f}"
        self.assertEqual(self.c.stop(token(), self.p, ["app"], timeout=60).code, 0)
        self.assertEqual(self.d.containers(project=self.u)[0]["State"]["Status"], "exited")
        events = self.d.events(since, f"{time.time():.6f}", [f"label={brand.label('instance')}={self.u}"])
        self.assertLessEqual({"die", "stop"}, {e["Action"] for e in events if e["Actor"]["ID"] == c["Id"]})
        self.d.remove_container(token(), c["Id"])
        self.d.remove_container(token(), c["Id"])  # already gone: no error
        self.assertEqual(self.d.containers(project=self.u), [])

        self.assertEqual(self.c.up(token(), self.p, ["app"], timeout=120).code, 0)
        self.assertEqual(self.c.down(token(), self.p, timeout=120).code, 0)
        self.assertEqual(self.d.containers(project=self.u), [])
        self.assertEqual(self.d.networks({PROJECT_LABEL: self.u}), [])

    def test_task_run(self) -> None:
        out = f"{self.root}/out"
        os.makedirs(out)
        os.chmod(out, 0o777)
        labels = {**self.ilabel, brand.label("op"): "7", brand.label("step"): "2", brand.label("role"): "task"}
        seen: list[dict[str, Any]] = []

        def tick() -> None:
            seen.extend([] if seen else self.d.containers({brand.label("op"): "7", **self.ilabel}))

        code = "import os, sys, time; time.sleep(3); open('/mnt/out/f', 'w').write(os.environ['K'] + str(os.getuid()))"
        code += "; sys.stderr.write('error during connect: dial tcp 10.0.0.1:1\\n')"  # app text, not a daemon error
        r = self.c.run(
            token(),
            self.p,
            "app",
            [code + "; print('ran'); sys.exit(3)"],
            name=f"{self.u}-x7-2-a1",
            labels=labels,
            volumes=[f"{out}:/mnt/out"],
            user="1234:1234",
            env={"K": "v1"},
            timeout=120,
            tick=tick,
        )
        self.assertEqual((r.code, r.out), (3, "ran\n"), r.err)
        with open(f"{out}/f", encoding="utf-8") as f:
            self.assertEqual(f.read(), "v11234")
        [c] = seen
        self.assertEqual(c["Name"], f"/{self.u}-x7-2-a1")
        self.assertLessEqual(labels.items(), c["Config"]["Labels"].items())
        self.assertTrue(c["HostConfig"]["AutoRemove"])
        self.assertTrue(any(b.startswith(f"{out}:/mnt/out") for b in c["HostConfig"]["Binds"]))
        self.assertTrue(eventually(lambda: not self.d.containers({brand.label("op"): "7", **self.ilabel})))

    def test_task_streams_are_byte_exact(self) -> None:
        data = bytes(range(256)) * 64 + b"\r\n\x00" + SECRET.encode()
        code = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
        path = f"{self.root}/stream.out"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            r = self.c.run(
                token(),
                self.p,
                "app",
                [code],
                name=f"{self.u}-x8-1-a1",
                labels=self.ilabel,
                stdin=data,
                stdout=fd,
                timeout=120,
            )
        finally:
            os.close(fd)
        self.assertEqual(r.code, 0, r.err)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), data)

    def test_launch_executor_name_is_a_mutex(self) -> None:
        write(f"{self.root}/main.py", FAKE_MAIN)
        name = f"{self.u}-exec"
        kw: dict[str, Any] = {
            "name": name,
            "image": IMAGE,
            "mounts": [f"{self.root}/main.py:{MAIN}:ro"],
            "env": {"PROBE_ENV": "v"},
            "labels": {**self.ilabel, brand.label("role"): "exec"},
        }
        self.addCleanup(self.d.stop, token(), name, 1)
        first = self.d.launch_executor(args=["2"], **kw)
        [c] = self.d.inspect("container", [first])
        hc = c["HostConfig"]
        self.assertEqual((hc["AutoRemove"], hc["Init"], hc["NetworkMode"]), (True, True, "host"))
        self.assertEqual(hc["LogConfig"], {"Type": "local", "Config": {"max-file": "3", "max-size": "10m"}})
        self.assertEqual(c["Config"]["StopTimeout"], 120)
        self.assertIn("PROBE_ENV=v", c["Config"]["Env"])
        self.assertLessEqual(kw["labels"].items(), c["Config"]["Labels"].items())
        start = time.monotonic()
        second = self.d.launch_executor(args=["0"], **kw)  # waits until the first one is gone
        self.assertNotEqual(first, second)
        self.assertGreater(time.monotonic() - start, 1.0)
        for _ in range(5):  # immediate reuse of the name of a container that just exited
            self.d.launch_executor(args=["0"], **kw)
        self.d.launch_executor(args=["60"], **kw)  # the full wait: the last one above may still be going away
        with mock.patch.object(docker_mod, "NAME_WAIT", 1.0), self.assertRaises(CannotRun) as cm:
            self.d.launch_executor(args=["0"], **kw)
        self.assertEqual(cm.exception.code, "executor-running")
        self.d.stop(token(), name, 1)
        self.assertTrue(eventually(lambda: not self.d.inspect("container", [name])))
        self.d.stop(token(), name, 1)  # already gone: no error

    def test_failures(self) -> None:
        with self.assertRaises(Failed):
            self.d.pull(token(), "example.invalid/none:0")
        cfg = tempfile.mkdtemp()  # a client config whose context points at no daemon
        self.addCleanup(shutil.rmtree, cfg, True)
        endpoint = {"docker": {"Host": "unix:///nonexistent.sock", "SkipTLSVerify": False}}
        meta = {"Name": "gone", "Metadata": {}, "Endpoints": endpoint}
        write(f"{cfg}/contexts/meta/{hashlib.sha256(b'gone').hexdigest()}/meta.json", json.dumps(meta))
        write(f"{cfg}/config.json", json.dumps({"currentContext": "gone"}))
        for call in (Docker(config_dir=cfg).info, lambda: Compose(cfg).ps(self.p)):
            with self.assertRaises(CannotRun) as cm:
                call()
            self.assertEqual(cm.exception.code, "daemon-unreachable")


if __name__ == "__main__":
    unittest.main()
