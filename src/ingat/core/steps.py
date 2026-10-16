"""The M1 step set, part 1: the operation context, shared helpers and the steps that need neither probes nor task
containers (LIFECYCLE §3.3). Every step gets its own EffectToken; a step returns its evidence, or raises to fail."""

import contextlib
import ipaddress
import os
import stat
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ingat import brand
from ingat.adapters.compose import Compose, Project
from ingat.adapters.docker import Docker, EffectToken
from ingat.adapters.runner import Result
from ingat.core.journal import Journal, heal
from ingat.core.plan import PROJECT_LABEL, Plan, Step
from ingat.model import records
from ingat.model.bundle import bundle_hash
from ingat.model.errors import Failed, Refused
from ingat.store import fs, state

SUMS = "SHA256SUMS"
SUBNET = "@subnet"  # a variant env value the executor replaces with the operation's isolation /24
SERVICE_LABEL = "com.docker.compose.service"
ONEOFF_LABEL = "com.docker.compose.oneoff"
UP_TIMEOUT = 600
DOWN_TIMEOUT = 600
SELFTEST_MARKER = "selftest.json"  # instances/<i>/selftest.json: a selftest run's proof that it made the instance
SELFTEST_KIND = "selftest-run"
SELFTEST_RUNS: set[str] = set()  # the selftest runs this process drives, in memory only (ops/selftest.py)
FROM_EVIDENCE = {"writes_reopened_at": "writes_reopened_at", "schema": "schema", "pre_change_bundle": "bundle_id"}


class Cancelled(Exception):
    """A cancel request reached an interruptible wait."""


@dataclass
class Op:
    """One open operation as the steps see it; evidence is keyed by plan step number."""

    layout: state.Layout
    docker: Docker
    compose: Compose
    plan: Plan
    name: str
    seq: int
    dir: str
    journal: Journal
    vdir: str  # where this plan's variant files live
    offset: int = 0  # journal number = offset + plan step number (a task joined to a paused operation)
    foreground: bool = False
    tty: bool = False
    signalled: Callable[[], bool] = lambda: False
    evidence: dict[int, dict[str, Any]] = field(default_factory=dict)
    attempts: dict[int, int] = field(default_factory=dict)
    subnets: dict[str, str] = field(default_factory=dict)
    step: int = 0
    attempt: int = 1

    def num(self, step: Step) -> int:
        return self.offset + step.n

    def path(self, *parts: str) -> str:
        return os.path.join(self.dir, *parts)

    def cancelled(self) -> bool:
        return self.signalled() or fs.exists(self.path("cancel"))

    def tick(self) -> None:
        if self.cancelled():
            raise Cancelled

    def variant(self, name: str) -> dict[str, Any]:
        v: dict[str, Any] = self.plan.inputs["variants"][name]
        return v

    def env(self, name: str) -> dict[str, str]:
        return {k: self.subnets[k] if v == SUBNET else v for k, v in self.variant(name)["env"].items()}

    def project(self, name: str, env_file: str | None = None) -> Project:
        v = self.variant(name)
        files, profiles = tuple(v["files"]), tuple(v.get("profiles", ()))
        env_file = env_file or f"{self.vdir}/{name}.env"
        return Project(v["project"], v["directory"], files, f"{self.vdir}/{name}.yaml", env_file, profiles)

    def values(self) -> dict[str, str]:
        """Runtime template values earlier steps produced (bundle.*, freeze_at)."""
        out: dict[str, str] = {}
        for n in sorted(self.evidence):
            out.update(self.evidence[n].get("values", {}))
        return out

    def find(self, key: str) -> dict[str, Any]:
        """The latest evidence that holds `key`, or {}."""
        return next((self.evidence[n] for n in sorted(self.evidence, reverse=True) if self.evidence[n].get(key)), {})

    def record(self) -> dict[str, Any]:
        return state.read_doc(self.layout.record_json(self.name), "instance")

    def update(self, **changes: Any) -> None:
        state.replace_doc(self.layout.record_json(self.name), records.merged(self.record(), **changes))


def selftest_run(layout: state.Layout, name: str) -> str | None:
    """The selftest run that made instance `name`: its name has the selftest prefix and its marker names the run and
    the instance. Only such an instance may skip the certification and take its live project and generations down
    at its teardown (ARCHITECTURE §3.6, §10.4); None for every other instance."""
    if not name.startswith(brand.SELFTEST_PREFIX) or not fs.exists(path := layout.inst(name, SELFTEST_MARKER)):
        return None
    doc = state.read_doc(path, SELFTEST_KIND)
    return str(doc["run_id"]) if doc.get("instance") == name and doc.get("run_id") else None


def in_selftest(layout: state.Layout, name: str) -> bool:
    """Whether `name` is an instance of a selftest run this process drives: the one exception gate tier 2 makes. The
    run is known only in memory, so no file widens the gate (ARCHITECTURE §3.6): a marker waives nothing by itself."""
    return bool(SELFTEST_RUNS) and selftest_run(layout, name) in SELFTEST_RUNS


def env_text(env: Mapping[str, str]) -> bytes:
    """`KEY='value'` lines (spike S6); a value that cannot be single-quoted is refused by key, never echoed."""
    for key, value in env.items():
        if any(c in value for c in "'\n\r\0"):
            raise Refused(f"the value of {key} cannot be written single-quoted", code="unsafe-value")
    return "".join(f"{k}='{v}'\n" for k, v in env.items()).encode()


def no_links(path: str) -> None:
    """A bind source must exist and have no symbolic link in any component (a link to the socket is a client)."""
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise Refused(f"bind source {path} is not a normalized absolute path", code="unsafe-path")
    cur = ""
    for part in path.split("/")[1:]:
        cur += "/" + part
        try:
            link = stat.S_ISLNK(os.lstat(cur).st_mode)
        except FileNotFoundError as e:
            raise Refused(f"bind source {path}: {cur} does not exist", code="unsafe-path") from e
        if link:
            raise Refused(f"bind source {path}: {cur} is a symbolic link", code="unsafe-path")


def safe_binds(op: Op, variant: str) -> None:
    """Before every Compose call that creates a container: the variant's bind sources (an app may have swapped one
    inside its own data for a link since the last check), and each secret file it uses must be a regular, non-empty
    file, never followed (ARCHITECTURE §9.4: Compose would make a directory at a missing path)."""
    v = op.variant(variant)
    for path in v.get("binds", []):
        no_links(path)
    for path in v.get("secret_files", []):
        try:
            st: os.stat_result | None = os.lstat(path)
        except FileNotFoundError:
            st = None
        if st is None or not stat.S_ISREG(st.st_mode) or not st.st_size:
            raise Refused(f"secret file {path} is not a regular, non-empty file", code="secret-file")
        no_links(path)


def check(res: Result, what: str) -> Result:
    if res.code != 0:
        detail = "timed out" if res.timed_out else res.err.strip()[-300:]
        raise Failed(f"{what} failed: {detail}", code="compose")
    return res


def compose_up(op: Op, t: EffectToken, proj: Project, services: list[str], timeout: float) -> None:
    """`compose up`, then once more with new containers for the services whose container runs without a port it
    binds: Engine 29.9.0 never publishes the ports of a container whose start once failed on a port conflict, and
    `up` only starts such a container again (its configuration is unchanged)."""
    check(op.compose.up(t, proj, services, timeout=timeout), "compose up")
    bare: set[Any] = set()
    for c in op.docker.containers(labels={brand.label("instance"): op.name}, project=proj.name):
        labels, ports = c["Config"].get("Labels") or {}, (c.get("NetworkSettings") or {}).get("Ports") or {}
        bound = [k for k, v in ((c.get("HostConfig") or {}).get("PortBindings") or {}).items() if v]
        if labels.get(ONEOFF_LABEL) != "True" and c["State"].get("Running") and any(not ports.get(k) for k in bound):
            bare.add(labels.get(SERVICE_LABEL))
    if again := sorted(s for s in services if s in bare):
        check(op.compose.up(t, proj, again, timeout=timeout, recreate=True), "compose up")


def once(path: str, doc: dict[str, Any], seq: int) -> None:
    """Write-once; an existing file this operation wrote counts as done (a redo after a crash)."""
    try:
        state.write_doc_once(path, doc)
    except FileExistsError:
        if state.read_doc(path, doc["kind"]).get("op") != seq:
            raise Refused(f"{path} already exists", code="exists") from None


def allocate(layout: state.Layout, docker: Docker, name: str, seq: int, params: set[str], pool: str) -> dict[str, str]:
    """One pool /24 per subnet param: reuse this op's entries, else the first /24 no entry and no network uses."""
    got = {param: subnet for param, (_, subnet) in allocations(layout, name, seq).items()}
    used = [
        ipaddress.ip_network(c["Subnet"]) for n in docker.networks() for c in (n.get("IPAM") or {}).get("Config") or []
        if c.get("Subnet") and ":" not in c["Subnet"]
    ]  # fmt: skip
    for param in sorted(params - set(got)):
        for net in ipaddress.ip_network(pool).subnets(new_prefix=24):
            path = layout.allocation("subnet", str(net))
            if fs.exists(path) or any(net.overlaps(u) for u in used):
                continue
            doc = records.new_doc("allocation", instance=name, purpose="isolated", param=param, op=seq, at=_now())
            with contextlib.suppress(FileExistsError):
                state.write_doc_once(path, doc)
                got[param] = str(net)
                break
        else:
            raise Refused(f"no free /24 left in the isolation pool {pool}", code="capacity")
    return got


def allocations(layout: state.Layout, name: str, seq: int) -> dict[str, tuple[str, str]]:
    """param -> (entry path, subnet) of the isolation subnets operation `seq` of `name` holds."""
    out = {}
    for entry in fs.listdir(layout.allocations_dir):
        if entry.startswith("subnet-") and entry.endswith(".json"):
            path = os.path.join(layout.allocations_dir, entry)
            doc = state.read_doc(path, "allocation")
            if doc.get("instance") == name and doc.get("op") == seq:
                out[doc["param"]] = (path, entry.removeprefix("subnet-").removesuffix(".json").replace("_", "/"))
    return out


def remove_generation(op: Op, store: str, gen: str) -> None:
    """Delete a bind generation this operation created and never promoted, re-proved by its marker (F8)."""
    path = op.layout.data_gen(op.name, store, gen)
    if not fs.exists(path + ".json"):
        return
    doc = state.read_doc(path + ".json", "generation")
    current = f"g{op.record().get('generations', {}).get(store)}"
    if doc.get("op") != op.seq or doc.get("instance") != op.name or gen == current:
        raise Refused(f"generation {gen} of store {store} is not this operation's to delete", code="not-owned")
    for c in op.docker.containers():
        if c["State"]["Running"] and any(m.get("Source") == path for m in c.get("Mounts") or []):
            raise Refused(f"generation {gen} of store {store} is in use by {c['Name'].lstrip('/')}", code="in-use")
    fs.remove_tree(path)
    fs.remove(path + ".json")


def discard(op: Op, group: Iterable[Step], bundle_id: str | None) -> None:
    """Partial outputs of scratch steps before a redo or an abandon: the stage, the bundle being built, generations
    the steps created, and a bundle an earlier attempt published but never catalogued (its id is this op's)."""
    fs.remove_tree(op.path("stage"))
    fs.remove_tree(op.path("bundle"))
    for s in group:
        if s.type == "CreateGeneration":
            remove_generation(op, s.args["store"], s.args["gen"])
    if bundle_id and not fs.exists(op.layout.catalog(op.name, bundle_id)):
        fs.remove_tree(op.layout.incoming_dir(op.name, bundle_id))
        fs.remove_tree(op.layout.bundle_dir(op.name, bundle_id))


def obtain(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    """Pull (or find a local pinned ID), check labels, write ledger entries."""
    ev: dict[str, dict[str, Any]] = {"images": {}, "refs": {}, "digests": {}, "labels": {}}
    for item in step.args["images"]:
        ref = item["ref"]
        if not ((ref.startswith("sha256:") or "@sha256:" in ref) and op.docker.image(ref)):
            op.docker.pull(t, ref, tick=op.tick)
        img = op.docker.image(ref)
        if img is None:
            raise Failed(f"image {ref} is not present after the pull", code="obtain")
        labels = img["Config"].get("Labels") or {}
        wrong = sorted(k for k, v in item.get("check_labels", {}).items() if labels.get(k) != v)
        if wrong:
            raise Refused(f"image {ref} does not carry the expected {', '.join(wrong)}", code="image-labels")
        repo = ref.split("@")[0]
        repo = repo.rsplit(":", 1)[0] if ":" in repo.rsplit("/", 1)[-1] else repo
        digest = next((d for d in img.get("RepoDigests") or [] if d.split("@")[0] == repo), None)
        doc = records.new_doc(
            "ledger", image=img["Id"], refs=[ref], digest=digest, commit=step.args.get("commit"),
            release=step.args.get("release"), labels=labels, pulled_by={"instance": op.name, "op": op.seq},
            at=records.iso(records.utc_now()),
        )  # fmt: skip
        with contextlib.suppress(FileExistsError):  # one provenance entry per image and operation
            state.write_doc_once(op.layout.ledger(img["Id"].removeprefix("sha256:"), f"{op.name}-{op.seq}"), doc)
        for svc in item["services"]:
            ev["images"][svc], ev["refs"][svc], ev["digests"][svc], ev["labels"][svc] = img["Id"], ref, digest, labels
    return ev


def create_generation(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    """The marker first, then the directory: a directory never exists without its proof. A redo replaces the partial
    directory its own marker proves; a directory without a marker is not this tool's (F8)."""
    a = step.args
    path = op.layout.data_gen(op.name, a["store"], a["gen"])
    if a.get("path", path) != path:
        raise Refused(f"generation path {a['path']} is not {path}", code="internal")
    if fs.exists(path + ".json"):
        if state.read_doc(path + ".json", "generation").get("op") != op.seq:
            raise Refused(f"generation {a['gen']} of store {a['store']} belongs to another operation", code="exists")
        fs.remove_tree(path)  # an interrupted attempt may have left it half made (owner or mode not yet set)
    elif fs.exists(path):
        raise Refused(f"{path} exists without a generation marker", code="not-owned")
    else:
        doc = records.new_doc(
            "generation", instance=op.name, store=a["store"], generation=a["gen"], purpose=a["purpose"], op=op.seq
        )
        state.write_doc_once(path + ".json", doc)
    fs.make_empty_dir(path, a["mode"], (a["owner"][0], a["owner"][1]) if a.get("owner") else None)
    return {"path": path}


def stop(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    a = step.args
    check(op.compose.stop(t, op.project(a["variant"]), a["services"], timeout=a.get("timeout", 120)), "compose stop")
    if not a.get("freeze"):
        return {}
    at = records.iso(records.utc_now())
    return {"freeze_at": at, "values": {"freeze_at": at}}


def isolated(op: Op, variant: str | None) -> Project | None:
    """The project of `variant` when it is this operation's own isolated one (`<i>--t<seq>` or `<i>--r<seq>`)."""
    if not variant or not op.variant(variant).get("isolated"):
        return None
    p = op.project(variant)
    return p if p.name in (f"{op.name}--t{op.seq}", f"{op.name}--r{op.seq}") else None


def down(op: Op, p: Project, t: EffectToken, mine: dict[str, str]) -> None:
    """`down` (never -v) of a whole project, re-proved right before it: every container and network in it carries the
    labels `mine` (F8: nothing foreign is stopped or removed); afterwards nothing carrying them may remain."""
    found = [(c["Name"], c["Config"].get("Labels")) for c in op.docker.containers(project=p.name)]
    found += [(n["Name"], n.get("Labels")) for n in op.docker.networks({PROJECT_LABEL: p.name})]
    if bad := [x.lstrip("/") for x, labels in found if not mine.items() <= (labels or {}).items()]:
        raise Refused(f"project {p.name} holds objects that are not its own: {', '.join(bad)}", code="foreign")
    check(op.compose.down(t, p, timeout=DOWN_TIMEOUT), "compose down")
    left = [c["Name"].lstrip("/") for c in op.docker.containers(mine)] + [n["Name"] for n in op.docker.networks(mine)]
    if left:
        raise Failed(f"objects of {p.name} remain: {', '.join(left)}", code="teardown")


def down_isolated(op: Op, t: EffectToken) -> bool:
    """`down` of this operation's isolated projects that still hold containers (before a redo); whether one did."""
    mine = {brand.label("instance"): op.name, brand.label("op"): str(op.seq)}
    projects = {p.name: p for v in op.plan.inputs.get("variants", {}) if (p := isolated(op, v))}
    held = [p for p in projects.values() if op.docker.containers(project=p.name)]
    for p in held:
        down(op, p, t, mine)
    return bool(held)


def teardown(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    """`down` of this op's isolated project (never -v, never a live project: F13), then its t<seq> generations and
    subnet allocations. Only a selftest run's own instance takes its live project down, at its teardown."""
    v = step.args["variant"]
    own = isolated(op, v)
    p = own or op.project(v)
    live = not own and not op.variant(v).get("isolated") and p.name == op.name and selftest_run(op.layout, op.name)
    if not own and not live:
        raise Refused(f"teardown acts only on this operation's isolated project, not {p.name}", code="not-isolated")
    down(op, p, t, {brand.label("instance"): op.name} | ({} if live else {brand.label("op"): str(op.seq)}))
    for s in op.plan.steps:
        if s.type == "CreateGeneration" and s.args["gen"] == f"t{op.seq}":
            remove_generation(op, s.args["store"], s.args["gen"])
    for path, _ in allocations(op.layout, op.name, op.seq).values():
        fs.remove(path)
    return {}


def delete(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    """Remove one listed item after re-proving it right now (F8)."""
    item = step.args["item"]
    if item["kind"] == "generation":
        _selftest_generation(op, item["store"], item["gen"])
        return {}
    if item["kind"] == "container":
        for c in op.docker.inspect("container", [item["id"]]):
            same = (c["Id"], c["Name"].lstrip("/"), c["Created"]) == (item["id"], item["name"], item["created"])
            labels = c["Config"].get("Labels") or {}  # owned: the instance label and its own Compose project (§7.5)
            project = labels.get(PROJECT_LABEL, "").split("--")[0]
            if not same or labels.get(brand.label("instance")) != op.name or project != op.name:
                raise Refused(f"container {item['name']} is not the one planned for deletion", code="not-owned")
            op.docker.remove_container(t, item["id"])
        return {}
    bid = item["id"]
    if state.read_doc(op.layout.catalog(op.name, bid), "catalog")["bundle_hash"] != item["hash"]:
        raise Refused(f"bundle {bid} changed since planning", code="not-owned")
    rec = op.record()
    for seq in (rec.get("current_deployment"), rec.get("previous_deployment")):
        if (
            seq
            and state.read_doc(op.layout.deployment_json(op.name, seq), "deployment").get("pre_change_bundle") == bid
        ):
            raise Refused(f"bundle {bid} is paired with deployment {seq}", code="pinned")
    path = op.layout.bundle_dir(op.name, bid)
    gone = os.path.join(os.path.dirname(path), ".deleting-" + bid)
    if fs.exists(path):
        if bundle_hash(fs.read(os.path.join(path, SUMS))) != item["hash"]:
            raise Refused(f"bundle {bid} on disk does not match its catalog entry", code="not-owned")
        fs.rename(path, gone)
    fs.remove_tree(gone)
    tomb = op.layout.catalog(op.name, f"{bid}.pruned")
    if not fs.exists(tomb):
        state.write_doc_once(tomb, records.new_doc("tombstone", bundle_id=bid, op=op.seq, at=_now()))
    return {}


def _selftest_generation(op: Op, store: str, gen: str) -> None:
    """A generation of a selftest run's own instance, the current one included, at its teardown: re-proved by the
    instance's selftest marker and the generation's own marker, and mounted by no container (F8). The directory goes
    before its marker, so a redo after a crash finds the proof again; neither left is done."""
    path = op.layout.data_gen(op.name, store, gen)
    if selftest_run(op.layout, op.name) is None:
        raise Refused(f"{op.name} is no selftest instance: its generations are not deleted", code="not-owned")
    if not fs.exists(path + ".json"):
        if fs.exists(path):
            raise Refused(f"{path} exists without a generation marker", code="not-owned")
        return
    doc = state.read_doc(path + ".json", "generation")
    if (doc.get("instance"), doc.get("store"), doc.get("generation")) != (op.name, store, gen):
        raise Refused(f"generation {gen} of store {store} is not this instance's", code="not-owned")
    users = [c["Name"].lstrip("/") for c in op.docker.containers() if path in [m.get("Source") for m in c["Mounts"]]]
    if users:
        raise Refused(f"generation {gen} of store {store} is in use by {', '.join(users)}", code="in-use")
    fs.remove_tree(path)
    fs.remove(path + ".json")


def record(op: Op, step: Step, t: EffectToken) -> dict[str, Any]:
    a, kind, ev = step.args, step.args["kind"], op.evidence
    if kind == "candidate":
        ob = ev[a["obtain_step"]]
        fields = {k: a[k] for k in ("commit", "release", "export", "manifest_sha256")}
        doc = records.new_doc(
            "candidate", **fields, images=ob["images"], refs=ob["refs"], digests=ob["digests"],
            labels_checked=sorted(s for s, x in ob["labels"].items() if x), op=op.seq, created_at=_now(),
        )  # fmt: skip
        once(op.layout.candidates(op.name, a["commit"], ob["refs"]), doc, op.seq)
    elif kind == "deployment":
        _deployment(op, a)
    elif kind == "state":
        op.update(state=a["state"])
    elif kind == "verification":
        _verification(op, a)
    elif kind == "task":
        if a.get("clears_hold") and ev.get(a["step"], {}).get("outcome") == "ok":
            op.update(held_since=None)
    else:
        raise Refused(f"internal: unknown record kind {kind!r}", code="internal")
    return {}


def _deployment(op: Op, a: dict[str, Any]) -> None:
    """A field `from` names takes that step's evidence; every other keeps the plan's value (a config-only change keeps
    the write window and the schema of the deployment it follows)."""
    n, src = a["doc"]["seq"], a.get("from") or {}
    picked = {key: op.evidence.get(src[key], {}).get(field) for key, field in FROM_EVIDENCE.items() if src.get(key)}
    doc = {
        **records.new_doc("deployment"), **dict.fromkeys(FROM_EVIDENCE), **a["doc"], "op": op.seq,
        "created_at": _now(), **picked,
    }  # fmt: skip
    once(op.layout.deployment_json(op.name, n), doc, op.seq)
    snap = op.layout.deployment_snapshot(op.name, n)
    files = {
        brand.MANIFEST_FILE: fs.read(a["manifest_path"]),
        "override.yaml": op.variant(a["variant"])["override"].encode(),
        "compose.env": fs.read(f"{op.vdir}/{a['variant']}.env"),
    }
    for fname, data in files.items():
        with contextlib.suppress(FileExistsError):
            fs.write_once(os.path.join(snap, fname), data)
    rec = op.record()
    cur = rec.get("current_deployment")
    op.update(
        state=a["state"], current_deployment=n,
        previous_deployment=rec.get("previous_deployment") if cur == n else cur,
        generations={**rec.get("generations", {}), **a.get("generations", {})},
    )  # fmt: skip


def _verification(op: Op, a: dict[str, Any], failed: dict[str, Any] | None = None) -> None:
    """One record per operation and level, bound to the catalogued bundle hash; `failed` (the evidence of the step
    that failed) makes it `ok: false`."""
    src, bid = a["bundle_from"], a["bundle_from"]
    if isinstance(src, int):  # the bundle that step verified: its evidence, else its own argument or the capture's
        arg = next((s.args.get("bundle") for s in op.plan.steps if s.n == src), None)
        bid = op.evidence.get(src, {}).get("bundle_id") or arg or op.find("bundle_id").get("bundle_id")
    if failed is not None and not (bid and fs.exists(op.layout.catalog(op.name, bid))):
        return  # nothing was sealed: no bundle hash to bind a record to
    bhash = state.read_doc(op.layout.catalog(op.name, bid), "catalog")["bundle_hash"]
    path = op.layout.verification(op.name, bid)
    lines = heal(path).splitlines()
    if any((d.get("op"), d.get("level")) == (op.seq, a["level"]) for d in map(records.loads, filter(None, lines))):
        return
    shown = failed if failed is not None else {str(n): op.evidence.get(n, {}) for n in a.get("steps_ok", [])}
    ok = failed is None and all(e.get("outcome", "ok") == "ok" for e in shown.values())
    doc = records.new_doc(
        "verification", bundle_id=bid, bundle_hash=bhash, level=a["level"], ok=ok, op=op.seq, at=_now(), evidence=shown
    )
    fs.append_line(path, records.dumps(doc))


def failed_verifications(op: Op, rep: dict[int, dict[str, Any]], n: int) -> None:
    """F10 (LIFECYCLE §5.5): an operation that failed before its verification record appends that level `ok: false`
    for its bundle, with the evidence of step `n` that failed; `status` reads the newest record per level."""
    for s in op.plan.steps:
        if s.type == "Record" and s.args["kind"] == "verification" and rep.get(op.num(s), {}).get("phase") != "done":
            _verification(op, s.args, {str(n): (rep.get(n) or {}).get("evidence") or {}})


def undo(op: Op, step: Step, t: EffectToken) -> None:
    """Reverse one attempted step: remove an unpromoted generation; stop what a live Up started and bring the
    recorded deployment back; restart what a Stop stopped. Other steps have no undo."""
    a = step.args
    if step.type == "CreateGeneration":
        remove_generation(op, a["store"], a["gen"])
    elif step.type in ("Up", "Stop") and a["services"] and not op.variant(a["variant"]).get("isolated"):
        if step.type == "Up":
            check(op.compose.stop(t, op.project(a["variant"]), a["services"], timeout=300), "compose stop")
        back = a["variant"] if step.type == "Stop" else "current"
        if op.record().get("state") == "running" and back in op.plan.inputs["variants"]:
            safe_binds(op, back)
            compose_up(op, t, op.project(back), a["services"], UP_TIMEOUT)


def _now() -> str:
    return records.iso(records.utc_now())
