"""`prepare` and `deploy` planners (LIFECYCLE §4.2-§4.5): first install, data-changing update, config-only change.

Plans are concrete data (contract §20.1): every variant, probe and task the executor runs is rendered here.
"""

import os
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ingat import brand
from ingat.adapters.compose import Compose
from ingat.adapters.docker import PROJECT_LABEL
from ingat.adapters.runner import Redactor
from ingat.core.journal import Journal
from ingat.core.plan import Plan, fingerprint, new_plan
from ingat.model import records, templates
from ingat.model.errors import Refused
from ingat.model.manifest import Manifest
from ingat.ops import context as cx
from ingat.ops import steps_build as sb
from ingat.ops.context import Ctx, Loaded, Source
from ingat.policy.gate import TIER2
from ingat.store import fs, state

STOP_TIMEOUT = 600
ONEOFF = "com.docker.compose.oneoff"
FROZEN = ("failed-frozen", "abandoned")  # the outcomes that may leave an instance frozen past the forward point
Step = dict[str, Any]


def _step(type_: str, klass: str, **args: Any) -> Step:
    return {"type": type_, "klass": klass, "args": args}


def _up(m: Manifest, variant: str, services: Iterable[str], wait: Iterable[str] = (), **kw: Any) -> Step:
    """An Up step; `reopens` marks the activation that reopens writes. A wait for the probe of a probe-based [schema]
    records the schema it reports (MANIFEST_SPEC §2.5)."""
    reopens, check, wait = kw.pop("reopens", False), kw.pop("check", False), list(wait)
    sc = m.schema if m.schema and m.schema.probe in wait else None
    args = {"variant": variant, "services": list(services), "wait": wait, "identity": check, "smoke": check}
    args |= {"reopens_writes": reopens, "schema_probe": sc.probe if sc else None}
    args["schema_paths"] = [sc.expected, sc.actual] if sc else None
    return {"type": "Up", "klass": kw.pop("klass"), "interruptible": True, "args": args}


def _activate(m: Manifest, steps: list[Step], forward: bool) -> None:
    """The activation groups on the candidate; the group that reopens writes and every later one are forward."""
    for g in m.activate:
        forward |= g.reopens_writes
        klass = "forward" if forward else "reversible"
        steps.append(_up(m, "candidate", g.services, g.wait, klass=klass, reopens=g.reopens_writes))


def _env(ctx: Ctx, ld: Loaded, src: Source, overrides: dict[str, str] | None = None) -> tuple[Any, bytes, Any]:
    """(app env spec, its full content, live Compose env) of the candidate."""
    spec, content = cx.app_env(ctx, ld, src.manifest)
    env = cx.live_env(ctx, ld, src.manifest, src.release, src.commit, spec["path"] if spec else "", overrides)
    return spec, content, env


def _refs(ctx: Ctx, ld: Loaded, src: Source, env: dict[str, str]) -> dict[str, str]:
    """The image reference of every service of the candidate (all profiles): pulled, never built (ADR-0026)."""
    app = cx.config(ctx, ld.name, src.export, src.manifest.files, env)
    refs = {s: x.get("image") or "" for s, x in app["services"].items()}
    if missing := sorted(s for s, r in refs.items() if not r):
        raise Refused(f"service(s) {', '.join(missing)} name no image; images are pulled, never built", code="no-image")
    if unknown := sorted(set(src.manifest.build_services) - set(refs)):  # its expect_labels would go unchecked
        raise Refused(f"compose.build_services: unknown {', '.join(unknown)}", code="invalid-manifest")
    return refs


def _candidate(ctx: Ctx, ld: Loaded, src: Source, refs: dict[str, str]) -> dict[str, Any] | None:
    """The candidate recorded for this commit and the image references rendered now (None when there is none)."""
    path = ctx.layout.candidates(ld.name, src.commit, refs)
    return state.read_doc(path, "candidate") if fs.exists(path) else None


def _present(ctx: Ctx, cand: dict[str, Any]) -> bool:
    ids = sorted(set(cand["images"].values()))
    return len(ctx.docker.inspect("image", ids)) == len(ids)


def _containers(ctx: Ctx, name: str) -> list[tuple[str, str, bool]]:
    """(service, config hash, running) of every service container of the instance; one-off tasks left out."""
    out = []
    for c in ctx.docker.containers(labels={brand.label("instance"): name}, project=name):
        labels = c["Config"].get("Labels") or {}
        if labels.get(ONEOFF) != "True":
            out.append((labels.get(cx.SERVICE, ""), labels.get(cx.CONFIG_HASH, ""), bool(c["State"].get("Running"))))
    return out


def foreign(ctx: Ctx, name: str) -> None:
    """Compose stops, recreates or removes what its project holds, so an object of the project that is not the
    instance's own refuses every plan that runs Compose on the live project (F8; ARCHITECTURE §7.5)."""
    d, own, label = ctx.docker, brand.label("instance"), {PROJECT_LABEL: name}
    found = [(f"container {c['Name'].lstrip('/')}", c["Config"].get("Labels")) for c in d.containers(project=name)]
    found += [(f"network {x['Name']}", x.get("Labels")) for x in d.networks(label)]
    found += [(f"volume {x['Name']}", x.get("Labels")) for x in d.volumes(label)]
    if foreign := [what for what, labels in found if (labels or {}).get(own) != name]:
        raise Refused(f"project {name} holds objects that are not its own: {', '.join(foreign)}", code="foreign")


def _secrets(ctx: Ctx, ld: Loaded, m: Manifest, models: Iterable[Mapping[str, Any]]) -> list[str]:
    """The secret files of both releases, for redaction (ARCHITECTURE §9.4). Each Compose secret file the models bind
    must be a regular, non-empty file now: a start that misses one would fail past the forward point."""
    bound = sorted({x["file"] for mo in models for x in (mo.get("secrets") or {}).values() if "file" in x})
    if bad := [p for p in bound if not fs.exists(p) or not fs.read(p)]:
        raise Refused(f"secret file(s) {', '.join(bad)} missing or empty", code="missing-secret")
    sdir, both = ctx.layout.secrets_dir(ld.name), (m, ld.manifest) if ld.manifest else (m,)
    keys = [k for x in both if x.app_env for k, key in x.app_env.keys.items() if key.secret]
    paths = [os.path.join(sdir, k) for x in both for k in x.secrets] + [os.path.join(sdir, "env", k) for k in keys]
    return sorted(p for p in set(paths) if fs.exists(p))


def data_changing(m: Manifest, cm: Manifest, old: Mapping[str, str], new: Mapping[str, str]) -> bool:
    """LIFECYCLE §4.4: the image of a writer (of either release) changes, or any image of an app that migrates at
    start."""
    changed = {s for s, i in new.items() if old.get(s) != i}
    starts = bool(m.schema and m.schema.migrates_on_start)
    return bool(changed & {*m.services.writers, *cm.services.writers}) or bool(changed and starts)


def _gens(ld: Loaded, m: Manifest) -> dict[str, int]:
    """The generation of every store once deployed: the recorded one, g1 for a new store."""
    return {k: 1 for k in m.stores} | (ld.record.get("generations") or {})


def _gen_paths(ctx: Ctx, ld: Loaded, m: Manifest) -> dict[str, str]:
    """store -> live generation directory, for `generation:<store>` mounts of live tasks."""
    return {k: ctx.layout.data_gen(ld.name, k, f"g{n}") for k, n in _gens(ld, m).items()}


def _plan(ctx: Ctx, kind: str, approval: str, ref: str, ld: Loaded, inputs: dict[str, Any], steps: list[Step]) -> Plan:
    for s in steps:  # the first forward step is the operation's forward point (LIFECYCLE §3.2)
        if s["klass"] == "forward":
            s["forward_point"] = True
            break
    command = [brand.CLI, kind, ld.name, ref]
    return new_plan(kind, ld.name, approval, command, fingerprint(ctx.layout, ctx.docker, ld.name), inputs, steps)


def _start(ctx: Ctx, name: str, ref: str) -> tuple[Loaded, Source, list[str]]:
    """The loaded instance, the source at `ref` and the gate's warnings for the plan."""
    cx.require_host(ctx)
    warnings = cx.gate(ctx, TIER2, name)
    ld = cx.load(ctx, name)
    src = cx.source(ctx, ld, ref)
    cx.supported(src.manifest)
    return ld, src, warnings


def plan_prepare(ctx: Ctx, name: str, ref: str) -> Plan | None:
    """Pull and pin the images of `ref` (class B, LIFECYCLE §4.2); None when its candidate is already prepared."""
    ld, src, warnings = _start(ctx, name, ref)
    m = src.manifest
    cx.capacity(ctx, {brand.PROBE_MOUNT: cx.GIB})  # pulls: a 2 GiB floor on the Docker root
    env = _env(ctx, ld, src)[2]
    refs = _refs(ctx, ld, src, env)
    if (cand := _candidate(ctx, ld, src, refs)) is not None and _present(ctx, cand):
        return None
    if cand is not None:  # recorded (write-once), but its images are gone: pull the recorded digests again
        digests = cand.get("digests") or {}
        if lost := sorted(s for s in refs if not digests.get(s)):
            msg = f"the images of the candidate of {src.commit} are gone; {', '.join(lost)} has no digest to pull again"
            raise Refused(msg, code="stale-candidate")
        refs = {s: digests[s] for s in refs}
    tv = cx.values(ctx, ld, src.release, src.commit) | {f"param.{k}": v for k, v in env.items()}
    labels = {k: templates.render(v, tv) for k, v in m.expect_labels.items()}  # binds {commit} for build_services
    by_ref: dict[str, list[str]] = {}
    for svc, r in sorted(refs.items()):
        by_ref.setdefault(r, []).append(svc)
    built = set(m.build_services)
    images = [{"ref": r, "services": s, "check_labels": labels if built & set(s) else {}} for r, s in by_ref.items()]
    seq = state.next_seq(ctx.layout, name)
    made = {"commit": src.commit, "release": src.release, "export": src.export, "manifest_sha256": m.raw_sha256}
    steps = [{"type": "Obtain", "klass": "scratch", "interruptible": True, "args": {"images": images, **made}}]
    if cand is None:
        steps.append(_step("Record", "idempotent", kind="candidate", obtain_step=1, **made))
    inputs = {"seq": seq, "op_dir": ctx.layout.op_dir(name, seq, "prepare"), **made, "warnings": warnings}
    return _plan(ctx, "prepare", "B", ref, ld, inputs, steps)


def plan_deploy(ctx: Ctx, name: str, ref: str) -> Plan | None:
    """First install, data-changing update, config-only change (class C, LIFECYCLE §4.3-§4.5) or the way forward of
    an update that froze the instance (§3.6); None when nothing would change. A deploy that ends frozen names this
    same command as its next one."""
    ld, src, warnings = _start(ctx, name, ref)
    m, dep, seq = src.manifest, ld.deployment, state.next_seq(ctx.layout, name)
    cx.exclusive(ctx, ld, m)
    foreign(ctx, name)
    spec, content, env = _env(ctx, ld, src)
    if (cand := _candidate(ctx, ld, src, _refs(ctx, ld, src, env))) is None or not _present(ctx, cand):
        raise Refused(
            f"no prepared candidate for {src.commit}", code="no-candidate", next=f"{brand.CLI} prepare {name} {ref}"
        )
    found = _containers(ctx, name)
    if gone := sorted({s for s, _, _ in found} - set(cand["images"])):  # the identity check would fail on them
        msg = f"{src.commit} has no service {', '.join(gone)}, which has containers here; removing a service"
        raise Refused(msg + " is not in this release", code="removed-service")
    kw: dict[str, Any] = {"export": src.export, "release": src.release, "commit": src.commit, "images": cand["images"]}
    cv, cmodel = cx.variant(ctx, ld, m, env=env, env_secrets=_env_secrets(spec), **kw)
    variants, steps, needs, models = {"candidate": cv}, list[Step](), dict[str, int](), [cmodel]
    fwd: dict[str, Any] | None = None
    if dep is None or ld.manifest is None:
        _install(ctx, ld, src, cv, cmodel, variants, steps)
        needs[brand.PROBE_MOUNT] = cx.GIB  # a 2 GiB floor on the Docker root
    elif ld.record.get("state") == "frozen":
        _owner_gated(ld, m, ld.manifest, content)
        fwd = _forward(ctx, ld, src, cand)
        cv["values"] |= fwd["values"]  # {freeze_at} and {bundle.*} of the capture, for the migrate
        check = {"bundle": fwd["bundle"], "input_owner": None}  # verified again before the forward point (F6)
        steps.append({"type": "VerifyBundle", "klass": "scratch", "interruptible": True, "args": check})
        if _change(ctx, ld, src, cv, cmodel, steps):  # the migrate reads the bundle's input copy
            needs[ctx.layout.root] = fwd["size"]
    else:
        cm = ld.manifest
        _owner_gated(ld, m, cm, content)
        _schema_gate(ctx, ld, src.commit)
        variants["current"], curmodel = cx.current(ctx, ld)
        models.append(curmodel)
        writes = data_changing(m, cm, dep["images"], cand["images"])
        if writes and cm.stores and cm.backup.strategy == "none":
            raise Refused(
                "a writer's image changes; [backup] strategy none cannot preserve the data", code="cannot-preserve"
            )
        if writes and cm.backup.strategy == "tasks":
            needs |= _update(ctx, ld, src, cm, variants, (curmodel, cmodel), steps)
        elif not _config_only(ctx, ld, src, cv, spec, content, found, steps):
            return None
    steps.append(_check(m, steps))
    steps.append(_record(ctx, ld, src, seq, cv, cand, spec, steps, fwd and fwd["bundle"]))
    cx.capacity(ctx, needs)
    for v in variants.values():
        v["values"] |= {"op.seq": str(seq), "reason": "", "target.release": src.release}
    redact = _secrets(ctx, ld, m, models)
    inputs = {
        "seq": seq,
        "op_dir": ctx.layout.op_dir(name, seq, "deploy"),
        "commit": src.commit,
        "release": src.release,
    }
    inputs |= {
        "export": src.export,
        "manifest_sha256": m.raw_sha256,
        "variants": variants,
        "app_env": spec,
        "files": {},
    }
    inputs |= {"throwaway_secrets": {}, "redact_files": sorted(redact), "writers": list(m.services.writers)}
    inputs |= {"data": list(m.services.data), "activation": [list(g.services) for g in m.activate]}
    inputs |= {"warnings": warnings, "forward": fwd, "next": dict.fromkeys(FROZEN, f"{brand.CLI} deploy {name} {ref}")}
    return _plan(ctx, "deploy", "C", ref, ld, inputs, steps)


def _install(ctx: Ctx, ld: Loaded, src: Source, cv: Any, cmodel: Any, variants: Any, steps: list[Step]) -> None:
    """New generations, then the manifest's [[install]] steps, else its activation groups (LIFECYCLE §4.3). The g1
    an unfinished install created (it ended frozen past its forward point) is kept and used again, never re-created."""
    m, have = src.manifest, ld.record.get("generations") or {}
    gens = _gen_paths(ctx, ld, m)
    for k, s in m.stores.items():
        path, mode = ctx.layout.data_gen(ld.name, k, "g1"), 0o700 if s.mode is None else s.mode
        if k not in have and not fs.exists(f"{path}.json"):
            gen = {"store": k, "gen": "g1", "path": path, "owner": list(s.owner) if s.owner else None, "mode": mode}
            steps.append(_step("CreateGeneration", "scratch", purpose="live", **gen))
    if not m.install:
        _activate(m, steps, forward=False)
        return
    reopen = {s for g in m.activate if g.reopens_writes for s in g.services}
    forward = opened = False
    for n, st in enumerate(m.install):
        if st.kind == "task":
            t = m.tasks[st.task or ""]
            forward |= t.effect != "read"
            klass = "forward" if t.effect != "read" else "scratch"
            steps.append(sb.task_step(ctx, m, cv, cmodel, t, variant="candidate", klass=klass, gen_paths=gens))
        elif st.kind == "start":
            name = "candidate"
            if st.params:  # its own variant: the step's string params override the instance's
                name, env = f"install-{n}", _env(ctx, ld, src, st.params)[2]
                at = {"export": src.export, "release": src.release, "commit": src.commit, "images": cv["images"]}
                variants[name] = cx.variant(ctx, ld, m, env=env, env_secrets=cv["secret_files"], **at)[0]
            opens = not opened and bool(reopen & set(st.services))
            opened, forward = opened or opens, forward or opens
            steps.append(
                _up(m, name, st.services, st.wait, klass="forward" if forward else "reversible", reopens=opens)
            )
        else:
            text = templates.render(st.text or "", cv["values"])
            steps.append(_step("Pause", "operator", text=text, allow_tasks=list(st.allow_tasks)))


def _update(
    ctx: Ctx, ld: Loaded, src: Source, cm: Manifest, variants: Any, models: Any, steps: list[Step]
) -> dict[str, int]:
    """Freeze, pre-change bundle with the current release, verify, then migrate and activate (LIFECYCLE §4.4, F6).
    Returns the space it needs (LIFECYCLE §5.8): the stage and the published copy, plus the input copy a task reads."""
    if cm.services.writers:
        stop = {"variant": "current", "services": list(cm.services.writers), "freeze": True, "timeout": STOP_TIMEOUT}
        steps.append(_step("Stop", "reversible", **stop))
    sb.capture_steps(ctx, ld, variants["current"], models[0], steps, "current", "pre-change", "writers-stopped")
    _change(ctx, ld, src, variants["candidate"], models[1], steps)
    size, copy = cx.payload_size(ctx, ld), any(s["type"] == "VerifyBundle" and s["args"]["input_owner"] for s in steps)
    return {ctx.layout.root: size * (1 + copy), ctx.layout.backups: size}


def _change(ctx: Ctx, ld: Loaded, src: Source, cv: Any, cmodel: Any, steps: list[Step]) -> bool:
    """Migrate (the forward point) and the activation groups, all forward: the first start of a candidate writer may
    already change the data. True when the migrate reads the input copy of the last VerifyBundle's bundle."""
    m, reads = src.manifest, False
    if m.deploy.migrate:
        t = m.tasks[m.deploy.migrate]
        room = {ctx.layout.root: cx.GIB}  # re-checked right before the forward point
        gens = _gen_paths(ctx, ld, m)
        migrate = sb.task_step(ctx, m, cv, cmodel, t, "candidate", "forward", capacity=room, gen_paths=gens)
        if reads := ["bundle"] in [x[1:] for x in migrate["args"]["mounts"]]:
            check = next(s for s in steps[::-1] if s["type"] == "VerifyBundle")["args"]
            if check["input_owner"] not in (None, uid := migrate["args"]["task_uid"]):
                raise Refused(f"tasks.{t.name}: a verify task of another user owns the bundle copy", code="task-user")
            check["input_owner"] = uid
        steps.append(migrate)
    _activate(m, steps, forward=True)
    return reads


def _forward(ctx: Ctx, ld: Loaded, src: Source, cand: dict[str, Any]) -> dict[str, Any]:
    """`frozen -> deploy (forward)` (LIFECYCLE §3.6): the newest deploy, of this same candidate over the current
    deployment, froze the instance past its forward point after its pre-change bundle was sealed and recorded
    `verified`; or it was such a way forward itself, frozen again or failed with nothing changed. Operations that
    keep the data (verify, drill, prune, read tasks) may have run since. Returns that bundle (id, hash, size)
    and the runtime values of its capture; any other frozen instance needs the restore of a pre-change bundle (M2)."""
    name, layout = ld.name, ctx.layout
    old, found = _frozen_by(layout, name) or (None, None)
    if old is not None:
        doc = next(s.args["doc"] for s in old.steps if s.type == "Record" and s.args["kind"] == "deployment")
        was = (old.inputs.get("commit"), old.inputs["variants"]["candidate"]["images"], doc["rollback_target"])
        found = found if was == (src.commit, cand["images"], (ld.deployment or {}).get("seq")) else None
    if (t := src.manifest.deploy.migrate) and not src.manifest.tasks[t].idempotent:  # its last run may have ended
        found = None  # unknown: never repeated blind (F5)
    pruned = found and fs.exists(layout.catalog(name, f"{found['bundle']}.pruned"))  # its tombstone (LIFECYCLE §5.6)
    if found and not pruned and fs.exists(path := layout.catalog(name, found["bundle"])):
        entry, ok = state.read_doc(path, "catalog"), sb.levels(layout, name, found["bundle"], found["hash"])
        if entry["bundle_hash"] == found["hash"] and ok.get("verified"):
            return found | {"size": int(entry["size"])}
    why = "only the candidate whose update froze it moves forward (its migrate task idempotent), on the pre-change"
    msg = f"{name} is frozen: {why} bundle that update sealed and verified; otherwise the way back is the restore of"
    msg += " a pre-change bundle (M2)"
    raise Refused(msg, code="frozen", next=f"{brand.CLI} status {name}")


def _frozen_by(layout: state.Layout, name: str) -> tuple[Plan, dict[str, Any] | None] | None:
    """The plan of the newest deploy when it may have left the instance frozen (it ended failed-frozen or abandoned,
    or it was a way forward that changed nothing), with the pre-change bundle it sealed and recorded `verified` or
    carried forward (id, hash, runtime values; None without one)."""
    seqs = [int(f[:-7]) for f in fs.listdir(layout.ops_dir(name)) if f.endswith("-deploy") and f[:-7].isdigit()]
    d = layout.op_dir(name, max(seqs), "deploy") if seqs else ""
    if not d or not fs.exists(result := os.path.join(d, "result.json")):
        return None
    outcome = state.read_doc(result, "result")["outcome"]
    old = Plan.from_doc(state.read_doc(os.path.join(d, "plan.json"), "plan"))
    tried = old.inputs.get("forward")  # a way forward that changed nothing left the instance as it was
    if outcome not in FROZEN and not (tried and outcome == "failed-unchanged"):
        return None
    return old, tried or _sealed(old, Journal(d, max(seqs)).replay())


def way_forward(layout: state.Layout, name: str) -> str | None:
    """The next command of the update that froze the instance (its result prints it, LIFECYCLE §3.2): None when
    `_forward` cannot take it (no sealed and verified pre-change bundle, or a migrate that is not idempotent)."""
    old, found = _frozen_by(layout, name) or (None, None)
    if old is None or found is None or not sb.levels(layout, name, found["bundle"], found["hash"]).get("verified"):
        return None
    if any(s.type == "RunTask" and s.forward_point and not s.args.get("idempotent") for s in old.steps):
        return None
    nxt: str | None = (old.inputs.get("next") or {}).get("failed-frozen")
    return nxt


def pinned(layout: state.Layout, name: str, record: Mapping[str, Any]) -> set[str]:
    """The pre-change bundle of the update that froze the instance: its way forward and its restore (M2) need it, so
    retention keeps it while the instance is frozen."""
    _, found = (_frozen_by(layout, name) if record.get("state") == "frozen" else None) or (None, None)
    return {found["bundle"]} if found else set()


def _sealed(old: Plan, rep: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    """The pre-change bundle the update plan `old` sealed and recorded `verified`, with its runtime values."""
    done = {s.n: rep[s.n]["done_evidence"] or {} for s in old.steps if rep.get(s.n, {}).get("phase") == "done"}
    seal = next((s.n for s in old.steps if s.type == "CaptureBundle" and s.args["phase"] == "seal"), 0)
    if seal not in done or not any(s.n in done for s in old.steps if s.args.get("kind") == "verification"):
        return None
    values = {k: x for n in sorted(done) for k, x in (done[n].get("values") or {}).items()}
    values = {k: x for k, x in values.items() if k == "freeze_at" or k.startswith("bundle.")}
    return {"bundle": done[seal]["bundle_id"], "hash": done[seal]["bundle_hash"], "values": values}


def _env_secrets(spec: Any) -> list[str]:
    """The secret files the live app env file `spec` is rendered from."""
    return [x["secret_file"] for _, x in (spec or {}).get("lines", ()) if "secret_file" in x]


def _config_only(
    ctx: Ctx, ld: Loaded, src: Source, cv: dict[str, Any], spec: Any, content: bytes, found: Any, steps: list[Step]
) -> bool:
    """Up exactly the services that are not one running container with the planned Compose config hash (`found`,
    LIFECYCLE §4.5); False when no service changes and the commit is the deployed one."""
    m, dep = src.manifest, ld.deployment or {}
    services = [s for g in m.activate for s in g.services]
    files = [k for k, p in m.params.items() if p.kind == "env_file"]
    secrets = [fs.read(x["secret_file"]).decode() for _, x in (spec or {}).get("lines", ()) if "secret_file" in x]
    with cx.project(
        ld.name, src.export, m.files, cv["env"], cv["override"], profiles=(), app_env=(files, content)
    ) as p:
        hashes = Compose(ctx.layout.docker_config, Redactor(secrets)).config_hashes(p, services)
    changed = {s for s in services if {(h, up) for x, h, up in found if x == s} != {(hashes.get(s), True)}}
    if not changed and dep.get("commit") == src.commit:
        return False
    for g in m.activate:
        if up := [s for s in g.services if s in changed]:
            steps.append(_up(m, "candidate", up, g.wait, klass="reversible"))
    return True


def _check(m: Manifest, steps: list[Step]) -> Step:
    """Identity and smoke of the whole project. It also reads a probe-based [schema] when no earlier Up does, so
    every deployment records the schema it runs on: the schema gate and the next pre-change bundle need it."""
    read = any(s["type"] == "Up" and s["args"]["schema_probe"] for s in steps)
    wait = [m.schema.probe] if m.schema and m.schema.probe and not read else []
    return _up(m, "candidate", (), wait, klass="scratch", check=True)


def _record(
    ctx: Ctx, ld: Loaded, src: Source, seq: int, cv: Any, cand: dict[str, Any], spec: Any, steps: list[Step], prior: Any
) -> Step:
    """Record the deployment; later steps' evidence fills `from` (contract §20.8). `prior`: the pre-change bundle an
    earlier deploy of this candidate sealed (the way forward from frozen), else None."""
    m, dep = src.manifest, ld.deployment

    def find(pred: Callable[[Step], bool]) -> int | None:
        return next((n for n, s in enumerate(steps, 1) if pred(s)), None)

    reopened = find(lambda s: s["type"] == "Up" and s["args"]["reopens_writes"])
    schema = find(lambda s: s["type"] == "Up" and s["args"]["schema_probe"])
    bundle = find(lambda s: s["type"] == "CaptureBundle" and s["args"]["phase"] == "seal")
    folder = ctx.layout.deployments_dir(ld.name)
    number = 1 + max((int(f[:-5]) for f in fs.listdir(folder) if f[:-5].isdigit() and f.endswith(".json")), default=0)
    gens = _gens(ld, m)
    keep = dep if dep and reopened is None else {}  # a config-only change keeps the write window (and the schema)
    doc = {"seq": number, "instance": ld.name, "op": seq, "release": src.release, "commit": src.commit}
    doc["origin"] = "install" if dep is None else "update" if bundle or prior else "config"
    doc |= {"export": src.export, "images": cand["images"], "refs": cand["refs"], "digests": cand.get("digests") or {}}
    doc |= {"manifest_sha256": m.raw_sha256, "model_sha256": cv["model_sha256"], "params": cv["env"]}
    doc["compose_sha256"] = {f: records.sha256_hex(fs.read(os.path.join(src.export, f))) for f in m.files}
    doc |= {"app_env_sha256": spec and spec["sha256"], "env_file": spec and spec["path"], "generations": gens}
    doc |= {"schema": None if schema else keep.get("schema"), "writes_reopened_at": keep.get("writes_reopened_at")}
    doc |= {"pre_change_bundle": prior, "rollback_target": dep["seq"] if dep else None}
    sources = {"writes_reopened_at": reopened, "schema": schema, "pre_change_bundle": bundle, "config_hashes": None}
    manifest_path = os.path.join(src.export, ld.inst.manifest_path)
    args = {"doc": doc, "state": "running", "variant": "candidate", "manifest_path": manifest_path, "from": sources}
    return _step("Record", "idempotent", kind="deployment", generations=gens, **args)


def _owner_gated(ld: Loaded, m: Manifest, cm: Manifest, content: bytes) -> None:
    """A changed owner-gated app-env value makes the deploy class D, which arrives in M2 (LIFECYCLE §4.5)."""
    keys = {k for x in (m, cm) if x.app_env for k, key in x.app_env.keys.items() if key.owner_gated}
    old_file = (ld.deployment or {}).get("env_file")
    old = cx.env_values(fs.read(old_file)) if keys and old_file else {}
    new = cx.env_values(content)
    if changed := sorted(k for k in keys if old.get(k) != new.get(k)):
        raise Refused(
            f"owner-gated app_env {', '.join(changed)} would change (class D, M2)", code="not-in-this-release"
        )


def older(a: object, b: object) -> bool:
    """Schema order: numeric when both are integers, else text order."""
    x, y = str(a), str(b)
    return int(x) < int(y) if x.isdigit() and y.isdigit() else x < y


def _schema_gate(ctx: Ctx, ld: Loaded, commit: str) -> None:
    """A commit deployed here before whose expected schema is older than the current actual schema cannot run on
    this data: the way back is the restore of its paired pre-change bundle (LIFECYCLE §4.4, §4.6)."""
    actual = ((ld.deployment or {}).get("schema") or {}).get("actual")
    folder = ctx.layout.deployments_dir(ld.name)
    docs = [state.read_doc(os.path.join(folder, f), "deployment") for f in fs.listdir(folder) if f.endswith(".json")]
    target = max((d for d in docs if d.get("commit") == commit), key=lambda d: int(d["seq"]), default=None)
    expected = ((target or {}).get("schema") or {}).get("expected")
    if target is None or actual is None or expected is None or not older(expected, actual):
        return
    pairs = [d.get("pre_change_bundle") for d in docs if d.get("rollback_target") == target["seq"]]
    bundle = next((b for b in pairs if b), None)
    restore = f"{brand.CLI} restore {ld.name} --bundle {bundle} --reason <text>" if bundle else None
    msg = f"code-only rollback impossible: {target['release']} expects schema {expected}, the data is at {actual}"
    raise Refused(msg, code="schema-gate", next=restore)
