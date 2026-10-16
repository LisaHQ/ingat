"""Approval classes and plan files (LIFECYCLE §2, ADR-0013). M1: classes A-C; class D arrives in M2."""

from collections.abc import Callable

from ingat.core.plan import Plan
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.store import fs, state


def approve(plan: Plan, *, tty: bool, ask: Callable[[str], str]) -> None:
    """Class A and B need nothing; class C needs the instance name typed on a terminal."""
    if plan.approval in ("A", "B"):
        return
    if plan.approval == "D":
        raise Refused("this change needs class D approval, which arrives in M2", code="not-in-this-release")
    if not tty:
        raise CannotRun(
            "a class C change needs a terminal to type the instance name (`apply` arrives in M2)", code="no-tty"
        )
    if ask("Type the instance name to approve: ").strip() != plan.instance:
        raise Refused("not approved; nothing was changed", code="not-approved")


def save(layout: state.Layout, plan: Plan) -> str:
    """Write the approved plan write-once to plans/<hash>.json and return its hash."""
    data = records.pretty(plan.doc())
    path = layout.plan(plan.hash)
    try:
        fs.write_once(path, data)
    except FileExistsError:
        if fs.read(path) != data:
            raise
    return plan.hash


def load(layout: state.Layout, plan_hash: str) -> Plan:
    try:
        data = fs.read(layout.plan(plan_hash))
    except FileNotFoundError as e:
        raise CannotRun(f"no saved plan {plan_hash}", code="no-plan") from e
    plan = Plan.from_doc(records.loads(data))
    if plan.hash != plan_hash:
        raise Refused("plan file does not match its hash", code="plan-mismatch")
    if records.parse_iso(plan.expires_at) < records.utc_now():
        raise CannotRun("the plan has expired; plan again", code="plan-expired")
    return plan
