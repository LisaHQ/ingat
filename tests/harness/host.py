"""Shared harness of the integration suites (tests/docker/test_it_*.py; ARCHITECTURE §10.3).

Every suite drives a scratch host the way an owner does: a release directory (`docker save` of the tool image,
SHA256SUMS, install.sh), `sh install.sh --from-tar`, then the real wrapper `<root>/bin/ingat`, on a pty when a command
needs typed approval. Behaviour is observed through exit codes, output, files and the Docker inventory and events.

The tool image is never rebuilt (ADR-0029). `build_image` derives the lane's claim image from INGAT_TEST_IMAGE: with
INGAT_TEST_OVERLAY_SRC=1 (the local dev runner) it first overlays the current source and fixtures
(`ingat:it-<srchash>`, kept as a build cache), then adds one layer holding the tested.json this lane would claim.

Several suite processes may share one scratch daemon, while a real host has one tool root per daemon. So each process
gets its own image tags, release tarball, registry (on an ephemeral port) and scratch roots; instances get explicit
random ports above the selftest's (the lowest free ones); and `certify` holds a daemon-wide lock around
`selftest --host`, whose host executor has one fixed name per daemon and which allocates the lowest free ports. An
executor allocates an isolation /24 by the allocation entries of its own root and the daemon's networks, so two drills
of different roots on one daemon could take the same /24: every process draws from an isolation pool of its own
(`own_pool`), which `certify` records in the host's host.json right after `host init`.
"""

import atexit
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
import pty
import re
import secrets
import select
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ingat import __version__, brand
from ingat.store import state

REPO = Path(__file__).resolve().parents[2]
SRV = "/srv"
SOCK = "/var/run/docker.sock"
PKG = "/usr/local/lib/python3.13/site-packages/ingat"
BASE_IMAGE = os.environ.get("INGAT_TEST_IMAGE", "ingat:dev")
OVERLAY = os.environ.get("INGAT_TEST_OVERLAY_SRC") == "1"
# library/registry 3.0.0, the multi-arch index digest the registry API reported for the tag.
REGISTRY_IMAGE = "registry:3.0.0@sha256:6c5666b861f3505b116bb9aa9b25175e71210414bd010d92035ff64018f9457e"
SCRATCH = "ingat.scratch"  # the label of the harness's own helper containers (lane.sh labels its dind the same way)
REVISION = "org.opencontainers.image.revision"
PROMPT = b"to approve: "
GIT_WHO = {"NAME": "fixture", "EMAIL": "fixture@example.invalid", "DATE": "2026-01-01T00:00:00Z"}
PORTS = range(21000, 30000)  # explicit instance ports: above the lowest free ones, which `selftest` allocates
ENV = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": "/root", "TERM": "dumb"}
PROC = secrets.token_hex(3)  # this process's tags and directories
POOLS = ipaddress.ip_network("10.251.0.0/16")  # per-process isolation pools: outside the default one and Docker's
Result = tuple[int, str, str]


def docker(*args: str, stdin: str | bytes | None = None, check: bool = True, timeout: float = 900) -> str:
    """stdout of a docker CLI call on the scratch daemon; `check` raises with its stderr."""
    data = stdin.encode() if isinstance(stdin, str) else stdin
    p = subprocess.run(["docker", *args], input=data, capture_output=True, env=ENV, timeout=timeout, check=False)
    if check and p.returncode:
        raise AssertionError(f"docker {' '.join(args[:3])} failed ({p.returncode}): {p.stderr.decode()[-2000:]}")
    return p.stdout.decode()


def present(kind: str, ref: str) -> bool:
    return not subprocess.run(["docker", kind, "inspect", ref], capture_output=True, env=ENV, check=False).returncode


def inspect(kind: str, ids: list[str]) -> list[dict[str, Any]]:
    """Inspect documents of the objects that still exist (one may go meanwhile, as a --rm executor does)."""
    docs: list[dict[str, Any]] = json.loads(docker(kind, "inspect", *ids, check=False) or "[]") if ids else []
    return docs


# ---------------------------------------------------------------- the tool image under test


def lane_facts() -> dict[str, str]:
    """This lane's tested.json entry, as tests/harness/lane.sh computes it: the daemon's Engine major.minor and
    architecture, the tool image's docker CLI and Compose (this runner is that image)."""
    server = json.loads(docker("version", "--format", "{{json .Server}}"))
    cli = docker("version", "--format", "{{.Client.Version}}").strip()
    compose = docker("compose", "version", "--short").strip()
    return {
        "engine": ".".join(server["Version"].split(".")[:2]),
        "arch": server["Arch"],
        "cli": cli,
        "compose": compose,
    }


def _srchash() -> str:
    """The base image's ID and every source and fixture file (path and bytes)."""
    h = hashlib.sha256(docker("image", "inspect", "--format", "{{.Id}}", BASE_IMAGE).encode())
    for top in (REPO / "src" / "ingat", REPO / "fixtures"):
        for d, _, files in sorted(os.walk(top)):
            if "__pycache__" in Path(d).parts:  # left out of the image too (.dockerignore)
                continue
            for f in sorted(x for x in files if not x.endswith(".pyc")):
                p = Path(d, f)
                h.update(f"{p.relative_to(REPO)}\0".encode() + p.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def _overlay() -> str:
    """`ingat:it-<srchash>`: INGAT_TEST_IMAGE with the current package and fixtures, the way the image bakes them;
    older overlays of this daemon are removed (best effort: one still in use stays)."""
    tag = f"ingat:it-{_srchash()}"
    if not present("image", tag):
        dockerfile = f"FROM {BASE_IMAGE}\nCOPY src/ingat {PKG}\nCOPY fixtures /opt/fixtures\n"
        docker("build", "-q", "-t", tag, "-f", "-", str(REPO), stdin=dockerfile)
    for old in docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}", "ingat").split():
        if re.fullmatch(r"ingat:it-[0-9a-f]{12}", old) and old != tag:
            docker("rmi", old, check=False)
    return tag


_BUILT: dict[str, str] = {}


def build_image(tag: str = "", tested: list[dict[str, str]] | None = None) -> str:
    """`<tag>-claim`: the image under test plus one layer holding this lane's tested.json (ADR-0029), or `tested`
    (for example a list without this lane), built with the legacy builder (plain COPY, no --chmod). Cached per
    process and tag; removed when the process exits."""
    tag = tag or f"ingat:it-{PROC}"
    if tag not in _BUILT:
        base = _overlay() if OVERLAY else BASE_IMAGE
        claim = f"{tag}-claim"
        with tempfile.TemporaryDirectory() as d:
            claimed = [lane_facts()] if tested is None else tested
            Path(d, "tested.json").write_text(json.dumps(claimed, indent=2) + "\n")
            os.chmod(Path(d, "tested.json"), 0o644)
            docker("build", "-q", "-t", claim, "-f", "-", d, stdin=f"FROM {base}\nCOPY tested.json {PKG}/tested.json\n")
        atexit.register(docker, "rmi", claim, check=False)
        _BUILT[tag] = claim
    return _BUILT[tag]


_TARS: dict[str, tuple[str, str]] = {}


def _release_tar(image: str) -> tuple[str, str]:
    """(path, sha256) of `docker save` of `image`, once per process and image under /srv (scratch hosts hard-link
    it)."""
    if image not in _TARS:
        top, d = f"{SRV}/it-img-{PROC}", f"{SRV}/it-img-{PROC}/{len(_TARS)}"
        if not _TARS:
            atexit.register(shutil.rmtree, top, True)
        os.makedirs(d, 0o700)
        arch = json.loads(docker("version", "--format", "{{json .Server}}"))["Arch"]
        path = f"{d}/ingat-{__version__}-{arch}.tar"
        docker("save", "-o", path, image)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _TARS[image] = (path, h.hexdigest())
    return _TARS[image]


# ---------------------------------------------------------------- processes on a terminal or not


def run(argv: list[str], *, tty: bool = False, answer: str | None = None, env: Mapping[str, str] | None = None,
        timeout: float = 900) -> Result:  # fmt: skip
    """(exit, stdout, stderr). With `tty` the command runs on a pty (stdout and stderr merged into stdout, line ends
    normalized) and `answer` is typed at the first approval prompt; without, stdin is empty."""
    environ = {**ENV, **(env or {})}
    if not tty:
        p = subprocess.run(argv, input=b"", capture_output=True, env=environ, timeout=timeout, check=False)
        return p.returncode, p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    pid, fd = pty.fork()
    if pid == 0:  # the child: the command on the pty
        try:
            os.execvpe(argv[0], argv, environ)
        finally:
            os._exit(127)
    out, sent, end = b"", answer is None, time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > end:
                os.kill(pid, signal.SIGKILL)
                out += b"\n[harness: timed out]"
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
            if not sent and PROMPT in out:
                os.write(fd, (answer or "").encode() + b"\r")
                sent = True
    finally:
        os.close(fd)
    code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
    return code, out.decode(errors="replace").replace("\r\n", "\n"), ""


@contextlib.contextmanager
def daemon_lock(name: str) -> Iterator[None]:
    """A lock shared by every runner of this scratch daemon (they all mount its /srv), for what is unique per daemon."""
    with open(f"{SRV}/.it-{name}.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


_POOL: list[Any] = []  # [pool, the open lock file that holds it]


def own_pool() -> str:
    """A /20 of POOLS that no other runner of this scratch daemon holds: its lock file under the shared /srv stays
    locked until this process exits (the kernel releases it, so a killed runner holds nothing)."""
    if not _POOL:
        for i, net in enumerate(POOLS.subnets(new_prefix=20)):
            f = open(f"{SRV}/.it-pool-{i}.lock", "a")  # noqa: SIM115 - held open for the life of the process
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                f.close()
                continue
            _POOL[:] = [str(net), f]
            break
        else:
            raise AssertionError(f"every isolation pool of {POOLS} is held by another runner of this daemon")
    return str(_POOL[0])


def free_port() -> int:
    """A random port in PORTS that no container of the daemon publishes, nothing listens on and no scratch root has
    allocated (`init` refuses a port another instance holds, running or not)."""
    used = {Path(p).name[5:-5] for p in Path(SRV).glob("*/root/host/allocations/port-*.json")}
    for c in inspect("container", docker("ps", "-aq", "--no-trunc").split()):
        used |= {b.get("HostPort") for bs in (c["HostConfig"].get("PortBindings") or {}).values() for b in bs or ()}
    while True:
        port = PORTS.start + secrets.randbelow(len(PORTS))
        with socket.socket() as s:
            if str(port) not in used and s.connect_ex(("127.0.0.1", port)) != 0:
                return port


# ---------------------------------------------------------------- observation


def tree_hash(path: str, exempt: tuple[str, ...] = ("lock.holder.json",)) -> str:
    """Every path, type, mode, size and content below `path`, names in `exempt` left out (F2: the lock holder file)."""
    h = hashlib.sha256()
    for d, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(dirs + files):
            if name in exempt:
                continue
            p = os.path.join(d, name)
            st = os.lstat(p)
            h.update(f"{os.path.relpath(p, path)}\0{st.st_mode}\0{st.st_size}\0".encode())
            if os.path.isfile(p) and not os.path.islink(p):
                h.update(Path(p).read_bytes())
    return h.hexdigest()


def inventory(label: str) -> dict[str, list[tuple[str, ...]]]:
    """The Docker objects of instance `label`: containers (ID, name, status, start time, image) carrying its instance
    label or in its Compose project, its networks (ID, name) and volumes (name)."""
    own, project = f"label={brand.label('instance')}={label}", f"label=com.docker.compose.project={label}"
    ids = {i for f in (own, project) for i in docker("ps", "-aq", "--no-trunc", "--filter", f).split()}
    docs = inspect("container", sorted(ids))
    containers = [(c["Id"], c["Name"].lstrip("/"), c["State"]["Status"], c["State"]["StartedAt"], c["Image"])
                  for c in docs]  # fmt: skip
    nets = {i for f in (own, project) for i in docker("network", "ls", "-q", "--no-trunc", "--filter", f).split()}
    networks = [(n["Id"], n["Name"]) for n in inspect("network", sorted(nets))]
    volumes = [(v,) for v in docker("volume", "ls", "-q", "--filter", own).split()]
    return {"containers": sorted(containers), "networks": sorted(networks), "volumes": sorted(volumes)}


def events(since: str, until: str) -> list[dict[str, Any]]:
    """Every daemon event in [since, until] (unix times), unfiltered: volume and network events carry no labels, so
    callers match them by name (Actor.Attributes.name)."""
    out = docker("events", "--since", since, "--until", until, "--format", "{{json .}}")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def now() -> str:
    """A unix time for `events`."""
    return f"{time.time():.6f}"


def wait_gone(container: str, timeout: float = 120) -> bool:
    """Whether `container` (name or ID) no longer exists within `timeout` seconds."""
    end = time.monotonic() + timeout
    while present("container", container):
        if time.monotonic() > end:
            return False
        time.sleep(0.5)
    return True


# ---------------------------------------------------------------- a scratch host


class ScratchHost:
    """One host: `/srv/it-<name>-<rand>/{root,backups,release}`; the release holds `image` (default: build_image())
    and installs as `version` (settable before `install`). `install` runs the release's install.sh; `cli` runs the
    wrapper it wrote. `close` removes every Docker object of the host's instances and the directory (the probe volume
    is shared by every scratch host of the daemon and stays)."""

    def __init__(self, name: str = "h", image: str = "") -> None:
        self.base = f"{SRV}/it-{name}-{secrets.token_hex(4)}"
        self.root, self.backups, self.release = f"{self.base}/root", f"{self.base}/backups", f"{self.base}/release"
        os.makedirs(self.release, 0o700)
        os.chmod(self.base, 0o700)
        self.layout = state.Layout(self.root, self.backups)
        self.hostname = socket.gethostname()  # what the wrapper's `hostname` passes as INGAT_HOST
        self.version = __version__
        self.claim = image or build_image()
        tar, digest = _release_tar(self.claim)
        self.tar = f"{self.release}/{os.path.basename(tar)}"
        os.link(tar, self.tar)
        Path(self.release, "SHA256SUMS").write_text(f"{digest}  {os.path.basename(tar)}\n")
        shutil.copy(REPO / "install.sh", f"{self.release}/install.sh")
        self.wrapper = f"{self.root}/bin/{brand.CLI}"

    # install and run
    def install(self, *extra: str, timeout: float = 900) -> Result:
        argv = ["sh", f"{self.release}/install.sh", "--version", self.version, "--root", self.root]
        return run([*argv, "--backups", self.backups, "--from-tar", self.tar, *extra], timeout=timeout)

    @property
    def image(self) -> str:
        """INGAT_IMAGE of the installed wrapper: the loaded image's ID."""
        for line in Path(self.wrapper).read_text().splitlines():
            if line.startswith(f"{brand.env('IMAGE')}="):
                return line.split("=", 1)[1].strip("'")
        raise AssertionError(f"{self.wrapper} names no image")

    def cli(self, *args: str, tty: bool = False, answer: str | None = None, env: Mapping[str, str] | None = None,
            timeout: float = 900) -> Result:  # fmt: skip
        """`sh <root>/bin/ingat <args>`: (exit, stdout, stderr); on a pty stdout holds both streams."""
        return run(["sh", self.wrapper, *args], tty=tty, answer=answer, env=env, timeout=timeout)

    def cli_direct(self, *args: str, env: Mapping[str, str], tty: bool = False, answer: str | None = None,
                   timeout: float = 900) -> Result:  # fmt: skip
        """The CLI container with the wrapper's exact `docker run` flags plus `-e K=V` for each of `env` (full names,
        for example brand.env("CRASH_AT")), which the wrapper's `env -i` never passes."""
        text = Path(self.wrapper).read_text()
        anchor = '"$INGAT_IMAGE" "$@"'
        if text.count(anchor) != 1:
            raise AssertionError(f"{self.wrapper}: the image argument is not where the harness expects it")
        extra = "".join(f"-e {shlex.quote(f'{k}={v}')} " for k, v in env.items())
        path = f"{self.base}/direct-{secrets.token_hex(4)}.sh"
        Path(path).write_text(text.replace(anchor, extra + anchor))
        try:
            return run(["sh", path, *args], tty=tty, answer=answer, timeout=timeout)
        finally:
            os.remove(path)

    def certify(self) -> None:
        """`host init` (class C, the host name typed on a pty), this runner's isolation pool, then `selftest --host`,
        which certifies this platform build for gate tier 2; under the daemon-wide lock of the host executor's fixed
        name."""
        code, out, _ = self.cli("host", "init", tty=True, answer=self.hostname)
        if code:
            raise AssertionError(f"host init exited {code}:\n{out}")
        doc = state.read_doc(self.layout.host_json, "host")  # this runner's own pool (module docstring)
        state.replace_doc(self.layout.host_json, doc | {"pools": doc["pools"] | {"isolation": own_pool()}})
        with daemon_lock("host-executor"):
            code, out, err = self.cli("selftest", "--host", timeout=1800)
        if code:
            raise AssertionError(f"selftest --host exited {code}:\n{out}{err}")

    # files of the host
    def inbox(self, filename: str, data: str | bytes) -> str:
        """Place an owner's file in the inbox (0600); returns its path."""
        path = f"{self.layout.inbox}/{filename}"
        Path(path).write_bytes(data.encode() if isinstance(data, str) else data)
        os.chmod(path, 0o600)
        return path

    def record(self, name: str) -> dict[str, Any]:
        return state.read_doc(self.layout.record_json(name), "instance")

    def repo_url(self, app: str) -> str:
        return f"file://{self.layout.fixtures_dir}/{app}.git"

    def fixture_repo(self, app: str, commits: list[Mapping[str, str | bytes | None]], base: str = "") -> list[str]:
        """`<root>/cache/fixtures/<app>.git` (ADR-0027): the tree of fixtures/<base or app>, overlaid with
        tests/data/<app> when it exists, then one commit per entry of `commits` after applying its edits
        (relative path -> new content, or None to delete). Returns the commit SHAs."""
        repo = f"{self.layout.fixtures_dir}/{app}.git"
        os.makedirs(self.layout.fixtures_dir, exist_ok=True)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(REPO / "fixtures" / (base or app), repo, ignore=ignore)
        if (data := REPO / "tests" / "data" / app).is_dir():
            shutil.copytree(data, repo, ignore=ignore, dirs_exist_ok=True)
        who = {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in GIT_WHO.items()}
        env = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", **who}

        def git(*args: str) -> str:
            code, out, err = run(["git", "-C", repo, *args], env=env, timeout=120)
            if code:
                raise AssertionError(f"git {args[0]} failed: {err}")
            return out.strip()

        git("init", "-q", "--initial-branch=main")
        shas = []
        for n, edits in enumerate(commits):
            for rel, content in edits.items():
                p = Path(repo, rel)
                if content is None:
                    p.unlink()
                    continue
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content.encode() if isinstance(content, str) else content)
            git("add", "-A")
            git("commit", "-q", "-m", f"{app} commit {n + 1}")
            shas.append(git("rev-parse", "HEAD"))
        return shas

    def close(self) -> None:
        """Remove the containers, networks and volumes of every instance of this host, then the directory."""
        names = os.listdir(self.layout.instances_dir) if os.path.isdir(self.layout.instances_dir) else []
        for name in names:
            own, project = f"label={brand.label('instance')}={name}", f"label=com.docker.compose.project={name}"
            ids = {i for f in (own, project) for i in docker("ps", "-aq", "--filter", f, check=False).split()}
            if ids:
                docker("rm", "-f", *sorted(ids), check=False)
            if nets := docker("network", "ls", "-q", "--filter", own, check=False).split():
                docker("network", "rm", *nets, check=False)
            if vols := docker("volume", "ls", "-q", "--filter", own, check=False).split():
                docker("volume", "rm", *vols, check=False)
        shutil.rmtree(self.base, ignore_errors=True)


# ---------------------------------------------------------------- the OD-11 (b) path: a registry the app's CI pushes to


class Registry:
    """A local registry (REGISTRY_IMAGE, pinned by digest) on an ephemeral loopback port of the scratch daemon, which
    treats 127.0.0.0/8 registries as insecure (plain HTTP); `address` is its `127.0.0.1:<port>`. `push` plays the
    app's CI: one image per commit, built FROM the tool image (the fixture image) with the revision label and the
    schema the commit's code expects, pushed, then untagged locally so that `prepare` really pulls it."""

    def __init__(self) -> None:
        self.name = f"it-registry-{PROC}-{secrets.token_hex(3)}"
        docker("run", "-d", "--name", self.name, "--label", f"{SCRATCH}=registry", "-p", "127.0.0.1::5000",
               REGISTRY_IMAGE)  # fmt: skip
        ports = [x for x in docker("port", self.name, "5000/tcp").split() if x.startswith("127.0.0.1:")]
        self.address = ports[0]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        end = time.monotonic() + 60
        while True:
            try:
                with opener.open(f"http://{self.address}/v2/", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() > end:
                raise AssertionError(f"registry {self.name} did not answer on {self.address}")
            time.sleep(0.5)

    def push(self, commit: str, schema: int, base: str, repo: str = "fx-lite", labels: Mapping[str, str] | None = None,
             tag: str = "") -> str:  # fmt: skip
        """Build `<address>/<repo>:<tag or commit>` FROM `base` with `labels` (default: the revision label = commit)
        and FXLITE_SCHEMA=<schema>, push it and drop the local tag; returns the reference."""
        ref = f"{self.address}/{repo}:{tag or commit}"
        lines = [f"FROM {base}", *(f"LABEL {k}={v}" for k, v in (labels or {REVISION: commit}).items())]
        docker("build", "-q", "-t", ref, "-", stdin="\n".join([*lines, f"ENV FXLITE_SCHEMA={schema}", ""]))
        docker("push", "-q", ref)
        docker("rmi", ref)
        return ref

    def close(self) -> None:
        """Remove every local image of this registry (pulled by `prepare`), then the registry and its volume."""
        mine = [x for x in docker("image", "ls", "--format", "{{.Repository}}:{{.Tag}}").split()
                if x.startswith(f"{self.address}/")]  # fmt: skip
        if mine:
            docker("rmi", *mine, check=False)
        docker("rm", "-f", "-v", self.name, check=False)


# ---------------------------------------------------------------- another release, or another platform build, on a host


def install_release(h: ScratchHost, image: str, *extra: str, version: str = "", timeout: float = 1800) -> Result:
    """install.sh of a further release of `image` (its own directory: the saved image, SHA256SUMS, install.sh) run
    against `h`'s roots, as an owner upgrades a host (ARCHITECTURE §3.5); `version` defaults to h.version. An upgrade of
    an installed host runs `selftest --host`: the caller holds daemon_lock("host-executor")."""
    release = f"{h.base}/release-{secrets.token_hex(4)}"
    os.makedirs(release, 0o700)
    tar, digest = _release_tar(image)
    local = f"{release}/{os.path.basename(tar)}"
    os.link(tar, local)
    Path(release, "SHA256SUMS").write_text(f"{digest}  {os.path.basename(tar)}\n")
    shutil.copy(REPO / "install.sh", f"{release}/install.sh")
    argv = ["sh", f"{release}/install.sh", "--version", version or h.version, "--root", h.root, "--backups", h.backups]
    return run([*argv, "--from-tar", local, *extra], timeout=timeout)


def cli_variant(h: ScratchHost, *args: str, image: str = "", os_release: str = "", tty: bool = False,
                answer: str | None = None, timeout: float = 900) -> Result:  # fmt: skip
    """`h`'s installed wrapper, run from a temporary copy that names another tool `image` (the host's wrapper on a
    release with another tested.json) and/or mounts the file `os_release` as the host's /etc/os-release (an OS update
    as the CLI observes it; the executor mounts the daemon host's own release file, so only checks the CLI makes, such
    as the gate of a plan, see the change)."""
    lines = Path(h.wrapper).read_text().splitlines(keepends=True)

    def swap(prefix: str, line: str) -> None:
        hits = [i for i, x in enumerate(lines) if x.startswith(prefix)]
        if len(hits) != 1:
            raise AssertionError(f"{h.wrapper}: no single line starts with {prefix!r}")
        lines[hits[0]] = line + "\n"

    if image:
        swap(f"{brand.env('IMAGE')}=", f"{brand.env('IMAGE')}={shlex.quote(image)}")
    if os_release:
        swap("FACTS=", f"FACTS={shlex.quote(f'-v {os_release}:{brand.HOST_FACTS_DIR}/etc/os-release:ro')}")
    path = f"{h.base}/variant-{secrets.token_hex(4)}.sh"
    Path(path).write_text("".join(lines))
    try:
        return run(["sh", path, *args], tty=tty, answer=answer, timeout=timeout)
    finally:
        os.remove(path)


def pool_free(pool: str, timeout: float = 300) -> bool:
    """Whether a /24 of the isolation `pool` is (or within `timeout` seconds becomes) clear of every network on the
    daemon. The default pool lies outside Docker's default address pools (ADR-0030), but a pool a host recorded
    earlier, or a network created with an explicit subnet, may cover it, and an isolated run then refuses
    (`capacity`) until that network goes."""
    end = time.monotonic() + timeout
    while True:
        used = [ipaddress.ip_network(c["Subnet"]) for n in inspect("network", docker("network", "ls", "-q").split())
                for c in (n.get("IPAM") or {}).get("Config") or () if ":" not in c.get("Subnet", ":")]  # fmt: skip
        if any(not any(s.overlaps(u) for u in used) for s in ipaddress.ip_network(pool).subnets(new_prefix=24)):
            return True
        if time.monotonic() > end:
            return False
        time.sleep(2)
