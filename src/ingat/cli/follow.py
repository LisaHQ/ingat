"""Launch the detached executor and follow its operation (ARCHITECTURE §4.2, §4.4).

The executor container gets the wrapper's mounts and environment allowlist; the follower prints `progress.log` and
ends with the run file the executor leaves. Losing the follower (Ctrl-C and detach, SIGTERM, SIGHUP) never stops the
operation: `attach` follows it again."""

import contextlib
import os
import secrets
import signal
import time
from collections.abc import Iterator
from typing import Any, TextIO

from ingat import brand
from ingat.cli import render
from ingat.cli.render import Report
from ingat.core import approval
from ingat.core.journal import PROGRESS
from ingat.core.plan import Plan
from ingat.model.errors import CannotRun, IngatError
from ingat.ops import context as cx
from ingat.ops.context import Ctx
from ingat.store import fs, state

POLL = 0.5
SOCKET = "/var/run/docker.sock"
FLAGS = {"resume": ["--resume"], "abandon": ["--abandon"]}  # plans that re-enter the open operation
CHOICE = (  # Ctrl-C while following on a terminal; anything but `c` detaches
    "\nYou pressed Ctrl-C. The operation is still running. Type d to stop watching it (it keeps running), or c to "
    "ask it to stop at its next safe point; Enter alone stops watching.\n[d]etach or [c]ancel? "
)


class Detach(Exception):
    """Stop following; the operation runs on."""


def launch_and_follow(ctx: Ctx, plan: Plan, out: TextIO | None) -> Report:
    """Write the approved plan (write-once), start `<prefix><instance>` running `_exec`, follow it."""
    if not ctx.image:
        raise CannotRun(
            f"This command must be started through the `{brand.CLI}` script that the installer created (the setting "
            f"{brand.env('IMAGE')} is missing, so it was started some other way). Nothing was changed.",
            code="no-image",
        )
    run_id, root, backups = secrets.token_hex(8), ctx.layout.root, ctx.layout.backups
    plan_hash = approval.save(ctx.layout, plan)
    args = ["_exec", plan.instance or "--host", plan_hash, run_id, *FLAGS.get(plan.op_kind, [])]
    mounts = [f"{SOCKET}:{SOCKET}", f"{root}:{root}", f"{backups}:{backups}"]
    mounts.append(f"{brand.PROBE_VOLUME}:{brand.PROBE_MOUNT}:ro")
    facts = [os.path.join(brand.HOST_FACTS_DIR, rel) for rel in cx.RELEASE_FILES]
    mounts += [f"{p.removeprefix(brand.HOST_FACTS_DIR)}:{p}:ro" for p in facts if fs.exists(p)]  # same host files
    env = {"ROOT": root, "BACKUPS": backups, "IMAGE": ctx.image, "HOST": ctx.hostname, "OPERATOR": ctx.operator}
    env["WRAPPER_VERSION"] = os.environ.get(brand.env("WRAPPER_VERSION"), "")
    if crash := os.environ.get(brand.env("CRASH_AT")):  # the test-only hook; the wrapper's `env -i` never passes it
        env["CRASH_AT"] = crash
    labels = {brand.label("role"): "exec"} | ({brand.label("instance"): plan.instance} if plan.instance else {})
    op_dir = plan.inputs.get("op_dir")  # a resume or a joined task appends to the open operation's progress
    log = os.path.join(op_dir, PROGRESS) if op_dir else ""
    offset = os.path.getsize(log) if log and fs.exists(log) else 0
    name, env = brand.executor_name(plan.instance), {brand.env(k): v for k, v in env.items()}
    try:
        cid = ctx.docker.launch_executor(name=name, image=ctx.image, args=args, mounts=mounts, env=env, labels=labels)
    except KeyboardInterrupt:  # the launch may have reached the daemon: then the operation runs on
        if not any(run_id in (c["Config"].get("Cmd") or ()) for c in ctx.docker.inspect("container", [name])):
            raise
        return _detached(plan.instance)
    return follow(ctx, plan.instance, op_dir, cid, run_id, out, offset)


def attach(ctx: Ctx, name: str, out: TextIO | None) -> Report:
    """Follow the open operation of `name` until its executor container is gone."""
    cx.load(ctx, name)
    found = state.open_ops(ctx.layout, name)
    if not found:
        why = f"{name} has no operation running or waiting, so there is nothing to watch."
        return {"exit": 0, "code": "no-open-operation", "next": f"{brand.CLI} status {name}", "lines": [why]}
    return follow(ctx, name, ctx.layout.op_dir(name, *found[-1]), brand.executor_name(name), None, out)


def follow(
    ctx: Ctx, name: str | None, op_dir: str | None, container: str, run_id: str | None, out: Any, offset: int = 0
) -> Report:
    """Print progress from `offset` until the run file `run_id` exists, or the executor container no longer runs (an
    exited one whose removal lags or failed counts as gone)."""
    run = ctx.layout.run(run_id) if run_id else None
    with _signals():
        while True:
            try:
                offset = _pump(op_dir, offset, out)
                if run and fs.exists(run):
                    _pump(op_dir, offset, out)
                    return _outcome(state.read_doc(run, "run"), name)
                if not _runs(ctx, container):
                    if run and fs.exists(run):
                        continue
                    _pump(op_dir, offset, out)
                    return _gone(ctx, name, op_dir, run is not None)
                time.sleep(POLL)
            except KeyboardInterrupt:
                if not (ctx.tty and name and _cancel(ctx, name, out)):
                    return _detached(name)
            except Detach:
                return _detached(name)


def _runs(ctx: Ctx, container: str) -> bool:
    """Whether the executor still runs. An unreachable daemon took it down with it (or `status` will tell): never
    exit 2, `nothing changed`, after the operation may have acted."""
    try:
        return any(c["State"].get("Running") for c in ctx.docker.inspect("container", [container]))
    except CannotRun:
        return False


def _pump(op_dir: str | None, offset: int, out: TextIO | None) -> int:
    """Print the complete new lines of progress.log; returns the new offset."""
    path = os.path.join(op_dir, PROGRESS) if op_dir else ""
    if not path or not fs.exists(path):
        return offset
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    end = data.rfind(b"\n") + 1
    render.say(out, data[:end].decode(errors="replace").splitlines())
    return offset + end


def _outcome(doc: dict[str, Any], name: str | None) -> Report:
    """The answer the executor decided, from its run file or the operation's result.json: `--json` carries its
    message too, as it does for an error the CLI decides."""
    return {"exit": doc["exit"], "code": doc["code"], "message": doc["message"], "next": doc.get("next"),
            "op": doc.get("op"), "instance": name, "lines": [doc["message"]]}  # fmt: skip


def _gone(ctx: Ctx, name: str | None, op_dir: str | None, launched: bool) -> Report:
    """The executor container is gone: the operation's result, else it is still open (exit 4)."""
    status = f"{brand.CLI} status {name}" if name else f"{brand.CLI} status"
    result = os.path.join(op_dir, "result.json") if op_dir else ""
    if result and fs.exists(result):
        return _outcome(state.read_doc(result, "result"), name)
    code = "executor-vanished" if launched else "open-operation"
    if launched:
        why = "The background worker that was running this operation disappeared before it reported a result, so the "
        why += f"operation may be unfinished. Run `{status}` to see where it stands and what to do next."
    else:
        why = f"An operation on {name} was left unfinished and nothing is working on it right now. Run `{status}` to "
        why += "see where it stopped and what to do next."
    return {"exit": 4, "code": code, "message": why, "next": status, "instance": name, "lines": [why]}


def _detached(name: str | None) -> Report:
    nxt = f"{brand.CLI} attach {name}" if name else None
    why = "Stopped watching. The operation keeps running in the background and was not cancelled."
    return {"exit": 4, "code": "detached", "message": why, "next": nxt, "instance": name, "lines": [why]}


def _cancel(ctx: Ctx, name: str, out: TextIO | None) -> bool:
    """Ctrl-C on a terminal: True to follow on (cancel requested, or not possible yet), False to detach. A second
    interrupt or a lost session while asking detaches."""
    from ingat.ops import lifecycle

    try:
        if not render.ask(CHOICE).strip().lower().startswith("c"):
            return False
        render.say(out, lifecycle.cancel(ctx, name).get("lines") or ["cancel requested"])
    except (KeyboardInterrupt, Detach):
        return False
    except IngatError as e:  # no open operation yet: the executor has not opened it
        render.say(out, [f"Cannot cancel now: {e.message}. Still watching; press Ctrl-C again to choose again "
                         "(d stops watching)."])  # fmt: skip
    return True


@contextlib.contextmanager
def _signals() -> Iterator[None]:
    """SIGTERM and SIGHUP detach (a lost session); SIGINT raises KeyboardInterrupt as usual."""

    def detach(signum: int, frame: object) -> None:
        raise Detach

    old = {s: signal.signal(s, detach) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for s, handler in old.items():
            signal.signal(s, handler)
