"""Diagnostics (LIFECYCLE §4.15, F9): status, doctor, list, ps, logs, history, bundles and scheduled status.

They read records first and live Docker data second, and write nothing; `scheduled status` writes only
host/attention.json. Each answer is a Report (contract §21.1) whose `next` is the exact command to run.
"""

import ipaddress
import os
import re
import stat
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from ingat import brand
from ingat.adapters.compose import Compose, Project
from ingat.adapters.docker import PROJECT_LABEL, Docker
from ingat.adapters.runner import Redactor
from ingat.core.executor import CLOSE, orphan_check
from ingat.core.journal import Journal
from ingat.core.steps import selftest_run
from ingat.model import records, words
from ingat.model.errors import CannotRun, IngatError, Refused
from ingat.model.instance import validate_against
from ingat.model.manifest import Manifest
from ingat.ops import context as cx
from ingat.ops.backup import catalogued
from ingat.ops.context import Ctx, Loaded
from ingat.ops.deploy import way_forward
from ingat.ops.host import roots
from ingat.policy.gate import TIER1, TIER2
from ingat.store import fs, state

Report = dict[str, Any]
Found = dict[str, list[tuple[str, str | None]]]  # attention code -> [(detail, next command)]
Flag = Callable[[str, str, str | None], None]
# Attention codes, most important first: an answer's `next` serves the first one present.
CODES = (
    "daemon-unreachable", "engine-mismatch", "invalid-config", "open-operation", "frozen", "last-op-failed",
    "needs-review", "changed-outside", "foreign", "drift", "held", "unverified-bundle", "backup-old",
    "restore-test-old", "uncertified",
)  # fmt: skip
LOG_TAIL = 500
ONEOFF = "com.docker.compose.oneoff"  # set on `compose run` (task) containers
_OP_DIR = re.compile(r"([1-9][0-9]*)-([a-z][a-z0-9-]*)")
_SINCE = re.compile(r"[0-9][0-9A-Za-z:.+-]{0,39}")  # a `docker logs --since` timestamp or duration


def _report(lines: list[str], exit: int = 0, code: str = "ok", next: str | None = None, **data: Any) -> Report:
    return {"exit": exit, "code": code, "next": next, "lines": lines, **data}


def _verdict(found: Found) -> tuple[int, str, str | None]:
    """Exit 5 and the next command of the most important code when any attention code is present."""
    first = next((c for c in CODES if c in found), None)
    return (5, "attention", found[first][0][1]) if first else (0, "ok", None)


def _hours(ctx: Ctx, at: str) -> float:
    return (ctx.now - records.parse_iso(at)).total_seconds() / 3600


def _age(ctx: Ctx, at: str | None) -> str:
    h = _hours(ctx, at) if at else None
    return "never" if h is None else f"{h / 24:.0f}d ago" if h >= 48 else f"{h:.0f}h ago" if h >= 1 else "just now"


def _host(ctx: Ctx) -> tuple[dict[str, Any], Found]:
    """What every instance shares: the daemon (reachable and the bound engine, F1), the gate tier observed with fresh
    build facts (ARCHITECTURE §3.6) and the free space of each root and of the Docker root."""
    try:
        engine = state.read_doc(ctx.layout.host_json, "host").get("engine_id")
    except FileNotFoundError:
        raise CannotRun(words.NOT_INITIALIZED, code="no-host", next=f"{brand.CLI} host init") from None
    paths = (ctx.layout.root, ctx.layout.backups, brand.PROBE_MOUNT)
    out: dict[str, Any] = {"daemon": "reachable", "gate_tier": None, "gate": []}
    out["free_bytes"] = {p: fs.statvfs(p)[1] for p in paths if fs.exists(p)}
    try:
        if ctx.info.get("ID") != engine:
            out["daemon"] = "engine-mismatch"
            return out, {"engine-mismatch": [(f"{words.ENGINE_MISMATCH}; nothing runs until that is resolved", None)]}
        out["gate_tier"], out["gate"], nxt = _tier(ctx)
    except CannotRun as e:
        if e.code != "daemon-unreachable":
            raise
        out["daemon"] = "unreachable"
        return out, {"daemon-unreachable": [(e.message, None)]}
    return out, {} if out["gate_tier"] == TIER2 else {"uncertified": [("; ".join(out["gate"]), nxt)]}


def _tier(ctx: Ctx) -> tuple[int, list[str], str | None]:
    """The highest gate tier this daemon and platform build allow, why it is not 2, and the gate's next command
    (`selftest --host` for a missing certification; none for an untested Engine, which needs a tool release)."""
    why: list[str] = []
    nxt = None
    for tier in (TIER2, TIER1):
        try:
            return tier, list(dict.fromkeys(why + cx.gate(ctx, tier))), nxt
        except CannotRun as e:
            if e.code not in ("uncertified", "untested-platform"):
                raise
            why.append(e.message)
            nxt = nxt or e.next
    return 0, why, nxt


def _secrets(ctx: Ctx, name: str) -> list[str]:
    """The instance's secret values (its secret files and env/ secrets), for redaction only."""
    sd = ctx.layout.secrets_dir(name)
    paths = [os.path.join(sd, f) for f in fs.listdir(sd) if f != "env"]
    paths += [os.path.join(sd, "env", f) for f in fs.listdir(os.path.join(sd, "env"))]
    try:
        return [fs.read(p).decode() for p in paths]
    except UnicodeDecodeError as e:
        raise Refused(f"a secret file of {name} is not UTF-8", code="invalid-value") from e


def _open_op(ctx: Ctx, name: str, seq: int, kind: str) -> tuple[dict[str, Any], bool]:
    """An operation without a result: `paused` at an install pause, else `interrupted`; its last step; and the
    command that goes on from it: `abandon` when the first step without `done` is a write task outside scratch that
    may have run and is not idempotent, which resume never repeats blind (F5, LIFECYCLE §3.4), unless its close was
    decided. Also whether the CLI may run it now: a terminal task (`inputs.foreground`) with a step in flight."""
    d = ctx.layout.op_dir(name, seq, kind)
    plan = os.path.join(d, "plan.json")
    doc = state.read_doc(plan, "plan") if fs.exists(plan) else {}
    steps = {s["n"]: s for s in doc.get("steps", ())}
    rep = Journal(d, seq).replay()
    paused = any(s["type"] == "Pause" and rep.get(n, {}).get("phase") == "intent" for n, s in steps.items())
    todo: dict[str, Any] = next((s for n, s in sorted(steps.items()) if rep.get(n, {}).get("phase") != "done"), {})
    a = todo.get("args") or {}
    blind = todo.get("type") == "RunTask" and todo["klass"] != "scratch" and todo["n"] in rep and CLOSE not in rep
    verb = "abandon" if blind and a.get("effect") != "read" and not a.get("idempotent") else "resume"
    out = {"seq": seq, "kind": kind, "state": "paused" if paused else "interrupted", "last_step": None}
    out["next"] = f"{brand.CLI} {verb} {name}"
    if done := [n for n in rep if n in steps]:
        n = max(done)
        out["last_step"] = {"n": n, "type": steps[n]["type"], "phase": rep[n]["phase"], "at": rep[n]["at"]}
    fg = bool((doc.get("inputs") or {}).get("foreground"))
    return out, fg and any(r["phase"] == "intent" for r in rep.values())


def _ops(ctx: Ctx, name: str, live: bool) -> list[dict[str, Any]]:
    """The open operations; one is `running` while an executor of the instance runs (the host executor runs a selftest
    instance's) or, when the CLI may run it (a terminal task), a task container of it does. A task container that
    outlived its executor, or whose step closed, runs no operation (F15): it refuses every command but its `docker
    stop`, which is then the next one (ARCHITECTURE §4.5). Without the daemon, the records alone."""
    ops = [_open_op(ctx, name, seq, kind) for seq, kind in state.open_ops(ctx.layout, name)]
    if not (live and ops):
        return [op for op, _ in ops]
    role, own = brand.label("role"), brand.label("instance")
    mine = {name, None} if selftest_run(ctx.layout, name) else {name}  # the host executor has no instance label
    try:
        execs = [c for c in ctx.docker.containers({role: "exec"}) if c["Config"]["Labels"].get(own) in mine]
        for op, cli in ops:
            try:
                orphan_check(ctx.docker, name, op["seq"])
                stop = None
            except CannotRun as e:
                if e.code != "task-running":
                    raise
                stop = e.next
            if any(c["State"].get("Running") for c in execs) or (cli and stop):
                op["state"] = "running"
            elif stop:
                op["next"] = stop
    except CannotRun as e:  # `history` on an unreachable daemon
        if e.code != "daemon-unreachable":
            raise
    return [op for op, _ in ops]


def _op_dirs(ctx: Ctx, name: str) -> list[tuple[int, str]]:
    found = (_OP_DIR.fullmatch(e) for e in fs.listdir(ctx.layout.ops_dir(name)))
    return sorted((int(x[1]), x[2]) for x in found if x)


def _stops(ctx: Ctx, name: str) -> dict[str, list[tuple[str, str]]]:
    """Per service, the span of each completed `stop` that stopped it: `stop <i> <service>` leaves the instance running
    (LIFECYCLE §4.11), so a container that last stopped within such a span is stopped as the owner asked."""
    out: dict[str, list[tuple[str, str]]] = {}
    for seq, kind in _op_dirs(ctx, name):
        d = ctx.layout.op_dir(name, seq, kind)
        r = state.read_doc(f"{d}/result.json", "result") if kind == "stop" and fs.exists(f"{d}/result.json") else {}
        for s in state.read_doc(f"{d}/plan.json", "plan")["steps"] if r.get("outcome") == "completed" else ():
            for service in s["args"]["services"] if s["type"] == "Stop" else ():
                out.setdefault(service, []).append((r["started_at"], r["finished_at"]))
    return out


def _asked(c: dict[str, Any], spans: Iterable[tuple[str, str]]) -> bool:
    at = str(c["State"].get("FinishedAt"))[:19]  # Docker's UTC time; the records' times are whole seconds
    return any(a[:19] <= at <= b[:19] for a, b in spans)


def _bundles(ctx: Ctx, name: str) -> list[dict[str, Any]]:
    """Catalogued bundles minus tombstones (as retention reads them), newest first, with what their verification
    records prove for the catalogued hash: the newest record per level wins (F10); a torn last line was never
    written (ARCHITECTURE §7.3)."""
    out = []
    for c in catalogued(ctx.layout, name).values():
        path, latest = ctx.layout.verification(name, c["bundle_id"]), dict[str, dict[str, Any]]()
        for line in filter(None, fs.read(path).split(b"\n")[:-1] if fs.exists(path) else ()):
            v = records.check_schema(records.loads(line), "verification")
            if v.get("bundle_hash") == c["bundle_hash"]:
                latest[v["level"]] = v
        ok = {k: v["at"] for k, v in latest.items() if v.get("ok")}
        row = {"id": c["bundle_id"], "class": c.get("class"), "size": c.get("size"), "created_at": c["created_at"]}
        row |= {"verified_at": max(ok.values(), default=None), "restore_tested_at": ok.get("restore-tested")}
        out.append(row | {"failed": sorted(k for k, v in latest.items() if not v.get("ok"))})
    return sorted(out, key=lambda b: str(b["created_at"]), reverse=True)


def _level(b: dict[str, Any]) -> str:
    if b["failed"]:
        return f"a check failed ({', '.join(b['failed'])})"
    return words.LEVELS["restore-tested" if b["restore_tested_at"] else "verified" if b["verified_at"] else None]


def _ages(ctx: Ctx, ld: Loaded, rows: list[dict[str, Any]], busy: bool, flag: Flag) -> dict[str, Any]:
    """backup-old, restore-test-old and unverified-bundle (LIFECYCLE §5.5); a bundle not yet verified while an
    operation is open may be that operation's own."""
    cli, name, limits = brand.CLI, ld.name, ld.inst.backups
    good = [b for b in rows if b["verified_at"] and not b["failed"]]
    tested = max((b["restore_tested_at"] for b in rows if b["restore_tested_at"] and not b["failed"]), default=None)
    if ld.deployment is not None and ld.manifest is not None and ld.manifest.backup.strategy == "tasks":
        if not good or _hours(ctx, good[0]["created_at"]) > limits.max_age_hours:
            why = f"the newest checked backup copy, {good[0]['id']}, is too old" if good else ""
            why = why or "there is no checked backup copy"
            why += f"; a checked backup copy is expected at least every {limits.max_age_hours} hours"
            flag("backup-old", why, f"{cli} backup {name}")
        if tested is None or _hours(ctx, tested) > 24 * limits.restore_test_max_age_days:
            why = f"the last test restore was {_age(ctx, tested)}; one is expected at least every "
            why += f"{limits.restore_test_max_age_days} days"
            flag("restore-test-old", why, f"{cli} verify {name} --latest --restore-test")
    for b in rows:  # only a newer record of the failed level clears it: a drill for a failed restore-test
        drill = " --restore-test" if "restore-tested" in b["failed"] else ""
        if b["failed"] or not (busy or b["verified_at"]):
            flag("unverified-bundle", f"backup copy {b['id']}: {_level(b)}", f"{cli} verify {name} {b['id']}{drill}")
    out = {"count": len(rows), "newest": rows[0] if rows else None, "newest_verified": good[0] if good else None}
    return out | {"restore_tested": tested}


def _row(c: dict[str, Any]) -> dict[str, Any]:
    labels, st = c["Config"].get("Labels") or {}, c["State"]
    out = {"name": c["Name"].lstrip("/"), "service": labels.get(cx.SERVICE), "state": st.get("Status")}
    out |= {"health": (st.get("Health") or {}).get("Status"), "restarts": c.get("RestartCount", 0), "image": c["Image"]}
    return out | {"project": labels.get(PROJECT_LABEL), "role": labels.get(brand.label("role"))}


def _live(ctx: Ctx, ld: Loaded, check: bool, flag: Flag) -> list[dict[str, Any]]:
    """The project's service containers, and its foreign containers and networks (ARCHITECTURE §7.5); with `check`,
    the recorded deployment against them: a missing, other-image container, one whose running state differs from the
    record or a missing network is changed-outside (§11.2), a config hash other than the deployment's own files give
    is drift."""
    name, dep, m, restart = ld.name, ld.deployment or {}, ld.manifest, f"{brand.CLI} restart {ld.name}"
    rows, by, own = [], dict[str, list[dict[str, Any]]](), brand.label("instance")
    for c in ctx.docker.containers(project=name):
        labels = c["Config"].get("Labels") or {}
        if labels.get(own) != name:
            flag("foreign", f"container {c['Name'].lstrip('/')} {words.foreign(name)}", f"{brand.CLI} ps {name}")
        elif labels.get(ONEOFF) != "True":
            by.setdefault(labels.get(cx.SERVICE, ""), []).append(c)
            rows.append(_row(c))
    for x in ctx.docker.networks({PROJECT_LABEL: name}):  # the override labels every network of the project
        if (x.get("Labels") or {}).get(own) != name:
            flag("foreign", f"Docker network {x['Name']} {words.foreign(name)}", None)
    services = [s for g in m.activate for s in g.services] if check and m else []
    running = ld.record.get("state") == "running"
    down = running and any(not c["State"].get("Running") for s in services for c in by.get(s, ()))
    asked = _stops(ctx, name) if down else {}
    for s in services:
        if not by.get(s):
            flag("changed-outside", f"service {s} has no container", restart)
        elif any(bool(c["State"].get("Running")) != running and not _asked(c, asked.get(s, ())) for c in by[s]):
            why = (
                "is not running, although the app should be running"
                if running
                else "is running, although the app was stopped"
            )
            flag("changed-outside", f"service {s} {why}", restart if running else f"{brand.CLI} stop {name}")
        for c in by.get(s, ()):
            if c["Image"] != dep["images"].get(s):
                why = f"service {s} is running a different image ({c['Image']}) than the one deployed "
                why += f"({dep['images'].get(s)}); restart the app to put the deployed one back"
                flag("changed-outside", why, restart)
    if not services or m is None:
        return rows
    snap = ctx.layout.deployment_snapshot(name, dep["seq"])
    p = Project(name, dep["export"], m.files, f"{snap}/override.yaml", f"{snap}/compose.env")
    compose = Compose(ctx.layout.docker_config, Redactor(_secrets(ctx, name)))
    try:  # read-only: the deployment's own files and its content-addressed env file
        hashes, model = compose.config_hashes(p, services), compose.config(p)
    except IngatError as e:
        why = f"the saved settings of the current deployment could not be read back: {e.message}"
        flag("changed-outside", why, f"{brand.CLI} doctor {name}")
        return rows
    for s in services:
        if any((c["Config"].get("Labels") or {}).get(cx.CONFIG_HASH) != hashes.get(s) for c in by.get(s, ())):
            why = f"service {s} is running with settings that differ from deployment {dep['seq']}; restart the app "
            flag("drift", why + "to put the deployed settings back", restart)
    nets = {k for s in services for k in (model["services"].get(s, {}).get("networks") or {})}
    names = {x["name"] for k, x in (model.get("networks") or {}).items() if k in nets and x.get("name")}
    for n in sorted(names - {x["Name"] for x in ctx.docker.inspect("network", sorted(names))}):
        flag("changed-outside", f"Docker network {n} is missing; restart the app to recreate it", restart)
    return rows


def _instance(ctx: Ctx, ld: Loaded, host: dict[str, Any], shared: Found) -> tuple[dict[str, Any], Found]:
    """One instance: its records first (state, deployment, open operations, holds, bundles), then live data."""
    name, rec, dep, m, cli = ld.name, ld.record, ld.deployment, ld.manifest, brand.CLI
    found: Found = {k: list(v) for k, v in shared.items()}

    def flag(code: str, detail: str, nxt: str | None) -> None:
        found.setdefault(code, []).append((detail, nxt))

    live = host["daemon"] == "reachable"
    ops = _ops(ctx, name, live)
    for op in ops:  # a running one is at work: `attach` follows it
        if op["state"] != "running":
            how = "is paused and waiting for you" if op["state"] == "paused" else "was interrupted before it finished"
            flag("open-operation", f"operation {op['seq']} ({op['kind']}) {how}", op["next"])
    st, last = rec.get("state"), rec.get("last_op") or {}
    if st == "frozen":  # without a way forward: `history` tells why; the way back, a restore, arrives in M2
        why = f"{words.FROZEN} until the way forward is taken"
        flag("frozen", why, way_forward(ctx.layout, name) or f"{cli} history {name}")
    if last.get("outcome") in ("failed-unchanged", "failed-frozen", "needs-review"):
        code = "needs-review" if last["outcome"] == "needs-review" else "last-op-failed"
        why = f"operation {last['seq']} ({last['kind']}) {words.ENDED[last['outcome']]} ({last['outcome']})"
        flag(code, why, _result_next(ctx, name, last))
    if rec.get("held_since"):
        clear = m.side_effects.clear_hold if m else None
        why = f"on hold since {rec['held_since']}: after its restore the app is holding its outgoing side effects "
        why += "(for example sending mail) until the hold is cleared"
        flag("held", why, f"{cli} task {name} {clear}" if clear else None)
    bundles = _ages(ctx, ld, _bundles(ctx, name), bool(ops), flag)
    check = dep is not None and not ops and st in ("running", "stopped")
    for store, n in (rec.get("generations") or {}).items() if check else ():
        if not fs.exists(ctx.layout.data_gen(name, store, f"g{n}")):
            why = f"the data copy g{n} of store {store} is missing from disk; it was removed outside {brand.PRODUCT}"
            flag("changed-outside", why, f"{cli} bundles {name}")
    data = {k: rec.get(k) for k in ("name", "app", "environment", "state", "held_since", "generations", "last_op")}
    keys = ("seq", "release", "commit", "origin", "created_at", "schema", "writes_reopened_at")
    data |= {"deployment": dep and {k: dep.get(k) for k in keys}, "operations": ops, "bundles": bundles}
    data["services"] = _live(ctx, ld, check, flag) if live else None
    return data, found


def _result_next(ctx: Ctx, name: str, last: dict[str, Any]) -> str:
    """The next command the closed operation's result printed; `history` (why it ended) when that is `status`."""
    path = os.path.join(ctx.layout.op_dir(name, last["seq"], last["kind"]), "result.json")
    nxt = state.read_doc(path, "result").get("next") if fs.exists(path) else None
    return str(nxt) if nxt and nxt != f"{brand.CLI} status {name}" else f"{brand.CLI} history {name}"


def _lines(ctx: Ctx, data: dict[str, Any], host: dict[str, Any], found: Found) -> list[str]:
    dep, b = data["deployment"], data["bundles"]
    out = [f"{data['name']}: {data['state']}" + (f", deployment {dep['seq']} ({dep['release']})" if dep else "")]
    for o in data["operations"]:
        s = o["last_step"]
        out.append(f"operation {o['seq']} ({o['kind']}): {o['state']}" + (f", step {s['n']} {s['type']}" if s else ""))
    newest, good = b["newest"], b["newest_verified"] or {}
    text = f"backup copies: {b['count']}" + (f", newest {newest['id']} ({_level(newest)})" if newest else "")
    text += f", newest checked copy made {_age(ctx, good.get('created_at'))}"
    out.append(f"{text}, last test restore {_age(ctx, b['restore_tested'])}")
    for r in data["services"] or ():
        out.append(f"service {r['service']}: {r['state']}, health {r['health'] or '-'}, {r['restarts']} restarts")
    if data["services"] is None:
        why = f"live information was not read from Docker ({host['daemon']}: {words.UNCHECKED[host['daemon']]})"
        out.append(f"{why}, so only the saved records are shown")
    return out + [f"needs your attention ({c}): {d}" for c in CODES for d, _ in found.get(c, ())]


def _host_lines(host: dict[str, Any]) -> list[str]:
    free = ", ".join(f"{p} {v / cx.GIB:.1f} GiB" for p, v in host["free_bytes"].items())
    tier = f"what may run on this computer: gate tier {host['gate_tier']} ({words.TIERS.get(host['gate_tier'], '')})"
    return [tier + "".join(f"; {g}" for g in host["gate"]), f"free: {free}"]


def status(ctx: Ctx, name: str | None) -> Report:
    """One instance, or every instance in short; exit 5 when any attention code is present (LIFECYCLE §4.15)."""
    host, shared = _host(ctx)
    if name is not None:
        data, found = _instance(ctx, cx.load(ctx, name), host, shared)
        attention = {k: [d for d, _ in v] for k, v in found.items()}
        lines = _lines(ctx, data, host, found) + _host_lines(host)
        return _report(lines, *_verdict(found), instance=data, host=host, attention=attention)
    rows, lines, merged = [], [], dict(shared)
    for n, data, found in _each(ctx, host, shared):
        for k, v in found.items():
            merged.setdefault(k, []).extend(x for x in v if x not in merged[k])
        release = data["deployment"] and data["deployment"]["release"]
        rows.append({"name": n, "state": data["state"], "release": release, "attention": sorted(found)})
        lines.append(", ".join([f"{n}: {data['state'] or 'unknown'}", *([release] if release else []), *sorted(found)]))
    return _report((lines or ["no instances"]) + _host_lines(host), *_verdict(merged), instances=rows, host=host)


def _each(ctx: Ctx, host: dict[str, Any], shared: Found) -> Iterator[tuple[str, dict[str, Any], Found]]:
    """Every instance with its data and codes. One whose config or records do not load is `invalid-config` (its own
    `status` names the errors) and the others go on."""
    for n in state.list_instances(ctx.layout):
        try:
            ld = cx.load(ctx, n)
        except (Refused, CannotRun, OSError) as e:
            why: Found = {"invalid-config": [(str(e), f"{brand.CLI} status {n}")]}
            yield n, {"state": None, "deployment": None}, shared | why
            continue
        yield n, *_instance(ctx, ld, host, shared)


def doctor(ctx: Ctx, name: str) -> Report:
    """status plus the instance against its deployed manifest, the policy over the recorded deployment's model, the
    gate, secret files, port and subnet collisions, the roots, the tool's DOCKER_CONFIG, the crash hook and what the
    app supports (LIFECYCLE §4.15). Exit 5 when status needs attention or a check failed."""
    rep, ld = status(ctx, name), cx.load(ctx, name)
    host, m, cfg, crash = rep["host"], ld.manifest, ctx.layout.docker_config, brand.env("CRASH_AT")
    live, unchecked = host["daemon"] == "reachable", [f"not checked: {words.UNCHECKED.get(host['daemon'])}"]
    checks: dict[str, list[str]] = {}
    if m is not None and ld.deployment is not None:
        checks["instance"] = validate_against(ld.inst, m)
        checks["policy"] = _policy(ctx, ld) if live else unchecked
    checks["gate"] = [] if host["gate_tier"] == TIER2 else host["gate"] or unchecked
    checks["secrets"] = _secret_files(ctx, ld)
    checks["collisions"] = _collisions(ctx, ld) if live else unchecked
    checks["roots"] = roots(ctx.layout)
    checks["docker-config"] = [] if fs.exists(cfg) and not fs.listdir(cfg) else [cx.docker_config_rule(cfg)]
    hook = f"the environment variable {crash} is set: it exists only for tests and makes operations crash on purpose; "
    checks["crash-hook"] = [hook + "unset it before running anything"] if crash in os.environ else []
    notes = _capabilities(m)
    lines = rep["lines"] + [f"{k}: {'; '.join(v) if v else 'ok'}" for k, v in checks.items()] + notes
    exit, code = (5, rep["code"] if rep["exit"] else "findings") if rep["exit"] or any(checks.values()) else (0, "ok")
    return rep | {"exit": exit, "code": code, "lines": lines, "checks": checks, "notes": notes}


def _policy(ctx: Ctx, ld: Loaded) -> list[str]:
    """The model and policy rules over the recorded deployment, replayed from its own override and params."""
    try:
        cx.current(ctx, ld)
    except Refused as e:
        return e.message.splitlines()
    return []


def _secret_files(ctx: Ctx, ld: Loaded) -> list[str]:
    """Each secret file regular, non-empty and of its mode (the manifest's; 0600 for app-env secrets), missing only
    when optional; the secrets directory 0700."""
    sd, m = ctx.layout.secrets_dir(ld.name), ld.manifest
    want: dict[str, tuple[int, bool]] = {k: (s.mode, True) for k, s in m.secrets.items()} if m else {}
    keys = m.app_env.keys if m and m.app_env else {}
    want |= {f"env/{k}": (0o600, x.required) for k, x in keys.items() if x.secret}
    have = [f for f in fs.listdir(sd) if f != "env"] + [f"env/{f}" for f in fs.listdir(os.path.join(sd, "env"))]
    bad = fs.exists(sd) and stat.S_IMODE(os.lstat(sd).st_mode) != 0o700
    out = [f"the secrets folder {sd} must be readable by its owner only (permissions 0700)"] if bad else []
    for rel in sorted({*want, *have}):
        mode, required = want.get(rel, (None, False))
        try:
            st = os.lstat(os.path.join(sd, rel))
        except FileNotFoundError:
            out += [f"{rel}: missing"] if required else []
            continue
        if not stat.S_ISREG(st.st_mode) or not st.st_size:
            out.append(f"{rel}: must be a plain file with something in it (not empty, not a folder or link)")
        elif mode is None:  # before the first deploy no manifest says which files belong, nor their modes
            out += [f"{rel}: the deployed app uses no secret of this name (stray file)"] if m else []
        elif stat.S_IMODE(st.st_mode) != mode:
            found = stat.S_IMODE(st.st_mode)
            out.append(f"{rel}: the file permissions are {found:04o} but must be {mode:04o}; fix them with chmod")
    return out


def _collisions(ctx: Ctx, ld: Loaded) -> list[str]:
    """The instance's live ports and subnets that another instance's allocation, another container's published port
    or another network's address pool also holds (LIFECYCLE §4.1)."""
    name, own, entries = ld.name, brand.label("instance"), cx.allocations(ctx)
    kinds = {k: p.kind for k, p in ld.manifest.params.items() if p.kind in ("port", "subnet")} if ld.manifest else {}
    mine = {(kinds[k], v) for k, v in ((ld.deployment or {}).get("params") or {}).items() if k in kinds}
    mine |= {key for key, e in entries.items() if e.get("instance") == name and e.get("purpose") == "live"}
    other = {key: e.get("instance") for key, e in entries.items() if key in mine and e.get("instance") != name}
    out = [f"{k} {v} is also reserved for the instance {i}" for (k, v), i in other.items()]
    ports = {v for k, v in mine if k == "port"}
    for c in ctx.docker.containers():
        if (c["Config"].get("Labels") or {}).get(own) != name:
            bound = (c["HostConfig"].get("PortBindings") or {}).values()
            published = {b.get("HostPort") for bs in bound for b in bs or ()}
            taken = f"is also assigned to another container, {c['Name'].lstrip('/')}"
            out += [f"port {p} {taken}" for p in sorted(ports & published)]
    subnets = [ipaddress.ip_network(v, strict=False) for k, v in mine if k == "subnet"]
    for n in ctx.docker.networks() if subnets else ():
        if (n.get("Labels") or {}).get(own) != name:
            pools = [x["Subnet"] for x in (n.get("IPAM") or {}).get("Config") or () if x.get("Subnet")]
            nets = [ipaddress.ip_network(p, strict=False) for p in pools]
            hits = {str(s) for s in subnets for x in nets if s.version == x.version and s.overlaps(x)}
            out += [f"subnet {s} overlaps network {n['Name']}" for s in sorted(hits)]
    return out


def _capabilities(m: Manifest | None) -> list[str]:
    if m is None:
        return ["what this app supports (backup, restore): known after its first deploy"]
    if m.backup.strategy == "none":
        return ["backup, check, test restore and restore: not needed, this app keeps no data ([backup] strategy none)"]
    online = all(s.online_backup for s in m.stores.values())
    how = "while the app keeps running" if online else f"with {words.WRITERS} stopped for the whole backup"
    return [f"backup: {how}", "restore: not available in this release yet"]


def list_(ctx: Ctx) -> Report:
    """Every instance from its records alone: app, environment, state, deployment and open operation."""
    rows, lines = [], []
    for n in state.list_instances(ctx.layout):
        rec = state.read_doc(ctx.layout.record_json(n), "instance")
        seq, op = rec.get("current_deployment"), rec.get("open_op")
        release = state.read_doc(ctx.layout.deployment_json(n, seq), "deployment").get("release") if seq else None
        row = {k: rec.get(k) for k in ("name", "app", "environment", "state", "held_since", "open_op")}
        rows.append(row | {"deployment": seq, "release": release})
        text = f"{n}: {row['app']} {row['environment']}, {row['state']}" + (f", {release}" if release else "")
        lines.append(text + (f", operation {op['seq']} ({op['kind']}) open" if op else ""))
    return _report(lines or ["no instances"], instances=rows)


def ps(ctx: Ctx, name: str) -> Report:
    """Every container of the instance (services, tasks, isolated runs) and every foreign one in its project."""
    cx.load(ctx, name)
    own = brand.label("instance")
    found = {c["Id"]: c for c in [*ctx.docker.containers({own: name}), *ctx.docker.containers(project=name)]}
    rows = [_row(c) | {"owned": (c["Config"].get("Labels") or {}).get(own) == name} for c in found.values()]
    rows.sort(key=lambda r: str(r["name"]))
    lines = [f"{r['name']}: {r['service'] or '-'} {r['state']}" + ("" if r["owned"] else " FOREIGN") for r in rows]
    return _report(lines or ["no containers"], containers=rows)


def logs(ctx: Ctx, name: str, service: str, since: str | None = None) -> Report:
    """The last LOG_TAIL lines of the service's containers, redacted with the instance's secret values."""
    cx.load(ctx, name)
    if since is not None and not _SINCE.fullmatch(since):
        why = f"--since {since!r} is not a time (for example 2026-10-16T08:00:00) or a duration (for example 30m or 2h)"
        raise CannotRun(why, code="usage")
    labels = {brand.label("instance"): name, cx.SERVICE: service}
    found = [c for c in ctx.docker.containers(labels, project=name) if c["Config"]["Labels"].get(ONEOFF) != "True"]
    if not found:
        why = f"{name} has no container for a service named {service!r}; check the service name"
        raise Refused(why, code="no-container", next=f"{brand.CLI} ps {name}")
    docker = Docker(config_dir=ctx.layout.docker_config, redactor=Redactor(_secrets(ctx, name)))
    out, lines = [], []
    for c in sorted(found, key=lambda c: str(c["Name"])):
        res, cname = docker.logs(c["Id"], since=since, tail=LOG_TAIL), c["Name"].lstrip("/")
        out.append({"container": cname, "stdout": res.out, "stderr": res.err, "truncated": res.truncated})
        lines += [f"{cname} | {x}" for x in res.out.splitlines()] + [f"{cname} ! {x}" for x in res.err.splitlines()]
    return _report(lines, logs=out)


def history(ctx: Ctx, name: str) -> Report:
    """Every operation with its outcome from result.json; one without a result is open: running, paused or
    interrupted, as status tells."""
    cx.load(ctx, name)
    rows, lines, opened = [], [], {o["seq"]: o["state"] for o in _ops(ctx, name, True)}
    for seq, kind in _op_dirs(ctx, name):
        path = os.path.join(ctx.layout.op_dir(name, seq, kind), "result.json")
        if not fs.exists(path):
            rows.append({"seq": seq, "kind": kind, "outcome": "open", "state": opened.get(seq)})
            lines.append(f"{seq} {kind}: open ({rows[-1]['state']})")
            continue
        r = state.read_doc(path, "result")
        keys = ("outcome", "exit", "code", "message", "next", "started_at", "finished_at", "warnings")
        rows.append({"seq": seq, "kind": kind} | {k: r.get(k) for k in keys})
        lines.append(f"{seq} {kind}: {r.get('outcome')} at {r.get('finished_at')}: {r.get('message')}")
    return _report(lines or ["no operations"], operations=rows)


def bundles(ctx: Ctx, name: str) -> Report:
    """Catalogued bundles minus tombstones, newest first, with their verification level and age."""
    cx.load(ctx, name)
    rows = _bundles(ctx, name)
    lines = []
    for b in rows:
        size = f"{b['size'] / (1 << 20):.1f} MiB" if b["size"] is not None else "size unknown"
        lines.append(f"{b['id']}: {b['class']} backup copy, {size}, made {_age(ctx, b['created_at'])}, {_level(b)}")
    return _report(lines or ["no bundles"], bundles=rows)


def scheduled_status(ctx: Ctx) -> Report:
    """Every instance's attention codes against host/attention.json, the only file it writes: exit 5 with the new
    and cleared codes when the set changed since the last run, else exit 0 and no output (LIFECYCLE §4.15)."""
    host, shared = _host(ctx)
    found = {n: sorted(codes) for n, _, codes in _each(ctx, host, shared)}
    now = {n: codes for n, codes in found.items() if codes}
    path = ctx.layout.attention_json
    old: dict[str, list[str]] = state.read_doc(path, "attention").get("codes") or {} if fs.exists(path) else {}
    if now == old:
        return _report([], code="unchanged", codes=now)
    new = [(n, c) for n, codes in now.items() for c in codes if c not in old.get(n, ())]
    gone = [(n, c) for n, codes in old.items() for c in codes if c not in now.get(n, ())]
    lines = [f"now needs attention: {n}: {c}" for n, c in new] + [
        f"no longer needs attention: {n}: {c}" for n, c in gone
    ]
    state.replace_doc(path, records.new_doc("attention", codes=now, at=records.iso(ctx.now)))
    return _report(lines, 5, "changed", f"{brand.CLI} status" if now else None, codes=now)
