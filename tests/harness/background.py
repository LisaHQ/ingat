"""Commands that run in the background while a suite acts on them, as the session-loss suite does
(tests/docker/test_it_session.py signals them mid-step): a command on a pty or not (`Proc`), and the scratch daemon's
container events as they happen (`EventStream`)."""

import contextlib
import json
import os
import pty
import select
import signal
import subprocess
import time
from collections.abc import Mapping
from typing import Any

from tests.harness.host import ENV, PROMPT, Result, now


class Proc:
    """A command started in the background, on a pty or not, whose output is collected whenever a method runs (no
    thread: `pty.fork` stays the only fork). On a pty both streams arrive in `out`, and `answer` is typed at the first
    approval prompt. `hangup` closes the terminal: the kernel then hangs up the command's session (SIGHUP), as a lost
    SSH connection does; `kill` signals the process; `type` writes to the terminal."""

    def __init__(self, argv: list[str], *, tty: bool = False, answer: str | None = None,
                 env: Mapping[str, str] | None = None) -> None:  # fmt: skip
        environ = {**ENV, **(env or {})}
        self.out, self.err = b"", b""
        self.code: int | None = None
        self._answer = None if answer is None else answer.encode() + b"\r"
        self._pty: int | None = None
        self._popen: subprocess.Popen[bytes] | None = None
        self._fds: dict[int, str] = {}
        if tty:
            self.pid, fd = pty.fork()
            if self.pid == 0:  # the child: the command on the pty
                try:
                    os.execvpe(argv[0], argv, environ)
                finally:
                    os._exit(127)
            self._pty, self._fds = fd, {fd: "out"}
        else:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=environ)  # fmt: skip
            assert p.stdout is not None and p.stderr is not None
            self.pid, self._popen = p.pid, p
            self._fds = {p.stdout.fileno(): "out", p.stderr.fileno(): "err"}
            for f in (p.stdout, p.stderr):
                os.set_blocking(f.fileno(), False)

    def drain(self, wait: float = 0.0) -> None:
        """Collect what the command printed, waiting up to `wait` seconds for the first bytes."""
        while self._fds:
            ready = select.select(list(self._fds), [], [], wait)[0]
            if not ready:
                return
            wait = 0.0
            for fd in ready:
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                except OSError:  # EIO: the pty's last process is gone
                    chunk = b""
                if not chunk:
                    self._close(fd)
                elif self._fds[fd] == "err":
                    self.err += chunk
                else:
                    self.out += chunk
            if self._answer is not None and PROMPT in self.out:
                self.type(self._answer.decode())
                self._answer = None

    def _close(self, fd: int) -> None:
        self._fds.pop(fd, None)
        if fd == self._pty:
            os.close(fd)
            self._pty = None

    def type(self, text: str) -> None:
        if self._pty is None:
            raise AssertionError("the command has no terminal (any more)")
        os.write(self._pty, text.encode())

    def hangup(self) -> None:
        """Close the terminal; what it still held is collected first."""
        self.drain()
        if self._pty is not None:
            self._close(self._pty)

    def kill(self, sig: int) -> None:
        os.kill(self.pid, sig)

    def poll(self) -> int | None:
        """The exit code once the command has ended (-N for signal N), else None."""
        self.drain()
        if self.code is None:
            if self._popen is not None:
                self.code = self._popen.poll()
            elif (done := os.waitpid(self.pid, os.WNOHANG))[0]:
                self.code = os.waitstatus_to_exitcode(done[1])
        return self.code

    def text(self) -> str:
        return self.out.decode(errors="replace").replace("\r\n", "\n")

    def wait_for(self, needle: str, timeout: float = 120) -> None:
        """Until the output holds `needle`; fails when the command ends or the time is up first."""
        end = time.monotonic() + timeout
        while needle not in self.text():
            if self.poll() is not None or time.monotonic() > end:
                raise AssertionError(f"no {needle!r} in the output (exit {self.code}):\n{self.text()}")
            self.drain(0.2)

    def wait(self, timeout: float = 300) -> Result:
        """(exit, stdout, stderr) once the command has ended and its streams are closed; SIGKILL after `timeout`."""
        end = time.monotonic() + timeout
        while self.poll() is None or self._fds:
            if time.monotonic() > end:
                if self.code is None:
                    os.kill(self.pid, signal.SIGKILL)
                raise AssertionError(f"the command did not end within {timeout}s:\n{self.text()}")
            self.drain(0.2)
        assert self.code is not None
        return self.code, self.text(), self.err.decode(errors="replace")

    def close(self) -> None:
        """Make sure the command is gone (a cleanup: a failed test may leave it running)."""
        if self.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.pid, signal.SIGKILL)
            with contextlib.suppress(AssertionError):
                self.wait(30)
        for fd in list(self._fds):
            self._close(fd)
        if self._popen is not None:
            for f in (self._popen.stdout, self._popen.stderr):
                if f is not None:
                    f.close()


class EventStream:
    """The daemon's container events from now on, streamed (`docker events --since <now>`, no end). `events(since,
    until)` replays the daemon's in-memory event buffer, which keeps only the newest few hundred events: on a scratch
    daemon that parallel suites share (probe execs alone add events every few seconds) the start of a window can be
    gone within seconds. A stream keeps every event; `events()` returns those that arrived so far."""

    def __init__(self) -> None:
        self._p = Proc(["docker", "events", "--since", now(), "--format", "{{json .}}", "--filter", "type=container"])

    def events(self, settle: float = 1.0) -> list[dict[str, Any]]:
        """Every event so far, after `settle` seconds for those in flight."""
        end = time.monotonic() + settle
        while (left := end - time.monotonic()) > 0:
            self._p.drain(left)
        text = self._p.out.decode(errors="replace")
        return [json.loads(x) for x in text[: text.rfind("\n") + 1].splitlines() if x.strip()]

    def close(self) -> None:
        self._p.close()
