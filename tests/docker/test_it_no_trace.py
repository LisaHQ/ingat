"""Suite 2, no trace (ARCHITECTURE §10.3; LIFECYCLE F2, F9, §3.1, §6): every refusal path M1 reaches and every
read-only command, through the real wrapper of a scratch host that the release's install.sh installed and certified.

Each case observes the host before and after one command: the INGAT_ROOT and INGAT_BACKUPS trees (path, type, mode,
size, content), the Docker inventory (containers with their state and start time, networks, volumes) and the daemon's
events in the command's window. A refusal and a read-only command leave all of it unchanged except:
`cache/` (planning's content-addressed caches, ARCHITECTURE §5.3); the lock holder files (`lock.holder.json`, F2, and
`host.lock.holder.json`); the approved plan and the run file a refusal inside a started executor adds (`plans/<hash>`,
written once, LIFECYCLE §3.1; `host/runs/<run-id>`; a foreground terminal task saves its plan too); the certification
of `host check` and the `host/attention.json` of `scheduled status` (LIFECYCLE §2, §4.15); the content of bind-store
generations, which the live app writes. Events allowed: those of the command's own `role=cli` container, of the
`role=exec` executor it starts, and probe execs. In a CI lane (INGAT_TEST_LANE set: one test process per daemon) the
whole daemon counts; on a shared local daemon only the objects and events of this suite's instances and projects do.

Instances: L (fx-lite, installed, resumed, one verified bundle), P (fx-lite, its install paused: an open operation),
R (fx-lite, registered only, `source.accept` set) and X (never created). Commits of the fixture repository: A, B and N
(no Compose change), PRIV (`privileged: true`, refused by the policy) and INCL (`include:`, refused before Compose).
"""

import atexit
import contextlib
import fcntl
import functools
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
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ingat import brand
from tests.harness import host

STRICT = bool(os.environ.get("INGAT_TEST_LANE"))
ROLE, INSTANCE, PROJECT = brand.label("role"), brand.label("instance"), "com.docker.compose.project"
HOLDERS = ("lock.holder.json", "host.lock.holder.json")
GEN = re.compile(r"data/[^/]+/[^/]+/[gt][0-9]+")  # a bind-store generation: the app's own content
EXECUTED = (r"\+ plans/[0-9a-f]+\.json", r"\+ host/runs/[0-9a-f]+\.json")  # the approved plan, the run file
PROBES = ("exec_create", "exec_start", "exec_die", "exec_detach", "health_status")
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
UNTESTED = [{"engine": "0.0", "arch": "none", "cli": "0", "compose": "0"}]
H: host.ScratchHost
L = P = R = X = A = B = N = PRIV = INCL = ""
NAMES: list[str] = []
PORT: dict[str, int] = {}
EXTRA: tuple[str, ...] = ()  # more name prefixes owned while a case runs (the selftest's instances)


def setUpModule() -> None:
    global H, L, P, R, X, A, B, N, PRIV, INCL
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    H = host.ScratchHost("nt")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()
    compose = (host.REPO / "fixtures" / "fx-lite" / "compose.yaml").read_text()
    priv = compose.replace("    read_only: true\n", "    read_only: true\n    privileged: true\n", 1)
    incl = {"compose.yaml": "include:\n  - extra.yaml\n" + compose, "extra.yaml": "services: {}\n"}
    edits: list[dict[str, str | bytes | None]] = [{}, {"CHANGES": "B\n"}, {"CHANGES": "N\n"}, {"compose.yaml": priv}]
    A, B, N, PRIV, INCL = H.fixture_repo("fx-lite", [*edits, incl])
    L, P, R, X = NAMES[:] = [f"nt{c}{secrets.token_hex(3)}" for c in "lprx"]
    while len(set(PORT.values())) < len(NAMES):
        PORT.update((n, host.free_port()) for n in NAMES)
    must("init", L, "--config", config(L), "--ref", A, answer=L)
    must("deploy", L, A, answer=L, code=4)  # the first install pauses for the owner's bootstrap
    must("resume", L, answer=L)
    must("backup", L)
    must("init", P, "--config", config(P), "--ref", A, answer=P)
    must("deploy", P, A, answer=P, code=4)  # P stays paused: its install is an open operation
    must("init", R, "--config", config(R, accept="[0-9a-f]{40}"), "--ref", A, answer=R)
    must("prepare", L, B)
    must("prepare", L, PRIV)


def must(*args: str, answer: str | None = None, code: int = 0) -> None:
    res = H.cli(*args, tty=answer is not None, answer=answer)
    if res[0] != code:
        raise AssertionError(f"{' '.join(args)} exited {res[0]}, not {code}:\n{res[1]}{res[2]}")


def config(name: str, *, port: int = 0, accept: str = "", named: str = "") -> str:
    """An owner's instance.toml in the inbox; [app_env] comes last, so a line appended to it joins that table."""
    lines = ["instance = 1", f'name = "{named or name}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
    lines += [f'repo = "{H.repo_url("fx-lite")}"', *([f"accept = '{accept}'"] if accept else []), "[params]"]
    lines += [f'FXLITE_IMAGE = "{H.image}"', f'FXLITE_PORT = "{port or PORT[name]}"', "[app_env]"]
    lines += [f'{k} = "{v}"' for k, v in APP_ENV.items()]
    return H.inbox(f"{name}-{secrets.token_hex(3)}.toml", "\n".join(lines) + "\n")


def pty_run(argv: list[str], answer: str | None, at_prompt: Callable[[], None] | None = None) -> host.Result:
    """`argv` on a pty (stdout and stderr merged); at the first approval prompt `at_prompt` runs, then `answer` (or an
    empty line) is typed."""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.execvpe(argv[0], argv, host.ENV)
        finally:
            os._exit(127)
    out, sent, end = b"", False, time.monotonic() + 900
    try:
        while time.monotonic() < end:
            if not select.select([fd], [], [], 1)[0]:
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:  # EIO: the command exited
                break
            if not chunk:
                break
            out += chunk
            if not sent and host.PROMPT in out:
                if at_prompt:
                    at_prompt()
                os.write(fd, (answer or "").encode() + b"\r")
                sent = True
        else:  # timed out
            os.kill(pid, signal.SIGKILL)
    finally:
        os.close(fd)
    code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
    return code, out.decode(errors="replace").replace("\r\n", "\n"), ""


def answer_doc(text: str) -> dict[str, Any]:
    """The JSON answer: the last object printed (on a pty it follows the plan summary and the prompt)."""
    lines = text.splitlines()
    start = max((i for i, x in enumerate(lines) if x == "{"), default=len(lines))
    return dict(json.loads("\n".join(lines[start:]) or "{}"))


@contextlib.contextmanager
def wrapper(**swap: str) -> Iterator[str]:
    """A copy of the installed wrapper with whole substrings swapped (another image, another mount): the same host
    seen by another tool image or with another filesystem at a mount point."""
    text = Path(H.wrapper).read_text()
    for old, new in swap.items():
        if text.count(old) != 1:
            raise AssertionError(f"{H.wrapper}: {old!r} is not where the suite expects it")
        text = text.replace(old, new)
    path = f"{H.base}/variant-{secrets.token_hex(4)}.sh"
    Path(path).write_text(text)
    try:
        yield path
    finally:
        os.remove(path)


@contextlib.contextmanager
def held(path: str) -> Iterator[None]:
    """Hold the flock of a lock file the way another process of the host would (the runner shares its kernel)."""
    with open(path, "rb") as f:  # closing it releases the lock
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def settle(host_exec: bool = False) -> None:
    """Wait until no executor of this suite's instances (and of the host, when asked) exists any more."""
    names = {brand.executor_name(n) for n in NAMES} | ({brand.executor_name(None)} if host_exec else set())
    end = time.monotonic() + 180
    while names & set(host.docker("ps", "-a", "--format", "{{.Names}}", "--filter", f"label={ROLE}=exec").split()):
        if time.monotonic() > end:
            raise AssertionError("an executor did not go away")
        time.sleep(0.5)


def tree(top: str, skip: tuple[str, ...] = ()) -> dict[str, tuple[Any, ...]]:
    """relative path -> (type, mode, owner, size, sha256 | link target) of everything below `top`, lock holder files
    and the top-level names in `skip` left out; a bind-store generation is listed without its content."""
    out: dict[str, tuple[Any, ...]] = {}
    for d, dirs, files in os.walk(top):
        rel = os.path.relpath(d, top)
        keep = []
        for name in sorted(dirs + files):
            path, sub = os.path.join(d, name), os.path.normpath(os.path.join(rel, name))
            if sub in skip or name in HOLDERS:
                continue
            st = os.lstat(path)
            mode = stat.S_IMODE(st.st_mode)
            if stat.S_ISLNK(st.st_mode):
                out[sub] = ("link", os.readlink(path))
            elif stat.S_ISDIR(st.st_mode):
                out[sub] = ("dir", mode, st.st_uid, st.st_gid)
                keep += [] if GEN.fullmatch(sub) else [name]
            elif stat.S_ISREG(st.st_mode):
                digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                out[sub] = ("file", mode, st.st_uid, st.st_gid, st.st_size, digest)
            else:
                out[sub] = ("other", stat.S_IFMT(st.st_mode), mode)
        dirs[:] = [x for x in dirs if x in keep]
    return out


def owned(name: str, labels: dict[str, str]) -> bool:
    """Whether a Docker object is this suite's (in a CI lane: any object counts)."""
    if STRICT or labels.get(INSTANCE) in NAMES or labels.get(PROJECT, "").split("--")[0] in NAMES:
        return True
    return name.startswith(tuple(f"{n}{sep}" for n in NAMES for sep in "-_") + EXTRA)


def inventory() -> dict[str, list[tuple[Any, ...]]]:
    """The Docker objects this suite counts; a CLI container (the command's own, waiting at a prompt) is not one."""
    ids = host.docker("ps", "-aq", "--no-trunc").split()
    containers = [
        (c["Id"], c["Name"], c["State"]["Status"], c["State"]["StartedAt"], c["Image"], c.get("RestartCount"))
        for c in host.inspect("container", ids)
        if owned(c["Name"].lstrip("/"), labels := c["Config"].get("Labels") or {}) and labels.get(ROLE) != "cli"
    ]
    nets = [x.split() for x in host.docker("network", "ls", "--no-trunc", "--format", "{{.ID}} {{.Name}}").splitlines()]
    vols = host.docker("volume", "ls", "-q").split()
    networks, volumes = sorted((i, n) for i, n in nets if owned(n, {})), sorted((v,) for v in vols if owned(v, {}))
    return {"containers": sorted(containers), "networks": networks, "volumes": volumes}


def observe() -> dict[str, Any]:
    return {"root": tree(H.root, ("cache",)), "backups": tree(H.backups), "docker": inventory()}


def changes(a: dict[str, tuple[Any, ...]], b: dict[str, tuple[Any, ...]]) -> list[str]:
    out = [f"+ {p}" for p in sorted(b.keys() - a.keys())] + [f"- {p}" for p in sorted(a.keys() - b.keys())]
    return out + [f"~ {p}" for p in sorted(a.keys() & b.keys()) if a[p] != b[p]]


def strays(since: str, until: str, executor: bool) -> list[str]:
    """Events of the window other than those of the command's CLI container, of an executor it started (`executor`)
    and of probes; network and volume events count with the container they name."""
    evs = [e for e in host.events(since, until) if e.get("Type") in ("container", "network", "volume", "image")]
    ok = {"cli", *(["exec"] if executor else [])}
    own = {e["Actor"]["ID"] for e in evs if e["Type"] == "container" and e["Actor"]["Attributes"].get(ROLE) in ok}
    out = []
    for e in evs:
        actor, action = e.get("Actor") or {}, str(e.get("Action", "")).split(":")[0]
        attrs = actor.get("Attributes") or {}
        name = actor.get("ID", "") if e["Type"] == "volume" else attrs.get("name", "")
        if action in PROBES or actor.get("ID") in own or attrs.get("container") in own or not owned(name, attrs):
            continue
        out.append(f"{e['Type']} {e['Action']} {name or actor.get('ID', '')[:12]} role={attrs.get(ROLE)}")
    return out


def plant(name: str, *labels: str) -> None:
    """A container this tool did not make (scratch-labelled for the harness's cleanup), never started."""
    host.docker("create", "--name", name, *(f"--label={x}" for x in (*labels, f"{host.SCRATCH}=1")), H.image)


def shown(res: host.Result) -> str:
    return f"exit {res[0]}\n{res[1][-4000:]}{res[2][-2000:]}"


class NoTrace(unittest.TestCase):
    maxDiff = None

    def case(self, *args: str, exit: int | tuple[int, ...], code: str | None = None, **kw: Any) -> dict[str, Any]:
        """One command, observed. Options: `answer` (typed at the prompt, on a pty), `tty`, `executor` / `host_exec`
        (an instance / the host executor may run), `adds` (allowed changes: regexes over `+ path`, `~ path`),
        `wrapper`, `change` (run at the prompt, before the window opens), `json` (default True), `extra` (prefixes)."""
        global EXTRA
        doc: dict[str, Any] = {}
        exits = (exit,) if isinstance(exit, int) else exit
        with self.subTest(" ".join(args)):
            EXTRA = kw.get("extra", ())
            try:
                res, doc, problems = self.observed(args, kw)
            finally:
                EXTRA = ()
            wrong = code is not None and doc.get("code") != code
            if res[0] not in exits or (kw.get("json", True) and doc.get("exit") != res[0]) or wrong:
                problems.insert(0, f"expected exit {exits} code {code}; got {res[0]} code {doc.get('code')}")
            self.assertEqual(problems, [], shown(res))
        return doc

    def observed(self, args: tuple[str, ...], kw: Any) -> tuple[host.Result, dict[str, Any], list[str]]:
        """(result, JSON answer, every trace the command left) for the options of `case`."""
        as_json, change, host_exec = kw.get("json", True), kw.get("change"), kw.get("host_exec", False)
        executor = kw.get("executor", False) or host_exec
        argv = ["sh", kw.get("wrapper") or H.wrapper, *args, *(["--json"] if as_json else [])]
        seen: dict[str, Any] = {}

        def mark() -> None:
            if change:
                change()
            settle(host_exec)
            seen.update(before=observe(), since=host.now())

        if change is None:
            mark()
        if kw.get("tty") or kw.get("answer") is not None or change:
            res = pty_run(argv, kw.get("answer"), mark if change else None)
        else:
            res = host.run(argv)
        settle(host_exec)
        until, after = host.now(), observe()
        self.assertIn("before", seen, f"no approval prompt:\n{shown(res)}")
        problems, before = list[str](), seen["before"]
        doc = answer_doc(res[1]) if as_json else {}
        allowed = (*EXECUTED, *kw.get("adds", ())) if executor else kw.get("adds", ())
        problems += [f"root: {c}" for c in changes(before["root"], after["root"])
                     if not any(re.fullmatch(a, c) for a in allowed)]  # fmt: skip
        problems += [f"backups: {c}" for c in changes(before["backups"], after["backups"])]
        for kind in ("containers", "networks", "volumes"):
            if before["docker"][kind] != after["docker"][kind]:
                problems.append(f"docker {kind}: {before['docker'][kind]} -> {after['docker'][kind]}")
        problems += [f"event: {e}" for e in strays(seen["since"], until, executor)]
        return res, doc, problems

    # the observation itself -----------------------------------------------------------------------------------
    def test_0_a_change_is_seen(self) -> None:
        """The observation is not blind: a completed restart of L shows in the instance tree, in the inventory (a new
        start time) and in the events (the app container stopped and started)."""
        res, doc, problems = self.observed(("restart", L, "app"), {"answer": L, "executor": True})
        self.assertEqual((res[0], doc.get("code")), (0, "completed"), shown(res))
        self.assertIn(f"root: ~ instances/{L}/record.json", problems)
        self.assertTrue(any(p.startswith("root: + instances/") and "-restart/" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("docker containers: ") for p in problems), problems)
        self.assertTrue(any(re.match(rf"event: container (stop|die|start) {L}-app-1 role=app", p) for p in problems))

    # read-only ------------------------------------------------------------------------------------------------
    def test_1_read_only(self) -> None:
        """Diagnostics never write (F9) and change nothing in Docker; neither does any other read-only answer."""
        src = H.layout.cache_src(A)
        exit: int | tuple[int, ...]
        for args, exit, code in (
            (("version",), 0, "ok"), (("status",), 5, "attention"), (("list",), 0, "ok"),
            *(((c, n), e, None) for c in ("status", "doctor") for n, e in ((L, (0, 5)), (P, 5), (R, (0, 5)))),
            *(((c, n), 0, "ok") for c in ("ps", "history", "bundles") for n in (L, P, R)),
            *((a, 0, "ok") for a in (("logs", L, "app"), ("logs", L, "app", "--since", "1h"), ("logs", P, "app"))),
            (("validate", src), 0, "valid"), (("validate", src, "--instance", H.layout.inst_toml(L)), 0, "valid"),
            (("attach", L), 0, "no-open-operation"), (("attach", P), 4, "open-operation"),
            (("prune", L, "--bundles"), 0, "dry-run"), (("selftest", "--offline"), 0, "ok"),
        ):  # fmt: skip
            self.case(*args, exit=exit, code=code)
        for args in (("status", L), ("doctor", P), ("list",), ("history", L), ("bundles", L), ("ps", P)):
            self.case(*args, exit=(0, 5), json=False)
        cert = r"\+ host/certifications/[^/]+-host-check(-[0-9]+)?\.json"
        self.case("host", "check", exit=(0, 5), adds=(cert,))
        self.case("scheduled", "status", exit=(0, 5), adds=(r"[+~] host/attention\.json",))
        self.case("scheduled", "status", exit=0, code="unchanged")  # an unchanged set writes nothing at all

    # input, names and usage -------------------------------------------------------------------------------------
    def test_2_names_and_usage(self) -> None:
        """A bad instance name, an unknown instance or a bad command line refuses before anything (F1, F2)."""
        args: tuple[str, ...]
        cfg, nobody = config(X), f"nt{secrets.token_hex(4)}"
        for args in (("status", "Bad_Name"), ("deploy", "Bad", A), ("backup", "a--b"), ("cancel", "UPPER")):
            self.case(*args, exit=2, code="usage")
        self.case("stop", "x" * 31, answer="x" * 31, exit=2, code="usage")
        self.case("init", "a--b", "--config", cfg, "--ref", A, answer="a--b", exit=2, code="usage")
        for args in (
            ("deploy", nobody, A), ("prepare", nobody, A), ("backup", nobody), ("verify", nobody, "--latest"),
            ("task", nobody, "queue-held"), ("prune", nobody, "--bundles"), ("cancel", nobody), ("status", nobody),
            ("doctor", nobody), ("ps", nobody), ("logs", nobody, "app"), ("history", nobody), ("bundles", nobody),
            ("attach", nobody), ("scheduled", "backup", nobody),
        ):  # fmt: skip
            self.case(*args, exit=1, code="unknown-instance")
        for args in (("stop", nobody), ("start", nobody), ("resume", nobody), ("abandon", nobody)):
            self.case(*args, answer=nobody, exit=1, code="unknown-instance")
        for args in (
            (), ("apply", "0" * 12), ("deploy", L), ("plan", "deploy", L, A), ("backup", L, "--class", "bogus"),
            ("verify", L), ("verify", L, "x", "--latest"), ("task", L, "queue-release-job"),
            ("task", L, "queue-release-job", "--arg", "job"), ("logs", L, "app", "--since", "yesterday!"),
            ("selftest", "--host", "--offline"),
        ):  # fmt: skip
            self.case(*args, exit=2, code="usage")
        missing = f"{H.layout.inbox}/missing.toml"
        self.case("init", X, "--config", missing, "--ref", A, answer=X, exit=2, code="usage")

    # approval -------------------------------------------------------------------------------------------------
    def test_3_approval(self) -> None:
        """Class C without a terminal (exit 2) or with a wrong typed name (exit 1) changes nothing (F3, LIFECYCLE §2);
        a deploy without a candidate refuses before it prepares one."""
        args: tuple[str, ...]
        cfg = config(X)
        for args in (
            ("host", "init"), ("init", X, "--config", cfg, "--ref", A), ("deploy", L, B), ("stop", L), ("restart", L),
            ("stop", L, "app"), ("resume", P), ("abandon", P), ("task", L, "queue-release-all"),
            ("task", L, "bootstrap-new-code"), ("task", L, "queue-held"),
        ):  # fmt: skip
            self.case(*args, exit=2, code="no-tty")
            self.case(*args, answer="nope", exit=1, code="not-approved")
        for args in (("deploy", L, N), ("deploy", R, A)):  # no candidate yet: refused before it is prepared
            self.case(*args, exit=2, code="no-tty")

    # refusals at plan time ------------------------------------------------------------------------------------
    def test_4_plan_refusals(self) -> None:
        """Wrong state, bad tasks and arguments, refs, sources, the Compose policy, owner edits that this release
        refuses, init's checks and foreign objects: refused in the plan phase, before any effect (F2, F8)."""
        args: tuple[str, ...]
        for args in (("start", R), ("stop", R), ("restart", R), ("resume", L), ("abandon", L)):
            self.case(*args, answer=args[1], exit=1, code="wrong-state")
        for args, code in (
            (("backup", R), "wrong-state"), (("task", R, "queue-held"), "wrong-state"), (("cancel", L), "wrong-state"),
            (("verify", R, "--latest"), "no-bundle"), (("verify", L, "nosuch-bundle"), "no-bundle"),
            (("verify", R, "--latest", "--restore-test"), "no-bundle"),
            (("task", L, "nosuch"), "unknown-task"), (("task", L, "migrate"), "not-operator"),
            (("task", L, "backup"), "not-operator"), (("task", L, "restore"), "not-operator"),
            (("task", L, "queue-release-job", "--arg", "job=no/slash"), "invalid-arg"),
            (("task", L, "bootstrap-config", "--input", "config=missing.toml"), "missing-input"),
            (("task", L, "bootstrap-config", "--input", "config=../host.json"), "unsafe-path"),
            (("deploy", L, "nosuch-ref"), "invalid-ref"), (("prepare", L, "abc1234"), "invalid-ref"),
            (("deploy", R, "main"), "ref-not-accepted"), (("prepare", R, "main"), "ref-not-accepted"),
            (("prepare", L, INCL), "unsupported-source"), (("deploy", L, INCL), "unsupported-source"),
            (("deploy", L, PRIV), "policy"),
        ):  # fmt: skip
            self.case(*args, exit=1, code=code)
        self.case("deploy", L, PRIV, answer=L, exit=1, code="policy")  # refused before the prompt
        for args in (("scheduled", "task", L, "queue-release-all"), ("scheduled", "task", L, "bootstrap-new-code")):
            self.case(*args, exit=2, code="unattended")
        for args in (("start", L), ("deploy", L, A), ("prepare", L, A), ("prepare", L, B)):  # nothing to do
            self.case(*args, answer=L, exit=0, code="nothing-to-do")
        self.case("prune", L, "--bundles", "--apply", exit=0, code="nothing-to-do")

        # the owner's edits of instance.toml that this release refuses (LIFECYCLE §4.5; ARCHITECTURE §7.5)
        toml = Path(H.layout.inst_toml(L))
        original = toml.read_bytes()
        try:
            toml.write_bytes(original + b'DELIVERY_ENABLED = "true"\n')  # owner-gated: class D, which is M2
            self.case("deploy", L, A, exit=1, code="not-in-this-release")
            self.case("deploy", L, B, answer=L, exit=1, code="not-in-this-release")
            toml.write_bytes(original.replace(f'name = "{L}"'.encode(), b'name = "renamed"'))
            for args in (("deploy", L, A), ("backup", L), ("stop", L), ("status", L), ("doctor", L)):
                self.case(*args, exit=1, code="invalid-instance", tty=args[0] == "stop")
        finally:
            toml.write_bytes(original)

        # init's checks, all before its first write (LIFECYCLE §4.1)
        foreign = f"{X}-app-1"
        plant(foreign, f"{PROJECT}={X}")
        try:
            self.case("init", X, "--config", config(X), "--ref", A, answer=X, exit=1, code="foreign")
        finally:
            host.docker("rm", foreign)
        for cfg, ref, code in (
            (config(X, named="other"), A, "invalid-instance"), (config(X, port=PORT[L]), A, "port-conflict"),
            (config(X), "nosuch-ref", "invalid-ref"), (config(L), A, "exists"),
        ):  # fmt: skip
            name = L if code == "exists" else X
            self.case("init", name, "--config", cfg, "--ref", ref, answer=name, exit=1, code=code)

        # a foreign container in the live project: every plan that runs Compose on it refuses, nothing touches it
        foreign = f"{L}-intruder-1"
        plant(foreign, f"{PROJECT}={L}")
        try:
            for args in (("stop", L), ("restart", L, "app"), ("deploy", L, B)):
                self.case(*args, answer=L, exit=1, code="foreign")
            self.case("status", L, exit=5, code="attention")
        finally:
            host.docker("rm", foreign)

    # an open operation (F5) -----------------------------------------------------------------------------------
    def test_5_open_operation(self) -> None:
        """P's paused install blocks every other change, in the CLI or in the executor that re-checks (F5)."""
        args: tuple[str, ...]
        for args in (("stop", P), ("start", P), ("restart", P), ("task", P, "queue-held")):
            self.case(*args, answer=P, exit=2, code="open-operation")
        self.case("cancel", P, exit=1, code="wrong-state")  # a paused operation is resumed or abandoned
        self.case("backup", P, exit=1, code="wrong-state")
        self.case("prepare", P, B, exit=2, code="open-operation", executor=True)
        self.case("deploy", P, A, answer=P, exit=2, code="open-operation", executor=True)
        seq = H.record(P)["open_op"]["seq"]  # a live task container of the open operation (F15, ARCHITECTURE §4.5)
        task, labels = f"{P}-x{seq}-9-a1", {INSTANCE: P, brand.label("op"): str(seq), ROLE: "task", PROJECT: P}
        tags = [f"--label={k}={v}" for k, v in labels.items()]
        host.docker("run", "-d", "--name", task, *tags, "--entrypoint", "sleep", H.image, "900")
        try:
            for args in (("resume", P), ("abandon", P)):
                doc = self.case(*args, answer=P, exit=2, code="task-running")
                self.assertEqual(doc.get("next"), f"docker stop {task}")
        finally:
            host.docker("rm", "-f", task)

    # busy locks -----------------------------------------------------------------------------------------------
    def test_6_busy(self) -> None:
        """A busy instance or host lock, or a present executor container, refuses at once with exit 2 (ARCHITECTURE
        §4.2, §7.4)."""
        with held(H.layout.lock(L)):
            self.case("backup", L, exit=2, code="lock-busy", executor=True)
            self.case("prepare", L, N, exit=2, code="lock-busy", executor=True)
            self.case("stop", L, answer=L, exit=2, code="lock-busy", executor=True)
            plan = (r"\+ plans/[0-9a-f]+\.json",)  # a foreground terminal task saves its plan, then takes the lock
            self.case("task", L, "bootstrap-new-code", answer=L, exit=2, code="lock-busy", adds=plan)
        with held(H.layout.host_lock):
            self.case("init", X, "--config", config(X), "--ref", A, answer=X, exit=2, code="lock-busy")
            self.case("host", "init", answer=H.hostname, exit=2, code="lock-busy")
            with host.daemon_lock("host-executor"):
                pre = (brand.SELFTEST_PREFIX,)
                self.case("selftest", exit=2, code="lock-busy", host_exec=True, extra=pre)
        name = brand.executor_name(L)  # the executor's name is the second mutex: a present container refuses
        plant(name)
        try:
            self.case("backup", L, exit=2, code="executor-running", executor=True)
        finally:
            host.docker("rm", name)

    # capacity -------------------------------------------------------------------------------------------------
    def test_7_capacity(self) -> None:
        """Too little space refuses before any effect (LIFECYCLE §5.8): the CLI sees a 1 MiB tmpfs where the Docker
        root's probe volume, or the backups root, is mounted."""
        tiny = f"it-tiny-{secrets.token_hex(4)}"
        host.docker("volume", "create", "--label", f"{host.SCRATCH}=1", "--driver", "local", "--opt", "type=tmpfs",
                    "--opt", "device=tmpfs", "--opt", "o=size=1m,mode=0700", tiny)  # fmt: skip
        try:
            probe = f"-v {brand.PROBE_VOLUME}:{brand.PROBE_MOUNT}:ro"
            with wrapper(**{probe: f"-v {tiny}:{brand.PROBE_MOUNT}:ro"}) as w:
                for args in (("prepare", L, N), ("backup", L), ("verify", L, "--latest", "--restore-test")):
                    self.case(*args, exit=1, code="capacity", wrapper=w)
                self.case("deploy", L, B, answer=L, exit=1, code="capacity", wrapper=w)
            backups = f'-v "${brand.env("BACKUPS")}:${brand.env("BACKUPS")}"'
            with wrapper(**{backups: f'-v {tiny}:"${brand.env("BACKUPS")}"'}) as w:
                self.case("backup", L, exit=1, code="capacity", wrapper=w)
        finally:
            host.docker("volume", "rm", tiny)

    # the host's own state -------------------------------------------------------------------------------------
    def test_7b_host_state(self) -> None:
        """A daemon other than the one host.json records (F1), or a tool DOCKER_CONFIG that is not empty, refuses."""
        args: tuple[str, ...]
        doc, config_json = Path(H.layout.host_json), Path(H.layout.docker_config, "config.json")
        original = doc.read_bytes()
        engine = json.loads(original)["engine_id"]
        try:
            doc.write_bytes(original.replace(engine.encode(), b"0" * len(engine)))
            for args in (("backup", L), ("prepare", L, N)):
                self.case(*args, exit=2, code="engine-mismatch")
            for args in (("deploy", L, B), ("stop", L), ("init", X, "--config", config(X), "--ref", A)):
                self.case(*args, answer=args[1], exit=2, code="engine-mismatch")
            self.case("host", "init", answer=H.hostname, exit=2, code="engine-mismatch")
            self.case("status", L, exit=(2, 5))
        finally:
            doc.write_bytes(original)
        config_json.write_text("{}\n")  # a client config could add proxy variables or run credential helpers
        try:
            for args in (("status", L), ("backup", L), ("stop", L)):
                self.case(*args, exit=2, code="docker-config", tty=args[0] == "stop")
        finally:
            config_json.unlink()

    # the version gate (F14) -------------------------------------------------------------------------------------
    def test_8_untested_platform(self) -> None:
        """A tool image whose tested.json lacks this Engine line refuses gate tier 2 with exit 2 and still answers
        read-only commands (gate tier 0, ARCHITECTURE §3.6)."""
        args: tuple[str, ...]
        claim = host.build_image(f"ingat:it-{host.PROC}-untested", tested=UNTESTED)
        image = host.docker("image", "inspect", "--format", "{{.Id}}", claim).strip()
        with wrapper(**{f"{brand.env('IMAGE')}='{H.image}'": f"{brand.env('IMAGE')}='{image}'"}) as w:
            for args in (("deploy", L, B), ("stop", L), ("init", X, "--config", config(X), "--ref", A)):
                self.case(*args, answer=args[1], exit=2, code="untested-platform", wrapper=w)
            for args in (("verify", L, "--latest", "--restore-test"), ("prepare", L, N)):
                self.case(*args, exit=2, code="untested-platform", wrapper=w)
            with host.daemon_lock("host-executor"):
                pre = (brand.SELFTEST_PREFIX,)
                self.case("selftest", exit=2, code="untested-platform", wrapper=w, host_exec=True, extra=pre)
            for args in (("status", L), ("doctor", L), ("ps", L), ("bundles", L)):
                self.case(*args, exit=(0, 5), wrapper=w)

    # stale plans (F3) -----------------------------------------------------------------------------------------
    def test_9a_stale_plan(self) -> None:
        """A change between the plan and its execution (another operation, or a container stopped by hand) makes
        the executor refuse the plan as stale (exit 1) with nothing written to the instance (F2, F3)."""
        self.case("stop", L, answer=L, change=lambda: must("backup", L), exit=1, code="stale-plan", executor=True)
        app = f"{L}-app-1"
        try:
            stop = functools.partial(host.docker, "stop", "-t", "30", app)
            self.case("deploy", L, B, answer=L, change=stop, exit=1, code="stale-plan", executor=True)
        finally:
            host.docker("start", app)
        self.assertEqual(json.loads(host.docker("inspect", app))[0]["State"]["Status"], "running")

    def test_9b_schema_gate(self) -> None:
        """Once the data runs schema 2, a deploy of a commit whose recorded deployment expects schema 1 refuses as a
        code-only rollback (LIFECYCLE §4.4) before any effect."""
        tag = f"ingat:it-{host.PROC}-schema2"
        host.docker("build", "-q", "-t", tag, "-", stdin=f"FROM {H.claim}\nENV FXLITE_SCHEMA=2\n")
        atexit.register(host.docker, "rmi", tag, check=False)  # after the host's containers are gone
        image = host.docker("image", "inspect", "--format", "{{.Id}}", tag).strip()
        toml = Path(H.layout.inst_toml(L))
        toml.write_text(toml.read_text().replace(H.image, image))  # the owner names the next image
        must("deploy", L, B, answer=L)  # data-changing: freeze, pre-change bundle, migrate to schema 2
        dep = H.record(L)["current_deployment"]
        doc = json.loads(Path(H.layout.deployment_json(L, dep)).read_text())
        self.assertEqual((doc["origin"], doc["schema"]["actual"]), ("update", 2))
        must("prepare", L, A)
        self.case("deploy", L, A, exit=1, code="schema-gate")
        self.case("deploy", L, A, answer=L, exit=1, code="schema-gate")


if __name__ == "__main__":
    unittest.main()
