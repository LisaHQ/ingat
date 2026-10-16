"""Task, capture and verify steps of plans (contract §20.8; LIFECYCLE §4.7, §4.8), rendered from the manifest and a
variant, and the verification levels a bundle holds (§5.5)."""

import os
import re
from collections.abc import Mapping
from typing import Any

from ingat import brand
from ingat.model import records
from ingat.model.errors import Refused
from ingat.model.manifest import Manifest, Task
from ingat.ops import context as cx
from ingat.ops.context import Ctx, Loaded
from ingat.store import fs, state

_USER = re.compile("([0-9]+)(?::([0-9]+))?")


def task_uid(ctx: Ctx, v: Mapping[str, Any], model: Mapping[str, Any], t: Task) -> list[int]:
    """Owner of a task's stage and input copies: the task's user, else the service's, else the image's; numeric."""
    image = ctx.docker.image(v["images"][t.service]) or {}
    user = t.user or model["services"][t.service].get("user") or image.get("Config", {}).get("User") or "0"
    if (u := _USER.fullmatch(user)) is None:
        raise Refused(f"tasks.{t.name}: user {user!r} is not a numeric uid[:gid]", code="task-user")
    return [int(u[1]), int(u[2] or u[1])]


def task_step(ctx: Ctx, m: Manifest, v: Any, model: Any, t: Task, variant: str, klass: str, **kw: Any) -> Any:
    """A RunTask step (contract §20.8) of task `t` in variant `v` (named `variant`); templates stay for the executor.
    Options: `group`, `require_ok` (default true), `findings_ok`, `capacity`, `gen_paths`."""
    args: dict[str, Any] = {"task": t.name, "variant": variant, "service": t.service, "argv": list(t.argv)}
    args |= {"env": dict(t.env), "user": t.user, "stdout": t.stdout, "stdin": t.stdin}
    args["mounts"] = [[k, s] for k, s in t.mounts.items()]
    args |= {"effect": t.effect, "idempotent": t.idempotent, "observe": t.observe, "timeout": t.timeout}
    args["exit"] = {str(c): o for c, o in t.exit.items()}
    args["expect"] = None if t.expect is None else {k: list(x) for k, x in t.expect.items()}
    args |= {"require_ok": kw.get("require_ok", True), "findings_ok": kw.get("findings_ok", False)}
    args |= {"report": t.stdout == "record", "capacity": kw.get("capacity")}
    args["gen_paths"] = dict(kw.get("gen_paths") or {})
    args["store_params"] = {s[11:]: m.stores[s[11:]].param for s in t.mounts.values() if s.startswith("generation:")}
    args |= {"task_uid": task_uid(ctx, v, model, t) if t.mounts else None, "inputs": {}, "args": {}}
    args["max_input_bytes"] = t.max_input_bytes
    step = {"type": "RunTask", "klass": klass, "args": args, "interruptible": klass == "scratch"}
    return step | {"group": kw.get("group")}


def capture_steps(ctx: Ctx, ld: Loaded, v: Any, model: Any, steps: list[Any], name: str, klass: str, how: str) -> None:
    """Append the capture group (begin, backup tasks, seal), then VerifyBundle, the verify tasks and the `verified`
    record, for a bundle of class `klass` and consistency `how` of the recorded deployment, run in its variant `v`
    (named `name`) (LIFECYCLE §4.7, §4.8)."""
    dep, m, layout = ld.deployment, ld.manifest, ctx.layout
    if dep is None or m is None:
        raise Refused(f"{ld.name} has no deployment to back up", code="wrong-state")
    if m.schema and m.schema.task:
        raise Refused("reading a task-based [schema] before a capture arrives in M2", code="not-in-this-release")
    gens = {k: layout.data_gen(ld.name, k, f"g{n}") for k, n in (ld.record.get("generations") or {}).items()}
    kw: dict[str, Any] = {"group": "capture", "gen_paths": gens}  # for generation:<store> mounts
    tasks = [task_step(ctx, m, v, model, m.tasks[x], name, "scratch", **kw) for x in m.backup.steps]
    owner = next((t["args"]["task_uid"] for t in tasks if t["args"]["task_uid"]), [0, 0])
    snap = layout.deployment_snapshot(ld.name, dep["seq"])
    meta = {f: os.path.join(dep["export"], f) for f in m.files}
    meta[brand.MANIFEST_FILE] = os.path.join(snap, brand.MANIFEST_FILE)
    meta["deployment.json"] = layout.deployment_json(ld.name, dep["seq"])
    common: dict[str, Any] = {"variant": name, "class": klass, "naming": m.backup.naming[klass]}
    common |= {"payload": m.backup.payload, "stage_owner": owner}  # begin makes the stage the backup tasks write
    schema = dep.get("schema") and {k: dep["schema"].get(k) for k in ("expected", "actual")}
    if schema and schema["expected"] is not None:  # {schema.expected} of backup tasks (MANIFEST_SPEC §3)
        v.setdefault("values", {})["schema.expected"] = str(schema["expected"])
    seal = common | {"schema": schema, "meta_files": meta, "consistency": how}
    keys = ("seq", "release", "commit", "images", "manifest_sha256", "model_sha256")
    seal["deployment"] = {k: dep.get(k) for k in keys}
    seal |= {"lineage": ld.record.get("lineage"), "app": m.app, "environment": ld.inst.environment}
    seal |= {"stores": dict(ld.record.get("generations") or {}), "tool": cx.tool_facts(ctx), "host": ctx.hostname}
    capture = {"type": "CaptureBundle", "klass": "scratch", "interruptible": True, "group": "capture"}
    steps += [capture | {"args": {"phase": "begin", **common}}, *tasks, capture | {"args": {"phase": "seal", **seal}}]
    verify_steps(ctx, m, v, model, steps, name, None)


def verify_steps(ctx: Ctx, m: Manifest, v: Any, model: Any, steps: list[Any], name: str, bundle: str | None) -> None:
    """Append VerifyBundle of `bundle` (None: the capture group's), the `backup.verify` tasks in variant `v` (named
    `name`; None when there are none) and the `verified` record (LIFECYCLE §4.8)."""
    verify = [task_step(ctx, m, v, model, m.tasks[x], name, "scratch", group="verify") for x in m.backup.verify]
    n = len(steps) + 1
    readers = [t["args"]["task_uid"] for t in verify if any(s == "bundle" for _, s in t["args"]["mounts"])]
    check = {"bundle": bundle, "input_owner": readers[0] if readers else None}
    steps += [{"type": "VerifyBundle", "klass": "scratch", "interruptible": True, "group": "verify", "args": check}]
    steps += verify
    done = {"kind": "verification", "level": "verified", "bundle_from": n}
    done["steps_ok"] = list(range(n + 1, len(steps) + 1))
    steps.append({"type": "Record", "klass": "idempotent", "args": done})


def levels(layout: state.Layout, name: str, bid: str, digest: str) -> dict[str, bool]:
    """Per level, whether the newest verification record bound to `digest` is ok; only complete lines count (a torn
    last line was never written)."""
    path, out = layout.verification(name, bid), {}
    for line in fs.read(path).split(b"\n")[:-1] if fs.exists(path) else ():
        doc = records.loads(line)
        if doc.get("bundle_hash") == digest:
            out[str(doc.get("level"))] = doc.get("ok") is True
    return out
