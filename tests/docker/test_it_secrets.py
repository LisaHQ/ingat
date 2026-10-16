"""Suite 5, the secret canary and terminal tasks (ARCHITECTURE §4.3, §9.4, §10.3; LIFECYCLE F12), on a scratch host
installed by the release's install.sh and driven through the real wrapper, class C approval typed on a pty.

fx-lite-secrets (tests/data/fx-lite-secrets) is fx-lite with a generated file secret `canary` and test-only tasks.
The owner places the app env secret `secrets/env/MAIL_PASSWORD` (`secret set` lands in M2); its value has characters
that URL-encoding changes. The app then puts both seeded values (and the URL-encoded form) into every text stream
Ingat captures: a `record` stdout, a `json` stdout, stderr (also of a failing task) and the service log; and, with
other bytes, into a data file that the backup copies into the bundle payload.

Asserted: no seeded value appears in any CLI output, nor in any file under the roots except where it belongs (the
secret files, the rendered app env files, the app's own data file and its copies); captured streams show the masks
where the values were; the payload file is byte-identical in the bundle and the bundle's Ingat-written files hold no
seeded value; the drill's isolated env file holds none either. The bootstrap code of the allowed terminal task of the
paused install, and the setup token and typed password of a `stdin = "terminal"` task, appear in no file under the
roots nor under the daemon's Docker root (read through a read-only bind into a helper container, never by argv), also
while the task waits at its prompt; that task runs on a TTY with echo disabled and no logging driver, and refuses
without a TTY and under `scheduled` with nothing written.

Nothing here prints a token: the test runner's own log is under the Docker root too."""

import hashlib
import json
import os
import pty
import re
import secrets
import select
import signal
import stat
import time
import unittest
import urllib.parse
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.store import state
from tests.harness import host

CLI = brand.CLI
APP = "fx-lite-secrets"  # tests/data/fx-lite-secrets over fixtures/fx-lite
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
CODE_LINE = re.compile(r"^[A-Za-z0-9_-]{16}$", re.M)  # fx-lite's single-use bootstrap code
TOKEN_LINE = re.compile(r"^setup-token: ([A-Za-z0-9_-]{24})$", re.M)
OP_DIR = re.compile(r"([0-9]+)-([a-z-]+)")
PROMPT = b"New password: "
# A helper container walks the Docker root (bound read-only at /dr) on its own filesystem only (no container rootfs
# mounts) and prints [path, index] for each file that holds one of the values read from stdin.
SCAN = """import json, os, stat, sys
pats = [p.encode() for p in sys.stdin.read().split("\\n") if p]
dev, hold, hits = os.lstat("/dr").st_dev, max(map(len, pats)) - 1, set()
for d, dirs, files in os.walk("/dr"):
    keep = []
    for x in dirs:
        try:
            if os.lstat(os.path.join(d, x)).st_dev == dev:
                keep.append(x)
        except OSError:
            pass
    dirs[:] = keep
    for f in files:
        p = os.path.join(d, f)
        try:
            if not stat.S_ISREG(os.lstat(p).st_mode):
                continue
            with open(p, "rb") as fh:
                tail = b""
                while chunk := fh.read(1 << 22):
                    buf = tail + chunk
                    hits |= {(p[3:], i) for i, x in enumerate(pats) if x in buf}
                    tail = buf[-hold:]
        except OSError:
            continue
print(json.dumps(sorted(hits)))
"""
H: host.ScratchHost
NAME = f"itk{secrets.token_hex(3)}"  # k: the key canary (its- is the session suite)
SEED: dict[str, str] = {}  # secret values "env", "file" and "throwaway" (the drill's); "commit": the deployed one
TOKENS: list[str] = []  # terminal-only values: bootstrap code, setup token, typed password
REFUSED: list[str] = []  # the parts of a secret value the env file cannot hold
OUTPUTS: list[str] = []  # every CLI output of this module


def setUpModule() -> None:
    global H
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    H = host.ScratchHost("sec")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()


def forms(value: str) -> list[str]:
    """A secret value and its URL-encoded form (what the runner's redactor masks)."""
    return list(dict.fromkeys([value, urllib.parse.quote(value, safe="")]))


def cli(*args: str, tty: bool = False, answer: str | None = None) -> host.Result:
    res = H.cli(*args, tty=tty, answer=answer)
    OUTPUTS.append(res[1] + res[2])
    return res


def converse(args: list[str], steps: list[tuple[bytes, Callable[[str], str]]], timeout: float = 600) -> tuple[int, str]:
    """The wrapper with `args` on a pty: at each prompt (in order) `act(output so far)` runs while the command waits,
    and its answer is typed. Returns (exit, output with line ends normalized)."""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execvpe("sh", ["sh", H.wrapper, *args], host.ENV)
        finally:
            os._exit(127)
    out, seen, todo, end = b"", 0, list(steps), time.monotonic() + timeout
    try:
        while True:
            if todo and (at := out.find(todo[0][0], seen)) >= 0:
                prompt, act = todo.pop(0)
                seen = at + len(prompt)
                os.write(fd, act(out.decode(errors="replace").replace("\r\n", "\n")).encode() + b"\r")
                continue
            if time.monotonic() > end:
                os.kill(pid, signal.SIGKILL)
                break
            if not select.select([fd], [], [], 1)[0]:
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:  # EIO: the command exited
                break
            if not chunk:
                break
            out += chunk
    finally:
        os.close(fd)
    text = out.decode(errors="replace").replace("\r\n", "\n")
    OUTPUTS.append(text)
    return os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), text


def docker_root(values: list[str]) -> list[tuple[str, int]]:
    """(path under the daemon's Docker root, index into `values`) of each file holding a value. The values reach the
    helper on its stdin only, which no logging driver keeps (never argv, which the daemon stores)."""
    top = host.docker("info", "--format", "{{.DockerRootDir}}").strip()
    out = host.docker("run", "--rm", "-i", "--pull", "never", "--network", "none", "--log-driver", "none",
                      "--label", f"{host.SCRATCH}=docker-root-scan", "-v", f"{top}:/dr:ro", "--entrypoint", "python3",
                      host.BASE_IMAGE, "-I", "-c", SCAN, stdin="\n".join(values) + "\n")  # fmt: skip
    return [(p, i) for p, i in json.loads(out)]


def files_with(values: Iterable[str], skip: Callable[[str], set[str]] = lambda p: set()) -> list[str]:
    """Files under the roots holding one of `values`, except the values `skip(path)` allows in that file."""
    found = []
    for top in (H.root, H.backups):
        for d, _, files in os.walk(top):
            for f in files:
                p = os.path.join(d, f)
                try:
                    data = b"" if os.path.islink(p) else Path(p).read_bytes()
                except FileNotFoundError:  # a running app's own temporary file (SQLite -wal, -shm) went meanwhile
                    continue
                allowed = skip(p)
                found += [p for v in values if v not in allowed and v.encode() in data]
    return found


class Secrets(unittest.TestCase):
    maxDiff = None

    # observation ------------------------------------------------------------------------------------------------
    def last(self, kind: str) -> tuple[int, str]:
        """(seq, directory) of the newest operation of `kind`."""
        found = (OP_DIR.fullmatch(d) for d in os.listdir(H.layout.ops_dir(NAME)))
        seq = max(int(m[1]) for m in found if m and m[2] == kind)
        return seq, H.layout.op_dir(NAME, seq, kind)

    def run_tty(self, *args: str, answer: str | None = None, code: int = 0) -> str:
        res = cli(*args, tty=True, answer=answer)
        self.assertEqual(res[0], code, res[1])
        return res[1]

    def ok(self, *args: str) -> dict[str, Any]:
        res = cli(*args, "--json")
        self.assertEqual(res[0], 0, res)
        doc: dict[str, Any] = json.loads(res[1])
        return doc

    def no_trace(self, *args: str, code: int, why: str) -> None:
        """A refused command: its exit and code; nothing under instances/ or plans/, no Docker object changed."""
        self.assertTrue(host.wait_gone(brand.executor_name(NAME)))

        def seen() -> tuple[str, str, dict[str, list[tuple[str, ...]]]]:
            return host.tree_hash(H.layout.instances_dir), host.tree_hash(H.layout.plans_dir), host.inventory(NAME)

        before = seen()
        res = cli(*args, "--json")
        self.assertEqual((res[0], json.loads(res[1])["code"]), (code, why), res)
        self.assertEqual(seen(), before)

    def clean(self, values: list[str], what: str) -> None:
        """No file under the roots nor under the Docker root holds a terminal-only value (by index: never printed)."""
        self.assertEqual(files_with(values), [], f"{what}: under the roots")
        self.assertEqual(docker_root(values), [], f"{what}: under the Docker root")

    # the suite ----------------------------------------------------------------------------------------------------
    def test_0_scan_sees_container_logs(self) -> None:
        """The Docker root scan is not vacuous: a value a container printed is found in its log file."""
        code = "import secrets; print('control', secrets.token_hex(16))"
        cid = host.docker("run", "-d", "--label", f"{host.SCRATCH}=scan-control", "--entrypoint", "python3",
                          host.BASE_IMAGE, "-c", code).strip()  # fmt: skip
        try:
            host.docker("wait", cid)
            [value] = re.findall(r"^control ([0-9a-f]{32})$", host.docker("logs", cid), re.M)
            hits = docker_root([value])
            self.assertTrue(hits and all(p.startswith(f"/containers/{cid}/") for p, _ in hits), hits)
        finally:
            host.docker("rm", "-f", cid, check=False)

    def test_1_install_and_bootstrap_code(self) -> None:
        [a] = H.fixture_repo(APP, [{}], base="fx-lite")
        SEED["commit"] = a
        port = host.free_port()
        lines = ["instance = 1", f'name = "{NAME}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
        lines += [f'repo = "{H.repo_url(APP)}"', "[params]", f'FXLITE_IMAGE = "{H.image}"', f'FXLITE_PORT = "{port}"']
        lines += ["[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items())]
        cfg = H.inbox(f"{NAME}.toml", "\n".join(lines) + "\n")
        out = self.run_tty("init", NAME, "--config", cfg, "--ref", a, answer=NAME)
        self.assertIn("secrets.canary: generated", out)
        sdir = H.layout.secrets_dir(NAME)
        self.assertEqual(stat.S_IMODE(os.stat(f"{sdir}/canary").st_mode), 0o444)  # the manifest's mode
        SEED["file"] = Path(sdir, "canary").read_text()
        self.assertRegex(SEED["file"], r"\A[A-Za-z0-9]{32}\Z")
        SEED["env"] = f"Cn{secrets.token_hex(8)}/+@ %&={secrets.token_hex(8)}"  # URL-encoding changes it
        Path(sdir, "env", "MAIL_PASSWORD").write_text(SEED["env"])
        os.chmod(f"{sdir}/env/MAIL_PASSWORD", 0o600)

        out = self.run_tty("deploy", NAME, a, answer=NAME, code=4)  # the first install stops at its pause
        self.assertIn(f"next: {CLI} resume {NAME}", out)
        out = self.run_tty("task", NAME, "bootstrap-new-code", answer=NAME)  # allowed in the pause, on a terminal
        [code] = CODE_LINE.findall(out)
        TOKENS.append(code)
        self.clean([code], "the bootstrap code")
        self.run_tty("resume", NAME, answer=NAME)
        self.assertEqual(H.record(NAME)["state"], "running")

    def test_2_terminal_stdin_task(self) -> None:
        # without a terminal, and unattended: refused before anything is written (class B: only the terminal rule)
        self.no_trace("task", NAME, "canary-prompt", code=2, why="no-tty")
        self.no_trace("scheduled", "task", NAME, "canary-prompt", code=2, why="unattended")
        self.no_trace("scheduled", "task", NAME, "bootstrap-new-code", code=2, why="unattended")

        password = f"pw-{secrets.token_urlsafe(18)}"
        seen: dict[str, Any] = {}

        def at_prompt(text: str) -> str:
            """While the task waits at its prompt: its container, the CLI container and the Docker root (an error
            is kept for after the command, which still gets its answer)."""
            try:
                [seen["token"]] = TOKEN_LINE.findall(text)
                role, own = brand.label("role"), brand.label("instance")
                mine, end = ["--filter", f"label={role}=task", "--filter", f"label={own}={NAME}"], time.monotonic() + 30
                while not (ids := host.docker("ps", "-aq", *mine)) and time.monotonic() < end:  # listed a moment later
                    time.sleep(0.5)
                seen["task"] = host.inspect("container", ids.split())
                ids = host.docker("ps", "-q", "--filter", f"label={role}=cli")
                clis = host.inspect("container", ids.split())  # other suites' CLI containers bind other roots
                seen["cli"] = [c for c in clis if H.root in (m["Source"] for m in c["Mounts"])]
                seen["root"] = docker_root([seen["token"]])
            except Exception as e:  # reported after the command ends; the prompt must still get its answer
                seen["error"] = e
            return password

        code, out = converse(["task", NAME, "canary-prompt"], [(PROMPT, at_prompt)])
        self.assertNotIn("error", seen)
        self.assertEqual(code, 0)
        token = seen["token"]
        TOKENS.extend([token, password])
        self.assertEqual(seen["root"], [], "the setup token under the Docker root while the task waited")
        self.assertIn("stdin-tty: True\n", out)
        self.assertNotIn("Warning", out)  # getpass controlled the terminal: no "password may be echoed"
        self.assertNotIn(password, out)  # typed with echo disabled
        self.assertIn(f"received {len(password)} {hashlib.sha256(password.encode()).hexdigest()[:16]}\n", out)
        seq, _ = self.last("task")
        [task] = seen["task"]
        self.assertEqual(task["Name"], f"/{NAME}-x{seq}-1-a1")
        self.assertEqual((task["Config"]["Tty"], task["Config"]["OpenStdin"]), (True, True))  # no -T: the TTY
        self.assertEqual(task["HostConfig"]["LogConfig"]["Type"], "none")  # terminal output is never kept
        [cli_c] = seen["cli"]
        self.assertEqual((cli_c["Config"]["Tty"], cli_c["HostConfig"]["LogConfig"]["Type"]), (True, "none"))
        configs = json.dumps([task["Config"], cli_c["Config"]])  # argv and env of both containers
        self.assertFalse([v for k in ("env", "file") for v in forms(SEED[k]) if v in json.dumps(cli_c["Config"])])
        self.assertFalse([v for v in forms(SEED["file"]) if v in configs])  # a file secret is never argv or env
        self.clean([token, password], "the setup token or the typed password")
        result = state.read_doc(f"{self.last('task')[1]}/result.json", "result")
        self.assertEqual(result["outcome"], "completed", result)

    def test_3_captured_text_is_redacted(self) -> None:
        mask = "leak-out *** *** ***\n"  # the env secret, its URL-encoded form and the file secret
        self.ok("task", NAME, "canary-record")  # class B, record: stored 0600 in reports/ and the artifacts
        seq, d = self.last("task")
        art, rep = f"{d}/artifacts/1-a1-canary-record.out", f"{H.layout.reports_dir(NAME)}/{seq}-1-a1-canary-record.out"
        self.assertEqual((Path(art).read_text(), Path(rep).read_text()), (mask, mask))
        self.assertEqual((stat.S_IMODE(os.stat(art).st_mode), stat.S_IMODE(os.stat(rep).st_mode)), (0o600, 0o600))
        self.ok("task", NAME, "canary-json")  # json: parsed after redaction; `expect` still holds
        _, d = self.last("task")
        doc = json.loads(Path(f"{d}/artifacts/1-a1-canary-json.out").read_text())
        self.assertEqual(doc, {"outcome": "ok", "p": "***", "q": "***", "f": "***"})
        self.ok("task", NAME, "canary-long")  # the redactor's held-back tail across the stream's read edges
        _, d = self.last("task")
        lines = Path(f"{d}/artifacts/1-a1-canary-long.out").read_text().splitlines()
        self.assertEqual(lines, ["x" * (65536 - 3 * i) + "***" for i in range(14)])

        [cid] = [c[0] for c in host.inventory(NAME)["containers"] if c[1] == f"{NAME}-app-1"]
        [live] = host.inspect("container", [cid])
        shown = json.dumps([live["Config"][k] for k in ("Cmd", "Entrypoint", "Labels")] + [live["HostConfig"]])
        self.assertFalse([v for k in ("env", "file") for v in forms(SEED[k]) if v in shown])  # only its env has one
        raw = host.docker("logs", cid)
        self.assertIn(SEED["env"], raw)  # the app really logs both values, so the masks below are redactions
        self.assertIn(SEED["file"], raw)
        self.assertIn(f"{NAME}-app-1 | canary-log *** ***", cli("logs", NAME, "app")[1])
        logs = self.ok("logs", NAME, "app")["logs"]
        self.assertIn("canary-log *** ***\n", logs[0]["stdout"])
        for args in (("status", NAME), ("doctor", NAME), ("ps", NAME), ("history", NAME), ("bundles", NAME)):
            cli(*args)
            cli(*args, "--json")
        cli("list")
        cli("status")

    def test_4_bundle_payload_is_byte_identical(self) -> None:
        self.run_tty("task", NAME, "canary-stash", answer=NAME)  # app-write, class C: the app stores the values
        gen = f"g{H.record(NAME)['generations']['data']}"
        data = Path(H.layout.data_gen(NAME, "data", gen), "files", "canary.bin").read_bytes()
        self.assertTrue(all(v.encode() in data for k in ("env", "file") for v in forms(SEED[k])))
        self.ok("backup", NAME)
        [bundle] = self.ok("bundles", NAME)["bundles"]
        bdir = H.layout.bundle_dir(NAME, bundle["id"])
        [copy] = list(Path(bdir, "payload").glob("*/files/canary.bin"))
        self.assertEqual(copy.read_bytes(), data)  # byte-exact: never redacted
        rel, digest = str(copy.relative_to(bdir)), hashlib.sha256(data).hexdigest()
        self.assertIn(f"{digest}  {rel}", Path(bdir, "SHA256SUMS").read_text().splitlines())
        doc = json.loads(Path(bdir, "bundle.json").read_bytes())
        sealed = [f for f in doc["payload"]["files"] if rel.endswith(f"/{f['path']}") or rel == f["path"]]
        self.assertEqual([(f["size"], f["sha256"]) for f in sealed], [(len(data), digest)], doc["payload"])
        written = [Path(bdir, "bundle.json"), Path(bdir, "SHA256SUMS"), *Path(bdir, "meta").rglob("*")]
        self.assertTrue(any(p.name == brand.MANIFEST_FILE for p in written))
        values = [v for k in ("env", "file") for v in forms(SEED[k])]
        leaks = [str(p) for p in written if p.is_file() and any(v.encode() in p.read_bytes() for v in values)]
        self.assertEqual(leaks, [], "seeded values in the bundle's Ingat-written files")

        self.ok("verify", NAME, "--latest", "--restore-test")  # the drill restores the file into isolation
        _, d = self.last("drill")
        if os.path.exists(f"{d}/secrets/canary"):  # the drill's throwaway value of the file secret
            SEED["throwaway"] = Path(d, "secrets", "canary").read_text()
            self.assertNotEqual(SEED["throwaway"], SEED["file"])
        isolated = Path(d, "env", "isolated.env").read_text()
        self.assertNotIn("MAIL_PASSWORD", isolated)  # secret keys are dropped from isolated runs
        self.assertIn("ALLOWED_ORIGINS=", isolated)

    def test_5_failure_message_is_redacted(self) -> None:
        res = cli("task", NAME, "canary-fail", "--json")
        self.assertEqual((res[0], json.loads(res[1])["code"]), (3, "task-failed"), res)
        _, d = self.last("task")
        result = state.read_doc(f"{d}/result.json", "result")
        self.assertIn("leak-err *** *** ***", result["message"])  # the stderr tail reached the error, masked
        self.assertEqual(Path(d, "artifacts", "1-a1-canary-fail.out").read_text(), "leak-out *** *** ***\n")
        res = cli("task", NAME, "canary-fail")  # the human answer prints the message
        self.assertEqual(res[0], 3, res)
        self.assertIn("leak-err *** *** ***", res[1] + res[2])
        res = cli("scheduled", "task", NAME, "canary-fail")  # unattended: a redacted summary on failure
        self.assertEqual(res[0], 3, res)
        self.assertIn("leak-err *** *** ***", res[1] + res[2])
        res = cli("status", NAME, "--json")
        self.assertIn("last-op-failed", json.loads(res[1])["attention"], res)

        # a secret value the env file cannot hold: refused by its key, the value never echoed, nothing written
        path = Path(H.layout.secrets_dir(NAME), "env", "MAIL_PASSWORD")
        halves = [secrets.token_hex(6), secrets.token_hex(6)]
        REFUSED.extend(halves)
        path.write_text("'".join(halves))
        try:
            self.no_trace("deploy", NAME, SEED["commit"], code=1, why="invalid-value")
            self.assertIn("MAIL_PASSWORD", OUTPUTS[-1])
            cli("doctor", NAME)
            cli("status", NAME, "--json")
            self.assertFalse([x for x in OUTPUTS[-3:] for h in halves if h in x], "a refused secret value echoed")
        finally:
            path.write_text(SEED["env"])

    def test_6_sweep(self) -> None:
        """Every seeded value is only where it belongs; no CLI output of this module holds one."""
        self.assertTrue(SEED.keys() >= {"env", "file"} and len(TOKENS) == 3, "an earlier test did not run")
        env, file = forms(SEED["env"]), forms(SEED["file"])
        throwaway = forms(SEED["throwaway"]) if "throwaway" in SEED else []
        secrets_dir, env_dir = H.layout.secrets_dir(NAME) + "/", H.layout.env_dir(NAME) + "/"

        def allowed(p: str) -> set[str]:
            if p.startswith(secrets_dir) or os.path.basename(p) == "canary.bin":  # the secret files; the app's data
                return {*env, *file, *throwaway}
            if p.startswith(env_dir):  # the rendered app env files hold the app env secret
                return set(env)
            if re.fullmatch(rf"{re.escape(H.layout.ops_dir(NAME))}/[0-9]+-drill/secrets/canary", p):
                return set(throwaway)
            return set()

        self.assertEqual(files_with([*env, *file, *throwaway, *TOKENS, *REFUSED], allowed), [])
        rendered = [Path(env_dir, f) for f in os.listdir(env_dir)]
        self.assertTrue(rendered and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in rendered), rendered)
        self.assertTrue(any(f"MAIL_PASSWORD='{SEED['env']}'".encode() in p.read_bytes() for p in rendered))
        for text in OUTPUTS:
            for v in (*env, *file, *throwaway, *REFUSED):
                self.assertNotIn(v, text)
        # the file secret reaches containers by a bind mount only: under the Docker root it is in no container
        # config or runtime spec (argv, env), only in the log of the live app that printed it
        hits = sorted({p for p, _ in docker_root(file)})
        self.assertTrue(hits, "the live app's log holds the file secret it printed")
        self.assertTrue(all(re.fullmatch(r"/containers/[0-9a-f]{64}/.*log.*", p) for p in hits), hits)


if __name__ == "__main__":
    unittest.main()
