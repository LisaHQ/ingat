"""Runner behaviour with real child processes (POSIX only: runs in the Linux test container)."""

import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import quote

from ingat.adapters import runner
from ingat.adapters.runner import Redactor, run
from ingat.model.errors import CannotRun

SECRET = "Zq7xK2mVb9TwLp4R"
ODD = "p@ss word/äé"


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):  # reaped before the open, or between the open and the read
        return False


def gone(pid: int, wait: float = 3.0) -> bool:
    end = time.monotonic() + wait
    while alive(pid):
        if time.monotonic() > end:
            return False
        time.sleep(0.05)
    return True


class RedactorTest(unittest.TestCase):
    def test_value_and_url_encoded_form_but_not_short_values(self) -> None:
        r = Redactor([ODD, "abc"])
        text = f"a {ODD} b {quote(ODD, safe='')} c abc"
        self.assertEqual(r.redact(text), "a *** b *** c abc")

    def test_overlapping_secrets_are_masked_as_one(self) -> None:
        r = Redactor(["wxyz12", "z1234567", "aaaa"])
        self.assertEqual(r.redact("a wxyz1234567 b aaaaaa c"), "a *** b *** c")

    def test_stream_split_anywhere_equals_whole_redaction(self) -> None:
        r = Redactor(["abcd", "abcdefgh", "wxyz12", "z1234567", SECRET, ODD])
        raw = f"x abcdefgh y {SECRET}{SECRET} {quote(ODD, safe='')} wxyz1234567 {ODD} abcd".encode()
        whole = r.redact_bytes(raw)[0]
        self.assertEqual(whole, b"x *** y ****** *** *** *** ***")
        for i in range(len(raw) + 1):
            for j in range(i, len(raw) + 1):
                a, tail, masked = r.redact_bytes(raw[:i], final=False)
                b, tail, masked = r.redact_bytes(tail + raw[i:j], final=False, masked=masked)
                c, _, _ = r.redact_bytes(tail + raw[j:], masked=masked)
                self.assertEqual(a + b + c, whole, (i, j))

    def test_prefix_secret_waits_for_the_longer_one(self) -> None:
        r = Redactor(["abcd", "abcdefgh"])
        out, tail, masked = r.redact_bytes(b"..abcd", final=False)
        more, _, _ = r.redact_bytes(tail + b"efgh", masked=masked)
        self.assertEqual(out + more, b"..***")


class RunTest(unittest.TestCase):
    def test_exit_code_and_both_streams(self) -> None:
        r = run(["sh", "-c", "echo out; echo err >&2; exit 3"])
        self.assertEqual((r.code, r.out, r.err, r.timed_out, r.truncated), (3, "out\n", "err\n", False, False))

    def test_environment_is_allowlisted(self) -> None:
        environ = {"PATH": os.environ["PATH"], "HOME": "/nowhere", "LEAK_ME": "1", "DOCKER_HOST": "tcp://x"}
        with mock.patch.dict(os.environ, environ, clear=True):
            seen = dict(line.split("=", 1) for line in run(["env"], env={"EXTRA": "x"}).out.splitlines())
            self.assertEqual(seen, {"PATH": environ["PATH"], "HOME": "/nowhere", "EXTRA": "x"})
            seen = dict(line.split("=", 1) for line in run(["env"], env={"HOME": "/tool"}).out.splitlines())
            self.assertEqual(seen["HOME"], "/tool")

    def test_secret_split_across_reads_is_redacted(self) -> None:
        code = (
            "import sys, time\n"
            f"s = {SECRET!r}\n"
            "for f in (sys.stdout, sys.stderr):\n"
            "    f.write('before ' + s[:7]); f.flush()\n"
            "time.sleep(0.4)\n"
            "for f in (sys.stdout, sys.stderr):\n"
            "    f.write(s[7:] + ' after\\n'); f.flush()\n"
        )
        r = run(py(code), redactor=Redactor([SECRET]))
        self.assertEqual((r.out, r.err), ("before *** after\n", "before *** after\n"))

    def test_url_encoded_secret_is_redacted(self) -> None:
        r = run(py(f"print({quote(ODD, safe='')!r}, {ODD!r})"), redactor=Redactor([ODD]))
        self.assertEqual(r.out, "*** ***\n")

    def test_capture_is_bounded_and_never_cuts_a_secret_open(self) -> None:
        r = run(py(f"print('x' * 998 + {SECRET!r} + 'y' * 5000)"), limit=1000, redactor=Redactor([SECRET]))
        self.assertTrue(r.truncated)
        self.assertEqual(r.out, "x" * 998 + "**")
        self.assertFalse(run(["echo", "short"], limit=1000).truncated)

    def test_file_streams_are_byte_exact_and_never_redacted(self) -> None:
        payload = os.urandom(300_000) + SECRET.encode() + b"\x00\xff" + quote(SECRET).encode()
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "in"), os.path.join(d, "out")
            with open(src, "wb") as f:
                f.write(payload)
            with open(src, "rb") as fin, open(dst, "wb") as fout:
                r = run(["cat"], stdin=fin.fileno(), stdout=fout.fileno(), limit=10, redactor=Redactor([SECRET]))
            with open(dst, "rb") as f:
                self.assertEqual(f.read(), payload)
        self.assertEqual((r.code, r.out, r.truncated), (0, "", False))

    def test_large_stdin_bytes_and_both_pipes_drain_concurrently(self) -> None:
        data = b"abcdefgh" * 200_000
        r = run(["cat"], stdin=data, limit=len(data), timeout=20)
        self.assertEqual((r.code, r.out.encode(), r.timed_out), (0, data, False))
        code = "import sys; sys.stderr.write('e' * 500000); sys.stdout.write('o' * 500000)"
        r = run(py(code), timeout=20)
        self.assertEqual((len(r.err), len(r.out), r.timed_out), (500_000, 500_000, False))

    def test_inherit_passes_the_callers_streams_and_none_is_dev_null(self) -> None:
        stdin_r, stdin_w = os.pipe()
        out_r, out_w = os.pipe()
        saved = os.dup(0), os.dup(1)
        sys.stdout.flush()
        os.dup2(stdin_r, 0)
        os.dup2(out_w, 1)
        try:
            os.write(stdin_w, b"typed\n")
            os.close(stdin_w)
            shown = run(["cat"], stdin="inherit", stdout="inherit", redactor=Redactor(["typed"]))
            closed = run(["readlink", "/proc/self/fd/0"])
        finally:
            os.dup2(saved[0], 0)
            os.dup2(saved[1], 1)
            for fd in (*saved, stdin_r, out_w):
                os.close(fd)
        with os.fdopen(out_r, "rb") as f:
            self.assertEqual(f.read(), b"typed\n")
        self.assertEqual((shown.code, shown.out, shown.truncated), (0, "", False))
        self.assertEqual(closed.out, "/dev/null\n")

    def test_timeout_stops_the_whole_group(self) -> None:
        start = time.monotonic()
        r = run(["sh", "-c", "sleep 30 & echo $!; wait"], timeout=1)
        self.assertTrue(r.timed_out)
        self.assertIsNone(r.code)
        self.assertLess(time.monotonic() - start, 6)
        self.assertTrue(gone(int(r.out.split()[0])))

    def test_sigkill_after_the_grace_period(self) -> None:
        with mock.patch.object(runner, "KILL_GRACE", 0.5):
            start = time.monotonic()
            r = run(["sh", "-c", "trap '' TERM; sleep 30 & echo $!; wait"], timeout=0.5)
        self.assertTrue(r.timed_out)
        self.assertLess(time.monotonic() - start, 5)
        self.assertTrue(gone(int(r.out.split()[0])))

    def test_tick_runs_while_waiting_and_a_raising_tick_stops_the_group(self) -> None:
        ticks: list[float] = []
        r = run(["sh", "-c", "sleep 1.3; exit 4"], stdout="inherit", stderr="inherit", tick=lambda: ticks.append(1))
        self.assertEqual((r.code, r.timed_out), (4, False))  # no pipe open: the exit itself ends the wait
        self.assertGreaterEqual(len(ticks), 2)

        class Cancel(Exception):
            pass

        def cancel() -> None:
            raise Cancel

        with tempfile.TemporaryDirectory() as d:
            pid_file = os.path.join(d, "pid")
            start = time.monotonic()
            with self.assertRaises(Cancel):
                run(["sh", "-c", f"sleep 30 & echo $! > {pid_file}; wait"], tick=cancel)
            self.assertLess(time.monotonic() - start, 5)
            with open(pid_file) as f:
                self.assertTrue(gone(int(f.read())))

    def test_an_interrupt_during_the_grace_period_still_kills_the_group(self) -> None:
        def cancel() -> None:
            threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT)).start()
            raise RuntimeError("cancel")

        with tempfile.TemporaryDirectory() as d:
            pid_file = os.path.join(d, "pid")
            start = time.monotonic()
            with self.assertRaises(KeyboardInterrupt):
                run(["sh", "-c", f"trap '' TERM; sleep 30 & echo $! > {pid_file}; wait"], tick=cancel)
            self.assertLess(time.monotonic() - start, 5)
            with open(pid_file) as f:
                self.assertTrue(gone(int(f.read())))

    def test_missing_binary_cannot_run(self) -> None:
        with self.assertRaises(CannotRun) as cm:
            run(["/nonexistent/tool"])
        self.assertEqual(cm.exception.exit_code, 2)


if __name__ == "__main__":
    unittest.main()
