"""No-follow, descriptor-relative file operations; every publish fsyncs the file, then its directory (ADR-0008).

Paths are absolute. Every component is opened from `/` with O_NOFOLLOW, so a symbolic link anywhere on a path,
a symbolic link or special file inside a walked tree, or a regular file where a directory belongs is refused
(`Refused`, code `unsafe-path`). Never calls sync(2).
"""

import contextlib
import errno
import hashlib
import os
import stat
from collections.abc import Generator, Iterator

from ingat.model.errors import Refused

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_NEW = os.O_WRONLY | os.O_CREAT | os.O_EXCL
_CHUNK = 1 << 20

Entry = tuple[str, os.stat_result, int, str]  # relpath ("" for the root), lstat, parent directory fd, name


LINK = "is a symbolic link (a shortcut to another place), which is never followed for safety"


def _refuse(path: str, what: str) -> Refused:
    return Refused(f"{path} {what}, so it is not used", code="unsafe-path")


@contextlib.contextmanager
def _fd(fd: int) -> Iterator[int]:
    try:
        yield fd
    finally:
        os.close(fd)


def _fsync_close(fd: int) -> None:
    with _fd(fd):
        os.fsync(fd)


def _open_at(dfd: int, name: str, flags: int, path: str, mode: int = 0o600) -> int:
    try:
        return os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=dfd)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            raise _refuse(path, LINK if e.errno == errno.ELOOP else "is not a directory") from e
        raise


def _open_dir(path: str, create: bool = False, mode: int = 0o700) -> int:
    """A directory's fd, reached from `/` without following links; `create` makes missing ones with `mode`."""
    if not os.path.isabs(path):
        raise _refuse(path, "is not an absolute path")
    fd, sofar = os.open("/", _DIR), ""
    try:
        for part in filter(None, os.path.normpath(path).split("/")):
            sofar += "/" + part
            made = False
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, mode, dir_fd=fd)
                    made = True
            fd, parent = _open_at(fd, part, _DIR, sofar), fd
            with _fd(parent):
                if made:  # exact mode whatever the umask, then the new directory and its entry are durable
                    os.fchmod(fd, mode)
                    os.fsync(fd)
                    os.fsync(parent)
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextlib.contextmanager
def _parent(path: str, create: bool = False) -> Iterator[tuple[int, str]]:
    head, name = os.path.split(os.path.normpath(path))
    with _fd(_open_dir(head, create)) as dfd:
        yield dfd, name


def _present(dfd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=dfd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _open_regular(dfd: int, name: str, path: str, single: bool) -> int:
    fd = _open_at(dfd, name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY, path)
    st = os.fstat(fd)
    if stat.S_ISREG(st.st_mode) and (st.st_nlink == 1 or not single):
        return fd
    os.close(fd)
    raise _refuse(path, "is not a regular file with one link" if single else "is not a regular file")


def _open_file(path: str, single: bool = False) -> int:
    with _parent(path) as (dfd, name):
        return _open_regular(dfd, name, path, single)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def _own(fd: int, owner: tuple[int, int] | None, mode: int) -> None:
    if owner is not None:
        os.fchown(fd, *owner)
    os.fchmod(fd, mode)


def _mode(st: os.stat_result, override: int | None) -> int:
    """The override, else the source's permission bits without group/other write, setuid, setgid and sticky."""
    return override if override is not None else stat.S_IMODE(st.st_mode) & 0o755


def _publish(path: str, data: bytes, mode: int, once: bool) -> None:
    """Write a fsynced temp file beside `path`, then link (write-once) or rename it into place; fsync the dir."""
    with _parent(path, create=True) as (dfd, name):
        tmp = f".{name}.{os.urandom(6).hex()}.tmp"
        try:
            with _fd(_open_at(dfd, tmp, _NEW, tmp)) as fd:
                os.fchmod(fd, mode)
                _write_all(fd, data)
                os.fsync(fd)
            if once:
                os.link(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
            else:
                os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp, dir_fd=dfd)
        os.fsync(dfd)


def mkdirs(path: str, mode: int = 0o700) -> None:
    os.close(_open_dir(path, create=True, mode=mode))


def write_once(path: str, data: bytes, mode: int = 0o600) -> None:
    """Publish a new file whole or not at all; FileExistsError when the name exists."""
    _publish(path, data, mode, once=True)


def replace_atomic(path: str, data: bytes, mode: int = 0o600) -> None:
    _publish(path, data, mode, once=False)


def append_line(path: str, line: bytes) -> None:
    with _parent(path, create=True) as (dfd, name):
        new = not _present(dfd, name)
        with _fd(_open_at(dfd, name, os.O_WRONLY | os.O_APPEND | os.O_CREAT, path)) as fd:
            _write_all(fd, line + b"\n")
            os.fsync(fd)
        if new:
            os.fsync(dfd)


def read(path: str, limit: int | None = None) -> bytes:
    """A regular file's bytes; Refused `too-large` when it holds more than `limit` bytes."""
    with open(_open_file(path), "rb") as f:
        data = f.read() if limit is None else f.read(limit + 1)
    if limit is not None and len(data) > limit:
        raise Refused(f"{path} is larger than {limit} bytes", code="too-large")
    return data


def exists(path: str) -> bool:
    """Whether anything, a symbolic link included, is at `path`."""
    try:
        with _parent(path) as (dfd, name):
            return _present(dfd, name)
    except FileNotFoundError:
        return False


def listdir(path: str) -> list[str]:
    """Sorted names; a missing directory is empty."""
    try:
        fd = _open_dir(path)
    except FileNotFoundError:
        return []
    with _fd(fd):
        return sorted(os.listdir(fd))


def open_write(path: str, mode: int = 0o600) -> int:
    """A new file's fd for a byte-exact stream; finish with close_fsync."""
    with _parent(path, create=True) as (dfd, name):
        fd = _open_at(dfd, name, _NEW, path)
    os.fchmod(fd, mode)
    return fd


def close_fsync(fd: int, path: str) -> None:
    _fsync_close(fd)
    with _parent(path) as (dfd, _):
        os.fsync(dfd)


def make_empty_dir(path: str, mode: int, owner: tuple[int, int] | None = None) -> None:
    """Create a new directory (FileExistsError when present) with exactly this mode and owner."""
    with _parent(path, create=True) as (dfd, name):
        os.mkdir(name, 0o700, dir_fd=dfd)
        with _fd(_open_at(dfd, name, _DIR, path)) as fd:
            _own(fd, owner, mode)
            os.fsync(fd)
        os.fsync(dfd)


def rename(src: str, dst: str) -> None:
    """Rename within one filesystem, never over an existing name; fsyncs both directories."""
    with _parent(src) as (sfd, sname), _parent(dst, create=True) as (dfd, dname):
        if _present(dfd, dname):
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), dst)
        os.rename(sname, dname, src_dir_fd=sfd, dst_dir_fd=dfd)
        os.fsync(dfd)
        os.fsync(sfd)


def _below(fd: int, prefix: str, root: str) -> Iterator[Entry]:
    for name in sorted(os.listdir(fd)):
        rel = prefix + name
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
            what = "is a symbolic link (a shortcut to another place) or a special file, neither of which is used for "
            what += "safety"
            raise _refuse(os.path.join(root, rel), what)
        yield rel, st, fd, name
        if stat.S_ISDIR(st.st_mode):
            with _fd(_open_at(fd, name, _DIR, os.path.join(root, rel))) as sub:
                yield from _below(sub, rel + "/", root)


def _tree(root: str) -> Generator[Entry]:
    """The root (relpath "") and every entry below it, top-down, sorted by name."""
    with _parent(root) as (pfd, name):
        st = os.stat(name, dir_fd=pfd, follow_symlinks=False)
        if not stat.S_ISDIR(st.st_mode):
            raise _refuse(root, "is not a directory")
        yield "", st, pfd, name
        with _fd(_open_at(pfd, name, _DIR, root)) as fd:
            yield from _below(fd, "", root)


def _checked(root: str) -> Iterator[Entry]:
    """`_tree` after a full pass, so a refusal comes before any change."""
    for _ in _tree(root):
        pass
    yield from _tree(root)


def walk(root: str) -> Iterator[tuple[str, os.stat_result]]:
    """Every entry below `root` as ('/'-separated relpath, lstat)."""
    for rel, st, _, _ in _tree(root):
        if rel:
            yield rel, st


def chown_tree(path: str, uid: int, gid: int) -> None:
    for _, _, dfd, name in _checked(path):
        os.chown(name, uid, gid, dir_fd=dfd, follow_symlinks=False)


def chmod_tree(path: str, dir_mode: int, file_mode: int) -> None:
    for _, st, dfd, name in _checked(path):
        os.chmod(name, dir_mode if stat.S_ISDIR(st.st_mode) else file_mode, dir_fd=dfd, follow_symlinks=False)


def _digest(fd: int, out: int | None = None) -> tuple[str, int]:
    h, size = hashlib.sha256(), 0
    while chunk := os.read(fd, _CHUNK):
        h.update(chunk)
        size += len(chunk)
        if out is not None:
            _write_all(out, chunk)
    return h.hexdigest(), size


def hash_file(path: str) -> tuple[str, int]:
    """(sha256, size) of a regular file with exactly one link."""
    with _fd(_open_file(path, single=True)) as fd:
        return _digest(fd)


def copy_tree(
    src: str,
    dst: str,
    *,
    owner: tuple[int, int] | None = None,
    dir_mode: int | None = None,
    file_mode: int | None = None,
) -> list[tuple[str, str, int]]:
    """Copy into a new `dst` (fsyncing every file and directory); (relpath, sha256, size) per file.

    Files need exactly one link; an unset mode keeps the source's bits as `_mode` says. A failure removes `dst`.
    """
    entries = _tree(src)
    make_empty_dir(dst, _mode(next(entries)[1], dir_mode), owner)
    files: list[tuple[str, str, int]] = []
    dirs: list[tuple[str, int]] = []  # (relpath, fd) of the destination directories on the current path
    try:
        dirs.append(("", _open_dir(dst)))
        for rel, st, sfd, name in entries:
            while dirs[-1][0] != os.path.dirname(rel):
                _fsync_close(dirs.pop()[1])
            dfd, path = dirs[-1][1], os.path.join(dst, rel)
            if stat.S_ISDIR(st.st_mode):
                os.mkdir(name, 0o700, dir_fd=dfd)
                dirs.append((rel, _open_at(dfd, name, _DIR, path)))
                _own(dirs[-1][1], owner, _mode(st, dir_mode))
                continue
            with (
                _fd(_open_regular(sfd, name, os.path.join(src, rel), True)) as fd,
                _fd(_open_at(dfd, name, _NEW, path)) as out,
            ):
                digest, size = _digest(fd, out)
                _own(out, owner, _mode(st, file_mode))
                os.fsync(out)
            files.append((rel, digest, size))
        while dirs:
            _fsync_close(dirs.pop()[1])
    except BaseException:
        for _, fd in dirs:
            os.close(fd)
        entries.close()
        remove_tree(dst)
        raise
    return files


def remove_tree(path: str) -> None:
    """Delete a directory tree; absent is done; a link or special file inside refuses before anything is removed."""
    if not exists(path):
        return
    for _ in _tree(path):
        pass
    with _parent(path) as (pfd, name):
        with _fd(_open_at(pfd, name, _DIR, path)) as fd:
            for _, dirs, files, sub in os.fwalk(".", topdown=False, dir_fd=fd):
                for n in files:
                    os.unlink(n, dir_fd=sub)
                for n in dirs:
                    os.rmdir(n, dir_fd=sub)
        os.rmdir(name, dir_fd=pfd)
        os.fsync(pfd)


def remove(path: str) -> None:
    """Delete one file (a link itself, never its target, and never a directory); absent is done."""
    try:
        with _parent(path) as (dfd, name):
            os.unlink(name, dir_fd=dfd)
            os.fsync(dfd)
    except FileNotFoundError:
        return


def statvfs(path: str) -> tuple[int, int]:
    """(st_dev, bytes available) of the filesystem holding `path`."""
    v = os.statvfs(path)
    return os.stat(path).st_dev, v.f_bavail * v.f_frsize


def tree_size(path: str) -> int:
    """Bytes in regular files below `path`, for estimates over live data: follows no link, skips what vanishes."""
    total = 0
    with _fd(_open_dir(path)) as fd:
        for _, _, files, sub in os.fwalk(".", dir_fd=fd):
            for name in files:
                with contextlib.suppress(FileNotFoundError):
                    st = os.stat(name, dir_fd=sub, follow_symlinks=False)
                    total += st.st_size if stat.S_ISREG(st.st_mode) else 0
    return total
