"""Tool-owned bare clones, exact-ref resolution and `git archive` exports (ARCHITECTURE §9.6)."""

import os
import re
import shlex
import threading
from collections.abc import Callable
from typing import Any

from ingat.adapters import runner
from ingat.model.errors import CannotRun, IngatError, Refused
from ingat.model.records import sha256_hex

_SHA = re.compile(r"[0-9a-f]{40}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")  # no revision syntax (^ ~ : @ {) and no option-like names
_CONFIG = (
    "core.hooksPath=/dev/null",
    "transfer.fsckObjects=true",
    "fetch.fsckObjects=true",
    "gc.auto=0",
    "protocol.allow=never",
    "protocol.ssh.allow=always",
    "protocol.https.allow=always",
)
_SHOW_LIMIT = 1 << 20
_TREE_LIMIT = 1 << 24


def repo_id(url: str) -> str:
    return sha256_hex(url.encode())[:16]


def _git(
    bare_dir: str, args: list[str], *, extra: tuple[str, ...] = (), env: dict[str, str] | None = None, **kw: Any
) -> runner.Result:
    """Every call: explicit git dir, hardened config on the command line, no system or global config, no prompts."""
    config = [part for item in (*_CONFIG, *extra) for part in ("-c", item)]
    where = [] if args[0] == "init" else ["--git-dir", bare_dir]  # init creates the directory and its parents
    base = {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": bare_dir}
    return runner.run(["git", *where, *config, *args], env={**base, **(env or {})}, **kw)


def _ok(res: runner.Result, what: str, error: type[IngatError] = CannotRun) -> None:
    if res.code != 0:
        detail = "timed out" if res.timed_out else res.err.strip()[-400:]
        raise error(f"{what} failed: {detail}", code="git")


def _commit(commit: str) -> str:
    if not _SHA.fullmatch(commit):
        raise Refused(f"not a full commit id: {commit!r}", code="invalid-ref")
    return commit


def _piped[T](bare_dir: str, args: list[str], sink: Callable[[int], T]) -> tuple[runner.Result, T]:
    """Run git with stdout on a pipe that `sink` drains in a thread: byte-exact, no temporary file."""
    r, w = os.pipe()
    box: list[T | BaseException] = []

    def drain() -> None:
        try:
            box.append(sink(r))
        except BaseException as e:  # handed to the calling thread, which raises it
            box.append(e)
        finally:
            os.close(r)

    thread = threading.Thread(target=drain)
    thread.start()
    try:
        res = _git(bare_dir, args, stdout=w)
    finally:
        os.close(w)
        thread.join()
    out = box[0]
    if isinstance(out, BaseException):
        raise out
    return res, out


def _read(fd: int, limit: int) -> bytes:
    data = b""
    while len(data) <= limit and (chunk := os.read(fd, 1 << 16)):
        data += chunk
    return data


def fetch(bare_dir: str, url: str, *, key_dir: str | None) -> None:
    """Create the bare clone if needed and mirror the remote's branches and tags into it."""
    _ok(_git(bare_dir, ["init", "--bare", "--quiet", "--template=", "--", bare_dir]), "git init")
    known = os.path.join(key_dir, "known_hosts") if key_dir else "/dev/null"
    ssh = "ssh -F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null".split()
    ssh += ["-o", f"UserKnownHostsFile={known}"]
    if key_dir:
        ssh += ["-i", os.path.join(key_dir, "id_ed25519"), "-o", "IdentitiesOnly=yes"]
    extra = ("protocol.file.allow=always",) if url.startswith("file://") else ()
    args = ["fetch", "--quiet", "--prune", "--", url, "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"]
    _ok(_git(bare_dir, args, extra=extra, env={"GIT_SSH_COMMAND": shlex.join(ssh)}), "git fetch")


def _rev(bare_dir: str, name: str) -> str | None:
    res = _git(bare_dir, ["rev-parse", "--verify", "--quiet", name + "^{commit}"])
    if res.code == 1:
        return None
    _ok(res, "git rev-parse")
    return res.out.strip()


def resolve(bare_dir: str, ref: str) -> str:
    """A tag, a branch or a full 40-hex commit id, resolved once to the commit id; never an abbreviation."""
    if _SHA.fullmatch(ref):
        names = [ref]
    elif _REF.fullmatch(ref):
        names = [f"refs/tags/{ref}", f"refs/heads/{ref}"]
    else:
        why = (
            f"{ref!r} is not a version that can be deployed: give a release tag, a branch name or a full 40-character "
            "commit id."
        )
        raise Refused(why, code="invalid-ref")
    found = {c for c in (_rev(bare_dir, n) for n in names) if c}
    if len(found) != 1:
        why = (
            "names two different commits (a tag and a branch share that name); give the full commit id"
            if found
            else "was not found in the app repository"
        )
        raise Refused(f"The version {ref!r} {why}.", code="invalid-ref")
    return found.pop()


def tag_of(bare_dir: str, commit: str) -> list[str]:
    res = _git(bare_dir, ["tag", "--list", "--points-at", _commit(commit)])
    _ok(res, "git tag")
    return res.out.split()


def show(bare_dir: str, commit: str, path: str) -> bytes:
    """Byte-exact content of `path` at `commit` (at most 1 MiB)."""
    res, data = _piped(bare_dir, ["cat-file", "blob", f"{_commit(commit)}:{path}"], lambda fd: _read(fd, _SHOW_LIMIT))
    if len(data) > _SHOW_LIMIT:
        raise Refused(f"{path} at {commit} is larger than {_SHOW_LIMIT} bytes", code="source")
    _ok(res, f"reading {path} at {commit}", Refused)
    return data


def archive(bare_dir: str, commit: str, dest: str) -> None:
    """Export `commit` into `dest`, an empty directory the caller created, and fsync it. Submodules, LFS and
    symbolic links (Docker would follow one out of the export) are refused before anything is written."""
    res = _git(bare_dir, ["ls-tree", "-r", "-z", _commit(commit)], limit=_TREE_LIMIT)
    _ok(res, "git ls-tree")
    if res.truncated:
        raise Refused(f"the tree of {commit} is too large to inspect", code="source")
    for entry in filter(None, res.out.split("\0")):
        meta, path = entry.split("\t", 1)
        mode, kind = meta.split(" ")[:2]
        if kind == "commit" or path == ".gitmodules":
            raise Refused(f"{commit} uses submodules ({path}); they are not supported", code="unsupported-source")
        if mode == "120000":
            raise Refused(f"{commit} has a symbolic link ({path}); links are not supported", code="unsupported-source")
        if os.path.basename(path) == ".gitattributes" and b"filter=lfs" in show(bare_dir, commit, path):
            raise Refused(f"{commit} uses Git LFS ({path}); it is not supported", code="unsupported-source")
    if os.listdir(dest):
        raise Refused(f"export directory {dest} is not empty", code="source")
    res, tar = _piped(
        bare_dir,
        ["archive", "--format=tar", commit],
        lambda fd: runner.run(["tar", "-x", "-f", "-", "-C", dest], stdin=fd),
    )
    _ok(tar, "tar")  # first: when tar stops early (a full disk), git only dies of a broken pipe
    _ok(res, "git archive")
    for top, _, files, dfd in os.fwalk(dest):  # durable before the caller publishes it
        for name in files:
            with open(os.path.join(top, name), "rb") as f:
                os.fsync(f.fileno())
        os.fsync(dfd)
