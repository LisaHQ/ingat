"""Errors carry an exit code (LIFECYCLE §6) and a stable machine code; messages never hold secret values."""


class IngatError(Exception):
    exit_code = 1
    code = "refused"

    def __init__(self, message: str, *, code: str | None = None, next: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.next = next


class Refused(IngatError):
    """Nothing changed: invalid input, policy, stale plan, capacity, wrong state."""

    exit_code = 1


class CannotRun(IngatError):
    """Nothing changed: daemon unreachable, lock busy, open operation, untested platform, usage."""

    exit_code = 2
    code = "cannot-run"


class Failed(IngatError):
    exit_code = 3
    code = "failed"


class NeedsAttention(IngatError):
    exit_code = 4
    code = "attention"
