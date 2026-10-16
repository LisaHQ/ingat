"""`host init` and `host check` (LIFECYCLE §4.1, ARCHITECTURE §3.4, §10.4, §11.2): the facts of this host and its
daemon, recorded in host.json and in host-check certifications. Both run in the CLI and change no Docker object."""

import os
import re
import stat
from typing import Any

from ingat import __version__, brand
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.ops import context as cx
from ingat.ops.context import Ctx
from ingat.policy import gate
from ingat.store import fs, state
from ingat.store.locks import Lock

ISOLATION_POOL = "10.250.0.0/20"  # carved into /24s for isolated runs (ARCHITECTURE §7.4, ADR-0030)
RUNC_FIXED = (1, 1, 12)  # CVE-2024-21626
CONTAINERD_STORE = ["driver-type", "io.containerd.snapshotter.v1"]


def roots(layout: state.Layout) -> list[str]:
    """Failed checks of both roots (ARCHITECTURE §7.2): INGAT_ROOT is a root:root 0700 directory, INGAT_BACKUPS a
    root-owned directory that no other account can write (mode bits; ACLs are the certification's checklist)."""
    out = []
    for path, strict in ((layout.root, True), (layout.backups, False)):
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            out.append(f"{path} does not exist")
            continue
        mode = stat.S_IMODE(st.st_mode)
        ok = (st.st_gid, mode) == (0, 0o700) if strict else not mode & 0o022
        if not (stat.S_ISDIR(st.st_mode) and st.st_uid == 0 and ok):
            want = "a root:root 0700 directory" if strict else "a root-owned directory no other account can write"
            out.append(f"{path} must be {want} (found {st.st_uid}:{st.st_gid} {mode:04o})")
    return out


def facts(ctx: Ctx) -> dict[str, Any]:
    """The daemon as host.json records it, observed now (ARCHITECTURE §11.2); `versions` and `facts` together hold
    the platform build that certifications name (gate.platform_build)."""
    info, build, tool = ctx.info, cx.build_facts(ctx), cx.tool_facts(ctx)
    versions = {k: build[k] for k in ("engine", "git_commit", "build_time", "containerd", "runc")}
    versions |= {k: tool[k] for k in ("api", "cli", "compose")}
    caps = {k: bool(info.get(x)) for k, x in (("cpu_cfs_quota", "CpuCfsQuota"), ("cpu_cfs_period", "CpuCfsPeriod"))}
    caps["memory_limit"] = bool(info.get("MemoryLimit"))
    found = {k: build[k] for k in ("os_release", "kernel", "storage_driver", "architecture")}
    found |= {"logging_driver": info.get("LoggingDriver"), "cgroup_version": info.get("CgroupVersion")}
    found |= {"os": info.get("OperatingSystem"), "live_restore": bool(info.get("LiveRestoreEnabled"))}
    found["security_options"] = list(info.get("SecurityOptions") or ())
    found["image_store"] = "containerd" if CONTAINERD_STORE in (info.get("DriverStatus") or ()) else "classic"
    out = {"engine_id": info.get("ID"), "docker_root_dir": info.get("DockerRootDir"), "versions": versions}
    return out | {"capabilities": caps, "facts": found}


def risks(f: dict[str, Any]) -> list[str]:
    """Host risks the facts show (ARCHITECTURE §11.2); another logging driver than `local` is none (§3.3)."""
    runc = f["versions"].get("runc")
    out = []
    if tuple(int(x) for x in re.findall(r"[0-9]+", str(runc or ""))[:3]) < RUNC_FIXED:
        out.append(f"runc {runc or 'of unknown version'} is older than 1.1.12 (CVE-2024-21626)")
    if not any("name=seccomp" in o for o in f["facts"]["security_options"]):
        out.append("the daemon runs containers without seccomp")
    return out


def _tier2(ctx: Ctx) -> tuple[str | None, str]:
    """(next, line): whether gate tier 2 may run on this platform build (ARCHITECTURE §3.6)."""
    try:
        cx.gate(ctx, gate.TIER2)
    except CannotRun as e:
        return e.next, f"gate tier 2 refuses: {e.message}"
    return None, "gate tier 2: this platform build is certified"


def host_init(ctx: Ctx) -> dict[str, Any]:
    """Bind this root to the daemon's engine and record its facts (class C, host lock, in the CLI); a re-run on the
    same engine refreshes the facts, keeping every field it does not own (ADR-0023)."""
    layout = ctx.layout
    if bad := roots(layout):
        raise Refused("\n".join(bad), code="roots")
    holder = {"op": "host-init", "command": [brand.CLI, "host", "init"], "operator": ctx.operator}
    with Lock(layout.host_lock, holder):
        old = state.read_doc(layout.host_json, "host") if fs.exists(layout.host_json) else {}
        now = facts(ctx)
        if old and old.get("engine_id") != now["engine_id"]:
            raise CannotRun(
                "host.json records another Docker engine (host rebind arrives in M4)", code="engine-mismatch"
            )
        for path in (layout.docker_config, layout.plans_dir, os.path.dirname(layout.runs_dir), layout.inbox):
            fs.mkdirs(path, 0o700)
        image = old.get("tool_image") or {}
        previous = image.get("previous") if image.get("current") in (None, ctx.image) else image.get("current")
        pools = {"isolation": ISOLATION_POOL, "ports": f"{cx.PORTS.start}-{cx.PORTS.stop - 1}"}
        doc = records.new_doc("host") | old | now | {"root": layout.root, "backups": layout.backups}
        doc |= {"label_namespace": brand.LABEL_NS, "pools": pools | (old.get("pools") or {})}
        doc |= {"tool_image": {"current": ctx.image, "previous": previous}}
        doc.setdefault("initialized_at", records.iso(ctx.now))
        state.replace_doc(layout.host_json, doc)
    v, f = now["versions"], now["facts"]
    lines = [
        f"host initialized: engine {now['engine_id']}, Engine {v['engine']} (API {v['api']}) on {f['architecture']}"
    ]
    lines.append(f"storage driver {f['storage_driver']}, image store {f['image_store']}, kernel {f['kernel']}")
    nxt, tier2 = _tier2(ctx)
    lines += [*(f"risk: {r}" for r in risks(now)), tier2]
    return {"exit": 0, "code": "ok", "next": nxt, "lines": lines, "host": doc}


def certification(ctx: Ctx, kind: str, result: str, **fields: Any) -> str:
    """Write `host/certifications/<stamp>-<kind>.json` (write-once) with the platform build observed now; returns
    its path. Used by `host check` (kind host-check) and `selftest --host` (kind selftest)."""
    doc = records.new_doc(kind, result=result, build=cx.build_facts(ctx), tool_version=__version__, **fields)
    doc["at"] = records.iso(ctx.now)
    stem, n = os.path.join(ctx.layout.certifications_dir, f"{records.stamp(ctx.now)}-{kind}"), 1
    while True:
        path = f"{stem}.json" if n == 1 else f"{stem}-{n}.json"
        try:
            state.write_doc_once(path, doc)
            return path
        except FileExistsError:
            n += 1


def host_check(ctx: Ctx) -> dict[str, Any]:
    """The host's facts as the tool sees them (ARCHITECTURE §10.4 step 2): roots, the tool's Docker client config,
    the platform build and its risks, recorded as a host-check certification. Exit 5 unless the result is PASS."""
    host, layout = cx.require_host(ctx), ctx.layout
    now, build = facts(ctx), cx.build_facts(ctx)
    failed = roots(layout)
    if not fs.exists(layout.docker_config):  # make_ctx refuses a non-empty one
        failed.append(f"{layout.docker_config} is missing")
    missing = [k for k in gate.BUILD_KEYS if not build.get(k)]
    result = "FAIL" if failed else "BLOCKED" if missing else "PASS"
    recorded = gate.platform_build(host)
    changed = [k for k in gate.BUILD_KEYS if recorded.get(k) != build.get(k)]  # a new build: re-certify (R14)
    found = {"failed": failed, "missing": missing, "risks": risks(now), "changed_since_host_init": changed}
    path = certification(ctx, "host-check", result, facts=now, **found)
    nxt, tier2 = _tier2(ctx)
    lines = [f"host check {result}: {path}", *(f"failed: {x}" for x in failed)]
    lines += [f"missing build fact: {k}" for k in missing] + [f"risk: {r}" for r in found["risks"]]
    lines += [f"changed since host init: {k}" for k in changed] + [tier2]
    report = {"exit": 0, "code": "ok"} if result == "PASS" else {"exit": 5, "code": "findings"}
    return report | {"next": nxt, "lines": lines, "result": result, "path": path, **found}
