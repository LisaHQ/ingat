"""T1: the CLI run as the wrapper runs it (ARCHITECTURE §3.3): a `role=cli` container of the tool image with the socket,
same-path roots, the probe volume, a release file under /run/host and the wrapper's environment, the current source
mounted over the image's package. Class C approval is typed on a pty (`docker run -t`); without a terminal it is refused
with exit 2 and leaves no trace. `deploy` prepares first and runs both operations in the detached executor
`<prefix><instance>` (`role=exec`), which pauses at fx-lite's install pause; `resume` completes the install.

The executor runs the image the CLI names, so the test builds one: the current source on top of the tool image. The
gate reads a `tested.json` naming this daemon's Engine line, mounted over the package's, and a selftest certification
of this platform build written into the scratch root."""

import json
import os
import pty
import select
import shutil
import signal
import subprocess
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ingat import __version__, brand
from ingat.model import records
from ingat.ops import context as cx
from ingat.store import state
from tests.harness import host as harness

IMAGE = os.environ.get("INGAT_TEST_IMAGE", "ingat:dev")
REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "fixtures" / "fx-lite"
PKG = "/usr/local/lib/python3.13/site-packages/ingat"
SOCK = "/var/run/docker.sock"
HOST = "testhost"
ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/root", "TERM": "dumb"}
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main"]
GIT_ENV = ENV | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"


def docker(*args: str, stdin: bytes | None = None, check: bool = True) -> str:
    return subprocess.run(["docker", *args], input=stdin, check=check, capture_output=True, env=ENV).stdout.decode()


def tree(path: str) -> dict[str, tuple[int, bytes]]:
    out = {}
    for top, dirs, files, _ in os.fwalk(path):
        for name in dirs + files:
            p = os.path.join(top, name)
            out[os.path.relpath(p, path)] = (os.lstat(p).st_mode, Path(p).read_bytes() if name in files else b"")
    return out


@unittest.skipUnless(os.path.exists(SOCK), "needs a scratch Docker daemon")
class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server = json.loads(docker("version", "--format", "{{json .Server}}"))
        cls.tested = [{"engine": ".".join(server["Version"].split(".")[:2]), "arch": server["Arch"]}]
        tag = f"tcli{os.urandom(4).hex()}:1"
        docker(
            "build", "-q", "-t", tag, "-f", "-", str(REPO / "src"), stdin=f"FROM {IMAGE}\nCOPY ingat {PKG}\n".encode()
        )
        cls.addClassCleanup(docker, "rmi", tag, check=False)
        cls.image = docker("image", "inspect", "--format", "{{.Id}}", tag).strip()
        cls.app_image = docker("image", "inspect", "--format", "{{.Id}}", IMAGE).strip()  # the fixture's image
        if subprocess.run(["docker", "volume", "inspect", brand.PROBE_VOLUME], capture_output=True, env=ENV).returncode:
            docker("volume", "create", "--label", f"{brand.label('role')}=probe", brand.PROBE_VOLUME)
            cls.addClassCleanup(docker, "volume", "rm", brand.PROBE_VOLUME, check=False)

    def setUp(self) -> None:
        u = os.urandom(4).hex()
        self.base, self.name = f"/srv/tcli{u}", f"tc{u}"
        self.root, self.backups = f"{self.base}/root", f"{self.base}/backups"
        self.addCleanup(self.cleanup)
        for d in (self.root, self.backups, f"{self.base}/facts/etc"):
            os.makedirs(d)
        for d in (self.root, self.backups):
            os.chmod(d, 0o700)
        Path(f"{self.base}/facts/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        Path(f"{self.base}/tested.json").write_text(json.dumps(self.tested))
        self.lay = state.Layout(self.root, self.backups)
        self.repo = f"{self.lay.fixtures_dir}/fx-lite"
        os.makedirs(self.repo)
        subprocess.run([*GIT, "init", "-q", self.repo], env=GIT_ENV, check=True)
        for f in ("ingat.toml", "compose.yaml"):
            shutil.copy(FIXTURE / f, self.repo)
        for args in (["add", "-A"], ["commit", "-q", "-m", "a"]):
            subprocess.run([*GIT, "-C", self.repo, *args], env=GIT_ENV, check=True)
        out = subprocess.run([*GIT, "-C", self.repo, "rev-parse", "HEAD"], env=GIT_ENV, check=True, capture_output=True)
        self.commit = out.stdout.decode().strip()

    def cleanup(self) -> None:
        mine = f"label={brand.label('instance')}={self.name}"
        if ids := docker("ps", "-aq", "--filter", mine, check=False).split():
            docker("rm", "-f", *ids, check=False)
        if nets := docker("network", "ls", "-q", "--filter", mine, check=False).split():
            docker("network", "rm", *nets, check=False)
        shutil.rmtree(self.base, ignore_errors=True)

    def argv(self, *args: str, tty: bool = False) -> list[str]:
        """The wrapper's `docker run` (install.sh), plus the current source and the test's tested.json."""
        r, b = self.root, self.backups
        env = {"ROOT": r, "BACKUPS": b, "IMAGE": self.image, "WRAPPER_VERSION": "9.9.9", "HOST": HOST}
        out = ["docker", "run", "--rm", "-i", *(["-t"] if tty else []), "--init", "--pull", "never"]
        out += ["--network", "host", "--label", f"{brand.label('role')}=cli", "--log-driver", "none"]
        out += ["-v", f"{SOCK}:{SOCK}", "-v", f"{r}:{r}", "-v", f"{b}:{b}"]
        out += ["-v", f"{brand.PROBE_VOLUME}:{brand.PROBE_MOUNT}:ro"]
        out += ["-v", f"{self.base}/facts/etc/os-release:{brand.HOST_FACTS_DIR}/etc/os-release:ro"]
        out += ["-v", f"{REPO}/src/ingat:{PKG}:ro", "-v", f"{self.base}/tested.json:{PKG}/tested.json:ro", "-e", "TERM"]
        out += [p for k, v in (env | {"OPERATOR": "tester"}).items() for p in ("-e", f"{brand.env(k)}={v}")]
        return [*out, self.image, *args]

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        p = subprocess.run(self.argv(*args), input=b"", capture_output=True, env=ENV, timeout=600, check=False)
        return p.returncode, p.stdout.decode(), p.stderr.decode()

    def run_tty(self, *args: str, answer: str) -> tuple[int, str]:
        """On a pty, typing `answer` at the approval prompt."""
        pid, fd = pty.fork()
        if pid == 0:  # the child: the docker client on the pty
            os.execvpe("docker", self.argv(*args, tty=True), ENV)
        out, sent, end = b"", False, time.monotonic() + 600
        try:
            while time.monotonic() < end:
                if not select.select([fd], [], [], 1)[0]:
                    continue
                try:
                    chunk = os.read(fd, 65536)
                except OSError:  # EIO: the client exited
                    break
                if not chunk:
                    break
                out += chunk
                if not sent and b"name to approve: " in out:
                    os.write(fd, answer.encode() + b"\r")
                    sent = True
            else:
                os.kill(pid, signal.SIGKILL)
        finally:
            os.close(fd)
        code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
        return code, out.decode(errors="replace")

    def certify(self) -> None:
        """A PASS selftest certification of this platform build, as `selftest --host` writes it."""
        with mock.patch.object(brand, "HOST_FACTS_DIR", f"{self.base}/facts"):
            ctx = cx.make_ctx({brand.env("ROOT"): self.root, brand.env("BACKUPS"): self.backups})
            doc = records.new_doc("selftest", result="PASS", build=cx.build_facts(ctx), tool_version=__version__)
        state.write_doc_once(f"{self.lay.certifications_dir}/0-selftest.json", doc)

    def record(self) -> dict[str, Any]:
        return state.read_doc(self.lay.record_json(self.name), "instance")

    def test_wrapper_flow(self) -> None:
        code, out, _ = self.run_cli("version", "--json")
        doc = json.loads(out)
        self.assertEqual((code, doc["version"], doc["wrapper"], doc["image"]), (0, __version__, "9.9.9", self.image))
        self.assertIsNone(doc["next"])

        before = tree(self.root)
        code, out, err = self.run_cli("host", "init")  # class C without a terminal
        self.assertEqual((code, out), (2, ""), err)
        self.assertTrue(err.startswith(f"{brand.CLI}: a class C change needs a terminal"), err)
        self.assertEqual(tree(self.root), before)
        code, text = self.run_tty("host", "init", answer=HOST)
        self.assertEqual(code, 0, text)
        self.assertEqual(state.read_doc(self.lay.host_json, "host")["root"], self.root)
        self.certify()

        code, out, err = self.run_cli("status", "--json")  # an empty host
        doc = json.loads(out)
        self.assertEqual((code, doc["instances"]), (doc["exit"], []), err)
        self.assertIn("next", doc)

        config = f"{self.lay.inbox}/{self.name}.toml"
        lines = ["instance = 1", f'name = "{self.name}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
        lines += [f'repo = "file://{self.repo}"', "[params]", f'FXLITE_IMAGE = "{self.app_image}"']
        lines += [f'FXLITE_PORT = "{harness.free_port()}"', "[app_env]"]  # above the ports a selftest allocates
        Path(config).write_text("\n".join(lines + [f'{k} = "{v}"' for k, v in APP_ENV.items()]) + "\n")
        before = tree(self.root)
        code, out, err = self.run_cli("init", self.name, "--config", config, "--ref", self.commit, "--json")
        self.assertEqual((code, json.loads(out)["code"], tree(self.root)), (2, "no-tty", before), err)
        code, text = self.run_tty("init", self.name, "--config", config, "--ref", self.commit, answer=self.name)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.record()["state"], "registered")

        before, plans = tree(self.lay.instances_dir), sorted(os.listdir(self.lay.plans_dir))
        code, out, err = self.run_cli("deploy", self.name, self.commit, "--json")  # class C without a terminal
        self.assertEqual((code, json.loads(out)["code"]), (2, "no-tty"), err)
        self.assertEqual((tree(self.lay.instances_dir), sorted(os.listdir(self.lay.plans_dir))), (before, plans))
        self.assertEqual(docker("ps", "-aq", "--filter", f"label={brand.label('instance')}={self.name}"), "")

        since = f"{time.time():.6f}"
        code, text = self.run_tty("deploy", self.name, self.commit, answer=self.name)
        self.assertEqual(code, 4, text)  # paused at the install pause
        self.assertIn("preparing", text)
        self.assertIn(f"deploy {self.name} at {self.commit}: approval class C", text)
        self.assertIn(f"next: {brand.CLI} resume {self.name}", text)
        self.assertEqual(state.read_doc(f"{self.lay.op_dir(self.name, 1, 'prepare')}/result.json", "result")["exit"], 0)
        self.assertEqual(self.record()["open_op"]["kind"], "deploy")
        # Scoped to this instance, so executors of other test processes on the shared daemon never count.
        filters = ["type=container", "event=create", f"label={brand.label('instance')}={self.name}"]
        events = docker("events", "--since", since, "--until", f"{time.time():.6f}", "--format", "{{json .}}",
                        *(p for f in filters for p in ("--filter", f)))  # fmt: skip
        made = [json.loads(e)["Actor"]["Attributes"] for e in events.splitlines()]
        execs = [a for a in made if a.get(brand.label("role")) == "exec"]
        self.assertEqual([a["name"] for a in execs], [brand.executor_name(self.name)] * 2)  # prepare, then deploy
        # --rm: the follower returns on the run file, so the executor may still be exiting; the daemon removes it then
        self.assertTrue(harness.wait_gone(brand.executor_name(self.name), 240))

        code, out, _ = self.run_cli("attach", self.name)  # the paused operation; no executor runs it
        self.assertEqual(code, 4, out)
        self.assertIn("step 4 Pause: started", out)
        before, plans = tree(self.lay.instances_dir), sorted(os.listdir(self.lay.plans_dir))
        code, text = self.run_tty("resume", self.name, answer=self.name[::-1])  # a wrong name approves nothing
        self.assertEqual(code, 1, text)
        self.assertIn("not approved", text)
        self.assertEqual((tree(self.lay.instances_dir), sorted(os.listdir(self.lay.plans_dir))), (before, plans))
        code, text = self.run_tty("resume", self.name, answer=self.name)
        self.assertEqual(code, 0, text)
        record = self.record()
        self.assertEqual((record["state"], record["open_op"], record["current_deployment"]), ("running", None, 1))
        code, out, _ = self.run_cli("attach", self.name, "--json")
        self.assertEqual((code, json.loads(out)["code"]), (0, "no-open-operation"))

        code, out, err = self.run_cli("scheduled", "backup", self.name)  # unattended: one line on success
        self.assertEqual((code, err), (0, ""), out)
        self.assertRegex(out, rf"\Ascheduled backup {self.name}: completed \(operation [0-9]+\)\n\Z")
        code, out, err = self.run_cli("status", self.name, "--json")
        doc = json.loads(out)
        self.assertEqual(code, doc["exit"], err)
        self.assertIn(code, (0, 5), out)


if __name__ == "__main__":
    unittest.main()
