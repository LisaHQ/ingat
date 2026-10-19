"""The only subprocess user: argv only, allowlisted environment, own process group, timeouts, byte-exact file
streams, and bounded, redacted capture of text streams with a held-back tail (ARCHITECTURE §5.1, §9.4)."""

import contextlib
import os
import re
import select
import selectors
import signal
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import IO, cast
from urllib.parse import quote

from ingat.model.errors import CannotRun

BASE_ENV_KEYS = ("PATH", "HOME")
TICK = 0.5
POLL = 0.02  # exit polling when no pipe is open
KILL_GRACE = 10.0
CHUNK = 1 << 16
MASK = b"***"


class Redactor:
    """Replaces every secret value (4 characters or more) and its URL-encoded form with ***; overlapping or
    chained occurrences become one mask, so no part of any secret survives."""

    def __init__(self, secrets: Iterable[str]) -> None:
        forms = {form.encode() for value in secrets if len(value) >= 4 for form in (value, quote(value, safe=""))}
        ordered = sorted(forms, key=len, reverse=True)  # the longest form wins where several start at one byte
        self._re = re.compile(b"|".join(re.escape(form) for form in ordered)) if ordered else None
        self.hold = len(ordered[0]) if ordered else 0

    def redact(self, text: str) -> str:
        return self.redact_bytes(text.encode(errors="surrogatepass"))[0].decode(errors="surrogatepass")

    def redact_bytes(self, buf: bytes, final: bool = True, masked: int = 0) -> tuple[bytes, bytes, int]:
        """Return (output, raw tail, length of the tail's head already masked). Unless `final`, the last hold-1
        bytes, where a secret may still start, are kept back for the next call (pass the tail first and `masked`
        along), so a stream fed chunk by chunk redacts exactly as the whole stream would."""
        if self._re is None:
            return buf, b"", 0
        cut = len(buf) if final else max(0, len(buf) - self.hold + 1)
        parts: list[bytes] = []
        end = masked  # bytes before `end` are emitted; a match that starts before it extends the open mask
        m = self._re.search(buf)
        while m is not None and m.start() < cut:
            if m.start() >= end:
                parts += [buf[end : m.start()], MASK]
            end = max(end, m.end())
            m = self._re.search(buf, m.start() + 1)
        parts.append(buf[end:cut])
        return b"".join(parts), buf[cut:], max(0, end - cut)


class _Capture:
    """One text stream: redacted as it arrives, the first `limit` redacted bytes kept."""

    def __init__(self, redactor: Redactor, limit: int) -> None:
        self.redactor, self.limit = redactor, limit
        self.tail = b""
        self.masked = 0
        self.kept = bytearray()
        self.truncated = False

    def feed(self, data: bytes, final: bool = False) -> None:
        done, self.tail, self.masked = self.redactor.redact_bytes(self.tail + data, final, self.masked)
        room = self.limit - len(self.kept)
        if len(done) > room:
            self.truncated = True
            done = done[:room]
        self.kept += done

    def text(self) -> str:
        self.feed(b"", final=True)
        return self.kept.decode(errors="replace")


@dataclass(frozen=True)
class Result:
    code: int | None  # None after a timeout; -N when a signal N ended the child
    out: str
    err: str
    timed_out: bool
    truncated: bool


def run(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: float = 300,
    stdin: bytes | int | str | None = None,
    stdout: str | int = "capture",
    stderr: str = "capture",
    limit: int = 1 << 20,
    redactor: Redactor | None = None,
    tick: Callable[[], None] | None = None,
    cwd: str | None = None,
) -> Result:
    """Run argv (never a shell) in its own process group. stdin: bytes, a byte-exact fd, None (/dev/null) or
    "inherit"; stdout: "capture", "inherit" (never captured) or a byte-exact fd; stderr: "capture" or "inherit".
    `tick` runs about every TICK seconds; if it raises, the group is terminated and the exception propagates."""
    base = {key: os.environ[key] for key in BASE_ENV_KEYS if key in os.environ}
    red = redactor or Redactor(())
    out, err = _Capture(red, limit), _Capture(red, limit)
    try:
        proc = subprocess.Popen(
            list(argv),
            stdin=_spec(stdin),
            stdout=_spec(stdout),
            stderr=_spec(stderr),
            env=base | dict(env or {}),
            cwd=cwd,
            start_new_session=True,
        )
    except OSError as e:
        why = f"The program {argv[0]} could not be started ({e.strerror}). Check that it is installed and on the PATH."
        raise CannotRun(why, code="cannot-start") from e
    with proc, selectors.DefaultSelector() as sel:
        try:
            if proc.stdin and isinstance(stdin, bytes):
                sel.register(proc.stdin, selectors.EVENT_WRITE, memoryview(stdin))
            for pipe, capture in ((proc.stdout, out), (proc.stderr, err)):
                if pipe:
                    sel.register(pipe, selectors.EVENT_READ, capture)
            timed_out = _pump(proc, sel, time.monotonic() + timeout, tick)
        except BaseException:
            _terminate(proc, sel)
            raise
        if timed_out:
            _terminate(proc, sel)
    out_text, err_text = out.text(), err.text()
    code = None if timed_out else proc.returncode
    return Result(code, out_text, err_text, timed_out, out.truncated or err.truncated)


def _spec(value: bytes | int | str | None) -> int | None:
    if isinstance(value, bytes):
        return subprocess.PIPE
    if value is None:
        return subprocess.DEVNULL
    return value if isinstance(value, int) else {"capture": subprocess.PIPE, "inherit": None}[value]


def _pump(
    proc: subprocess.Popen[bytes], sel: selectors.BaseSelector, deadline: float, tick: Callable[[], None] | None
) -> bool:
    """Move stream data until every pipe is closed and the child has exited; True when the deadline came first.
    The child is never reaped here, so its pid, the group id, cannot be reused while the group may be signalled."""
    next_tick = time.monotonic() + TICK
    while sel.get_map() or os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
        left = deadline - time.monotonic()
        if left <= 0:
            return True
        if sel.get_map():
            for key, _ in sel.select(min(TICK, left)):
                _transfer(sel, key)
        else:
            time.sleep(min(POLL, left))
        if tick is not None and time.monotonic() >= next_tick:
            next_tick = time.monotonic() + TICK
            tick()
    return False


def _transfer(sel: selectors.BaseSelector, key: selectors.SelectorKey) -> None:
    pipe = cast(IO[bytes], key.fileobj)
    if key.events & selectors.EVENT_WRITE:
        view: memoryview = key.data
        try:
            view = view[os.write(key.fd, view[: select.PIPE_BUF]) :]
        except BrokenPipeError:
            view = view[:0]  # the child stopped reading; its exit status tells the rest
        if view:
            sel.modify(pipe, selectors.EVENT_WRITE, view)
            return
    else:
        data = os.read(key.fd, CHUNK)
        if data:
            key.data.feed(data)
            return
    sel.unregister(pipe)
    pipe.close()


def _terminate(proc: subprocess.Popen[bytes], sel: selectors.BaseSelector) -> None:
    """SIGTERM the group, drain it for up to KILL_GRACE seconds, then SIGKILL whatever is left of it, even when an
    interrupt cuts the grace short."""
    _signal_group(proc.pid, signal.SIGTERM)
    try:
        _pump(proc, sel, time.monotonic() + KILL_GRACE, None)
    finally:
        _signal_group(proc.pid, signal.SIGKILL)
        proc.wait()


def _signal_group(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, sig)
