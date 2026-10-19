"""`init` (LIFECYCLE §4.1): register an instance from the owner's instance.toml at a resolved commit, in the CLI under
the host lock. Every check runs before the first write (F2) and nothing in Docker changes. record.json is written
last: until it exists the name is no instance, and a re-run completes what an interrupted `init` left."""

import ipaddress
import os
import secrets
import string
from typing import Any

from ingat import brand
from ingat.adapters.docker import PROJECT_LABEL
from ingat.model import records
from ingat.model.errors import CannotRun, Refused
from ingat.model.instance import NAME_RE, Instance, parse_instance
from ingat.model.manifest import Manifest
from ingat.ops import context as cx
from ingat.ops.context import Ctx
from ingat.policy.gate import TIER2
from ingat.store import fs, state
from ingat.store.locks import Lock

ALNUM = string.ascii_letters + string.digits
CONFIG_LIMIT = 1 << 20
OWN = ("instance.toml", "lock", "lock.holder.json", "secrets", "placeholder")  # all that an interrupted init leaves


def init(ctx: Ctx, name: str, config_path: str, ref: str) -> dict[str, Any]:
    """`init <name> --config <file> --ref <ref>` (class C, gate tier 2, host lock)."""
    cx.require_host(ctx)
    cx.gate(ctx, TIER2)
    try:
        data = fs.read(config_path, CONFIG_LIMIT)
    except FileNotFoundError:
        raise CannotRun(f"{config_path} does not exist", code="usage") from None
    command = [brand.CLI, "init", name, "--config", config_path, "--ref", ref]
    with Lock(ctx.layout.host_lock, {"op": "init", "command": command, "operator": ctx.operator}):
        return create(ctx, name, data, ref)


def create(ctx: Ctx, name: str, data: bytes, ref: str) -> dict[str, Any]:
    """The work of `init` for a caller that holds the host lock; no gate, so that `selftest` can register its own
    instances on a host it is about to certify."""
    layout = ctx.layout
    if not NAME_RE.fullmatch(name):
        raise CannotRun(cx.bad_name(name), code="usage")
    host = cx.require_host(ctx)
    inst = parse_instance(data)
    if inst.name != name:
        raise Refused(f"name: instance.toml names {inst.name!r}, not {name!r}", code="invalid-instance")
    if fs.exists(layout.record_json(name)):
        raise Refused(f"instance {name} exists", code="exists")
    if extra := [n for n in fs.listdir(layout.inst(name)) if n not in OWN and not n.endswith(".tmp")]:
        raise Refused(f"{layout.inst(name)} holds {', '.join(extra)} of an earlier instance", code="exists")
    toml, placeholder = layout.inst_toml(name), layout.placeholder(name)
    if fs.exists(toml) and fs.read(toml) != data:
        raise Refused(f"{toml} exists and differs from the given config", code="exists")
    if fs.listdir(placeholder):  # one an interrupted init left is reused only while empty
        raise Refused(f"{placeholder} is not empty", code="exists")
    _foreign(ctx, name)
    ld = cx.Loaded(name, inst, {}, None, None)
    src = cx.source(ctx, ld, ref)
    m = src.manifest
    cx.supported(m)  # M1 has no way to remove an instance it registered but cannot deploy
    if left := [s for s in m.stores if fs.listdir(os.path.dirname(layout.data_gen(name, s, "g1")))]:
        # their markers name this instance, so a new lineage could take over or delete them (F7, F8)
        why = f"data copies of an earlier instance named {name} still exist for store(s) {', '.join(left)}; "
        raise Refused(
            why + f"{brand.PRODUCT} never deletes data, so move them away or choose another name", code="exists"
        )
    _exclusive(ctx, ld, m)
    ports = cx.allocate_ports(ctx, name, m, inst)
    subnets = _subnets(ctx, name, m, inst, (host.get("pools") or {}).get("isolation"))
    kept, made = _secrets(layout, name, m)
    # Every check passed: allocation entries, then the instance directory, then record.json.
    _allocate(ctx, name, [("port", v, k) for k, v in ports.items()] + [("subnet", v, k) for k, v in subnets.items()])
    with Lock(layout.lock(name), {"op": "init", "command": [brand.CLI, "init", name], "operator": ctx.operator}):
        if not fs.exists(toml):
            fs.write_once(toml, data, 0o600)
        fs.mkdirs(os.path.join(layout.secrets_dir(name), "env"), 0o700)
        for k, value in (kept | made).items():  # a kept secret is published again with the manifest's mode
            path = os.path.join(layout.secrets_dir(name), k)
            (fs.replace_atomic if k in kept else fs.write_once)(path, value, m.secrets[k].mode)
        fs.mkdirs(placeholder, 0o555)
        fs.chmod_tree(placeholder, 0o555, 0o444)
        record: dict[str, Any] = {"name": name, "app": m.app, "environment": inst.environment}
        record["lineage"] = secrets.token_hex(16)  # 128 random bits (ARCHITECTURE §7.5)
        record |= {"disposable": inst.disposable, "state": "registered", "current_deployment": None}
        record |= {"previous_deployment": None, "generations": {}, "held_since": None, "open_op": None}
        record |= {"next_seq": 1, "created_at": records.iso(ctx.now), "last_op": None}
        state.write_doc_once(layout.record_json(name), records.new_doc("instance", **record))
    lines = [f"initialized {name}: {m.app}, environment {inst.environment}, commit {src.commit}"]
    lines += [f"params.{k} = {v}" for k, v in (ports | subnets).items()]
    lines += [f"secrets.{k}: generated" for k in made] + [f"secrets.{k}: kept" for k in kept]
    where = "put its value in the instance's secrets folder before deploying"
    lines += [f"secrets.{k}: not set ({where})" for k in m.secrets if k not in kept | made]
    out = {"exit": 0, "code": "ok", "next": f"{brand.CLI} deploy {name} {ref}", "lines": lines, "instance": name}
    return out | {"app": m.app, "commit": src.commit, "release": src.release, "params": ports | subnets}


def _foreign(ctx: Ctx, name: str) -> None:
    """Docker objects of a Compose project of this name belong to no instance of this root (it has none of that name
    yet), so they are foreign and never touched (ARCHITECTURE §7.5)."""
    d, label = ctx.docker, {PROJECT_LABEL: name}
    found = [f"container {c['Name'].lstrip('/')}" for c in d.containers(project=name)]
    found += [f"network {n['Name']}" for n in d.networks(label)] + [f"volume {v['Name']}" for v in d.volumes(label)]
    if found:
        msg = f"Docker already has a project named {name} ({', '.join(found)}); it belongs to no instance here and is "
        msg += "never touched, so choose another instance name"
        raise Refused(msg, code="foreign")


def _exclusive(ctx: Ctx, ld: cx.Loaded, m: Manifest) -> None:
    """`exclusive_environments` both ways (LIFECYCLE §4.3): no other instance of the app beside one whose environment
    the manifest lists."""
    cx.exclusive(ctx, ld, m)
    layout, listed = ctx.layout, set(m.exclusive_environments)
    docs = [state.read_doc(layout.record_json(n), "instance") for n in state.list_instances(layout)]
    if found := [str(d.get("name")) for d in docs if d.get("app") == m.app and d.get("environment") in listed]:
        raise Refused(f"{', '.join(found)} of {m.app} runs in an exclusive environment", code="exclusive")


def _net(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(value, strict=False)


def _subnets(ctx: Ctx, name: str, m: Manifest, inst: Instance, pool: str | None) -> dict[str, str]:
    """The instance's subnet params, each overlapping no other one, no other instance's allocation entry, no network on
    the daemon and not the isolation pool (LIFECYCLE §4.1). M1 allocates none: one left unset would later bypass these
    checks, so it refuses here as `deploy` would."""
    out = {k: inst.params.get(k, "") for k, p in m.params.items() if p.kind == "subnet"}
    if unset := [k for k, v in out.items() if not v]:
        raise Refused(f"params.{unset[0]}: set the live subnet in instance.toml", code="not-in-this-release")
    if not out:
        return out
    taken = [("the isolation pool", pool)] if pool else []
    for (kind, value), e in cx.allocations(ctx).items():
        if kind == "subnet" and e.get("instance") != name:  # an entry of this name is an interrupted init's
            taken.append((f"the subnet of {e.get('instance')}", value))
    for n in ctx.docker.networks():
        taken += [(f"network {n['Name']}", c.get("Subnet")) for c in (n.get("IPAM") or {}).get("Config") or ()]
    for k, v in out.items():
        rivals = taken + [(f"params.{j}", x) for j, x in out.items() if j != k]
        if hit := [what for what, x in rivals if x and _net(v).overlaps(_net(x))]:
            raise Refused(f"params.{k}: subnet {v} overlaps {hit[0]}", code="subnet-conflict")
    return out


def _secrets(layout: state.Layout, name: str, m: Manifest) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """(kept, generated) values of the manifest's [secrets.*] files: an existing file (left by an interrupted init, or
    placed by the owner) is kept, never regenerated; each other one with `generate` gets 32 characters [A-Za-z0-9].
    The values are pairwise distinct (ARCHITECTURE §9.4); errors name keys only."""
    kept: dict[str, bytes] = {}
    for k in m.secrets:
        if fs.exists(path := os.path.join(layout.secrets_dir(name), k)):
            if not (value := fs.read(path)) or value in kept.values():
                raise Refused(f"secrets.{k}: the existing file is empty or repeats another secret", code="secret")
            kept[k] = value
    made: dict[str, bytes] = {}
    for k, s in m.secrets.items():
        if s.generate and k not in kept:
            value = b""
            while not value or value in kept.values() or value in made.values():
                value = "".join(secrets.choice(ALNUM) for _ in range(32)).encode()
            made[k] = value
    return kept, made


def _allocate(ctx: Ctx, name: str, wanted: list[tuple[str, str, str]]) -> None:
    """Write the live allocation entries (kind, value, param) write-once, after removing those an interrupted init of
    this name left; a value another process took meanwhile refuses, and this init's entries are removed again."""
    layout, done = ctx.layout, list[str]()
    for (kind, value), e in cx.allocations(ctx).items():
        if e.get("instance") == name:
            fs.remove(layout.allocation(kind, value))
    for kind, value, param in wanted:
        doc = records.new_doc("allocation", instance=name, purpose="live", param=param, op=None)
        try:
            state.write_doc_once(path := layout.allocation(kind, value), doc | {"at": records.iso(ctx.now)})
        except FileExistsError:
            for p in done:
                fs.remove(p)
            msg = f"params.{param}: {kind} {value} was taken meanwhile; run init again"
            raise Refused(msg, code=f"{kind}-conflict") from None
        done.append(path)
