"""Docker and Compose argv and error mapping, with the runner replaced (no daemon needed)."""

import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from ingat.adapters import runner
from ingat.adapters.compose import Compose, Project
from ingat.adapters.docker import Docker, EffectToken
from ingat.model.errors import CannotRun, Failed, Refused

CFG = "/cfg"
P = Project("site", "/x/export", ("compose.yaml", "/abs/extra.yaml"), "/x/op/override.yaml", "/x/op/compose.env")
HEAD = ["docker", "compose", "-p", "site", "--project-directory", "/x/export", "-f", "/x/export/compose.yaml"]
HEAD += ["-f", "/abs/extra.yaml", "-f", "/x/op/override.yaml", "--env-file", "/x/op/compose.env"]


def token() -> EffectToken:
    return EffectToken(1, 1)


class Fake:
    """Records every runner call and answers from a queue of results."""

    def __init__(self, *results: runner.Result) -> None:
        self.results = list(results)
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kw: Any) -> runner.Result:
        self.calls.append((list(argv), kw))
        return self.results.pop(0) if self.results else runner.Result(0, "", "", False, False)


def res(code: int = 0, out: str = "", err: str = "", truncated: bool = False) -> runner.Result:
    return runner.Result(code, out, err, False, truncated)


class ArgvTest(unittest.TestCase):
    def call(self, fn: Any, *results: runner.Result) -> tuple[Any, Fake]:
        fake = Fake(*results)
        with mock.patch.object(runner, "run", fake):
            return fn(), fake

    def test_compose_verbs(self) -> None:
        c = Compose(CFG)
        _, f = self.call(lambda: c.up(token(), P, ["web", "db"], timeout=9))
        self.assertEqual(f.calls[0][0], [*HEAD, "up", "-d", "--no-build", "--pull", "never", "--no-deps", "web", "db"])
        self.assertEqual(f.calls[0][1]["env"], {"DOCKER_CONFIG": CFG})
        self.assertEqual(f.calls[0][1]["timeout"], 9)
        _, f = self.call(lambda: c.stop(token(), P, ["web"], timeout=9))
        self.assertEqual(f.calls[0][0], [*HEAD, "stop", "web"])
        _, f = self.call(lambda: c.down(token(), P, timeout=9))
        self.assertEqual(f.calls[0][0], [*HEAD, "down"])
        for fn in (lambda: c.up(token(), P, [], timeout=9), lambda: c.stop(token(), P, (), timeout=9)):
            with self.assertRaises(Refused):
                self.call(fn)

    def test_profiles_and_no_override(self) -> None:
        p = Project("site", "/e", ("c.yaml",), None, "/e.env", ("a", "b"))
        _, f = self.call(lambda: Compose(CFG).ps(p), res(out='{"Service":"web"}\n{"Service":"db"}\n'))
        argv = ["docker", "compose", "-p", "site", "--project-directory", "/e", "-f", "/e/c.yaml", "--env-file"]
        self.assertEqual(
            f.calls[0][0], [*argv, "/e.env", "--profile", "a", "--profile", "b", "ps", "-a", "--format", "json"]
        )

    def test_run(self) -> None:
        c = Compose(CFG)
        kw: dict[str, Any] = {"name": "site-x3-2-a1", "labels": {"l.op": "3"}, "volumes": ["/s:/stage"], "timeout": 5}
        _, f = self.call(lambda: c.run(token(), P, "app", ["dump", "-v"], user="1000:1000", env={"A": "b"}, **kw))
        tail = ["run", "--rm", "--no-deps", "-T", "--name", "site-x3-2-a1", "--label", "l.op=3", "-v", "/s:/stage"]
        self.assertEqual(f.calls[0][0], [*HEAD, *tail, "-u", "1000:1000", "-e", "A=b", "app", "dump", "-v"])
        self.assertEqual((f.calls[0][1]["stdin"], f.calls[0][1]["stdout"]), (None, "capture"))
        _, f = self.call(lambda: c.run(token(), P, "app", ["x"], tty=True, stdin="inherit", stdout="inherit", **kw))
        self.assertNotIn("-T", f.calls[0][0])
        self.assertEqual((f.calls[0][1]["stdin"], f.calls[0][1]["stdout"]), ("inherit", "inherit"))

    def test_config_parsing_and_refusal(self) -> None:
        c = Compose(CFG)
        out, f = self.call(lambda: c.config_hashes(P, ["a", "b"]), res(out=f"a {'1' * 64}\nb {'2' * 64}\n"))
        self.assertEqual(out, {"a": "1" * 64, "b": "2" * 64})
        self.assertEqual(f.calls[0][0][-3:], ["config", "--hash", "a,b"])
        doc = '{"A": {"Name": "A", "DefaultValue": ""}, "B": {"Name": "B", "DefaultValue": "x"}}'
        out, _ = self.call(lambda: c.variables(P), res(out=doc))
        self.assertEqual(out, {"A": False, "B": True})
        out, f = self.call(lambda: c.config(P), res(out='{"name": "site"}', err="warning"))
        self.assertEqual(
            (out, f.calls[0][0][-4:]), ({"name": "site"}, ["config", "--format", "json", "--no-env-resolution"])
        )
        with self.assertRaises(Refused) as cm:
            self.call(lambda: c.config(P), res(1, err="services.web: bad key"))
        self.assertEqual(cm.exception.code, "compose-config")
        self.assertIn("bad key", cm.exception.message)

    def test_unreachable_daemon(self) -> None:
        for err in (
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
            'level=warning msg="The W variable is not set."\nfailed to connect to the docker API at unix:///x: dial',
            "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock",
        ):
            with self.assertRaises(CannotRun) as cm:
                self.call(lambda: Docker(config_dir=CFG).info(), res(1, err=err))
            self.assertEqual(cm.exception.code, "daemon-unreachable")
            with self.assertRaises(CannotRun):
                self.call(lambda: Compose(CFG).up(token(), P, ["a"], timeout=1), res(1, err=err))

    def test_app_stderr_is_not_a_daemon_error(self) -> None:
        """A task or probe that fails with connection text of its own keeps its exit code."""
        err = " Container site-x3-2-a1 Creating\nerror during connect: dial tcp 10.0.0.5:5432: connection refused\n"
        kw: dict[str, Any] = {"name": "site-x3-2-a1", "labels": {}, "timeout": 5}
        out, _ = self.call(lambda: Compose(CFG).run(token(), P, "app", ["dump"], **kw), res(1, err=err))
        self.assertEqual(out.code, 1)
        out, _ = self.call(lambda: Docker(config_dir=CFG).probe_exec("c", ["probe"], 5), res(2, err=err))
        self.assertEqual(out.code, 2)

    def test_env_file_never_sets_compose_settings(self) -> None:
        """Compose reads COMPOSE_* settings from the --env-file (COMPOSE_REMOVE_ORPHANS would delete containers)."""
        with tempfile.TemporaryDirectory() as d:
            p = Project("site", "/e", ("c.yaml",), None, os.path.join(d, "compose.env"))
            for text in ("A='1'\nCOMPOSE_REMOVE_ORPHANS='true'\n", "export COMPOSE_PROFILES=x\n", " DOCKER_X='x'\n"):
                with open(p.env_file, "w", encoding="utf-8") as f:
                    f.write(text)
                with self.assertRaises(Refused) as cm:
                    self.call(lambda: Compose(CFG).up(token(), p, ["a"], timeout=1))
                self.assertEqual(cm.exception.code, "policy")
            with open(p.env_file, "w", encoding="utf-8") as f:
                f.write("A='COMPOSE_REMOVE_ORPHANS=true'\nB_COMPOSE_X='1'\n")
            _, fake = self.call(lambda: Compose(CFG).up(token(), p, ["a"], timeout=1))
            self.assertEqual(len(fake.calls), 1)

    def test_truncated_output_is_never_parsed(self) -> None:
        d = Docker(config_dir=CFG)
        for fn in (d.containers, lambda: d.inspect("network", ["n"]), lambda: d.events("1", "2")):
            with self.assertRaises(CannotRun):
                self.call(fn, res(out="[]\n", truncated=True))
        with self.assertRaises(CannotRun):
            self.call(lambda: Compose(CFG).ps(P), res(out="{}\n", truncated=True))

    def test_docker_queries_and_effects(self) -> None:
        d = Docker(config_dir=CFG)
        out, f = self.call(
            lambda: d.containers({"k": "v", "k2": "v2"}, project="site"),
            res(out="aa\nbb\n"),
            res(1, out='[{"Id": "aa"}]', err="Error response from daemon: No such container: bb"),
        )
        self.assertEqual(out, [{"Id": "aa"}])
        filt = ["--filter", "label=k=v", "--filter", "label=k2=v2", "--filter", "label=com.docker.compose.project=site"]
        self.assertEqual(f.calls[0][0], ["docker", "ps", "-a", "-q", "--no-trunc", *filt])
        self.assertEqual(f.calls[1][0], ["docker", "container", "inspect", "--", "aa", "bb"])
        out, f = self.call(lambda: d.containers(), res(out=""))
        self.assertEqual((out, len(f.calls)), ([], 1))
        out, _ = self.call(
            lambda: d.image("x:1"), res(1, out="[]", err="Error response from daemon: No such image: x:1")
        )
        self.assertIsNone(out)
        with self.assertRaises(CannotRun):
            self.call(lambda: d.image("x:1"), res(1, err="permission denied"))
        _, f = self.call(
            lambda: d.stop(token(), "c1", 7), res(1, err="Error response from daemon: No such container: c1")
        )
        self.assertEqual(f.calls[0][0], ["docker", "stop", "-t", "7", "--", "c1"])
        with self.assertRaises(Failed):
            self.call(lambda: d.remove_container(token(), "c1"), res(1, err="container is running"))
        with self.assertRaises(Failed):
            self.call(lambda: d.pull(token(), "r/x:1"), res(1, err="manifest unknown"))

    def test_launch_executor(self) -> None:
        d = Docker(config_dir=CFG)
        busy = res(1, err='Conflict. The container name "/e" is already in use')
        out, f = self.call(
            lambda: d.launch_executor(
                name="e", image="img", args=["_x", "a"], mounts=["/a:/a"], env={"E": "1"}, labels={"l": "v"}
            ),
            res(out='[{"Id": "old"}]'),
            res(out="[]"),
            busy,
            res(out="[]"),
            res(out="cid\n"),
        )
        self.assertEqual(out, "cid")
        run = ["docker", "run", "-d", "--rm", "--init", "--pull", "never", "--network", "host", "--stop-timeout", "120"]
        run += [
            "--log-driver",
            "local",
            "--log-opt",
            "max-size=10m",
            "--log-opt",
            "max-file=3",
            "--name",
            "e",
            "--label",
            "l=v",
        ]
        self.assertEqual(f.calls[-1][0], [*run, "-v", "/a:/a", "-e", "E=1", "img", "_x", "a"])
        self.assertEqual(len(f.calls), 5)


if __name__ == "__main__":
    unittest.main()
