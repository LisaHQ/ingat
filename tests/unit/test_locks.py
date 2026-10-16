import multiprocessing
import os
import tempfile
import unittest
from typing import Any

from ingat.model.errors import CannotRun
from ingat.model.records import loads
from ingat.store.locks import Lock

HOLDER = {"op": "3-deploy", "command": ["deploy", "site"], "operator": "alice"}


def try_lock(path: str) -> tuple[str, str]:
    """In another process: take and release the lock, or report the refusal."""
    try:
        with Lock(path, {"op": "9-backup", "command": "backup", "operator": "bob"}):
            return "acquired", ""
    except CannotRun as e:
        return e.code, e.message


def hold_lock(path: str, held: Any, release: Any) -> None:
    with Lock(path, {"op": "5-backup", "command": ["scheduled", "backup"], "operator": "cron"}):
        held.set()
        release.wait(30)


class LockTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "instances", "site", "lock")
        self.mp = multiprocessing.get_context("spawn")

    def other(self) -> tuple[str, str]:
        with self.mp.Pool(1) as pool:
            result: tuple[str, str] = pool.apply(try_lock, (self.path,))
        return result

    def test_another_process_is_refused_with_the_holder_named(self) -> None:
        with Lock(self.path, HOLDER):
            code, message = self.other()
        self.assertEqual(code, "lock-busy")
        for part in ("op 3-deploy", f"pid {os.getpid()}", "command deploy site", "operator alice", "started_at 2"):
            self.assertIn(part, message)
        self.assertEqual(self.other(), ("acquired", ""))
        self.assertTrue(os.path.isfile(self.path), "the lock file is never unlinked")

    def test_a_holder_in_another_process_excludes_this_one_until_it_releases(self) -> None:
        held, release = self.mp.Event(), self.mp.Event()
        proc = self.mp.Process(target=hold_lock, args=(self.path, held, release))
        proc.start()
        try:
            self.assertTrue(held.wait(30))
            with self.assertRaises(CannotRun) as cm, Lock(self.path, HOLDER):
                self.fail("lock taken while another process holds it")
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("lock-busy", 2))
            self.assertIn(f"pid {proc.pid}", cm.exception.message)
            self.assertIn("command scheduled backup", cm.exception.message)
        finally:
            release.set()
            proc.join(30)
        with Lock(self.path, HOLDER) as lock, open(lock.holder_path, "rb") as f:
            doc = loads(f.read())
        self.assertEqual((doc["op"], doc["pid"], doc["operator"]), ("3-deploy", os.getpid(), "alice"))

    def test_an_error_inside_releases_the_lock(self) -> None:
        with self.assertRaises(ValueError), Lock(self.path, HOLDER):
            raise ValueError("step failed")
        self.assertEqual(self.other(), ("acquired", ""))

    def test_busy_without_a_readable_holder_still_refuses(self) -> None:
        with Lock(self.path, HOLDER) as lock:
            os.unlink(lock.holder_path)
            code, message = self.other()
        self.assertEqual(code, "lock-busy")
        self.assertIn("holder unknown", message)


if __name__ == "__main__":
    unittest.main()
