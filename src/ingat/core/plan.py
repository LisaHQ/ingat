"""Plans: an ordered list of typed steps plus frozen inputs and the observed fingerprint (LIFECYCLE §3.1, F3, F4)."""

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from ingat import __version__, brand
from ingat.adapters.docker import Docker
from ingat.model import records
from ingat.model.errors import Refused
from ingat.store import fs, state

KLASSES = ("scratch", "reversible", "forward", "idempotent", "operator")
STEP_TYPES = (
    "Obtain RunTask SnapshotLogs Stop CreateGeneration Up CaptureBundle VerifyBundle SwitchGeneration"
    " Teardown Delete Record Pause".split()
)
PLAN_TTL = timedelta(hours=24)
PROJECT_LABEL = "com.docker.compose.project"
CONFIG_HASH_LABEL = "com.docker.compose.config-hash"


@dataclass(frozen=True)
class Step:
    n: int
    type: str
    klass: str
    args: dict[str, Any] = field(default_factory=dict)
    interruptible: bool = False
    group: str | None = None
    always: bool = False
    forward_point: bool = False


@dataclass(frozen=True)
class Plan:
    op_kind: str
    instance: str | None
    approval: str
    command: list[str]
    fingerprint: dict[str, Any]
    inputs: dict[str, Any]
    steps: tuple[Step, ...]
    created_at: str
    expires_at: str
    tool_version: str

    def doc(self) -> dict[str, Any]:
        return records.new_doc("plan", **asdict(self))

    @property
    def hash(self) -> str:
        return records.doc_hash(self.doc())

    @staticmethod
    def from_doc(doc: object) -> "Plan":
        d = dict(records.check_schema(doc, "plan"))
        steps = tuple(Step(**s) for s in d.pop("steps"))
        d.pop("state_schema")
        d.pop("kind")
        return Plan(steps=steps, **d)


def new_plan(
    op_kind: str,
    instance: str | None,
    approval: str,
    command: list[str],
    fingerprint: dict[str, Any],
    inputs: dict[str, Any],
    steps: Iterable[dict[str, Any]],
) -> Plan:
    """Number the steps 1..n, check their types and classes, and stamp the plan's lifetime."""
    built = []
    for n, s in enumerate(steps, 1):
        step = Step(n=n, **s)
        if step.type not in STEP_TYPES or step.klass not in KLASSES:
            raise Refused(f"internal: step {n} has type {step.type!r} and class {step.klass!r}", code="internal")
        built.append(step)
    now = records.utc_now()
    return Plan(
        op_kind, instance, approval, command, fingerprint, inputs, tuple(built),
        records.iso(now), records.iso(now + PLAN_TTL), __version__,
    )  # fmt: skip


def fingerprint(layout: state.Layout, docker: Docker, instance: str, bundles: Iterable[str] = ()) -> dict[str, Any]:
    """What a plan was computed against; the executor recomputes it and refuses a mismatch (F3)."""
    rec = state.read_doc(layout.record_json(instance), "instance")
    containers = []
    for c in docker.containers(labels={brand.label("instance"): instance}):
        labels = c["Config"].get("Labels") or {}
        if PROJECT_LABEL in labels:
            containers.append(
                [c["Name"].lstrip("/"), c["Id"], c["Image"], labels.get(CONFIG_HASH_LABEL, ""), c["State"]["Status"]]
            )
    paths = {b: layout.catalog(instance, b) for b in bundles}
    catalog = {b: state.read_doc(p, "catalog")["bundle_hash"] if fs.exists(p) else None for b, p in paths.items()}
    return {
        "record": {k: rec.get(k) for k in ("state", "current_deployment", "generations", "held_since", "open_op")},
        "next_seq": state.next_seq(layout, instance),
        "containers": sorted(containers),
        "bundles": catalog,
    }
