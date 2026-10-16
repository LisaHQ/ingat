"""The command line (LIFECYCLE §2, §6; ARCHITECTURE §4): parse, plan, approve, then run the plan in the detached
executor and follow it, or answer in the CLI. Every error prints as `<cli>: message` plus `next:`; `--json` prints one
JSON object with `code`, `exit` and `next`."""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple, NoReturn

from ingat import __version__, brand
from ingat.cli import follow, render
from ingat.cli.render import Report
from ingat.core import approval, executor
from ingat.core.plan import Plan, new_plan
from ingat.model import records
from ingat.model.errors import CannotRun, IngatError, Refused
from ingat.ops import context as cx
from ingat.ops import deploy
from ingat.ops.context import Ctx
from ingat.ops.validate import validate
from ingat.store import fs, state

Args = argparse.Namespace


class Cmd(NamedTuple):
    """One row of the command table (LIFECYCLE §2)."""

    klass: str  # approval class; `task` is B or C by its effect, as its plan says
    lock: str  # "", "instance" or "host"
    approval: str  # "none", or "typed": class C, the name typed on a terminal (no terminal: exit 2, nothing written)
    unattended: bool  # may run from a scheduler; `scheduled …` refuses class C and D plans and terminal tasks
    foreground: bool  # runs in the CLI process; otherwise in the detached executor (a terminal task runs here too)


READ = Cmd("A", "", "none", True, True)
NEW = Cmd("B", "instance", "none", True, False)
CHANGE = Cmd("C", "instance", "typed", False, False)
COMMANDS: dict[str, Cmd] = {
    **dict.fromkeys(("version", "host check", "status", "doctor", "list", "ps", "logs", "history"), READ),
    **dict.fromkeys(("bundles", "validate", "attach"), READ),
    "host init": Cmd("C", "host", "typed", False, True),
    "init": Cmd("C", "host", "typed", False, True),
    "cancel": Cmd("B", "", "none", True, True),
    **dict.fromkeys(("prepare", "backup", "verify", "prune", "scheduled"), NEW),
    **dict.fromkeys(("deploy", "start", "stop", "restart", "resume", "abandon"), CHANGE),
    "task": Cmd("B/C", "instance", "typed", False, False),
    "selftest": Cmd("B", "host", "none", True, False),
}


def main(argv: Sequence[str] | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in words
    try:
        a = parser().parse_args(words)
        as_json = getattr(a, "json", False)
        if a.cmd == "_exec":
            return _exec(a)
        return render.report(_run(a), as_json)
    except IngatError as e:
        return render.error(e, as_json)
    except KeyboardInterrupt:
        rep = {"exit": 130, "code": "cancelled", "message": "cancelled", "next": None, "lines": ["cancelled"]}
        return render.report(rep, as_json)
    except SystemExit as e:  # --help
        return e.code if isinstance(e.code, int) else 0


def _tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _run(a: Args) -> Report:
    a.out = sys.stderr if getattr(a, "json", False) else sys.stdout  # progress; stdout then holds only the answer
    if a.cmd == "version":
        return _version()
    ctx = cx.make_ctx(os.environ, tty=_tty())
    key = f"host {a.what}" if a.cmd == "host" else a.cmd
    if COMMANDS[key].approval == "typed" and COMMANDS[key].foreground:  # class C in the CLI: host init, init
        _confirm(ctx, *((a.instance, "instance") if key == "init" else (ctx.hostname, "host")))
    return HANDLERS[key](ctx, a)


def _confirm(ctx: Ctx, expected: str, what: str) -> None:
    """Class C approval of a command that runs in the CLI: the name typed on a terminal (LIFECYCLE §2)."""
    if not ctx.tty:
        raise CannotRun(f"a class C change needs a terminal to type the {what} name", code="no-tty")
    if render.ask(f"Type the {what} name to approve: ").strip() != expected:
        raise Refused("not approved; nothing was changed", code="not-approved")


def _version() -> Report:
    wrapper = os.environ.get(brand.env("WRAPPER_VERSION")) or None
    image = os.environ.get(brand.env("IMAGE")) or None
    lines = [f"{brand.CLI} {__version__}", f"wrapper {wrapper or '-'}", f"image {image or '-'}"]
    data = {"version": __version__, "wrapper": wrapper, "image": image}
    return {"exit": 0, "code": "ok", "next": None, "lines": lines, **data}


def _go(ctx: Ctx, a: Args, plan: Plan | None, nothing: str) -> Report:
    """Summary, approval, then the detached executor (or this process for a terminal task)."""
    if plan is None:
        return {"exit": 0, "code": "nothing-to-do", "next": None, "lines": [nothing]}
    if plan.approval < COMMANDS.get(plan.op_kind, COMMANDS[a.cmd]).klass[0]:  # the table's class is a floor (F3)
        raise Refused(f"internal: a {plan.op_kind} plan of class {plan.approval}", code="internal")
    tasks = [s.args for s in plan.steps if s.type == "RunTask"]
    terminal = bool(plan.inputs.get("foreground")) or any(
        "terminal" in (t.get("stdin"), t.get("stdout")) for t in tasks
    )
    if a.scheduled and (plan.approval not in ("A", "B") or terminal):
        why = "a terminal task" if terminal else f"class {plan.approval}"
        raise CannotRun(f"`scheduled` runs only unattended class A and B plans; this is {why}", code="unattended")
    if not a.scheduled:
        render.say(a.out, render.plan_summary(plan))
    if any(t.get("stdin") == "terminal" for t in tasks) and not ctx.tty:
        raise CannotRun("this task reads from the terminal: run it on one", code="no-tty")
    approval.approve(plan, tty=ctx.tty, ask=render.ask)
    if terminal:
        return _foreground(ctx, plan)
    opened = state.open_ops(ctx.layout, plan.instance) if a.scheduled and plan.instance else []
    rep = follow.launch_and_follow(ctx, plan, None if a.scheduled else a.out)
    if a.scheduled and rep["exit"] in (0, 5):  # one line on success, naming an auto-abandon (LIFECYCLE §3.4, §7)
        line = f"{' '.join(plan.command[1:])}: {' '.join(rep['lines'])} (operation {rep.get('op')})"
        for seq, kind in opened:
            path = os.path.join(ctx.layout.op_dir(plan.instance or "", seq, kind), "result.json")
            if fs.exists(path) and state.read_doc(path, "result")["outcome"] == "abandoned-auto":
                line += f"; operation {seq} ({kind}) abandoned-auto"
        rep["lines"], rep["next"] = [line], rep["next"] if getattr(a, "json", False) else None  # JSON keeps `next`
    return rep


def _foreground(ctx: Ctx, plan: Plan) -> Report:
    """A terminal task, or the resume of its operation: under the instance lock in this process (ARCHITECTURE
    §4.3). A resume reports the result of the operation it resumed, unless its plan was stale (exit 1)."""
    approval.save(ctx.layout, plan)
    code = executor.run_in_process(ctx.layout, ctx.docker, ctx.compose, plan, tty=ctx.tty)
    op_dir, name = plan.inputs["op_dir"], plan.instance
    own, result = os.path.join(op_dir, "plan.json"), os.path.join(op_dir, "result.json")
    resumed = plan.op_kind == "resume" and code != 1
    if fs.exists(result) and (resumed or records.doc_hash(state.read_doc(own, "plan")) == plan.hash):
        doc = state.read_doc(result, "result")
        line, nxt = doc["message"], doc["next"]
        return {"exit": code, "code": doc["code"], "message": line, "next": nxt, "op": doc["op"], "lines": [line]}
    if code == 0 and plan.op_kind == "task" and plan.inputs.get("into_op") is not None:  # the paused one stays open
        line, nxt = "task completed", f"{brand.CLI} resume {name}"
        return {"exit": 0, "code": "completed", "message": line, "next": nxt, "lines": [line]}
    why = {1: ("stale-plan", f"{name} changed since this plan was made; plan again")}
    why[130] = ("cancelled", "cancelled before any effect")
    key, line = why.get(code, ("task", f"task ended with exit {code}"))
    return {"exit": code, "code": key, "message": line, "next": f"{brand.CLI} status {name}", "lines": [line]}


def _prepare(ctx: Ctx, a: Args) -> Report:
    return _go(ctx, a, deploy.plan_prepare(ctx, a.instance, a.ref), f"{a.ref} is already prepared for {a.instance}")


def _deploy(ctx: Ctx, a: Args) -> Report:
    """Deploy; a ref without a prepared candidate is prepared first (class B), then planned again."""
    try:
        plan = deploy.plan_deploy(ctx, a.instance, a.ref)
    except Refused as e:
        if e.code != "no-candidate":
            raise
        if not ctx.tty:  # the deploy needs typed approval: refuse before preparing anything
            raise CannotRun("deploy is class C: it needs a terminal to type the instance name", code="no-tty") from e
        render.say(a.out, [f"{e.message}: preparing {a.ref} first"])
        rep = _go(ctx, a, deploy.plan_prepare(ctx, a.instance, a.ref), f"{a.ref} is prepared")
        if rep["exit"] != 0:
            return rep
        render.say(a.out, rep["lines"])
        plan = deploy.plan_deploy(ctx, a.instance, a.ref)
    return _go(ctx, a, plan, f"{a.instance} already runs {a.ref} as planned: nothing to do")


def _lifecycle(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import lifecycle as lc

    plan: Plan | None
    if a.cmd in ("resume", "abandon"):
        plan = (lc.plan_resume if a.cmd == "resume" else lc.plan_abandon)(ctx, a.instance)
    else:
        plan = {"start": lc.plan_start, "stop": lc.plan_stop, "restart": lc.plan_restart}[a.cmd](
            ctx, a.instance, a.services
        )
    return _go(ctx, a, plan, f"{a.instance}: nothing to {a.cmd}")


def _pairs(items: list[str] | None, flag: str) -> dict[str, str]:
    out = {}
    for item in items or ():
        key, eq, value = item.partition("=")
        if not eq or not key:
            raise CannotRun(f"{flag} takes name=value, not {item!r}", code="usage")
        out[key] = value
    return out


def _task(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import lifecycle as lc

    args, inputs = _pairs(a.arg, "--arg"), _pairs(a.input, "--input")
    return _go(ctx, a, lc.plan_task(ctx, a.instance, a.task, args, inputs, a.scheduled), "nothing to run")


def _backup(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import backup

    if a.scheduled:  # class `scheduled`, then retention (LIFECYCLE §7)
        return _go(ctx, a, backup.plan_backup(ctx, a.instance, "scheduled", None, False, scheduled=True), "")
    return _go(ctx, a, backup.plan_backup(ctx, a.instance, a.klass, a.reason, a.prune), "")


def _verify(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import backup

    if (a.bundle is None) != a.latest:
        raise CannotRun("verify takes a bundle id or --latest", code="usage")
    plan = backup.plan_verify(ctx, a.instance, a.bundle, a.latest, a.restore_test, scheduled=a.scheduled)
    return _go(ctx, a, plan, "")


def _prune(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import backup

    found = backup.plan_prune(ctx, a.instance, a.apply)
    return found if isinstance(found, dict) else _go(ctx, a, found, f"{a.instance}: no bundle to delete")


def _scheduled(ctx: Ctx, a: Args) -> Report:
    """Unattended jobs (LIFECYCLE §7): never prompt; one line on success."""
    if a.job == "status":
        from ingat.ops import status

        return status.scheduled_status(ctx)
    return {"backup": _backup, "verify": _verify, "task": _task}[a.job](ctx, a)


def _selftest(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import selftest

    if a.offline:
        return selftest.run(ctx, host=False, offline=True)
    command = [brand.CLI, "selftest", *(["--host"] if a.host else [])]
    return _go(ctx, a, new_plan("selftest", None, "B", command, {}, {"host": a.host}, []), "")


def _read(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import status as st

    match a.cmd:
        case "status":
            return st.status(ctx, a.instance)
        case "doctor":
            return st.doctor(ctx, a.instance)
        case "list":
            return st.list_(ctx)
        case "ps":
            return st.ps(ctx, a.instance)
        case "logs":
            return st.logs(ctx, a.instance, a.service, a.since)
        case "history":
            return st.history(ctx, a.instance)
    return st.bundles(ctx, a.instance)


def _host(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import host

    return host.host_init(ctx) if a.what == "init" else host.host_check(ctx)


def _init(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import instance

    return instance.init(ctx, a.instance, a.config, a.ref)


def _validate(ctx: Ctx, a: Args) -> Report:
    validate(ctx, a.repo_dir, a.instance_file)
    return {"exit": 0, "code": "valid", "next": None, "lines": [f"{a.repo_dir}: valid"]}


def _cancel(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import lifecycle

    return lifecycle.cancel(ctx, a.instance)


HANDLERS: dict[str, Callable[[Ctx, Args], Report]] = {
    **dict.fromkeys(("status", "doctor", "list", "ps", "logs", "history", "bundles"), _read),
    **dict.fromkeys(("start", "stop", "restart", "resume", "abandon"), _lifecycle),
    "host init": _host,
    "host check": _host,
    "init": _init,
    "validate": _validate,
    "attach": lambda ctx, a: follow.attach(ctx, a.instance, a.out),
    "cancel": _cancel,
    "prepare": _prepare,
    "deploy": _deploy,
    "task": _task,
    "backup": _backup,
    "verify": _verify,
    "prune": _prune,
    "scheduled": _scheduled,
    "selftest": _selftest,
}


def _exec(a: Args) -> int:
    """The executor container's entry: run a saved plan; the host executor runs selftest (contract §21.2). The words
    must name the plan's own instance (or the host) and re-entry flag: the instance is resolved once (F1)."""
    words = a.words
    if len(words) != (2 if a.host else 3):
        raise CannotRun("usage: _exec <instance>|--host <plan-hash> <run-id> [--resume|--abandon]", code="usage")
    ctx = cx.make_ctx(os.environ)
    plan_hash, run_id = words[-2:]
    try:
        plan = approval.load(ctx.layout, plan_hash)
        want = (None if a.host else words[0], a.host, ["--resume"] * a.resume + ["--abandon"] * a.abandon)
        if (plan.instance, plan.op_kind == "selftest", follow.FLAGS.get(plan.op_kind, [])) != want:
            raise CannotRun("the executor's words do not match the plan", code="usage")
    except IngatError as e:
        _run_file(ctx, run_id, {"exit": e.exit_code, "code": e.code, "next": e.next, "lines": [e.message]})
        return e.exit_code
    if not a.host:
        return executor.execute(
            ctx.layout, ctx.docker, ctx.compose, plan_hash, run_id, resume=a.resume, abandon=a.abandon
        )
    from ingat.ops import selftest

    try:
        rep = selftest.run(ctx, host=bool(plan.inputs.get("host")), offline=False)
    except IngatError as e:
        rep = {"exit": e.exit_code, "code": e.code, "next": e.next, "lines": [e.message]}
    except BaseException:
        _run_file(ctx, run_id, {"exit": 4, "code": "executor-error", "lines": ["selftest stopped on an error"]})
        raise
    _run_file(ctx, run_id, rep)
    return int(rep["exit"])


def _run_file(ctx: Ctx, run_id: str, rep: Report) -> None:
    doc = records.new_doc("run", run_id=run_id, exit=rep["exit"], code=rep.get("code", ""), op=None)
    state.write_doc_once(
        ctx.layout.run(run_id), doc | {"message": "\n".join(rep.get("lines") or ()), "next": rep.get("next")}
    )


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CannotRun(f"{message}\n{self.format_usage().rstrip()}", code="usage")


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print one JSON object")
    top = _Parser(prog=brand.CLI, parents=[common], description="Deploy and keep Docker Compose apps on one host.")
    sub = top.add_subparsers(dest="cmd", required=True, metavar="<command>", parser_class=_Parser)

    def add(name: str, text: str | None, group: Any = sub, scheduled: bool = False) -> argparse.ArgumentParser:
        p: argparse.ArgumentParser = group.add_parser(name, parents=[common], help=text or argparse.SUPPRESS)
        p.set_defaults(scheduled=scheduled)
        return p

    def instance(name: str, text: str, group: Any = sub, scheduled: bool = False) -> argparse.ArgumentParser:
        p = add(name, text, group, scheduled)
        p.add_argument("instance")
        return p

    def verify(p: argparse.ArgumentParser) -> None:
        p.add_argument("bundle", nargs="?")
        p.add_argument("--latest", action="store_true")
        p.add_argument("--restore-test", action="store_true", help="the drill: restore into an isolated copy")

    def task(p: argparse.ArgumentParser) -> None:
        p.add_argument("task")
        p.add_argument("--arg", action="append", metavar="NAME=VALUE")
        p.add_argument("--input", action="append", metavar="NAME=FILE", help="a file in the inbox")

    add("version", "tool, wrapper and image versions")
    hosts = add("host", "host init | host check").add_subparsers(dest="what", required=True, parser_class=_Parser)
    add("init", "bind the tool root to this Docker engine (class C)", hosts)
    add("check", "record the host's facts and risks", hosts)
    p = instance("init", "register an instance from its instance.toml (class C)")
    p.add_argument("--config", required=True)
    p.add_argument("--ref", required=True)
    add("status", "records and live state; exit 5 when attention is needed").add_argument("instance", nargs="?")
    for name in ("doctor", "ps", "history", "bundles", "attach", "cancel", "resume", "abandon"):
        instance(name, f"{name} (class {COMMANDS[name].klass})")
    add("list", "the instances of this host")
    p = instance("logs", "a service's logs")
    p.add_argument("service")
    p.add_argument("--since")
    p = add("validate", "check an app repository")
    p.add_argument("repo_dir")
    p.add_argument("--instance", dest="instance_file", metavar="FILE")
    for name in ("prepare", "deploy"):
        instance(name, f"{name} a git ref (class {COMMANDS[name].klass})").add_argument("ref")
    for name in ("start", "stop", "restart"):
        instance(name, f"{name} services (class C)").add_argument("services", nargs="*")
    task(instance("task", "run a declared task (class B or C)"))
    p = instance("backup", "a bundle of the current deployment (class B)")
    p.add_argument("--class", dest="klass", default="manual")
    p.add_argument("--reason")
    p.add_argument("--prune", action="store_true")
    verify(instance("verify", "verify a bundle (class B)"))
    p = instance("prune", "retention of bundles (class B; dry run without --apply)")
    p.add_argument("--bundles", action="store_true", required=True)
    p.add_argument("--apply", action="store_true")
    jobs = add("scheduled", "unattended jobs").add_subparsers(dest="job", required=True, parser_class=_Parser)
    instance("backup", "a scheduled backup, then retention", jobs, True)
    verify(instance("verify", "verify or drill a bundle", jobs, True))
    task(instance("task", "a class B task", jobs, True))
    add("status", "mail-worthy attention changes", jobs, True)
    sel = add("selftest", "throwaway instances end to end (--host certifies the platform build)")
    mode = sel.add_mutually_exclusive_group()
    mode.add_argument("--host", action="store_true")
    mode.add_argument("--offline", action="store_true")
    p = add("_exec", None)
    p.add_argument("--host", action="store_true")
    p.add_argument("words", nargs="+")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--abandon", action="store_true")
    return top
