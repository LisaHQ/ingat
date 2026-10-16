"""Output (LIFECYCLE §4.15, §6): human lines, or one JSON object on stdout carrying `code`, `exit` and `next`.

A Report is a plain dict `{"exit", "code", "next", "lines", ...data}`; `--json` prints it without `lines`. Errors print
as `<cli>: message` plus `next: <command>` on stderr. Plans and records never hold secret values, so a plan summary
shows step arguments as they are."""

import json
import sys
from typing import Any, TextIO

from ingat import brand
from ingat.core.plan import Plan, Step
from ingat.model.errors import IngatError

Report = dict[str, Any]
SHOWN = {  # the step arguments a plan summary names, per step type
    "Obtain": ("images", "commit"),
    "CreateGeneration": ("store", "gen", "purpose"),
    "Up": ("variant", "services", "wait", "identity", "smoke"),
    "Stop": ("variant", "services"),
    "RunTask": ("task", "variant", "effect"),
    "CaptureBundle": ("phase", "class"),
    "VerifyBundle": ("bundle",),
    "Teardown": ("variant",),
    "Delete": ("item",),
    "Record": ("kind", "level"),
    "Pause": ("allow_tasks",),
}


def _text(v: Any) -> str:
    if isinstance(v, list):
        return ",".join(_text(x) for x in v)
    if isinstance(v, dict):
        for key in ("ref", "id", "name", "path"):
            if isinstance(v.get(key), str):
                return str(v[key])
        return json.dumps(v, sort_keys=True, separators=(",", ":"))
    return "-" if v is None else str(v)


def step_line(s: Step) -> str:
    args = " ".join(f"{k}={_text(s.args[k])}" for k in SHOWN.get(s.type, ()) if s.args.get(k) not in (None, [], False))
    marks = [s.klass] + ["forward point"] * s.forward_point + ["always"] * s.always
    return f"{s.n:>3}. {s.type} {args}".rstrip() + f"  [{', '.join(marks)}]"


def plan_summary(plan: Plan) -> list[str]:
    """Op kind, target, approval class, each step `n. Type key=args [class]`, warnings."""
    target = plan.instance or "host"
    release = plan.inputs.get("release")
    head = f"{plan.op_kind} {target}" + (f" at {release}" if release else "")
    lines = [f"{head}: approval class {plan.approval}, {len(plan.steps)} step(s)"]
    lines += [step_line(s) for s in plan.steps]
    return lines + [f"warning: {w}" for w in plan.inputs.get("warnings") or ()]


def say(out: TextIO | None, lines: list[str]) -> None:
    """Progress and summaries: stdout, or stderr under --json (stdout then holds only the answer); None is quiet."""
    for line in lines if out is not None else ():
        print(line, file=out, flush=True)


def ask(prompt: str) -> str:
    """One answer typed on the terminal; the prompt goes to stderr so that stdout stays the answer. EOF is ""."""
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline()


def report(rep: Report, as_json: bool) -> int:
    """Print a Report and return its exit code."""
    code = int(rep.get("exit", 0))
    if as_json:
        doc = {k: v for k, v in rep.items() if k != "lines"} | {"exit": code, "next": rep.get("next")}
        doc.setdefault("code", "ok" if code == 0 else "error")
        print(json.dumps(doc, sort_keys=True, indent=2), flush=True)
        return code
    ok = code in (0, 5)
    stream = sys.stdout if ok else sys.stderr
    for line in rep.get("lines") or ():
        print(line if ok else f"{brand.CLI}: {line}", file=stream)
    if rep.get("next"):
        print(f"next: {rep['next']}", file=stream)
    stream.flush()
    return code


def error(e: IngatError, as_json: bool) -> int:
    rep = {"exit": e.exit_code, "code": e.code, "message": e.message, "next": e.next, "lines": [e.message]}
    return report(rep, as_json)
