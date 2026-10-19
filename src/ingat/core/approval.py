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
        why = (
            "This change is of the most serious kind (class D: it needs you at a real terminal with a typed "
            "challenge), and this version cannot approve such changes yet. Nothing was changed."
        )
        raise Refused(why, code="not-in-this-release")
    if not tty:
        raise CannotRun(
            "This command needs your approval: the instance name must be typed on a terminal, and it was not started "
            "from one (for example from a script or a scheduler). Run it yourself in a terminal window (`apply`, the "
            "way to approve without one, arrives in M2). Nothing was changed.",
            code="no-tty",
        )
    prompt = (
        "This command needs your approval before it runs. Any answer other than the instance name refuses it, and "
        "nothing is changed.\nType the instance name to approve: "
    )
    if ask(prompt).strip() != plan.instance:
        why = "The answer did not match the instance name: not approved; nothing was changed."
        raise Refused(why, code="not-approved")


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
        raise CannotRun(f"No saved plan with id {plan_hash} was found. Plan the change again.", code="no-plan") from e
    plan = Plan.from_doc(records.loads(data))
    if plan.hash != plan_hash:
        why = (
            "The saved plan file was altered after it was approved, so it will not run. Nothing was changed; plan "
            "again."
        )
        raise Refused(why, code="plan-mismatch")
    if records.parse_iso(plan.expires_at) < records.utc_now():
        why = (
            "This plan is too old to run safely (plans expire). Nothing was changed. Run the command again to make a "
            "fresh plan."
        )
        raise CannotRun(why, code="plan-expired")
    return plan
