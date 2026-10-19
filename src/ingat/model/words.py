"""The plain words of the messages people read (README conventions): one fixed pairing per internal term, shared by
the layers that print it. The machine `code` strings beside these lines never change."""

from ingat import brand

WRITERS = "the parts of the app that change your data"
# Why an instance is frozen (LIFECYCLE §3.4): a failed or abandoned update, or a first install, past its forward point.
FROZEN = f"an operation stopped after it had started changing your data, so {WRITERS} are kept stopped on purpose"
ENGINE_MISMATCH = f"this is a different Docker engine than the one this {brand.PRODUCT} folder was set up with"
NOT_INITIALIZED = f"this computer has not been set up for {brand.PRODUCT} yet"
# Why live information was not read from Docker, by the daemon state status reports.
UNCHECKED = {"unreachable": "Docker could not be reached", "engine-mismatch": ENGINE_MISMATCH}
# A bundle's verification level (F10), by the newest level record that passed; None without one.
LEVELS: dict[str | None, str] = {
    "restore-tested": "checked and test-restored (restore-tested)",
    "verified": "checked (verified)",
    None: "not checked yet",
}
# How a closed operation ended, by its outcome (LIFECYCLE §3.2, §3.5).
ENDED = {
    "failed-unchanged": "failed before changing anything",
    "failed-frozen": f"failed after it had started changing your data, so {WRITERS} are kept stopped",
    "needs-review": "could not fully undo or clean up, or its result is uncertain, so it needs your attention",
}
# How an operation ended, for its last progress line (`completed` needs no words): the closed-operation words plus
# the two abandons (LIFECYCLE §3.4); past the forward point an abandon undoes nothing and keeps the writers stopped.
OUTCOME_WORDS = {
    **ENDED,
    "abandoned": "abandoned at your request; what could safely be undone was undone",
    "abandoned-auto": "abandoned automatically to make way for the new command; what could safely be undone was undone",
}
# Each step type in plain words (plan summaries, progress lines); a type not listed here prints bare.
STEP_WORDS = {
    "Obtain": "get the app's images",
    "CreateGeneration": "make a new area for the app's data; the current data is kept",
    "Up": "start the app's services",
    "Stop": "stop the app's services",
    "RunTask": "run an app task",
    "CaptureBundle": "make a backup copy",
    "VerifyBundle": "check a backup copy",
    "Teardown": "remove the containers and temporary data this run made",
    "Delete": "delete the one item named",
    "Record": "write a record",
    "Pause": "pause and wait for you",
}
# What each gate tier lets run on this computer (ARCHITECTURE §3.6); None when Docker was not read.
TIERS = {
    None: "unknown, Docker was not read",
    0: "read-only commands only",
    1: "only backups and checks that leave the app running; nothing that changes the app until this Docker build "
    "is certified",
    2: "everything",
}


def foreign(name: str) -> str:
    """Why a Docker object of the instance's project is foreign (F8): not labelled as the instance's own, whoever
    made it; an object of another or an earlier instance of the same name is foreign too."""
    did = f"{brand.PRODUCT} did not create it for {name}"
    return f"sits in this app's Docker project but does not belong to this instance ({did}); it is left untouched"
