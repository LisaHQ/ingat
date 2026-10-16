"""The executor (LIFECYCLE §3, ARCHITECTURE §4): one operation per instance under its lock. Checks run first and
write nothing (F2); then intent before effect for every step (F5), undo or freeze on failure, resume and abandon.
The only constructor of EffectToken; opening, loading and joining an operation live in core/opening.py."""

import contextlib
import os
import signal
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from ingat import brand
from ingat.adapters.compose import Compose
from ingat.adapters.docker import Docker, EffectToken
from ingat.core import approval, opening, probes, steps, tasks
from ingat.core.plan import PROJECT_LABEL, Plan, Step, fingerprint
from ingat.core.steps import Cancelled, Op
from ingat.model import records
from ingat.model.errors import CannotRun, IngatError, NeedsAttention, Refused
from ingat.store import fs, state
from ingat.store.locks import Lock

AUTO_ABANDON = ("prepare", "backup", "verify", "drill")  # operations without a forward step (LIFECYCLE §3.4)
CLOSE = 0  # journal step of the close decision, written before the close acts on it
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)

_STEPS: dict[str, Callable[[Op, Step, EffectToken], dict[str, Any]]] = {
    "Obtain": steps.obtain,
    "CreateGeneration": steps.create_generation,
    "Up": probes.up,
    "Stop": steps.stop,
    "RunTask": tasks.run_task,
    "CaptureBundle": tasks.capture,
    "VerifyBundle": tasks.verify,
    "Teardown": steps.teardown,
    "Delete": steps.delete,
    "Record": steps.record,
}


@dataclass(frozen=True)
class Res:
    exit: int
    code: str
    message: str
    op: int | None
    next: str | None
    warnings: tuple[str, ...] = ()


def execute(
    layout: state.Layout, docker: Docker, compose: Compose, plan_hash: str, run_id: str, *, resume: bool = False,
    abandon: bool = False,
) -> int:  # fmt: skip
    """Entry of `_exec`: run a saved plan (or resume / abandon the open operation); always leaves the run file, which
    carries the plan's warnings too."""
    mode = "resume" if resume else "abandon" if abandon else "new"
    warned: list[str] = []
    with _signals():
        try:
            plan = approval.load(layout, plan_hash)
            warned = _warnings(plan)
            res = _run(layout, docker, compose, plan, mode, False, False)
        except IngatError as e:
            res = Res(e.exit_code, e.code, e.message, None, e.next)
        except BaseException:
            res = Res(4, "executor-error", "the executor stopped on an unexpected error", None, None)
            _run_file(layout, run_id, res, warned)
            raise
    _run_file(layout, run_id, res, warned)
    return res.exit


def run_in_process(layout: state.Layout, docker: Docker, compose: Compose, plan: Plan, *, tty: bool) -> int:
    """A foreground terminal task, or the resume of one: the CLI holds the lock and journals like the executor
    (ARCHITECTURE §4.3)."""
    with _signals():
        return _run(layout, docker, compose, plan, "resume" if plan.op_kind == "resume" else "new", True, tty).exit


@contextlib.contextmanager
def _signals() -> Iterator[None]:
    """SIGINT, SIGTERM, SIGHUP and SIGQUIT are cancel requests (ARCHITECTURE §4.4)."""

    def hit(signum: int, frame: object) -> None:
        opening.SIGNALLED[0] = True

    opening.SIGNALLED[0] = False
    old = {s: signal.signal(s, hit) for s in SIGNALS}
    try:
        yield
    finally:
        for s, handler in old.items():
            signal.signal(s, handler)


def _warnings(plan: Plan) -> list[str]:
    """Warnings the planner gave (an uncertified tier, a skipped retention): the result and run file repeat them."""
    return [str(w) for w in plan.inputs.get("warnings") or []]


def _run_file(layout: state.Layout, run_id: str, res: Res, warned: list[str]) -> None:
    doc = records.new_doc("run", run_id=run_id, exit=res.exit, code=res.code, message=res.message, op=res.op)
    warnings = list(dict.fromkeys([*warned, *res.warnings]))
    state.write_doc_once(layout.run(run_id), {**doc, "next": res.next, "warnings": warnings})


def _run(layout: state.Layout, docker: Docker, compose: Compose, plan: Plan, mode: str, fg: bool, tty: bool) -> Res:
    name = plan.instance
    if not name or not fs.exists(layout.record_json(name)):
        raise Refused(f"instance {name} is not initialized", code="unknown-instance")
    later = sorted({s.type for s in plan.steps} - {*_STEPS, "Pause"})
    if later:
        raise Refused(f"{', '.join(later)} steps are not in this release", code="not-in-this-release")
    holder = {"op": plan.op_kind, "command": plan.command, "operator": os.environ.get(brand.env("OPERATOR"), "")}
    with Lock(layout.lock(name), holder):
        host = state.read_doc(layout.host_json, "host")
        if docker.info()["ID"] != host["engine_id"]:
            raise CannotRun("the Docker daemon is not the one host.json records", code="engine-mismatch")
        opened = state.open_ops(layout, name)
        old = opening.load(layout, docker, compose, name, *opened[-1], fg, tty) if opened else None
        if mode != "new" and old is None:
            raise Refused(f"{name} has no open operation", code="wrong-state")
        join = mode == "new" and old is not None and opening.joinable(old, plan)
        if mode == "new" and old is not None and not join and old.plan.op_kind not in AUTO_ABANDON:
            nxt = f"{brand.CLI} resume {name}  or  {brand.CLI} abandon {name}"
            raise CannotRun(f"operation {old.seq} ({old.plan.op_kind}) is open", code="open-operation", next=nxt)
        orphans = orphan_check(docker, name, old.seq) if old else []
        if plan.fingerprint != fingerprint(layout, docker, name, plan.fingerprint.get("bundles", {})):
            return Res(1, "stale-plan", f"{name} changed since this plan was made; plan again", None, None)
        live = (old.plan if old and mode == "resume" else plan).inputs.get("app_env")
        need = mode == "new" or (mode == "resume" and live is not None and not fs.exists(live["path"]))
        env = opening.app_env(layout, name, live) if need else None  # a resume writes the op's own file if missing
        values = opening.secret_values(plan) if mode == "new" else []
        for v in plan.inputs.get("variants", {}).values():  # an env value Compose cannot read refuses before effects
            steps.env_text(v["env"])
        if opening.SIGNALLED[0]:
            return Res(130, "cancelled", "cancelled before any effect", None, None)
        if old:  # effects from here on
            _bury(old, orphans)
        if mode == "resume" and old:
            opening.ensure(env)
            return _resume(old)
        if mode == "abandon" and old:
            return _abandon(old, "abandoned")
        if join and old:
            return _steps(opening.join(old, plan, env, values, fg, tty), 0)
        if old:
            _abandon(old, "abandoned-auto")
        return _steps(opening.open_op(layout, docker, compose, plan, host, env, values, fg, tty), 0)


def orphan_check(docker: Docker, name: str, seq: int) -> list[dict[str, Any]]:
    """Task containers of operation `seq` (F15): a running one refuses (CannotRun naming the exact `docker stop`),
    exited ones are returned as evidence. Read-only."""
    labels = {brand.label("instance"): name, brand.label("op"): str(seq), brand.label("role"): "task"}
    found = docker.containers(labels)
    alive = [c["Name"].lstrip("/") for c in found if c["State"]["Status"] in ("running", "restarting", "paused")]
    if alive:
        stop = "; ".join(f"docker stop {n}" for n in alive)
        why = f"task containers of operation {seq} still run; stop them first: {stop}"
        raise CannotRun(why, code="task-running", next=stop)
    return found


def _bury(op: Op, orphans: list[dict[str, Any]]) -> None:
    """Journal the exit of a step's current-attempt container as that step's outcome, as if the executor had seen
    it, then remove each stopped container, re-proved (§20.5): evidence is never lost to a crash in between. Only an
    exited container is evidence; one created but never started (ExitCode 0) proves nothing. A container outside the
    instance's own Compose projects is not owned (ARCHITECTURE §7.5): never evidence, never removed."""
    by_num = {op.num(s): s for s in op.plan.steps}
    for c in [c for c in orphans if c["Config"]["Labels"].get(PROJECT_LABEL, "").split("--")[0] == op.name]:
        n, name = int(c["Config"]["Labels"][brand.label("step")]), c["Name"].lstrip("/")
        r, s = op.journal.replay().get(n, {}), by_num.get(n)
        current = r.get("phase") == "intent" and name == f"{op.name}-x{op.seq}-{n}-a{r['attempt']}"
        if current and c["State"]["Status"] == "exited":
            code = c["State"]["ExitCode"]
            out = tasks.outcome(s.args, code) if s and s.type == "RunTask" else "unknown"
            orphan = {"container": name, "exit_code": code, "finished_at": c["State"]["FinishedAt"]}
            ev: dict[str, Any] = {"orphan": orphan, "outcome": out}
            phase = tasks.phase(s.args, out) if s else "unknown"
            op.journal.close_step(n, phase, ev)
            if phase == "done":
                op.evidence[n] = ev
        again = op.docker.inspect("container", [c["Id"]])
        if again and again[0]["Config"]["Labels"] == c["Config"]["Labels"]:
            op.docker.remove_container(EffectToken(op.seq, n), c["Id"])


def _apply(op: Op, step: Step) -> tuple[str, dict[str, Any]]:
    try:
        ev = _STEPS[step.type](op, step, EffectToken(op.seq, op.num(step)))
    except Cancelled:
        return "cancelled", {"code": "cancelled", "error": "cancel requested"}
    except (IngatError, OSError) as e:
        why, code = (e.message, e.code) if isinstance(e, IngatError) else (str(e), "os-error")
        red, nxt = op.docker.redactor, getattr(e, "next", None)
        ev = {"code": code, "error": red.redact(why) if red else why, **({"next": nxt} if nxt else {})}
        return "unknown" if code == "task-running" else "failed", ev
    return str(ev.pop("phase", "done")), ev


def _attempt(op: Op, step: Step) -> tuple[str, dict[str, Any]]:
    n = op.num(step)
    op.step, op.attempt = n, op.attempts.get(n, 0) + 1
    op.attempts[n] = op.attempt
    op.journal.intent(n, op.attempt)
    op.journal.progress(f"step {n} {step.type}: started")
    if step.type == "Pause":
        return "paused", {}
    phase, ev = _apply(op, step)
    op.journal.close_step(n, phase, ev)
    op.journal.progress(f"step {n} {step.type}: {phase}")
    return phase, ev


def _steps(op: Op, start: int) -> Res:
    for step in op.plan.steps[start:]:
        if op.cancelled():
            return _fail(op, step, "cancelled", {"code": "cancelled", "error": "cancel requested"})
        phase, ev = _attempt(op, step)
        if phase == "paused":
            return Res(4, "paused", step.args.get("text", "paused"), op.seq, f"{brand.CLI} resume {op.name}")
        if phase != "done":
            return _fail(op, step, phase, ev)
        op.evidence[step.n] = ev
    findings = any(ev.get("outcome") == "finding" for ev in op.evidence.values())
    return _end(op, "completed", 5 if findings else 0, "findings" if findings else "completed", "completed")


def _write_task(op: Op, s: Step) -> bool:
    """The step of a one-step app-write task operation: it closes needs-review and never freezes (LIFECYCLE §3.5)."""
    return op.plan.op_kind == "task" and s.type == "RunTask" and s.args.get("effect") == "app-write"


def _forward(op: Op) -> bool:
    """The forward point is reached once a step that may change live state for good was attempted: a forward step,
    but not a deletion or a one-step app-write task (they never freeze) and not a first attempt the app refused
    (nothing changed, LIFECYCLE §4.4)."""
    rep = op.journal.replay()
    for s in op.plan.steps:
        r = rep.get(op.num(s))
        if not r or not (s.forward_point or s.klass == "forward") or s.type == "Delete" or _write_task(op, s):
            continue
        refused = (r.get("evidence") or {}).get("outcome") == "refused"
        if not (r["attempts"] == 1 and r["phase"] == "failed" and refused):
            return True
    return False


def _fail(op: Op, step: Step, phase: str, ev: dict[str, Any]) -> Res:
    n = op.num(step)
    code, why = str(ev.get("code", phase)), str(ev.get("error") or f"step {n} {step.type} ended {phase}")
    if code == "task-running":  # F15: never closed while its task container may still run
        return Res(4, code, why, op.seq, ev.get("next"))
    if op.offset:  # a joined task leaves the paused operation as it was
        return Res(4 if phase == "unknown" else 3, code, why, op.seq, f"{brand.CLI} status {op.name}")
    if phase == "unknown" and step.klass != "scratch":  # scratch has no lasting effect: an unknown one failed
        if _write_task(op, step):
            return _end(op, "needs-review", 4, "needs-review", why, n=n)
        return Res(4, "interrupted", why, op.seq, f"{brand.CLI} resume {op.name}  or  {brand.CLI} abandon {op.name}")
    types = {op.num(s): s.type for s in op.plan.steps}
    if phase == "cancelled" and all(types.get(k) == "Pause" for k in op.journal.replay()):
        return _end(op, "abandoned", 130, "cancelled", "cancelled before any effect", n=n)  # only `always` steps act
    frozen = _forward(op)
    return _end(op, "failed-frozen" if frozen else "failed-unchanged", 3, code, why, frozen, n)


def _end(op: Op, outcome: str, exit: int, code: str, message: str, frozen: bool = False, n: int = 0) -> Res:
    """Journal the close decision, then act on it: a crash while unwinding or closing makes the next resume or
    abandon finish this same close, never resume past steps the unwind already reversed."""
    if op.offset:  # a joined task leaves its paused operation open
        return Res(exit, code, message, op.seq, f"{brand.CLI} resume {op.name}")
    decision = {"outcome": outcome, "exit": exit, "code": code, "message": message, "frozen": frozen, "step": n}
    op.journal.close_step(CLOSE, "done", decision)
    return _finish(op, decision)


def _finish(op: Op, d: dict[str, Any]) -> Res:
    """Unwind a decided failure or abandon, then close. An unwind that left warnings closes needs-review: an undo
    that did not happen may have left writers stopped while the record says running."""
    outcome, exit = d["outcome"], d["exit"]
    warnings = [] if outcome in ("completed", "needs-review") else _unwind(op, d)
    if warnings and outcome == "failed-unchanged":
        outcome, exit = "needs-review", 4
    return _close(op, outcome, exit, d["code"], d["message"], warnings, d["frozen"])


def _unwind(op: Op, d: dict[str, Any]) -> list[str]:
    """A failure first records a failed verification (F10); then the `always` steps (teardown) that have not
    completed; then before the forward point undo every attempted step in reverse, after it stop the writers (the
    deciding step acts); then discard scratch outputs."""
    warnings: list[str] = []
    rep, frozen, n = op.journal.replay(), d["frozen"], d["step"]

    def guard(what: str, fn: Callable[..., object], *args: Any) -> None:
        try:
            fn(*args)
        except (IngatError, OSError) as e:
            warnings.append(f"{what}: {e}")

    if d["outcome"].startswith("failed") and d["code"] != "cancelled":
        guard("record the failed verification", steps.failed_verifications, op, rep, n)
    for s in op.plan.steps:
        if s.always and rep.get(op.num(s), {}).get("phase") != "done":
            phase, ev = _attempt(op, s)
            if phase != "done":
                warnings.append(f"step {op.num(s)} {s.type} ended {phase}: {ev.get('error', '')}")

    writers = op.plan.inputs.get("writers") or []
    live = [k for k, v in op.plan.inputs.get("variants", {}).items() if not v.get("isolated")]
    if frozen and writers and live:
        stop = op.compose.stop
        guard(
            "stop writers",
            lambda: steps.check(stop(EffectToken(op.seq, n), op.project(live[0]), writers, timeout=300), "stop"),
        )
    for s in [] if frozen else reversed(op.plan.steps):
        if op.num(s) in rep:
            guard(f"undo step {op.num(s)}", steps.undo, op, s, EffectToken(op.seq, op.num(s)))
    guard("discard partial outputs", steps.discard, op, [], op.find("bundle_id").get("bundle_id"))
    return warnings


def _close(op: Op, outcome: str, exit: int, code: str, message: str, warnings: list[str], frozen: bool) -> Res:
    """Remove scratch leftovers (input copies, an empty stage; artifacts stay), then record.json, then result.json
    (write-once): its presence is what closes the operation, so a crash in between leaves the operation open for its
    close to be finished."""
    try:
        fs.remove_tree(op.path("in"))
        if not fs.listdir(op.path("stage")):
            fs.remove_tree(op.path("stage"))
    except (IngatError, OSError) as e:
        warnings = [*warnings, f"remove scratch leftovers: {e}"]
    warnings = [*_warnings(op.plan), *warnings]
    nxt = (op.plan.inputs.get("next") or {}).get(outcome) or f"{brand.CLI} status {op.name}"
    rec, now = op.record(), _now()
    last = {"seq": op.seq, "kind": op.plan.op_kind, "outcome": outcome, "at": now}
    op.update(open_op=None, last_op=last, **({"state": "frozen"} if frozen else {}))
    doc = records.new_doc(
        "result", op=op.seq, op_kind=op.plan.op_kind, instance=op.name, outcome=outcome, exit=exit, code=code,
        message=message, next=nxt, started_at=(rec.get("open_op") or {}).get("started_at", now), finished_at=now,
        warnings=warnings,
    )  # fmt: skip
    state.write_doc_once(op.path("result.json"), doc)
    op.journal.progress(f"operation {outcome}")
    return Res(exit, code, message, op.seq, nxt, tuple(warnings))


def _resume(op: Op) -> Res:
    """Finish a decided close; else go on from the first step without `done` (LIFECYCLE §3.4; group redo §20.6). A
    seal whose bundle is catalogued with its hash is done (its observe, LIFECYCLE §3.3): no second bundle."""
    rep = op.journal.replay()
    if CLOSE in rep:
        return _finish(op, rep[CLOSE]["done_evidence"])
    todo = [s for s in op.plan.steps if rep.get(s.n, {}).get("phase") != "done"]
    if not todo:
        return _steps(op, len(op.plan.steps))
    first = todo[0]
    i, last = op.plan.steps.index(first), rep.get(first.n, {})
    phase = last.get("phase")
    if phase in ("failed", "cancelled"):  # seen before a crash, or decided by orphan evidence: as if seen now
        return _fail(op, first, phase, last.get("evidence") or {})
    if first.type == "Pause" and phase == "intent":
        op.journal.close_step(first.n, "done")
        op.evidence[first.n] = {}
        i += 1
    elif phase == "intent" and (ev := tasks.sealed(op, first)) is not None:  # observed: sealed and catalogued
        fs.remove_tree(op.path("bundle"))  # the seal's last act: its working copy is published
        op.journal.close_step(first.n, "done", ev)
        op.journal.progress(f"step {first.n} {first.type}: done (observed)")
        op.evidence[first.n] = ev
        i += 1
    elif first.klass == "scratch" and not first.always:
        i = _rewind(op, first)
    elif first.type == "RunTask" and first.klass == "forward" and phase and not first.args.get("idempotent"):
        why = f"step {first.n} ({first.type}) may have run and is not safe to repeat"
        if _write_task(op, first):
            return _fail(op, first, "unknown", {"code": "unknown", "error": why})
        raise NeedsAttention(why, code="unknown", next=f"{brand.CLI} status {op.name}")
    return _steps(op, i)


def _rewind(op: Op, first: Step) -> int:
    """Where the redo of a scratch step starts (LIFECYCLE §3.4, §3.5): its group's first step; once this operation's
    isolated project had to come `down` (its containers are partial outputs too), the first step that acted on that
    project or made a generation. The partial outputs of every step redone are discarded first."""
    plan, j = op.plan.steps, op.plan.steps.index(first)
    i = next(k for k, s in enumerate(plan) if s is first or (first.group and s.group == first.group))
    if steps.down_isolated(op, EffectToken(op.seq, op.num(first))):
        for k, s in enumerate(plan[:i]):
            if s.type == "CreateGeneration" or steps.isolated(op, s.args.get("variant")):
                i = k
                break
    steps.discard(op, plan[i : j + 1], op.find("bundle_id").get("bundle_id"))
    for s in plan[i : j + 1]:
        op.evidence.pop(s.n, None)
    return i


def _abandon(op: Op, outcome: str) -> Res:
    """Undo reversible steps, tear down scratch; past the forward point writers stay stopped (frozen). A decided
    close is finished as decided."""
    rep = op.journal.replay()
    if CLOSE in rep:
        return _finish(op, rep[CLOSE]["done_evidence"])
    return _end(op, outcome, 0, outcome, f"operation {op.seq} {outcome}", _forward(op), max(rep, default=0))


def _now() -> str:
    return records.iso(records.utc_now())
