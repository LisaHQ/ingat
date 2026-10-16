"""`backup`, `verify`, the drill (`verify --restore-test`) and `prune --bundles` planners (LIFECYCLE §4.7-§4.9, §4.13,
§5.3-§5.8). Every plan is class B; backup, verify and drill hold only scratch and reversible steps plus, for retention,
deletions, which never freeze, so an interrupted one is auto-abandoned by the next command (LIFECYCLE §3.3, §3.4)."""

import os
from typing import Any

from ingat import __version__, brand
from ingat.core.journal import Journal
from ingat.core.plan import Plan, fingerprint, new_plan
from ingat.model import records, templates
from ingat.model.bundle import CLASSES, ID_RE, bundle_hash, parse_sums
from ingat.model.errors import CannotRun, Refused
from ingat.model.manifest import Manifest, parse_manifest
from ingat.ops import context as cx
from ingat.ops import steps_build as sb
from ingat.ops.context import Ctx, Loaded
from ingat.ops.deploy import STOP_TIMEOUT, Step, _step, _up, foreign, pinned, way_forward
from ingat.ops.steps_build import levels as levels
from ingat.policy import retention
from ingat.policy.gate import TIER1, TIER2
from ingat.store import fs, state

MEMINFO = "/proc/meminfo"
SUBNET = "@subnet"  # an isolated run's subnet: the executor allocates a pool /24 at op open (contract §20.1)
KINDS = ("catalog", "tombstone")
KEEP = ".keep"  # makes a drill's empty secrets directory, which an app may bind, when it has no secret to hold
Report = dict[str, Any]


def plan_backup(ctx: Ctx, name: str, klass: str, reason: str | None, prune: bool, *, scheduled: bool = False) -> Plan:
    """A bundle of the recorded deployment, sealed and verified. Writers stop unless every store backs up online and
    the class allows it; retention follows when `prune` or `scheduled` (LIFECYCLE §4.7)."""
    klass = "scheduled" if scheduled else klass
    if klass not in CLASSES or set(reason or "") & set("\0\n\r"):
        raise CannotRun(f"the class must be one of {', '.join(CLASSES)}; --reason one line", code="usage")
    ld = _load(ctx, name)
    m, _ = _deployed(ld)
    if ld.record.get("state") == "frozen":  # the recorded release's tasks would capture, and restart, other data
        msg = f"{name} is frozen: its data may be past the forward point of the update that froze it"
        raise Refused(msg, code="frozen", next=way_forward(ctx.layout, name) or f"{brand.CLI} status {name}")
    running = ld.record.get("state") == "running"
    online = klass in ("scheduled", "manual") and all(s.online_backup for s in m.stores.values())
    warnings = cx.gate(ctx, TIER1 if online else TIER2, name)
    seq, layout = state.next_seq(ctx.layout, name), ctx.layout
    v, model = _current(ctx, ld, seq, reason or (f"scheduled {klass} backup" if scheduled else ""))
    _naming(ctx, name, m, v["values"], klass)
    writers = list(m.services.writers) if running and not online else []
    if writers:  # Compose stops and starts every container of a writer service in the project (F8)
        foreign(ctx, name)
    stop = {"variant": "current", "services": writers, "freeze": True, "timeout": STOP_TIMEOUT}
    steps = [_step("Stop", "reversible", **stop)] if writers else []
    how = "online-app" if online and running else "writers-stopped"
    sb.capture_steps(ctx, ld, v, model, steps, "current", klass, how)
    for g in m.activate:  # writers start again in activation order, each group waiting for its probes
        if up := [s for s in g.services if s in writers]:
            steps.append(_up(m, "current", up, g.wait, klass="reversible"))
    cat: dict[str, Any] = {}
    if prune or scheduled:  # `prune --bundles`, gate tier 2 (ARCHITECTURE §3.6), even after an online backup
        try:
            cx.gate(ctx, TIER2)
        except CannotRun as e:  # the nightly backup goes on and keeps every bundle until the build is certified
            if not scheduled:
                raise
            warnings.append(f"retention skipped: {e.message}")
        else:  # over the bundles catalogued now; the new one is the newest, kept by the next run
            _, delete, cat = _retention(ctx, ld)
            steps += _deletes(cat, delete)
    size = cx.payload_size(ctx, ld)
    cx.capacity(ctx, {layout.root: size, layout.backups: size})
    inputs = _inputs(ctx, name, seq, "backup", {"current": v}, _redact(ctx, name, m), warnings=warnings)
    command = [brand.CLI, "scheduled", "backup", name] if scheduled else [brand.CLI, "backup", name, "--class", klass]
    command += [*(["--reason", reason] if reason else []), *(["--prune"] if prune else [])]
    return _plan(ctx, "backup", name, command, inputs, steps, sorted(cat))


def plan_verify(
    ctx: Ctx, name: str, bundle: str | None, latest: bool, restore_test: bool, *, scheduled: bool = False
) -> Plan:
    """Re-hash a sealed bundle against its catalog entry and run the verify tasks (LIFECYCLE §4.8), or drill it."""
    if latest == (bundle is not None):
        raise CannotRun("name one bundle or --latest", code="usage")
    ld = _load(ctx, name)
    bid, entry = _pick(ctx, ld, bundle)
    command = [brand.CLI, *(["scheduled"] if scheduled else []), "verify", name, bid]
    if restore_test:
        return _drill(ctx, ld, bid, entry, [*command, "--restore-test"])
    m, _ = _deployed(ld)
    warnings = cx.gate(ctx, TIER1 if all(s.online_backup for s in m.stores.values()) else TIER2, name)
    seq, variants, steps = state.next_seq(ctx.layout, name), dict[str, Any](), list[Step]()
    v, model = _current(ctx, ld, seq) if m.backup.verify else (None, None)  # hash only: no Compose project
    variants |= {"current": v} if v else {}
    sb.verify_steps(ctx, m, v, model, steps, "current", bid)
    copy = steps[0]["args"]["input_owner"] is not None
    cx.capacity(ctx, {ctx.layout.root: int(entry["size"]) if copy else 0})
    inputs = _inputs(ctx, name, seq, "verify", variants, _redact(ctx, name, m), warnings=warnings, bundle=bid)
    return _plan(ctx, "verify", name, command, inputs, steps, [bid])


def plan_prune(ctx: Ctx, name: str, apply: bool = False) -> Plan | Report | None:
    """Retention over the catalogued bundles (LIFECYCLE §5.6): a dry run reports keep and delete; `apply` plans the
    deletions (None: nothing to delete)."""
    cx.require_host(ctx)
    ld = cx.load(ctx, name)
    keep, delete, cat = _retention(ctx, ld)
    if not apply:
        order = sorted(cat, key=lambda b: (cat[b]["created_at"], b), reverse=True)
        lines = [f"{'delete' if b in delete else 'keep'} {b} {cat[b]['class']} {cat[b]['created_at']}" for b in order]
        report = {"exit": 0, "code": "dry-run", "lines": lines or ["no bundles"], "keep": keep, "delete": delete}
        return report | {"next": f"{brand.CLI} prune {name} --bundles --apply" if delete else None}
    if not delete:
        return None
    warnings = cx.gate(ctx, TIER2)
    seq = state.next_seq(ctx.layout, name)
    command = [brand.CLI, "prune", name, "--bundles", "--apply"]
    inputs = _inputs(ctx, name, seq, "prune", {}, [], warnings=warnings)
    return _plan(ctx, "prune", name, command, inputs, _deletes(cat, delete), sorted(cat))


def _drill(ctx: Ctx, ld: Loaded, bid: str, entry: dict[str, Any], command: list[str]) -> Plan:
    """Restore the bundle into t<seq> generations of an isolated project in the bundle's own release, run its checks,
    record `restore-tested`, tear down; the live project is never touched (LIFECYCLE §4.9, §5.7; F13)."""
    name, layout = ld.name, ctx.layout
    warnings = cx.gate(ctx, TIER2, name)
    made = _bundle_json(ctx, name, bid, entry)["deployment"]
    if made.get("seq") is None:  # an imported adoption payload (M4)
        raise Refused(f"bundle {bid} records no deployment of this instance", code="not-in-this-release")
    dep = state.read_doc(layout.deployment_json(name, made["seq"]), "deployment")
    snap = os.path.join(layout.deployment_snapshot(name, dep["seq"]), brand.MANIFEST_FILE)
    m = parse_manifest(fs.read(snap), tool_version=__version__)
    ids = sorted(set(dep["images"].values()))
    if len(ctx.docker.inspect("image", ids)) != len(ids):  # `prepare` rebuilds removed images from M3
        raise Refused(f"images of release {dep['release']} are no longer present", code="missing-image")
    if m.drill.min_free_memory > (free := _memory() if m.drill.min_free_memory else 0):
        raise Refused(f"{free} bytes of memory available; the drill needs {m.drill.min_free_memory}", code="memory")
    _exported(name, dep)
    cx.capacity(ctx, {layout.root: 3 * int(entry["size"])})  # the input copy plus twice the restored store
    seq = state.next_seq(layout, name)
    op_dir = layout.op_dir(name, seq, "drill")
    gens = {k: layout.data_gen(name, k, f"t{seq}") for k in m.stores}
    env_file, secrets = os.path.join(op_dir, "env", "isolated.env"), os.path.join(op_dir, "secrets")
    keep = ("template", "subnet", *cx.PATH_KINDS)  # paths are this run's own: never a live generation or secret
    given = {k: x for k, x in dep["params"].items() if k in m.params and m.params[k].kind not in keep}
    given |= {k: SUBNET for k, p in m.params.items() if p.kind == "subnet"}
    given |= {k: secrets for k, p in m.params.items() if p.kind == "secrets_dir"}
    given |= {k: gens[p.store] for k, p in m.params.items() if p.kind == "store" and p.store}
    env = cx.params(m, layout, name, given, cx.values(ctx, ld, dep["release"], dep["commit"]), {}, env_file)
    at = {"export": dep["export"], "release": dep["release"], "commit": dep["commit"], "images": dep["images"]}
    v, model = cx.variant(ctx, ld, m, env=env, isolated=seq, name=f"{name}--t{seq}", **at)
    v["values"] |= {"op.seq": str(seq), "reason": "", "target.release": dep["release"]}

    def tasks(names: tuple[str, ...], **kw: Any) -> list[Step]:
        return [sb.task_step(ctx, m, v, model, m.tasks[x], "drill", "scratch", gen_paths=gens, **kw) for x in names]

    restore, checks = tasks(m.restore.steps, group="restore"), tasks((*m.restore.post, *m.restore.checks))
    checks += tasks(m.drill.checks)
    found = tasks(m.drill.record, findings_ok=True)  # recorded; findings allowed
    every = restore + checks + found
    reads = {tuple(t["args"]["task_uid"]) for t in every if any(x == "bundle" for _, x in t["args"]["mounts"])}
    if len(reads) > 1:  # one private input copy, owned by one user (ARCHITECTURE §7.2)
        raise Refused("tasks of different users read the bundle copy", code="task-user")
    check: dict[str, Any] = {"bundle": bid, "input_owner": list(reads.pop()) if reads else None}
    steps: list[Step] = [{"type": "VerifyBundle", "klass": "scratch", "interruptible": True, "args": check}]
    for k, s in m.stores.items():
        gen: dict[str, Any] = {"store": k, "gen": f"t{seq}", "path": gens[k], "owner": s.owner and list(s.owner)}
        gen |= {"mode": 0o700 if s.mode is None else s.mode, "purpose": "drill"}
        steps.append(_step("CreateGeneration", "scratch", **gen) | {"group": "restore"})
    if m.restore.start:  # data services on the new generations, ready only when their stores' probes pass (F16)
        ready = [s.ready for s in m.stores.values() if s.ready and s.service in m.restore.start]
        steps.append(_up(m, "drill", m.restore.start, ready, klass="scratch") | {"group": "restore"})
    steps += every
    groups = m.activate if m.drill.activate else ()
    steps += [_up(m, "drill", g.services, g.wait, klass="scratch", check=g is groups[-1]) for g in groups]
    ok = [n for n, s in enumerate(steps, 1) if s["type"] in ("RunTask", "Up") and not s["args"].get("findings_ok")]
    steps.append(_step("Record", "idempotent", kind="verification", level="restore-tested", bundle_from=1, steps_ok=ok))
    steps.append({"type": "Teardown", "klass": "scratch", "always": True, "args": {"variant": "drill"}})
    spec, content = cx.app_env(ctx, ld, m, isolated=True)  # no secret, no owner-gated key: plain text in the plan
    files = {env_file: content.decode()} if spec else {}
    if not m.secrets and any(p.kind == "secrets_dir" for p in m.params.values()):  # throwaway ones make it otherwise
        files[os.path.join(secrets, KEEP)] = ""
    at |= {"files": files, "manifest_sha256": m.raw_sha256, "bundle": bid, "warnings": warnings}
    at["throwaway_secrets"] = {os.path.join(secrets, k): s.mode for k, s in m.secrets.items()}
    inputs = _inputs(ctx, name, seq, "drill", {"drill": v}, [], **at)
    return _plan(ctx, "drill", name, command, inputs, steps, [bid])


def _load(ctx: Ctx, name: str) -> Loaded:
    cx.require_host(ctx)
    ld = cx.load(ctx, name)
    if ld.manifest and ld.manifest.backup.strategy == "none":
        raise Refused(f"{name} keeps no data ([backup] strategy none)", code="not-applicable")
    return ld


def _deployed(ld: Loaded) -> tuple[Manifest, dict[str, Any]]:
    if ld.manifest is None or ld.deployment is None:
        raise Refused(f"{ld.name} has no deployment", code="wrong-state")
    return ld.manifest, ld.deployment


def _exported(name: str, dep: dict[str, Any]) -> None:
    if not fs.exists(dep["export"]):
        nxt = f"{brand.CLI} prepare {name} {dep['release']}"  # exports that commit again
        raise Refused(f"the project directory of {dep['release']} is missing", code="missing-export", next=nxt)


def _current(ctx: Ctx, ld: Loaded, seq: int, reason: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """The recorded deployment's variant with this operation's template values."""
    dep = _deployed(ld)[1]
    _exported(ld.name, dep)
    v, model = cx.current(ctx, ld)
    v["values"] |= {"op.seq": str(seq), "reason": reason, "target.release": dep["release"]}
    return v, model


def _naming(ctx: Ctx, name: str, m: Manifest, values: dict[str, str], klass: str) -> None:
    """The bundle id and payload must render now to an unused id (LIFECYCLE §5.4); the executor renders them again."""
    values = values | {"bundle.stamp": records.stamp(ctx.now), "class": klass}
    bid = templates.render(m.backup.naming[klass], values)
    if not ID_RE.fullmatch(bid):
        raise Refused(f"backup.naming.{klass} renders {bid!r}, which is not a bundle id", code="bundle-id")
    if m.backup.payload:
        templates.render(m.backup.payload, values | {"bundle.id": bid})
    if fs.exists(ctx.layout.catalog(name, bid)):
        raise Refused(f"bundle id {bid} is already used", code="bundle-exists")


def _pick(ctx: Ctx, ld: Loaded, bundle: str | None) -> tuple[str, dict[str, Any]]:
    """The named bundle, else the newest catalogued one."""
    cat, name = catalogued(ctx.layout, ld.name), ld.name
    if bundle is None and not cat:
        raise Refused(f"{name} has no bundle", code="no-bundle", next=f"{brand.CLI} backup {name}")
    bid = max(cat, key=lambda b: (cat[b]["created_at"], b)) if bundle is None else bundle
    if bid not in cat:
        raise Refused(f"{name} has no catalogued bundle {bid!r}", code="no-bundle", next=f"{brand.CLI} bundles {name}")
    return bid, cat[bid]


def _bundle_json(ctx: Ctx, name: str, bid: str, entry: dict[str, Any]) -> Any:
    """bundle.json, read only after SHA256SUMS matched the catalog and listed it (LIFECYCLE §5.3)."""
    d = ctx.layout.bundle_dir(name, bid)
    try:
        sums, data = fs.read(os.path.join(d, "SHA256SUMS")), fs.read(os.path.join(d, "bundle.json"))
    except FileNotFoundError:
        raise Refused(f"bundle {bid} is missing from {ctx.layout.backups}", code="bundle-missing") from None
    if bundle_hash(sums) != entry["bundle_hash"] or parse_sums(sums).get("bundle.json") != records.sha256_hex(data):
        raise Refused(f"bundle {bid} does not match its catalog entry", code="bundle-hash")
    return records.loads(data)


def _memory() -> int:
    """MemAvailable of the host kernel (LIFECYCLE §4.9)."""
    for line in fs.read(MEMINFO).decode().splitlines():
        key, _, rest = line.partition(":")
        if key == "MemAvailable":
            return int(rest.split()[0]) * 1024
    raise Refused(f"{MEMINFO} reports no MemAvailable", code="memory")


def _redact(ctx: Ctx, name: str, m: Manifest) -> list[str]:
    """Secret files whose values the live project's tasks can see (F12)."""
    keys = [f"env/{k}" for k, x in (m.app_env.keys.items() if m.app_env else ()) if x.secret]
    paths = [os.path.join(ctx.layout.secrets_dir(name), k) for k in [*keys, *m.secrets]]
    return sorted(p for p in paths if fs.exists(p))


def _inputs(ctx: Ctx, name: str, seq: int, kind: str, variants: Any, redact: list[str], **kw: Any) -> dict[str, Any]:
    base = {"seq": seq, "op_dir": ctx.layout.op_dir(name, seq, kind), "variants": variants, "app_env": None}
    return base | {"files": {}, "throwaway_secrets": {}, "redact_files": redact} | kw


def _plan(
    ctx: Ctx, kind: str, name: str, command: list[str], inputs: Any, steps: list[Step], bundles: list[str]
) -> Plan:
    """Class B, bound to the hashes of `bundles` (F3). `scheduled` needs no check here: the manifest refuses terminal
    tasks in every list these plans run, and the CLI refuses class C and D for `scheduled` (LIFECYCLE §7)."""
    return new_plan(kind, name, "B", command, fingerprint(ctx.layout, ctx.docker, name, bundles), inputs, steps)


def _deletes(cat: dict[str, Any], ids: list[str]) -> list[Step]:
    """Closed deletion items, re-proved by the step right before removal (F8). Forward, as a deletion cannot be undone
    (LIFECYCLE §3.3); the executor never freezes on one, so retention never stops writers (§3.4)."""
    return [_step("Delete", "forward", item={"kind": "bundle", "id": b, "hash": cat[b]["bundle_hash"]}) for b in ids]


def _retention(ctx: Ctx, ld: Loaded) -> tuple[list[str], list[str], dict[str, Any]]:
    cat, pins = catalogued(ctx.layout, ld.name), pinned(ctx.layout, ld.name, ld.record)
    infos = bundle_infos(ctx.layout, ld.name, ld.record, cat, referenced(ctx.layout, ld.name) | pins)
    b = ld.inst.backups
    keep, delete = retention.select(
        infos, ctx.now, keep_daily=b.keep_daily, keep_weekly=b.keep_weekly, keep_monthly=b.keep_monthly,
        pin_pre_change_days=b.pin_pre_change_days,
    )  # fmt: skip
    return keep, delete, cat


def catalogued(layout: state.Layout, name: str) -> dict[str, Any]:
    """Catalog entries of the bundles that were not pruned (no tombstone), by id."""
    folder = layout.catalog_dir(name)
    raw = [records.loads(fs.read(os.path.join(folder, f))) for f in fs.listdir(folder) if f.endswith(".json")]
    docs = [records.check_schema(d, d["kind"]) for d in raw if isinstance(d, dict) and d.get("kind") in KINDS]
    gone = {d["bundle_id"] for d in docs if d["kind"] == "tombstone"}
    return {d["bundle_id"]: d for d in docs if d["kind"] == "catalog" and d["bundle_id"] not in gone}


def referenced(layout: state.Layout, name: str) -> set[str]:
    """Bundles an open operation names in its plan or has produced (LIFECYCLE §5.6: always kept)."""
    out: set[Any] = set()
    for seq, kind in state.open_ops(layout, name):
        d = layout.op_dir(name, seq, kind)
        if fs.exists(path := os.path.join(d, "plan.json")):
            plan = state.read_doc(path, "plan")
            out |= set(plan["fingerprint"].get("bundles") or ())
            out |= {s["args"].get("bundle") for s in plan["steps"] if s["type"] == "VerifyBundle"}
        out |= {(r.get("done_evidence") or {}).get("bundle_id") for r in Journal(d, seq).replay().values()}
    return {b for b in out if isinstance(b, str)}


def bundle_infos(
    layout: state.Layout, name: str, record: dict[str, Any], cat: dict[str, Any], pinned: set[str]
) -> list[retention.BundleInfo]:
    """Retention input: pinned are `pinned` plus the pre-change bundles of the current and previous deployment."""
    pins: set[Any] = set(pinned)
    for seq in (record.get("current_deployment"), record.get("previous_deployment")):
        if seq is not None:
            pins.add(state.read_doc(layout.deployment_json(name, seq), "deployment").get("pre_change_bundle"))
    out = []
    for bid, c in sorted(cat.items()):
        lv, when = levels(layout, name, bid, c["bundle_hash"]), records.parse_iso(c["created_at"])
        out.append(
            retention.BundleInfo(
                bid, when, c["class"], lv.get("verified", False), lv.get("restore-tested", False), bid in pins
            )
        )
    return out
