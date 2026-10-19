"""`start`, `stop`, `restart`, `task`, `resume`, `abandon` and `cancel` (LIFECYCLE §3.4, §4.11, §4.12; ARCHITECTURE
§4.3, §4.4). Plans run the recorded deployment's pinned images and recorded Compose inputs (F4), or re-enter the open
operation; `cancel` writes only the open operation's cancel file."""

import contextlib
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

from ingat import __version__, brand
from ingat.core.executor import AUTO_ABANDON, CLOSE, orphan_check
from ingat.core.journal import Journal
from ingat.core.plan import Plan, fingerprint, new_plan
from ingat.core.steps import ONEOFF_LABEL
from ingat.model import words
from ingat.model.errors import CannotRun, Refused
from ingat.model.instance import NAME_RE
from ingat.model.manifest import Manifest, Task, parse_manifest
from ingat.ops import context as cx
from ingat.ops import steps_build as sb
from ingat.ops.context import Ctx, Loaded
from ingat.ops.deploy import STOP_TIMEOUT, foreign
from ingat.policy.gate import TIER2
from ingat.store import fs, state

Step = dict[str, Any]
Given = Mapping[str, str]  # --arg or --input name=value pairs
Opened = tuple[int, str, Plan]  # seq, kind and plan of the open operation


def _begin(ctx: Ctx, name: str) -> tuple[Loaded, list[str]]:
    """The loaded instance and the gate's warnings for the plan."""
    cx.require_host(ctx)
    warnings = cx.gate(ctx, TIER2, name)
    return cx.load(ctx, name), warnings


def _opened(ctx: Ctx, name: str) -> Opened | None:
    found = state.open_ops(ctx.layout, name)
    if not found:
        return None
    seq, kind = found[-1]
    doc = state.read_doc(os.path.join(ctx.layout.op_dir(name, seq, kind), "plan.json"), "plan")
    return seq, kind, Plan.from_doc(doc)


def _pause(ctx: Ctx, name: str, opened: Opened) -> list[str] | None:
    """The tasks the open operation's pause allows (ARCHITECTURE §4.3); None when it is not paused, or when its
    close is already decided (a crash while closing it: resume or abandon finishes that close)."""
    seq, kind, plan = opened
    rep = Journal(ctx.layout.op_dir(name, seq, kind), seq).replay()
    paused = [s for s in plan.steps if s.type == "Pause" and rep.get(s.n, {}).get("phase") == "intent"]
    return list(paused[-1].args.get("allow_tasks", ())) if paused and CLOSE not in rep else None


def _either(name: str) -> str:
    return f"{brand.CLI} resume {name}  or  {brand.CLI} abandon {name}"


def _busy(name: str, opened: Opened | None) -> None:
    """An open operation blocks another one, unless the executor may auto-abandon it (LIFECYCLE §3.4, F5)."""
    if opened and opened[1] not in AUTO_ABANDON:
        why = f"operation {opened[0]} ({opened[1]}) has not finished; continue it or give it up first"
        raise CannotRun(why, code="open-operation", next=_either(name))


def _current(ctx: Ctx, ld: Loaded) -> tuple[Manifest, dict[str, Any], dict[str, Any]]:
    """The recorded deployment's manifest, variant `current` and model."""
    if ld.manifest is None:
        raise Refused(
            f"{ld.name} has not been deployed yet", code="wrong-state", next=f"{brand.CLI} deploy {ld.name} <ref>"
        )
    v, model = cx.current(ctx, ld)
    return ld.manifest, v, model


def _frozen(ld: Loaded) -> None:
    if ld.record.get("state") == "frozen":
        msg = f"{ld.name} is frozen: {words.FROZEN}; unfreezing (`start --unfreeze`) is not in this release yet"
        raise Refused(msg, code="frozen", next=f"{brand.CLI} status {ld.name}")


def _inputs(
    ctx: Ctx, ld: Loaded, m: Manifest, variants: Any, kind: str, warnings: list[str], into: Opened | None = None
) -> Any:
    """Inputs of an operation on live variants; the deployment's app env file exists, so none is rendered and its
    secret files are redacted by path. `into`: the paused operation a task joins."""
    seq, sdir = into[0] if into else state.next_seq(ctx.layout, ld.name), ctx.layout.secrets_dir(ld.name)
    for v in variants.values() if into is None else ():
        v["values"] |= {"op.seq": str(seq), "reason": ""}
    keys = [k for k, x in (m.app_env.keys if m.app_env else {}).items() if x.secret]
    redact = [os.path.join(sdir, "env", k) for k in keys] + [os.path.join(sdir, k) for k in m.secrets]
    out = {"seq": seq, "op_dir": ctx.layout.op_dir(ld.name, seq, into[1] if into else kind), "variants": variants}
    out |= {"into_op": seq if into else None, "app_env": None, "files": {}, "throwaway_secrets": {}}
    out |= {"redact_files": sorted(p for p in redact if fs.exists(p)), "writers": list(m.services.writers)}
    out |= {"data": list(m.services.data), "activation": [list(g.services) for g in m.activate]}
    return out | {"warnings": warnings}


def _plan(ctx: Ctx, ld: Loaded, kind: str, approval: str, command: Sequence[str], inputs: Any, steps: Any) -> Plan:
    fp = fingerprint(ctx.layout, ctx.docker, ld.name)
    return new_plan(kind, ld.name, approval, [brand.CLI, *command], fp, inputs, steps)


def _running(ctx: Ctx, name: str) -> dict[str, str]:
    """service -> image ID of the project's running service containers (one-off task containers left out)."""
    out = {}
    for c in ctx.docker.containers(labels={brand.label("instance"): name}, project=name):
        labels = c["Config"].get("Labels") or {}
        if c["State"].get("Running") and labels.get(ONEOFF_LABEL) != "True":
            out[labels.get(cx.SERVICE, "")] = c["Image"]
    return out


def _up(services: list[str], wait: list[str], klass: str, check: bool = False) -> Step:
    args = {"variant": "current", "services": services, "wait": wait, "identity": check, "smoke": check}
    args |= {"reopens_writes": False, "schema_probe": None, "schema_paths": None}
    return {"type": "Up", "klass": klass, "interruptible": True, "args": args}


def stops(m: Manifest, want: list[str]) -> list[Step]:
    """Writers first, then the rest in reverse activation order (LIFECYCLE §4.11)."""
    writers = [s for s in want if s in m.services.writers]
    groups = [writers, *([s for s in g.services if s in want and s not in writers] for g in reversed(m.activate))]
    args = {"variant": "current", "freeze": False, "timeout": STOP_TIMEOUT}
    return [{"type": "Stop", "klass": "reversible", "args": args | {"services": g}} for g in groups if g]


def starts(m: Manifest, want: list[str], check: bool) -> list[Step]:
    """The activation groups in order with their waits (a partly started group keeps the waits on the services it
    starts); then the identity check and smoke when every service runs afterwards."""
    out = []
    for g in m.activate:
        if up := [s for s in g.services if s in want]:
            wait = [w for w in g.wait if len(up) == len(g.services) or m.probes[w].service in up]
            out.append(_up(up, wait, "reversible"))
    return out + ([_up([], [], "scratch", check=True)] if check else [])


def plan_start(ctx: Ctx, name: str, services: Sequence[str]) -> Plan | None:
    return _cycle(ctx, name, services, "start")


def plan_stop(ctx: Ctx, name: str, services: Sequence[str]) -> Plan | None:
    return _cycle(ctx, name, services, "stop")


def plan_restart(ctx: Ctx, name: str, services: Sequence[str]) -> Plan | None:
    """Stop then start in one operation (the log snapshot before it, SnapshotLogs, arrives in M2)."""
    return _cycle(ctx, name, services, "restart")


def _cycle(ctx: Ctx, name: str, services: Sequence[str], kind: str) -> Plan | None:
    """start, stop or restart of `services` (all when empty) on the recorded deployment (class C); None when the
    instance already is in the asked state."""
    ld, warnings = _begin(ctx, name)
    _busy(name, _opened(ctx, name))
    _frozen(ld)  # stop and restart too: a stopped instance may start, which would bypass the unfreeze
    m, v, _ = _current(ctx, ld)
    every = [s for g in m.activate for s in g.services]
    if bad := sorted(set(services) - set(every)):
        raise CannotRun(f"{', '.join(bad)}: not a service the deployment activates", code="usage")
    want, running, now = [s for s in every if not services or s in services], _running(ctx, name), ld.record["state"]
    if kind == "stop" and now == "stopped" and not set(want) & set(running):
        return None
    if kind == "start" and now == "running" and all(running.get(s) == v["images"][s] for s in want):
        return None
    if kind != "stop":
        cx.exclusive(ctx, ld, m)
        if m.schema and m.schema.task:  # a probe-based schema needs no check: the same images ran on this data
            raise Refused("the schema task check before a start arrives in M2", code="not-in-this-release")
    foreign(ctx, name)  # Compose stops and starts every container of a service in the project (F8)
    steps = [] if kind == "start" else stops(m, want)
    steps += [] if kind == "stop" else starts(m, want, check=set(every) <= {*want, *running})
    if kind != "stop" or want == every:
        state_ = "stopped" if kind == "stop" else "running"
        steps.append({"type": "Record", "klass": "idempotent", "args": {"kind": "state", "state": state_}})
    inputs = _inputs(ctx, ld, m, {"current": v}, kind, warnings)
    return _plan(ctx, ld, kind, "C", [kind, name, *services], inputs, steps)


def _task(m: Manifest, name: str) -> Task:
    """A declared operator task on the current images; a bundle, a new generation or a stage (the bundle being
    built, ARCHITECTURE §7.1) exists only inside the operations that mount one, so a task that mounts any of them
    cannot run alone."""
    t = m.tasks.get(name)
    if t is None:
        raise Refused(f"{m.app} declares no task {name!r}", code="unknown-task")
    only = [s for s in t.mounts.values() if s in ("bundle", "stage") or s.startswith("generation:")]
    if not t.operator or t.image != "current" or only:
        why = f" (it mounts {only[0]})" if only else ""
        why = f"task {name} cannot be run on its own; it runs only as part of the operations that use it{why}"
        raise Refused(why, code="not-operator")
    return t


def task_args(t: Task, given: Given) -> dict[str, str]:
    """`--arg name=value`: exactly the declared names, each value matching its regex (MANIFEST_SPEC §4)."""
    if extra := sorted(set(given) - set(t.args)):
        raise CannotRun(f"task {t.name} has no argument {extra[0]}", code="usage")
    if missing := sorted(set(t.args) - set(given)):
        raise CannotRun(f"task {t.name} needs --arg {missing[0]}=<value>", code="usage")
    if bad := sorted(k for k, rx in t.args.items() if not re.fullmatch(rx, given[k])):
        raise Refused(f"--arg {bad[0]} does not match {t.args[bad[0]]}", code="invalid-arg")
    return dict(given)


def task_inputs(ctx: Ctx, t: Task, given: Given) -> dict[str, str]:
    """`--input name=file`: exactly the task's `input:` mounts, each a regular file directly in the inbox (a bare
    name is looked up there) with no link on its path and at most max_input_bytes; the executor copies it."""
    names, inbox = {s[6:] for s in t.mounts.values() if s.startswith("input:")}, ctx.layout.inbox
    if set(given) != names:
        raise CannotRun(f"task {t.name} takes --input {', '.join(sorted(names)) or '(none)'}", code="usage")
    out = {}
    for k, f in sorted(given.items()):
        path = os.path.normpath(os.path.join(inbox, f))
        if os.path.dirname(path) != inbox:
            raise Refused(f"--input {k}: the file must lie directly in {inbox}/", code="unsafe-path")
        try:
            fs.read(path, t.max_input_bytes)
        except FileNotFoundError:
            raise Refused(f"--input {k}: {path} does not exist", code="missing-input") from None
        out[k] = path
    return out


def plan_task(ctx: Ctx, name: str, task: str, args: Given, inputs: Given, scheduled: bool) -> Plan:
    """One declared task as a one-step operation on the recorded deployment's images (read: class B, else C;
    LIFECYCLE §4.12). A task the paused install allows joins that operation (`inputs.into_op`; the executor numbers
    its steps from 1000). A terminal task is flagged `inputs.foreground`: the CLI runs it in its own process.
    A live write task is a forward step (LIFECYCLE §3.3) and only a `data` one is a forward point (§3.2): the
    executor never freezes for an app-write task and closes its unknown outcome `needs-review`, never repeating it
    blind (§3.5, F5)."""
    ld, warnings = _begin(ctx, name)
    opened = _opened(ctx, name)
    allowed = _pause(ctx, name, opened) if opened else None
    into = opened if allowed is not None and task in allowed else None
    if into is not None:  # the install's own candidate images and Compose inputs
        rec = next(s for s in into[2].steps if s.type == "Record" and s.args.get("kind") == "deployment")
        m = parse_manifest(fs.read(rec.args["manifest_path"]), tool_version=__version__)
        if m.raw_sha256 != into[2].inputs.get("manifest_sha256"):
            raise Refused("the paused install's manifest changed", code="stale-plan")
        vname, v, model = "candidate", into[2].inputs["variants"]["candidate"], None
    else:
        _busy(name, opened)
        (m, v, model), vname = _current(ctx, ld), "current"
    t = _task(m, task)
    values, files = task_args(t, args), task_inputs(ctx, t, inputs)
    terminal, approval = "terminal" in (t.stdin, t.stdout), "B" if t.effect == "read" else "C"
    if scheduled and (terminal or approval != "B"):
        why = f"task {task} needs a person at a terminal or an approval, so it cannot run from the scheduler"
        raise CannotRun(why, code="unattended")
    if t.stdin == "terminal" and not ctx.tty:
        why = f"task {task} asks for input on the terminal; run it from an interactive terminal, not from a script"
        raise CannotRun(why, code="no-tty")
    if t.effect != "read":
        _frozen(ld)
    if model is None and t.mounts:
        model = cx.model(ctx, v)
    klass = "scratch" if t.effect == "read" else "forward"
    step = sb.task_step(ctx, m, v, model or {}, t, vname, klass, findings_ok=True)
    step["args"] |= {"args": values, "inputs": files}
    step["forward_point"] = t.effect == "data"
    record = {"kind": "task", "task": task, "clears_hold": t.clears_hold, "step": 1}
    steps = [step, {"type": "Record", "klass": "idempotent", "args": record}]
    command = [*(["scheduled"] if scheduled else []), "task", name, task]
    command += [f"--arg={k}={x}" for k, x in sorted(values.items())] + [f"--input={k}={x}" for k, x in files.items()]
    plan_inputs = _inputs(ctx, ld, m, {vname: v}, "task", warnings, into) | {"foreground": terminal}
    return _plan(ctx, ld, "task", approval, command, plan_inputs, steps)


def plan_resume(ctx: Ctx, name: str) -> Plan:
    """Re-enter the open operation from its first step without `done` (LIFECYCLE §3.4; `_exec --resume`). The
    executor decides each step by its class and evidence: an unknown write is never repeated blind (F5)."""
    return _reenter(ctx, name, "resume")


def plan_abandon(ctx: Ctx, name: str) -> Plan:
    """Undo, tear down and close the open operation `abandoned`; past its forward point writers stay stopped and the
    instance is frozen (LIFECYCLE §3.4; `_exec --abandon`)."""
    return _reenter(ctx, name, "abandon")


def _reenter(ctx: Ctx, name: str, kind: str) -> Plan:
    ld, warnings = _begin(ctx, name)
    opened = _opened(ctx, name)
    if opened is None:
        raise Refused(f"{name} has no open operation", code="wrong-state", next=f"{brand.CLI} status {name}")
    orphan_check(ctx.docker, name, opened[0])  # a running task container refuses (F15)
    inputs = {"seq": opened[0], "op_dir": ctx.layout.op_dir(name, opened[0], opened[1]), "into_op": opened[0]}
    # a terminal task's operation resumes where its task runs again: in the CLI, on this terminal (ARCHITECTURE §4.3)
    inputs |= {"warnings": warnings, "foreground": kind == "resume" and bool(opened[2].inputs.get("foreground"))}
    return _plan(ctx, ld, kind, "C", [kind, name], inputs, [])


def cancel(ctx: Ctx, name: str) -> dict[str, Any]:
    """Ask the running operation to stop at its next safe point: writes only `<op>/cancel` (ARCHITECTURE §4.4). A
    paused operation is refused: the file would also end every task its pause allows and its resume (a task that
    runs in it stops with Ctrl-C on its terminal, or with `docker stop` of its executor). The instance file is not
    read: an edit of it for the next deploy must not keep a running operation from stopping."""
    if not NAME_RE.fullmatch(name):
        raise CannotRun(cx.bad_name(name), code="usage")
    if not fs.exists(ctx.layout.record_json(name)):
        raise Refused(f"there is no instance {name}", code="unknown-instance")
    opened = _opened(ctx, name)
    if opened is None:
        raise Refused(f"{name} has no open operation", code="wrong-state", next=f"{brand.CLI} status {name}")
    seq, kind, _ = opened
    if _pause(ctx, name, opened) is not None:
        msg = f"operation {seq} ({kind}) is paused and waiting for you, so cancel does not apply: continue it with "
        msg += "resume or give it up with abandon"
        raise Refused(msg, code="wrong-state", next=_either(name))
    with contextlib.suppress(FileExistsError):  # asked before
        fs.write_once(os.path.join(ctx.layout.op_dir(name, seq, kind), "cancel"), b"")
    line = f"cancel requested for operation {seq} ({kind}); it stops at its next safe point"
    return {"exit": 0, "code": "cancel-requested", "next": f"{brand.CLI} attach {name}", "op": seq, "lines": [line]}
