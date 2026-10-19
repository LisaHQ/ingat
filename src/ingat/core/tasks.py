"""The M1 step set, part 2: one-off task containers and bundles (LIFECYCLE §3.3, §4.7, §4.8, §5.3; ARCHITECTURE
§4.1, §7.2). Task I/O stays in the operation directory; only sealed copies go to the backups root."""

import dataclasses
import os
import stat
from typing import Any

from ingat import brand
from ingat.adapters import override
from ingat.adapters.docker import EffectToken
from ingat.core.plan import Step
from ingat.core.probes import matches
from ingat.core.steps import SUMS, Op, env_text, no_links, safe_binds
from ingat.model import records, templates
from ingat.model.bundle import ID_RE, bundle_doc, bundle_hash, parse_sums, sums_text
from ingat.model.errors import CannotRun, Failed, IngatError, NeedsAttention, Refused
from ingat.store import fs, state

STOP_GRACE = 10
PAYLOAD = "payload/"
TASK_WORDS = {  # how a task's outcome reads in its error (`ok` never gets there; a stray word falls back to itself)
    "finding": "finished but reported findings this operation does not accept",
    "refused": "refused to run, so it changed nothing",
    "failed": "failed",
    "unknown": "ended in an unknown state: it cannot be told whether it changed data",
}


def outcome(a: dict[str, Any], code: int | None) -> str:
    """The exit map; undeclared: 0 is ok, anything else failed for a read task and unknown for a write."""
    if code is not None and code >= 0 and str(code) in a["exit"]:
        return str(a["exit"][str(code)])
    return "ok" if code == 0 else "failed" if a["effect"] == "read" else "unknown"


def phase(a: dict[str, Any], out: str) -> str:
    """Step phase of a task outcome: refused and failed fail; a finding fails only under require_ok."""
    if out == "unknown":
        return "unknown"
    if out == "ok" or (out == "finding" and (a.get("findings_ok") or not a.get("require_ok"))):
        return "done"
    return "failed"


def _owner(value: Any) -> tuple[int, int] | None:
    return (int(value[0]), int(value[1])) if value else None


def _tree(path: str) -> dict[str, str]:
    """sha256 of every regular file below `path` (links and special files refused, one link per file)."""
    return {rel: fs.hash_file(os.path.join(path, rel))[0] for rel, st in fs.walk(path) if stat.S_ISREG(st.st_mode)}


def _payload(op: Op, bid: str) -> dict[str, str]:
    """The payload files of a sealed bundle as SHA256SUMS lists them, after re-checking it against the catalog."""
    sums = fs.read(os.path.join(op.layout.bundle_dir(op.name, bid), SUMS))
    if bundle_hash(sums) != state.read_doc(op.layout.catalog(op.name, bid), "catalog")["bundle_hash"]:
        raise Failed(_mismatch(bid), code="bundle-hash")
    return {p.removeprefix(PAYLOAD): h for p, h in parse_sums(sums).items() if p.startswith(PAYLOAD)}


def _mismatch(bid: str) -> str:
    return (
        f"The backup copy {bid} does not match its recorded checksum (its {SUMS} file differs from the catalog "
        "entry). The copy may be damaged or altered; do not rely on it until this is explained."
    )


def _capacity(needs: dict[str, int]) -> None:
    want: dict[int, int] = {}
    free: dict[int, int] = {}
    for path, size in needs.items():
        dev, free[dev] = fs.statvfs(path)
        want[dev] = want.get(dev, 0) + size
    for dev, size in want.items():
        if size > free[dev]:
            why = (
                f"Not enough free disk space: this needs about {size:,} bytes but only {free[dev]:,} bytes are free "
                "on that disk. The operation stops here. Free some space, then try again."
            )
            raise Refused(why, code="capacity")


def _source(op: Op, a: dict[str, Any], source: str, values: dict[str, str]) -> str:
    """The host path behind a mount source (MANIFEST_SPEC §4); every one is inside the op dir or a generation."""
    owner = _owner(a.get("task_uid"))
    kind, _, key = source.partition(":")
    if source == "stage":
        if not fs.exists(op.path("stage")):
            fs.make_empty_dir(op.path("stage"), 0o700, owner)
        return op.path("stage")
    if source == "bundle":
        path: str | None = op.find("input_dir").get("input_dir")
        if not path:
            raise Refused("the task reads a bundle but no verified input copy exists", code="internal")
        return path + ":ro"
    if kind == "generation":
        path = a["gen_paths"][key]
        if path != op.layout.data_gen(op.name, key, os.path.basename(path)):
            raise Refused(f"generation path {path} is not a generation of store {key}", code="unsafe-path")
        no_links(path)
        return path
    if kind == "input":
        src = a["inputs"][key]
        if os.path.dirname(src) != op.layout.inbox:
            raise Refused(f"input {key} must be a file directly in the inbox", code="unsafe-path")
        data, d = fs.read(src, a.get("max_input_bytes")), op.path("in", f"input-{key}")
        fs.remove_tree(d)
        fs.write_once(os.path.join(d, os.path.basename(src)), data, 0o440)
        if owner:
            fs.chown_tree(d, *owner)
        fs.chmod_tree(d, 0o550, 0o440)
        values[f"input.{key}"] = os.path.basename(src)
        return d + ":ro"
    raise Refused(f"internal: unknown mount source {source!r}", code="internal")


def run_task(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    """One attempt in its own named, labelled container (`compose run --rm`); the exit map and `expect` decide."""
    a = step.args
    term_in, term_out = a.get("stdin") == "terminal", a.get("stdout") == "terminal"
    if ((term_in or term_out) and not op.foreground) or (term_in and not op.tty):
        why = (
            f"The task {a['task']} needs to talk to you on screen, so it cannot run in the background. Run the "
            "command from a terminal window, not from a script or a background job."
        )
        raise CannotRun(why, code="no-tty")
    _capacity(a.get("capacity") or {})
    v = op.variant(a["variant"])
    safe_binds(op, a["variant"])
    values = {**v.get("values", {}), **op.values(), **{f"arg.{k}": x for k, x in (a.get("args") or {}).items()}}
    env = op.env(a["variant"])
    env.update(dict.fromkeys((a.get("store_params") or {}).values(), op.layout.placeholder(op.name)))
    volumes = []
    for target, source in a.get("mounts", []):
        src = _source(op, a, source, values)
        if target.startswith("/"):
            volumes.append(f"{src.removesuffix(':ro')}:{target}{':ro' if src.endswith(':ro') else ''}")
        else:
            env[target] = src.removesuffix(":ro")
    n, attempt = op.step, op.attempt
    env_file = op.path("env", f"{n}-{attempt}.env")
    fs.write_once(env_file, env_text(env))
    argv = [templates.render(x, values) for x in a["argv"]]
    task_env = {k: templates.render(x, values) for k, x in (a.get("env") or {}).items()}
    name = f"{op.name}-x{op.seq}-{n}-a{attempt}"
    labels = {brand.label("instance"): op.name, brand.label("op"): str(op.seq), brand.label("step"): str(n)}
    labels[brand.label("role")] = "task"
    stopped: list[bool] = []
    started: list[bool] = []

    def tick() -> None:
        if op.journal.crash_at == f"{n}:task" and not started and op.docker.inspect("container", [name]):
            started.append(True)
            op.journal.task_started(n)
        if step.interruptible and not stopped and op.cancelled() and op.docker.inspect("container", [name]):
            stopped.append(True)  # once the container exists: a stop before its create would be lost
            op.docker.stop(t, name, STOP_GRACE)

    proj = op.project(a["variant"], env_file)
    if term_in or term_out:  # terminal output is streamed only: never captured, never kept by a logging driver (F12)
        quiet = op.path("env", f"{n}-{attempt}.yaml")
        fs.write_once(quiet, override.render({"services": {a["service"]: {"logging": {"driver": "none"}}}}).encode())
        proj = dataclasses.replace(proj, files=(*proj.files, str(proj.override)), override=quiet)
    try:
        res = op.compose.run(
            t, proj, a["service"], argv, name=name, labels=labels, volumes=volumes, user=a.get("user"),
            env=task_env, tty=term_in, stdin="inherit" if term_in else None,
            stdout="inherit" if term_in or term_out else "capture", timeout=a["timeout"], tick=tick,
        )  # fmt: skip
    except BaseException:
        _stop(op, t, name)  # the client is gone; the container is not (spike S14)
        raise
    if res.timed_out:
        _stop(op, t, name)
    out = outcome(a, None if res.timed_out else res.code)
    if out == "ok" and a.get("expect") and not _expected(res.out, a["expect"]):
        out = "failed" if a["effect"] == "read" else "unknown"
    ev: dict[str, Any] = {"outcome": out, "exit": res.code, "attempt": attempt, "container": name}
    if a.get("stdout") in ("json", "record"):
        stem = f"{n}-a{attempt}-{a['task']}.out"
        ev["artifact"] = op.path("artifacts", stem)
        fs.write_once(ev["artifact"], res.out.encode())
        if a["stdout"] == "record":
            fs.write_once(os.path.join(op.layout.reports_dir(op.name), f"{op.seq}-{stem}"), res.out.encode())
    if any(src == "bundle" for _, src in a.get("mounts", [])):
        _check_input(op)
    ev["phase"] = "cancelled" if stopped else phase(a, out)
    if ev["phase"] != "done":
        ev["code"] = "cancelled" if stopped else f"task-{out}"
        how = TASK_WORDS.get(out, f"ended {out}")
        ev["error"] = (
            f"The task {a['task']} {how} (exit code {res.code}). The app's last output: {res.err.strip()[-300:]}"
        )
    return ev


def _stop(op: Op, t: EffectToken, name: str) -> None:
    """Stop a task container and wait for it (F15). When that fails the container may still run, so the step stays
    unknown and the operation open: the next command's orphan check sees it."""
    try:
        op.docker.stop(t, name, STOP_GRACE)
    except IngatError as e:
        why = (
            f"The helper container {name} may still be running ({e.message}). Stop it with `docker stop {name}`, "
            "then resume or abandon the operation."
        )
        raise NeedsAttention(why, code="task-running", next=f"docker stop {name}") from e


def _expected(text: str, spec: dict[str, list[Any]]) -> bool:
    try:
        return matches(records.loads(text.encode()), spec)
    except Refused:
        return False


def _check_input(op: Op) -> None:
    """Hashes of a private bundle copy are re-checked after every step that saw it (ARCHITECTURE §7.2)."""
    path = op.find("input_dir")["input_dir"]
    if _tree(path) != _payload(op, os.path.basename(path)):
        raise Failed(f"the private bundle copy {path} changed during the task", code="bundle-hash")


def capture(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    return _begin(op, step.args) if step.args["phase"] == "begin" else _seal(op, step.args)


def _begin(op: Op, a: dict[str, Any]) -> dict[str, Any]:
    """Choose the bundle id and stamp and make the stage, owned by the backup tasks' user."""
    now = records.utc_now()
    stamp = records.stamp(now)
    base = op.variant(a["variant"]).get("values", {}) if a.get("variant") else {}
    values = {**base, **op.values(), "bundle.stamp": stamp, "class": a["class"]}
    bid = templates.render(a["naming"], values)
    if not ID_RE.fullmatch(bid):
        why = f"The backup copy name {bid!r} is not allowed: it must match the pattern {ID_RE.pattern}."
        raise Refused(why, code="bundle-id")
    paths = (op.layout.catalog, op.layout.bundle_dir, op.layout.incoming_dir)
    if any(fs.exists(p(op.name, bid)) for p in paths):
        why = (
            f"A backup copy named {bid} already exists (or one by that name was left half made), and an existing "
            "backup copy is never overwritten. The operation stops here."
        )
        raise Refused(why, code="bundle-exists")
    payload = templates.render(a["payload"], {**values, "bundle.id": bid}) if a.get("payload") else None
    fs.make_empty_dir(op.path("stage"), 0o700, _owner(a.get("stage_owner")))
    out = {"bundle.id": bid, "bundle.stamp": stamp, **({"bundle.payload": payload} if payload else {})}
    return {"bundle_id": bid, "stamp": stamp, "created_at": records.iso(now), "payload": payload, "values": out}


def _seal(op: Op, a: dict[str, Any]) -> dict[str, Any]:
    """Payload rule, bundle.json, SHA256SUMS (bundle.json included), copy into .incoming-<id>, rename, catalog."""
    begin = op.find("stamp")
    bid, payload, stage = begin["bundle_id"], begin["payload"], op.path("stage")
    entries = fs.listdir(stage)
    if len(entries) != 1 or (payload and entries != [payload]):
        want = f"exactly one entry{f' named {payload}' if payload else ''}"
        why = (
            f"The app's backup step produced {len(entries)} items where {want} was expected, so the backup copy "
            "could not be finished. This usually points to a problem in the app's backup definition."
        )
        raise Failed(why, code="payload")
    work = op.path("bundle", bid)
    fs.rename(os.path.join(stage, entries[0]), os.path.join(work, "payload", entries[0]))
    fs.remove_tree(stage)
    meta = []
    for mname, src in sorted(a["meta_files"].items()):
        fs.write_once(os.path.join(work, "meta", mname), fs.read(src))
        meta.append(f"meta/{mname}")
    files = [(rel, *fs.hash_file(os.path.join(work, rel))) for rel, st in fs.walk(work) if stat.S_ISREG(st.st_mode)]
    doc = bundle_doc(
        bundle_id=bid, klass=a["class"], instance=op.name, app=a["app"], environment=a["environment"],
        lineage=a["lineage"], created_at=begin["created_at"], freeze_at=op.values().get("freeze_at"),
        consistency=a["consistency"], deployment=a["deployment"], schema=a.get("schema"), stores=a["stores"],
        entry=entries[0], files=[f for f in files if f[0].startswith(PAYLOAD)], meta=meta, tool=a["tool"],
        host=a["host"],
    )  # fmt: skip
    fs.write_once(os.path.join(work, "bundle.json"), records.pretty(doc))
    files.append(("bundle.json", *fs.hash_file(os.path.join(work, "bundle.json"))))
    sums = sums_text([(p, h) for p, h, _ in files])
    fs.write_once(os.path.join(work, SUMS), sums)
    incoming, final = op.layout.incoming_dir(op.name, bid), op.layout.bundle_dir(op.name, bid)
    fs.remove_tree(incoming)
    copied = fs.copy_tree(work, incoming)
    if {p: h for p, h, _ in copied} != {**{p: h for p, h, _ in files}, SUMS: records.sha256_hex(sums)}:
        raise Failed(f"bundle {bid} changed while it was copied", code="bundle-hash")
    fs.rename(incoming, final)
    size, digest = sum(s for _, _, s in copied), bundle_hash(sums)
    entry = {"bundle_id": bid, "bundle_hash": digest, "class": a["class"], "size": size}
    entry |= {"created_at": begin["created_at"], "path": final, "imported": False}
    state.write_doc_once(op.layout.catalog(op.name, bid), records.new_doc("catalog", **entry))
    fs.remove_tree(op.path("bundle"))
    return {"bundle_id": bid, "bundle_hash": digest, "size": size, "path": final}


def sealed(op: Op, step: Step) -> dict[str, Any] | None:
    """The observe of a seal (LIFECYCLE §3.3: a catalog entry with the bundle hash): the bundle id its begin chose is
    catalogued and the published bundle's SHA256SUMS has the catalog's hash. The seal's evidence then, so a resume
    goes on instead of sealing a second bundle; None when the seal did not complete (redo the group). Read-only."""
    bid = op.find("stamp").get("bundle_id")
    if step.type != "CaptureBundle" or step.args["phase"] != "seal" or not bid:
        return None
    cat, sums = op.layout.catalog(op.name, bid), os.path.join(op.layout.bundle_dir(op.name, bid), SUMS)
    if not fs.exists(cat) or not fs.exists(sums):
        return None
    entry = state.read_doc(cat, "catalog")
    if bundle_hash(fs.read(sums)) != entry["bundle_hash"]:
        return None
    return {"bundle_id": bid, "bundle_hash": entry["bundle_hash"], "size": entry["size"], "path": entry["path"]}


def verify(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    """Re-hash every listed file (regular, one link; nothing unlisted), compare with the catalog, and optionally
    make the private read-only input copy owned by the task user (LIFECYCLE §4.8)."""
    a = step.args
    bid = a.get("bundle") or op.find("bundle_id").get("bundle_id")
    if not bid:
        raise Refused("internal: no bundle to verify", code="internal")
    d = op.layout.bundle_dir(op.name, bid)
    digest = state.read_doc(op.layout.catalog(op.name, bid), "catalog")["bundle_hash"]
    sums = fs.read(os.path.join(d, SUMS))
    found = _tree(d)
    if bundle_hash(sums) != digest or found.pop(SUMS, None) != records.sha256_hex(sums):
        raise Failed(_mismatch(bid), code="bundle-hash")
    listed = parse_sums(sums)
    if found != listed:
        odd = sorted(p for p in set(found) | set(listed) if found.get(p) != listed.get(p))
        why = (
            f"The backup copy {bid} failed its check: these files are missing, extra or changed: {', '.join(odd)}. "
            "Do not rely on this copy."
        )
        raise Failed(why, code="bundle-hash")
    entry = records.loads(fs.read(os.path.join(d, "bundle.json")))["payload"]["entry"]
    ev = {"bundle_id": bid, "bundle_hash": digest, "entry": entry, "input_dir": None}
    ev["values"] = {"bundle.id": bid, "bundle.payload": entry}
    if a.get("input_owner"):
        dst = op.path("in", bid)
        fs.remove_tree(dst)
        copied = fs.copy_tree(
            os.path.join(d, "payload"), dst, owner=_owner(a["input_owner"]), dir_mode=0o550, file_mode=0o440
        )
        payload = {p.removeprefix(PAYLOAD): h for p, h in listed.items() if p.startswith(PAYLOAD)}
        if {p: h for p, h, _ in copied} != payload:
            raise Failed(f"bundle {bid} changed while its input copy was made", code="bundle-hash")
        ev["input_dir"] = dst
    return ev
