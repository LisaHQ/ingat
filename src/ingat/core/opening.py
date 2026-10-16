"""Opening, loading and joining an operation for the executor (ARCHITECTURE §4, contract §20.2): read-only loads of
an open operation, the rendered app env file, and an operation directory made whole before it exists (F2)."""

import os
import secrets
import string
from typing import Any

from ingat import brand
from ingat.adapters.compose import Compose
from ingat.adapters.docker import Docker
from ingat.adapters.runner import Redactor
from ingat.core import steps
from ingat.core.journal import Journal
from ingat.core.plan import Plan
from ingat.core.steps import SUBNET, Op
from ingat.model import records
from ingat.model.errors import Refused
from ingat.store import fs, state

JOIN_BASE = 1000  # a task a paused operation allows is journaled there as step 1000 + k
OPENING = ".opening"  # an operation directory being materialized; renamed into place whole
ALNUM = string.ascii_letters + string.digits
SIGNALLED = [False]  # set by the executor's signal handlers: a cancel request (ARCHITECTURE §4.4)


def op_of(layout: state.Layout, docker: Docker, compose: Compose, plan: Plan, seq: int, d: str, **kw: Any) -> Op:
    name = plan.instance or ""
    journal = Journal(d, seq, os.environ.get(brand.env("CRASH_AT")))
    return Op(layout, docker, compose, plan, name, seq, d, journal, signalled=lambda: SIGNALLED[0], **kw)


def load(
    layout: state.Layout, docker: Docker, compose: Compose, name: str, seq: int, kind: str, fg: bool, tty: bool
) -> Op:
    """The open operation as its own plan.json and journal describe it (read-only), run by the CLI when `fg`."""
    d = layout.op_dir(name, seq, kind)
    plan = Plan.from_doc(state.read_doc(os.path.join(d, "plan.json"), "plan"))
    op = op_of(layout, docker, compose, plan, seq, d, vdir=os.path.join(d, "v"), foreground=fg, tty=tty)
    rep = op.journal.replay()
    op.evidence = {n: r["done_evidence"] or {} for n, r in rep.items() if r["phase"] == "done"}
    op.attempts = {n: r["attempts"] for n, r in rep.items()}
    op.subnets = {param: subnet for param, (_, subnet) in steps.allocations(layout, name, seq).items()}
    redact(op, secret_values(op.plan))
    return op


def secret_values(plan: Plan) -> list[str]:
    """Every secret value a plan's operation may meet: its secret files, app env secrets and throwaway secrets."""
    paths = [*plan.inputs.get("redact_files", []), *plan.inputs.get("throwaway_secrets", {})]
    lines = (plan.inputs.get("app_env") or {}).get("lines", [])
    paths += [src["secret_file"] for _, src in lines if "secret_file" in src]
    try:
        texts = [fs.read(x).decode() for x in paths if fs.exists(x)]
    except UnicodeDecodeError as e:
        raise Refused("a secret file is not UTF-8 text, so it could not be redacted", code="secret-file") from e
    return texts + [x.rstrip("\r\n") for x in texts]  # an app reads a file secret without its final newline


def redact(op: Op, values: list[str]) -> None:
    """Captured text of this operation masks these values (F12)."""
    op.docker.redactor = op.compose.redactor = Redactor(values)


def joinable(old: Op, plan: Plan) -> bool:
    rep = old.journal.replay()
    paused = [s for s in old.plan.steps if s.type == "Pause" and rep.get(s.n, {}).get("phase") == "intent"]
    names = {s.args.get("task") for s in plan.steps if s.type == "RunTask"}
    allowed = set(paused[-1].args.get("allow_tasks", [])) if paused else set()
    return plan.op_kind == "task" and bool(names) and names <= allowed


def app_env(layout: state.Layout, name: str, spec: dict[str, Any] | None) -> tuple[str, bytes] | None:
    """The live app env file, rendered now (secrets read from their files); its hash must be the plan's."""
    if not spec:
        return None
    try:
        lines = {k: fs.read(s["secret_file"]).decode() if "secret_file" in s else s["value"] for k, s in spec["lines"]}
    except UnicodeDecodeError as e:
        raise Refused("an app env secret file is not UTF-8 text", code="secret-file") from e
    data, path = steps.env_text(lines), os.path.join(layout.env_dir(name), f"{spec['sha256']}.env")
    if (
        records.sha256_hex(data) != spec["sha256"]
        or spec["path"] != path
        or (fs.exists(path) and fs.read(path) != data)
    ):
        raise Refused(
            "the app env file differs from the plan (a secret or setting changed); plan again", code="stale-plan"
        )
    return path, data


def ensure(env: tuple[str, bytes] | None) -> None:
    """Write the content-addressed live app env file if it is missing."""
    if env and not fs.exists(env[0]):
        fs.write_once(*env)


def _variants(vdir: str, plan: Plan, subnets: dict[str, str]) -> None:
    for vname, v in plan.inputs.get("variants", {}).items():
        fs.write_once(os.path.join(vdir, f"{vname}.yaml"), v["override"].encode())
        env = {k: subnets[k] if x == SUBNET else x for k, x in v["env"].items()}
        fs.write_once(os.path.join(vdir, f"{vname}.env"), steps.env_text(env))


def _inside(base: str, op_dir: str, path: str) -> str:
    rel = os.path.relpath(path, op_dir)
    if os.path.normpath(path) != path or not os.path.isabs(path) or rel.startswith(".."):
        raise Refused(f"internal: {path} is not inside the operation directory", code="internal")
    return os.path.join(base, rel)


def open_op(
    layout: state.Layout,
    docker: Docker,
    compose: Compose,
    plan: Plan,
    host: dict[str, Any],
    env: tuple[str, bytes] | None,
    values: list[str],
    fg: bool,
    tty: bool,
) -> Op:
    """Make ops/<seq>-<kind>/ whole (plan, variants, files, throwaway secrets), then mark the record."""
    name, seq, inputs = plan.instance or "", int(plan.inputs["seq"]), plan.inputs
    d = layout.op_dir(name, seq, plan.op_kind)
    if inputs.get("op_dir", d) != d or seq != state.next_seq(layout, name):
        raise Refused("internal: the plan's operation sequence is not the next one", code="internal")
    params = {k for v in inputs.get("variants", {}).values() for k, x in v["env"].items() if x == SUBNET}
    throwaway = {
        path: "".join(secrets.choice(ALNUM) for _ in range(32)) for path in inputs.get("throwaway_secrets", {})
    }
    tmp = os.path.join(layout.ops_dir(name), OPENING)
    try:
        subnets = steps.allocate(layout, docker, name, seq, params, host["pools"]["isolation"]) if params else {}
        op = op_of(layout, docker, compose, plan, seq, d, vdir=f"{d}/v", foreground=fg, tty=tty, subnets=subnets)
        redact(op, [*values, *throwaway.values()])
        fs.remove_tree(tmp)
        state.write_doc_once(os.path.join(tmp, "plan.json"), plan.doc())
        _variants(os.path.join(tmp, "v"), plan, subnets)
        for path, text in inputs.get("files", {}).items():
            fs.write_once(_inside(tmp, d, path), text.encode())
        for path, mode in inputs.get("throwaway_secrets", {}).items():
            fs.write_once(_inside(tmp, d, path), throwaway[path].encode(), mode)
        ensure(env)  # before the operation exists, so it never exists without its env file
        fs.rename(tmp, d)
    except BaseException:  # a refusal while opening leaves no trace (F2): no half-made directory, no allocation
        fs.remove_tree(tmp)
        for path, _ in steps.allocations(layout, name, seq).values():
            fs.remove(path)
        raise
    started = records.iso(records.utc_now())
    op.update(open_op={"seq": seq, "kind": plan.op_kind, "dir": d, "started_at": started}, next_seq=seq + 1)
    return op


def join(old: Op, plan: Plan, env: tuple[str, bytes] | None, values: list[str], fg: bool, tty: bool) -> Op:
    """Run an allowed task inside the paused operation, journaled as steps above JOIN_BASE (ARCHITECTURE §4.3)."""
    ensure(env)
    offset = max([JOIN_BASE, *old.journal.replay()])
    vdir = old.path(f"v{offset}")
    fs.remove_tree(vdir)  # left by a join killed before its first intent
    _variants(vdir, plan, old.subnets)
    op = op_of(old.layout, old.docker, old.compose, plan, old.seq, old.dir, vdir=vdir, offset=offset, foreground=fg,
               tty=tty, subnets=old.subnets)  # fmt: skip
    redact(op, [*secret_values(old.plan), *values])
    return op
