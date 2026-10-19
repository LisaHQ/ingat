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
        why = "Stopped by Ctrl-C. If a command was in the middle of its work, run "
        why += f"`{brand.CLI} status` to see where it stands."
        rep = {"exit": 130, "code": "cancelled", "message": why, "next": None, "lines": [why]}
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
        raise CannotRun(
            f"This command needs your approval: the {what} name must be typed on a terminal, and it was not started "
            "from one (for example from a script or a scheduler). Run it yourself in a terminal window. "
            "Nothing was changed.",
            code="no-tty",
        )
    prompt = (
        f"This command needs your approval before it runs. Any answer other than the {what} name refuses it, and "
        f"nothing is changed.\nType the {what} name to approve: "
    )
    if render.ask(prompt).strip() != expected:
        why = f"The answer did not match the {what} name: not approved; nothing was changed."
        raise Refused(why, code="not-approved")


def _version() -> Report:
    wrapper = os.environ.get(brand.env("WRAPPER_VERSION")) or None
    image = os.environ.get(brand.env("IMAGE")) or None
    lines = [f"{brand.CLI} {__version__}", f"start script (wrapper): {wrapper or 'not set'}"]
    lines.append(f"tool image: {image or 'not set'}")
    data = {"version": __version__, "wrapper": wrapper, "image": image}
    return {"exit": 0, "code": "ok", "next": None, "lines": lines, **data}


def _go(ctx: Ctx, a: Args, plan: Plan | None, nothing: str) -> Report:
    """Summary, approval, then the detached executor (or this process for a terminal task)."""
    if plan is None:
        return {"exit": 0, "code": "nothing-to-do", "next": None, "lines": [nothing]}
    if plan.approval < COMMANDS.get(plan.op_kind, COMMANDS[a.cmd]).klass[0]:  # the table's class is a floor (F3)
        raise Refused(
            f"Internal error: the plan for '{plan.op_kind}' carries approval class {plan.approval}, lower than this "
            "command allows. Nothing was changed; please report this.",
            code="internal",
        )
    tasks = [s.args for s in plan.steps if s.type == "RunTask"]
    terminal = bool(plan.inputs.get("foreground")) or any(
        "terminal" in (t.get("stdin"), t.get("stdout")) for t in tasks
    )
    if a.scheduled and (plan.approval not in ("A", "B") or terminal):
        why = f"needs your typed approval (approval class {plan.approval})"
        if plan.approval == "D":
            why = f"needs you at a real terminal with a typed challenge (approval class {plan.approval})"
        if terminal:
            why = "needs a terminal (it shows its output there or reads answers from it)"
        raise CannotRun(
            "Scheduled jobs run with nobody present, so they can only do work that needs no approval and no "
            f"terminal. This job {why}, so it was not started. Run it yourself in a terminal window. "
            "Nothing was changed.",
            code="unattended",
        )
    if not a.scheduled:
        render.say(a.out, render.plan_summary(plan))
    if any(t.get("stdin") == "terminal" for t in tasks) and not ctx.tty:
        raise CannotRun(
            "This task needs you to type answers while it runs. Run it yourself in a terminal window, not from a "
            "script or a scheduler. Nothing was changed.",
            code="no-tty",
        )
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
                line += f"; the earlier unfinished operation {seq} ({kind}) was undone and closed automatically first"
        rep["lines"], rep["next"] = [line], rep["next"] if getattr(a, "json", False) else None  # JSON keeps `next`
    return rep


def _foreground(ctx: Ctx, plan: Plan) -> Report:
    """A terminal task, or the resume of its operation: under the instance lock in this process (ARCHITECTURE
    §4.3). A resume reports the result of the operation it resumed, unless its plan was stale (exit 1). An operation
    left open (its task container still running, paused, interrupted) reports what the executor decided, the exact
    next command included, as the detached executor's run file would."""
    approval.save(ctx.layout, plan)
    res = executor.run_in_process(ctx.layout, ctx.docker, ctx.compose, plan, tty=ctx.tty)
    op_dir, name, code = plan.inputs["op_dir"], plan.instance, res.exit
    own, result = os.path.join(op_dir, "plan.json"), os.path.join(op_dir, "result.json")
    resumed = plan.op_kind == "resume" and code != 1
    if fs.exists(result) and (resumed or records.doc_hash(state.read_doc(own, "plan")) == plan.hash):
        doc = state.read_doc(result, "result")
        line, nxt = doc["message"], doc["next"]
        return {"exit": code, "code": doc["code"], "message": line, "next": nxt, "op": doc["op"], "lines": [line]}
    if code == 0 and plan.op_kind == "task" and plan.inputs.get("into_op") is not None:  # the paused one stays open
        line = "The task finished. The paused operation it ran inside is still waiting; run the 'next' command to "
        line, nxt = line + "continue it.", f"{brand.CLI} resume {name}"
        return {"exit": 0, "code": "completed", "message": line, "next": nxt, "lines": [line]}
    nxt = res.next or f"{brand.CLI} status {name}"
    return {"exit": code, "code": res.code, "message": res.message, "next": nxt, "op": res.op, "lines": [res.message]}


def _prepare(ctx: Ctx, a: Args) -> Report:
    nothing = f"Version {a.ref} is already downloaded and ready to deploy to {a.instance}. Nothing to do."
    return _go(ctx, a, deploy.plan_prepare(ctx, a.instance, a.ref), nothing)


def _deploy(ctx: Ctx, a: Args) -> Report:
    """Deploy; a ref without a prepared candidate is prepared first (class B), then planned again."""
    try:
        plan = deploy.plan_deploy(ctx, a.instance, a.ref)
    except Refused as e:
        if e.code != "no-candidate":
            raise
        if not ctx.tty:  # the deploy needs typed approval: refuse before preparing anything (prepare is class B)
            raise CannotRun(
                "deploy changes your app, so you must approve it by typing the instance name on a terminal, and this "
                "was not started from one. From a script you can only download and prepare the version first "
                "(no approval needed): see 'next' below. Nothing was changed.",
                code="no-tty",
                next=f"{brand.CLI} prepare {a.instance} {a.ref}",
            ) from e
        render.say(a.out, [f"Version {a.ref} is not ready on this computer yet: preparing {a.ref} first (downloading "
                           "its images), then deploying."])  # fmt: skip
        nothing = f"Version {a.ref} is downloaded and ready to deploy."
        rep = _go(ctx, a, deploy.plan_prepare(ctx, a.instance, a.ref), nothing)
        if rep["exit"] != 0:
            return rep
        render.say(a.out, rep["lines"])
        plan = deploy.plan_deploy(ctx, a.instance, a.ref)
    nothing = f"{a.instance} is already deployed at {a.ref} with these settings, so nothing would change. "
    return _go(ctx, a, plan, nothing + "Nothing to do.")


def _lifecycle(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import lifecycle as lc

    plan: Plan | None
    if a.cmd in ("resume", "abandon"):
        plan = (lc.plan_resume if a.cmd == "resume" else lc.plan_abandon)(ctx, a.instance)
    else:
        plan = {"start": lc.plan_start, "stop": lc.plan_stop, "restart": lc.plan_restart}[a.cmd](
            ctx, a.instance, a.services
        )
    return _go(ctx, a, plan, f"{a.instance}: nothing to {a.cmd}; it is already in that state.")


def _pairs(items: list[str] | None, flag: str) -> dict[str, str]:
    out = {}
    for item in items or ():
        key, eq, value = item.partition("=")
        if not eq or not key:
            raise CannotRun(
                f"{flag} needs the form NAME=VALUE (a name, then =, then the value, no spaces around =); got {item!r}.",
                code="usage",
            )
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
        raise CannotRun(
            "verify needs exactly one of these: the id of the backup copy to check "
            f"(see `{brand.CLI} bundles {a.instance}`), or --latest for the newest backup copy.",
            code="usage",
        )
    plan = backup.plan_verify(ctx, a.instance, a.bundle, a.latest, a.restore_test, scheduled=a.scheduled)
    return _go(ctx, a, plan, "")


def _prune(ctx: Ctx, a: Args) -> Report:
    from ingat.ops import backup

    found = backup.plan_prune(ctx, a.instance, a.apply)
    nothing = f"{a.instance}: no old backup copies to remove; every copy is still within the keep rules."
    return found if isinstance(found, dict) else _go(ctx, a, found, nothing)


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
    line = f"{a.repo_dir}: the app's settings file ({brand.MANIFEST_FILE}) is valid"
    line += f", and the instance file {a.instance_file} fits it" if a.instance_file else ""
    return {"exit": 0, "code": "valid", "next": None, "lines": [line]}


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
        why = (
            "The self-test stopped on an unexpected error in the tool itself. It only works on its own throwaway test "
            f"instances, never on your apps, but some of those may be left behind: run `{brand.CLI} status` to see. "
            "Please report this error."
        )
        _run_file(ctx, run_id, {"exit": 4, "code": "executor-error", "lines": [why]})
        raise
    _run_file(ctx, run_id, rep)
    return int(rep["exit"])


def _run_file(ctx: Ctx, run_id: str, rep: Report) -> None:
    doc = records.new_doc("run", run_id=run_id, exit=rep["exit"], code=rep.get("code", ""), op=None)
    state.write_doc_once(
        ctx.layout.run(run_id), doc | {"message": "\n".join(rep.get("lines") or ()), "next": rep.get("next")}
    )


JSON_HELP = "print the answer as one JSON object (for scripts and automation)"
ABOUT = "Install, update, back up and look after your apps (Docker Compose) on this computer."
HELP = {  # the help line of each command (plain words; the approval class in words, LIFECYCLE §2)
    "version": "show the version of this tool, of its start script and of its image",
    "host": "set up or check this computer: host init (first-time setup), host check (record facts and risks)",
    "host init": "first-time setup: tie this tool's folder to the Docker engine on this computer "
    "(needs your typed approval)",
    "host check": "check this computer and record what was found, including risks",
    "init": "add a new app instance from its instance.toml settings file (needs your typed approval)",
    "status": "show how your apps are doing; the exit code is 5 when something needs your attention",
    "doctor": "a deeper check of one app: its settings, the safety rules, whether this computer is cleared to run "
    "changes, its secret files, port and network clashes, and its folders",
    "ps": "list the app's containers (its parts, running or not), including any that this tool did not create",
    "history": "list the app's past operations and how each one ended",
    "bundles": "list the app's backup copies, how well each one was checked, and how old it is",
    "attach": "watch an operation that is still running or waiting",
    "cancel": "ask the running operation to stop at its next safe point (no approval needed)",
    "resume": "continue an unfinished operation from where it stopped (needs your typed approval)",
    "abandon": "give up an unfinished operation: undo what it did where possible, clean up and close it "
    "(needs your typed approval)",
    "list": "list the app instances on this computer",
    "logs": "show the log messages of one part (service) of the app",
    "validate": f"check that an app's settings files ({brand.MANIFEST_FILE}, and optionally an instance.toml) are "
    "correct, without changing anything",
    "prepare": "download a version of the app (a git branch, tag or commit) and its images so it is ready to "
    "deploy; the running app is not changed",
    "deploy": "install the app, or switch it to a version (git branch, tag or commit); downloads the version first "
    "if needed (needs your typed approval)",
    "backup": "make a backup copy of the app's data as it is now (no approval needed)",
    "verify": "check that a backup copy is complete and unchanged; add --restore-test to also try restoring it "
    "in isolation",
    "prune": "remove old backup copies by the keep rules; without --apply it only lists what would be removed",
    "scheduled": "jobs for a scheduler to run with nobody present (they never ask questions)",
    "selftest": "test this tool on this computer with throwaway apps that are removed afterwards (anything it "
    "cannot remove is reported); --host also records the result as this computer's certification, which the "
    "tool needs before it changes anything here",
}
RESTORE_TEST_HELP = (
    "test restore: restore the backup copy into a separate, isolated copy of the app, check it, then remove it; "
    "your live app and data are not touched"
)
INPUT_HELP = "a file you placed in the tool's inbox folder, given as NAME=FILE with just the file name"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        usage = f"{message}\n{self.format_usage().rstrip()}\n"
        raise CannotRun(usage + f"Run `{self.prog} --help` to see what each command needs.", code="usage")


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=JSON_HELP)
    top = _Parser(prog=brand.CLI, parents=[common], description=ABOUT)
    sub = top.add_subparsers(dest="cmd", required=True, metavar="<command>", parser_class=_Parser)

    def add(name: str, text: str | None, group: Any = sub, scheduled: bool = False) -> argparse.ArgumentParser:
        """`text` None: the subcommand is left out of the listing (argparse would print SUPPRESS there literally)."""
        listed = {} if text is None else {"help": text}
        p: argparse.ArgumentParser = group.add_parser(name, parents=[common], **listed)
        p.set_defaults(scheduled=scheduled)
        return p

    def instance(name: str, text: str, group: Any = sub, scheduled: bool = False) -> argparse.ArgumentParser:
        p = add(name, text, group, scheduled)
        p.add_argument("instance")
        return p

    def verify(p: argparse.ArgumentParser) -> None:
        p.add_argument("bundle", nargs="?")
        p.add_argument("--latest", action="store_true")
        p.add_argument("--restore-test", action="store_true", help=RESTORE_TEST_HELP)

    def task(p: argparse.ArgumentParser) -> None:
        p.add_argument("task")
        p.add_argument("--arg", action="append", metavar="NAME=VALUE")
        p.add_argument("--input", action="append", metavar="NAME=FILE", help=INPUT_HELP)

    add("version", HELP["version"])
    hosts = add("host", HELP["host"]).add_subparsers(dest="what", required=True, parser_class=_Parser)
    add("init", HELP["host init"], hosts)
    add("check", HELP["host check"], hosts)
    p = instance("init", HELP["init"])
    p.add_argument("--config", required=True)
    p.add_argument("--ref", required=True)
    add("status", HELP["status"]).add_argument("instance", nargs="?")
    for name in ("doctor", "ps", "history", "bundles", "attach", "cancel", "resume", "abandon"):
        instance(name, HELP[name])
    add("list", HELP["list"])
    p = instance("logs", HELP["logs"])
    p.add_argument("service")
    p.add_argument("--since")
    p = add("validate", HELP["validate"])
    p.add_argument("repo_dir")
    p.add_argument("--instance", dest="instance_file", metavar="FILE")
    p = instance("prepare", HELP["prepare"])
    p.add_argument("ref")
    p = instance("deploy", HELP["deploy"])
    p.add_argument("ref")
    for name in ("start", "stop", "restart"):
        text = f"{name} the app as last deployed, or only the parts (services) you name (needs your typed approval)"
        instance(name, text).add_argument("services", nargs="*")
    text = "run one of the app's own commands that its settings declare"
    task(instance("task", f"{text} (no approval for a read-only one; typed approval for one that changes data)"))
    p = instance("backup", HELP["backup"])
    p.add_argument("--class", dest="klass", default="manual")
    p.add_argument("--reason")
    p.add_argument("--prune", action="store_true")
    verify(instance("verify", HELP["verify"]))
    p = instance("prune", HELP["prune"])
    p.add_argument("--bundles", action="store_true", required=True)
    p.add_argument("--apply", action="store_true")
    jobs = add("scheduled", HELP["scheduled"]).add_subparsers(dest="job", required=True, parser_class=_Parser)
    instance(
        "backup",
        "make a backup copy, then remove old copies by the keep rules (no approval needed; for a scheduler)",
        jobs,
        True,
    )
    verify(
        instance(
            "verify",
            "check a backup copy, or with --restore-test try restoring it in isolation (for a scheduler)",
            jobs,
            True,
        )
    )
    task(
        instance(
            "task",
            "run one of the app's read-only commands (for a scheduler; a command that changes data is refused)",
            jobs,
            True,
        )
    )
    text = "print only what newly needs your attention or stopped needing it since the last run"
    add("status", f"{text}, so a scheduler can mail you once", jobs, True)
    sel = add("selftest", HELP["selftest"])
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
