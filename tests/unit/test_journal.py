"""The step journal: intent before effect, attempts, done evidence, torn last lines and the crash hook."""

import os
import signal
import subprocess
import sys
import tempfile
import unittest

from ingat.core.journal import Journal
from ingat.model.errors import Refused


class JournalTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = os.path.join(tmp.name, "ops", "3-backup")
        self.journal = Journal(self.dir, 3)

    def lines(self) -> bytes:
        with open(os.path.join(self.dir, "steps.jsonl"), "rb") as f:
            return f.read()

    def test_replay_counts_attempts_and_keeps_the_last_done_evidence(self) -> None:
        j = self.journal
        self.assertEqual(j.replay(), {})
        j.intent(1, 1)
        j.close_step(1, "done", {"bundle_id": "a"})
        j.intent(2, 1)
        j.close_step(2, "unknown")
        j.intent(1, 2)
        rep = j.replay()
        self.assertEqual(
            (rep[1]["phase"], rep[1]["attempts"], rep[1]["done_evidence"]), ("intent", 2, {"bundle_id": "a"})
        )
        self.assertEqual((rep[2]["phase"], rep[2]["attempts"], rep[2]["done_evidence"]), ("unknown", 1, None))
        j.close_step(1, "done", {"bundle_id": "b"})
        self.assertEqual(j.replay()[1]["done_evidence"], {"bundle_id": "b"})
        self.assertTrue(all(b'"seq":3' in line for line in self.lines().splitlines()))
        with self.assertRaises(ValueError):
            j.close_step(1, "intent")

    def test_a_torn_last_line_counts_as_never_written(self) -> None:
        self.journal.intent(1, 1)
        with open(os.path.join(self.dir, "steps.jsonl"), "ab") as f:
            f.write(b'{"seq":3,"step":1,"pha')
        self.assertEqual(self.journal.replay()[1]["phase"], "intent")
        with open(os.path.join(self.dir, "steps.jsonl"), "ab") as f:
            f.write(b"\n" + self.lines().splitlines()[0] + b"\n")
        with self.assertRaises(Refused):  # a broken line before the end is corruption, not a crash
            self.journal.replay()

    def test_an_append_after_a_torn_tail_starts_a_fresh_line(self) -> None:
        """A write cut by a power loss must not glue onto the next record and corrupt the whole journal."""
        self.journal.intent(1, 1)
        with open(os.path.join(self.dir, "steps.jsonl"), "ab") as f:
            f.write(b'{"seq":3,"step":1,"pha')
        later = Journal(self.dir, 3)  # the next executor process
        later.close_step(1, "unknown", {"why": "observed"})
        rep = later.replay()
        self.assertEqual((rep[1]["phase"], rep[1]["attempts"], rep[1]["evidence"]), ("unknown", 1, {"why": "observed"}))
        self.assertEqual(len(self.lines().splitlines()), 2)

    def test_progress_lines_are_stamped(self) -> None:
        self.journal.progress("step 1 Obtain: started")
        with open(os.path.join(self.dir, "progress.log"), encoding="utf-8") as f:
            self.assertRegex(f.read(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ step 1 Obtain: started\n$")

    def test_crash_hook_kills_the_process_at_the_named_point(self) -> None:
        code = "import sys; from ingat.core.journal import Journal; j = Journal(sys.argv[1], 3, '2:intent:after'); "
        code += "j.intent(1, 1); j.close_step(1, 'done'); j.intent(2, 1); j.close_step(2, 'done')"
        res = subprocess.run([sys.executable, "-c", code, self.dir], check=False)
        self.assertEqual(res.returncode, -signal.SIGKILL)
        self.assertEqual(self.journal.replay()[2]["phase"], "intent")
        Journal(self.dir, 3, None).task_started(2)  # without the hook nothing happens


if __name__ == "__main__":
    unittest.main()
