"""The append-only step log of one operation: intent before effect, one fsynced JSON line per record
(ARCHITECTURE §7.3)."""

import os
import signal
from typing import Any

from ingat.model import records
from ingat.model.errors import Refused
from ingat.store import fs

PHASES = ("intent", "done", "failed", "unknown", "cancelled")
STEPS = "steps.jsonl"
PROGRESS = "progress.log"


def heal(path: str) -> bytes:
    """The complete lines of an append-only JSON Lines file. A torn last line (a write cut by a power loss) is first
    dropped from the file, so the next append starts a fresh line instead of corrupting a record."""
    data = fs.read(path) if fs.exists(path) else b""
    if data and not data.endswith(b"\n"):
        data = data[: data.rfind(b"\n") + 1]
        fs.replace_atomic(path, data)
    return data


class Journal:
    def __init__(self, op_dir: str, seq: int, crash_at: str | None = None) -> None:
        self.op_dir = op_dir
        self.seq = seq
        self.crash_at = crash_at
        self.healed = False

    def _crash(self, point: str) -> None:
        """Test-only hook: SIGKILL this process at a named point (never passed by the wrapper)."""
        if self.crash_at == point:
            os.kill(os.getpid(), signal.SIGKILL)

    def _append(self, step: int, phase: str, attempt: int | None, evidence: dict[str, Any] | None) -> None:
        rec: dict[str, Any] = {"seq": self.seq, "step": step, "phase": phase, "at": records.iso(records.utc_now())}
        if attempt is not None:
            rec["attempt"] = attempt
        if evidence:
            rec["evidence"] = evidence
        path = os.path.join(self.op_dir, STEPS)
        if not self.healed:  # only an earlier process can have left a torn line
            heal(path)
            self.healed = True
        self._crash(f"{step}:{phase}:before")
        fs.append_line(path, records.dumps(rec))
        self._crash(f"{step}:{phase}:after")

    def intent(self, step: int, attempt: int, evidence: dict[str, Any] | None = None) -> None:
        self._append(step, "intent", attempt, evidence)

    def close_step(self, step: int, phase: str, evidence: dict[str, Any] | None = None) -> None:
        if phase not in PHASES[1:]:
            raise ValueError(phase)
        self._append(step, phase, None, evidence)

    def task_started(self, step: int) -> None:
        self._crash(f"{step}:task")

    def progress(self, text: str) -> None:
        line = f"{records.iso(records.utc_now())} {text}"
        fs.append_line(os.path.join(self.op_dir, PROGRESS), line.encode())

    def replay(self) -> dict[int, dict[str, Any]]:
        """Last record per step plus its intent count; a torn last line counts as never written."""
        path = os.path.join(self.op_dir, STEPS)
        if not fs.exists(path):
            return {}
        lines = fs.read(path).split(b"\n")  # read-only: healing is the next writer's job
        out: dict[int, dict[str, Any]] = {}
        for i, line in enumerate(lines):
            if not line:
                continue
            try:
                rec = records.loads(line)
            except Refused:
                if i == len(lines) - 1:
                    break
                raise
            step = rec["step"]
            attempts = out.get(step, {}).get("attempts", 0) + (rec["phase"] == "intent")
            evidence = rec.get("evidence") if rec["phase"] == "done" else out.get(step, {}).get("done_evidence")
            out[step] = {**rec, "attempts": attempts, "done_evidence": evidence}
        return out
