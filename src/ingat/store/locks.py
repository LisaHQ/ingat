"""Instance and host locks: a non-blocking flock on a never-unlinked file (ARCHITECTURE §7.4)."""

import fcntl
import os
from typing import Any, Self

from ingat.model.errors import CannotRun, Refused
from ingat.model.records import iso, loads, pretty, utc_now
from ingat.store import fs

_SHOWN = ("op", "pid", "command", "operator", "started_at")


class Lock:
    """Held while the context is open; busy refuses at once (exit 2) naming the holder from `<path>.holder.json`."""

    def __init__(self, path: str, holder: dict[str, Any]) -> None:
        self.path = path
        self.holder_path = path + ".holder.json"
        self.holder = holder
        self.fd: int | None = None

    def __enter__(self) -> Self:
        fs.mkdirs(os.path.dirname(self.path))
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException as e:
            os.close(fd)
            if isinstance(e, BlockingIOError):
                why = (
                    f"Another command is still running and holds the lock {self.path} ({self._held_by()}). Wait for "
                    "it to finish, then try again. Nothing was changed."
                )
                raise CannotRun(why, code="lock-busy") from e
            raise
        self.fd = fd
        try:
            fs.replace_atomic(
                self.holder_path, pretty({"pid": os.getpid(), "started_at": iso(utc_now()), **self.holder})
            )
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _held_by(self) -> str:
        try:
            doc = loads(fs.read(self.holder_path))
        except (FileNotFoundError, Refused):
            doc = None
        if not isinstance(doc, dict):
            return "holder unknown"
        show = {k: " ".join(map(str, v)) if isinstance(v, list) else v for k, v in doc.items()}
        return ", ".join(f"{k} {show.get(k)}" for k in _SHOWN)
