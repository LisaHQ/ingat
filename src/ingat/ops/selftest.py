"""`selftest` (ARCHITECTURE §3.4-§3.6, §10.4). `--offline` checks the fixtures in the image without a daemon (the
install runs it). The full run, in the host executor under the host lock, drives throwaway instances of fx-lite and
fx-web, made from fixture repositories it creates (ADR-0027), through the real planners and executor; then it deletes
everything it made through closed deletion operations and removes its records, each item re-proved as this run's.
`--host` records the result as the certification of this platform build. Gate tier 2 waives the certification only
for the instances whose selftest marker names this run (context.gate, core/steps.selftest_run)."""

import dataclasses
import os
import secrets
from collections.abc import Callable, Iterator
from typing import Any

from ingat import __version__, brand
from ingat.adapters import git, runner
from ingat.adapters.compose import Compose
from ingat.adapters.docker import PROJECT_LABEL, Docker
from ingat.core import approval, executor, steps
from ingat.core.plan import Plan, fingerprint, new_plan
from ingat.model import records, templates
from ingat.model.bundle import ID_RE
from ingat.model.errors import CannotRun, Failed, IngatError, Refused
from ingat.model.manifest import Manifest, parse_manifest
from ingat.ops import backup, deploy
from ingat.ops import context as cx
from ingat.ops import host as hostops
from ingat.ops import instance as instances
from ingat.ops import lifecycle as lc
from ingat.ops import status as st
from ingat.ops.context import Ctx
from ingat.ops.validate import validate
from ingat.policy import compose_policy
from ingat.policy import gate as gates
from ingat.store import fs, state
from ingat.store.locks import Lock

Report = dict[str, Any]
FIXTURES = "/opt/fixtures"  # the fixtures in the tool image (ARCHITECTURE §10.2)
APPS = {"fx-lite": ("lite", "FXLITE_IMAGE"), "fx-web": ("web", "FXWEB_IMAGE")}  # name suffix, the image param
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
AUTHOR = {"NAME": f"{brand.PRODUCT} selftest", "EMAIL": "selftest@example.invalid", "DATE": "2026-01-01T00:00:00Z"}
RUN_MARKER = "run.json"  # in cache/fixtures/<run-id>/, beside the fixture repositories
HOST_WIDE = {"uncertified"}  # a status code of the host, not of an instance: this run is how it clears
HOSTILE: tuple[dict[str, Any], ...] = (  # each alone must be refused (ARCHITECTURE §9.5, §10.3 policy table)
    {"privileged": True},
    {"cap_add": ["SYS_ADMIN"]},
    {"network_mode": "host"},
    {"pid": "host"},
    {"devices": ["/dev/sda:/dev/sda"]},
    {"security_opt": ["seccomp:unconfined"]},
    {"container_name": "fixed"},
    {"volumes": [{"type": "bind", "source": "/var/run/docker.sock", "target": "/s"}]},
    {"volumes": [{"type": "bind", "source": "/etc", "target": "/e"}]},
    {"ports": [{"host_ip": "0.0.0.0", "published": "20000", "target": 80}]},
)


class _Stop(Exception):
    """A check of the full run failed: the rest is skipped; the teardown still runs."""


@dataclasses.dataclass
class _Run:
    id: str
    dir: str  # cache/fixtures/<run-id>
    names: list[str]  # <prefix><n>-lite, <prefix><n>-web
    lines: list[str] = dataclasses.field(default_factory=list)
    plans: list[str] = dataclasses.field(default_factory=list)
    runs: list[str] = dataclasses.field(default_factory=list)
    commits: list[str] = dataclasses.field(default_factory=list)
    urls: list[str] = dataclasses.field(default_factory=list)


def run(ctx: Ctx, *, host: bool, offline: bool, fixtures: str = FIXTURES) -> Report:
    """`selftest [--host | --offline]`: one line per check; exit 0 PASS, 3 FAIL."""
    if offline:
        return _offline(ctx, fixtures)
    cx.require_host(ctx)
    if warnings := cx.gate(ctx, gates.TIER1):  # F14 holds: a tested Engine; only the certification is waived
        raise CannotRun(warnings[0], code="untested-platform")
    if missing := [k for k in gates.BUILD_KEYS if not cx.build_facts(ctx).get(k)]:
        raise CannotRun(f"platform build facts missing: {', '.join(missing)}", code="uncertified")
    image = ctx.docker.image(ctx.image) if ctx.image else None
    if image is None:  # the instances run the tool image by ID: nothing is pulled
        raise CannotRun(f"the tool image {ctx.image or '(unset)'} is not on this daemon", code="no-image")
    command = [brand.CLI, "selftest", *(["--host"] if host else [])]
    with Lock(ctx.layout.host_lock, {"op": "selftest", "command": command, "operator": ctx.operator}):
        t = _start(ctx)
        steps.SELFTEST_RUNS.add(t.id)  # the gate waiver: this process, this run, until its teardown ends
        try:
            _drive(ctx, t, image["Id"], fixtures)
        except _Stop:
            pass
        finally:
            try:
                _teardown(ctx, t)
            finally:
                steps.SELFTEST_RUNS.discard(t.id)
        ctx.now = records.utc_now()
        result, cert = "FAIL" if _failed(t.lines) else "PASS", None
        if host:  # the platform build it names is observed now, as the gate observes it (ADR-0014)
            cert = hostops.certification(ctx, "selftest", result, facts=hostops.facts(ctx), checks=t.lines)
    return _report(t.lines, cert, f"{brand.CLI} status") | {"instances": t.names}


def _failed(lines: list[str]) -> bool:
    return any(x.startswith("FAIL") for x in lines)


def _report(lines: list[str], cert: str | None, nxt: str | None) -> Report:
    bad = _failed(lines)
    tail = f"selftest {'FAIL' if bad else 'PASS'}" + (f": certification {cert}" if cert else "")
    out = {"exit": 3 if bad else 0, "code": "failed" if bad else "ok", "next": nxt if bad else None}
    return out | {"lines": [*lines, tail], "result": "FAIL" if bad else "PASS", "certification": cert}


def _check(lines: list[str], what: str, fn: Callable[..., Any], *args: Any, **kw: Any) -> tuple[bool, Any]:
    """One check: a PASS line, or a FAIL line with the reason (errors name keys and paths, never secret values)."""
    try:
        out = fn(*args, **kw)
    except (IngatError, OSError) as e:
        lines.append(f"FAIL {what}: {e.message if isinstance(e, IngatError) else e}")
        return False, None
    lines.append(f"PASS {what}")
    return True, out


def _must(t: _Run, what: str, fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    ok, out = _check(t.lines, what, fn, *args, **kw)
    if not ok:
        raise _Stop
    return out


# ---------------------------------------------------------------- offline: no daemon, no root


def _offline(ctx: Ctx, fixtures: str) -> Report:
    """The fixture manifests parse and validate, their templates render, their Compose models (rendered client-side
    with sample params, live and isolated) pass the policy, and the policy refuses hostile services."""
    lines: list[str] = []
    for fx in APPS:
        d = os.path.join(fixtures, fx)
        ok, m = _check(lines, f"{fx}: the manifest parses and validates", _manifest, d)
        if ok:  # the next two need the manifest
            _check(lines, f"{fx}: every template renders with sample values", _templates, m)
            _check(lines, f"{fx}: the Compose models, live and isolated, pass the policy", validate, ctx, d)
    _check(lines, f"the Compose policy refuses {len(HOSTILE)} hostile services", _hostile)
    return _report(lines, None, None)


def _manifest(directory: str) -> Manifest:
    return parse_manifest(fs.read(os.path.join(directory, brand.MANIFEST_FILE)), tool_version=__version__)


def _strings(x: Any) -> Iterator[str]:
    if isinstance(x, str):
        yield x
    elif dataclasses.is_dataclass(x) and not isinstance(x, type):
        for f in dataclasses.fields(x):
            yield from _strings(getattr(x, f.name))
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from (*_strings(k), *_strings(v))
    elif isinstance(x, list | tuple):
        for v in x:
            yield from _strings(v)


def _templates(m: Manifest) -> None:
    """Every template of the manifest renders with sample values (MANIFEST_SPEC §3); bundle names render to ids."""
    texts = [s for s in _strings(m) if templates.variables(s)]
    sample = {v: "sample" for s in texts for v in templates.variables(s)}
    sample["bundle.stamp"] = records.stamp(records.utc_now())
    for text in texts:
        templates.render(text, sample)
    for klass, naming in m.backup.naming.items():
        if not ID_RE.fullmatch(bid := templates.render(naming, sample | {"class": klass})):
            raise Refused(f"backup.naming.{klass} renders {bid!r}, which is not a bundle id", code="bundle-id")


def _hostile() -> None:
    pctx = compose_policy.PolicyContext("/sample", (), frozenset(), frozenset({"20000"}), True, brand.LABEL_NS)
    for snippet in HOSTILE:
        if not compose_policy.check({"name": "x", "services": {"x": {"image": "x", **snippet}}}, pctx):
            raise Failed(f"the Compose policy accepts {snippet}", code="policy")


# ---------------------------------------------------------------- the full run


def _data(layout: state.Layout, name: str) -> str:
    return os.path.dirname(os.path.dirname(layout.data_gen(name, "s", "g")))


def _bundles(layout: state.Layout, name: str) -> str:
    return os.path.dirname(layout.bundle_dir(name, "b"))


def _paths(layout: state.Layout, name: str) -> list[str]:
    return [layout.inst(name), _data(layout, name), _bundles(layout, name)]


def _ledger(lay: state.Layout) -> list[str]:
    """Every image ledger entry, `host/images/<id>/<instance>-<seq>.json`."""
    images = os.path.dirname(os.path.dirname(lay.ledger("i", "e")))
    return [os.path.join(images, i, f) for i in fs.listdir(images) for f in fs.listdir(os.path.join(images, i))]


def _owner(path: str) -> str:
    """The instance a ledger entry's name gives."""
    return os.path.basename(path).rsplit("-", 1)[0]


def _start(ctx: Ctx) -> _Run:
    """The run id, the first pair of instance names that nothing on this host carries yet (an instance, data or backup
    directory, a container or network as project or instance label, an allocation or ledger entry), so that all the
    teardown later finds under those names is this run's (F8); and the run's fixture directory with its marker."""
    lay, d = ctx.layout, ctx.docker
    labels = [c["Config"].get("Labels") or {} for c in d.containers()] + [x.get("Labels") or {} for x in d.networks()]
    taken = {x.get(k) for x in labels for k in (PROJECT_LABEL, brand.label("instance"))}
    taken |= {e.get("instance") for e in cx.allocations(ctx).values()} | set(map(_owner, _ledger(lay)))
    n = 1
    while any(x in taken or any(map(fs.exists, _paths(lay, x))) for x in _names(n)):
        n += 1
    t = _Run(secrets.token_hex(8), "", _names(n))
    t.dir = os.path.join(lay.fixtures_dir, t.id)
    fs.mkdirs(t.dir)
    doc = records.new_doc(steps.SELFTEST_KIND, run_id=t.id, instances=t.names, at=records.iso(records.utc_now()))
    state.write_doc_once(os.path.join(t.dir, RUN_MARKER), doc)
    return t


def _names(n: int) -> list[str]:
    return [f"{brand.SELFTEST_PREFIX}{n}-{suffix}" for suffix, _ in APPS.values()]


def _drive(ctx: Ctx, t: _Run, image: str, fixtures: str) -> None:
    """init, prepare and deploy (a first install, resumed at its pause), backup, verify, drill, a config-only update
    and status, per fixture as its manifest allows (LIFECYCLE §4.1-§4.9)."""
    repos = {fx: _must(t, f"{fx}: fixture repository with commits A and B", _repo, t, fixtures, fx) for fx in APPS}
    for name, (fx, (url, a, b, m)) in zip(t.names, repos.items(), strict=True):
        paused = any(s.kind == "pause" for s in m.install)
        _must(t, f"{name}: init at A", _init, ctx, t, name, m, url, APPS[fx][1], image, a)
        _must(t, f"{name}: prepare A", _op, ctx, t, deploy.plan_prepare, name, a)
        what = f"{name}: deploy A, the first install" + (" up to its pause" if paused else "")
        _must(t, what, _op, ctx, t, deploy.plan_deploy, name, a, code="paused" if paused else "completed")
        if paused:  # an operator's step; selftest runs none of the tasks the pause allows
            _must(t, f"{name}: resume the install", _op, ctx, t, lc.plan_resume, name, mode="resume")
        if m.backup.strategy == "tasks":
            _must(t, f"{name}: backup", _op, ctx, t, backup.plan_backup, name, "manual", "selftest", False)
            _must(t, f"{name}: verify the bundle", _op, ctx, t, backup.plan_verify, name, None, True, False)
            _must(t, f"{name}: drill the bundle", _op, ctx, t, backup.plan_verify, name, None, True, True)
        _must(t, f"{name}: prepare B", _op, ctx, t, deploy.plan_prepare, name, b)
        _must(t, f"{name}: deploy B, a config-only update", _op, ctx, t, deploy.plan_deploy, name, b)
        _must(t, f"{name}: status needs no attention", _status, ctx, name)


def _git(repo: str, *args: str) -> str:
    who = {f"GIT_{role}_{k}": v for role in ("AUTHOR", "COMMITTER") for k, v in AUTHOR.items()}
    env = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": repo, **who}
    argv = ["git", "-C", repo, "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false", *args]
    res = runner.run(argv, env=env, timeout=120)
    if res.code != 0:
        raise Failed(f"git {args[0]} failed: {res.err.strip()[-300:]}", code="git")
    return res.out.strip()


def _repo(t: _Run, fixtures: str, fx: str) -> tuple[str, str, str, Manifest]:
    """The fixture tree as a git repository under this run's directory: commit A, then commit B with a config-only
    change of its Compose file; a fixed author, committer and date, and the run id in each message, so the commits
    and their exports are this run's own."""
    src, d = os.path.join(fixtures, fx), os.path.join(t.dir, f"{fx}.git")
    m = _manifest(src)
    fs.copy_tree(src, d)
    t.urls.append(f"file://{d}")
    _git(d, "init", "--quiet", "--template=", "--initial-branch=main")
    for step in ("A", "B"):
        if step == "B":
            compose = os.path.join(d, m.files[0])
            fs.replace_atomic(compose, _config_change(fs.read(compose)), 0o644)
        _git(d, "add", "--all")
        _git(d, "commit", "--quiet", "--message", f"selftest {t.id} {step}")
        t.commits.append(_git(d, "rev-parse", "HEAD"))
    return t.urls[-1], t.commits[-2], t.commits[-1], m


def _config_change(text: bytes) -> bytes:
    """One more environment value in the first `environment:` mapping: the images stay, the config changes."""
    lines = text.decode().splitlines(keepends=True)
    at = next((i for i, x in enumerate(lines[:-1]) if x.strip() == "environment:"), None)
    if at is None:
        raise Failed("the fixture's Compose file has no environment mapping to change", code="fixture")
    pad = lines[at + 1][: len(lines[at + 1]) - len(lines[at + 1].lstrip())]
    return "".join([*lines[: at + 1], f'{pad}SELFTEST_UPDATE: "B"\n', *lines[at + 1 :]]).encode()


def _init(ctx: Ctx, t: _Run, name: str, m: Manifest, repo: str, param: str, image: str, ref: str) -> None:
    """`init` of a disposable instance from this run's repository (ports allocated), then its selftest marker,
    written under the host lock before any operation of the instance (core/steps.selftest_run)."""
    lines = ["instance = 1", f'name = "{name}"', f'app = "{m.app}"', 'environment = "selftest"', "disposable = true"]
    lines += ["[source]", f'repo = "{repo}"', "[params]", f'{param} = "{image}"']
    if m.app_env:
        lines += ["[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items() if k in m.app_env.keys)]
    instances.create(ctx, name, ("\n".join(lines) + "\n").encode(), ref)
    doc = records.new_doc(steps.SELFTEST_KIND, run_id=t.id, instance=name, at=records.iso(records.utc_now()))
    state.write_doc_once(ctx.layout.inst(name, steps.SELFTEST_MARKER), doc)


def _op(ctx: Ctx, t: _Run, planner: Callable[..., Any], *args: Any, code: str = "completed", mode: str = "") -> None:
    """Plan as the CLI does, save the plan and run it in this process as `_exec` would; the run must end `code`.
    Inside selftest no plan waits for typed approval (LIFECYCLE §2)."""
    ctx.now = records.utc_now()
    plan = planner(ctx, *args)
    if not isinstance(plan, Plan):
        raise Failed("nothing was planned", code="selftest")
    t.plans.append(approval.save(ctx.layout, plan))
    t.runs.append(run_id := secrets.token_hex(8))
    lay = ctx.layout  # fresh adapters: the executor sets its redactor on them
    docker, compose = Docker(config_dir=lay.docker_config), Compose(lay.docker_config)
    executor.execute(lay, docker, compose, plan.hash, run_id, resume=mode == "resume", abandon=mode == "abandon")
    doc = state.read_doc(lay.run(run_id), "run")
    if doc["code"] != code:
        raise Failed(f"{plan.op_kind} ended {doc['code']} (exit {doc['exit']}): {doc['message']}", code="selftest")


def _status(ctx: Ctx, name: str) -> None:
    ctx.now = records.utc_now()
    if codes := sorted(set(st.status(ctx, name)["attention"]) - HOST_WIDE):
        raise Failed(f"status needs attention: {', '.join(codes)}", code="attention")


# ---------------------------------------------------------------- teardown: the closed deletion path


def _teardown(ctx: Ctx, t: _Run) -> None:
    """Per instance: close an open operation, run its deletion operation, remove its records; then the run's own
    files. Each item is re-proved as this run's; what cannot be proved or removed stays, and the run fails."""
    gone = [name for name in t.names if _check(t.lines, f"{name}: teardown", _remove, ctx, t, name)[0]]
    _check(t.lines, "the run's plans, run files, clones, exports and repositories removed", _files, ctx, t, gone)
    _check(t.lines, "nothing of the run remains", _left, ctx, t)


def _remove(ctx: Ctx, t: _Run, name: str) -> None:
    lay = ctx.layout
    if not fs.exists(lay.inst(name)):  # never initialized
        return
    if steps.selftest_run(lay, name) != t.id:
        raise Refused(f"{name} carries no marker of run {t.id}: it is left as it is", code="not-owned")
    if state.open_ops(lay, name):
        _op(ctx, t, lc.plan_abandon, name, code="abandoned", mode="abandon")
    _op(ctx, t, _deletions, name)
    _records(ctx, t, name)


def _deletions(ctx: Ctx, name: str) -> Plan:
    """The closed deletion operation of a selftest instance: its live project down (never -v), every generation its
    markers prove, every catalogued bundle; each step re-proves its item (core/steps.py)."""
    ld, lay = cx.load(ctx, name), ctx.layout
    variants: dict[str, Any] = {}
    todo: list[dict[str, Any]] = []
    if (v := _live(ctx, ld)) is not None:
        deploy.foreign(ctx, name)  # `down` acts on the whole project: nothing foreign may be in it (F8)
        variants["current"] = v
        todo.append({"type": "Teardown", "klass": "forward", "args": {"variant": "current"}})
    for store in fs.listdir(data := _data(lay, name)):
        for gen in (f[:-5] for f in fs.listdir(os.path.join(data, store)) if f.endswith(".json")):
            item = {"kind": "generation", "store": store, "gen": gen}
            todo.append({"type": "Delete", "klass": "forward", "args": {"item": item}})
    cat = backup.catalogued(lay, name)
    for bid, entry in sorted(cat.items()):
        item = {"kind": "bundle", "id": bid, "hash": entry["bundle_hash"]}
        todo.append({"type": "Delete", "klass": "forward", "args": {"item": item}})
    seq = state.next_seq(lay, name)
    inputs = {"seq": seq, "op_dir": lay.op_dir(name, seq, "teardown"), "variants": variants, "app_env": None}
    # no writers: a failed teardown stops nothing, since `stop` would act on a foreign container in the project too
    inputs |= {"files": {}, "throwaway_secrets": {}, "redact_files": [], "writers": []}
    fp = fingerprint(lay, ctx.docker, name, sorted(cat))
    return new_plan("teardown", name, "B", [brand.CLI, "selftest", "teardown", name], fp, inputs, todo)


def _live(ctx: Ctx, ld: cx.Loaded) -> dict[str, Any] | None:
    """A variant of the live project for `down`: the recorded deployment's, else the newest deploy operation's
    candidate (an install that never completed); None when no deploy ever ran."""
    if ld.deployment is not None:
        return cx.current(ctx, ld)[0]
    folder = ctx.layout.ops_dir(ld.name)
    found = sorted((int(d.split("-")[0]), d) for d in fs.listdir(folder) if d.endswith("-deploy"))
    if not found:
        return None
    plan = state.read_doc(os.path.join(folder, found[-1][1], "plan.json"), "plan")
    variant: dict[str, Any] = plan["inputs"]["variants"]["candidate"]
    return variant


def _records(ctx: Ctx, t: _Run, name: str) -> None:
    """What the instance left outside Docker once its deletion operation closed, under its lock and re-proved: empty
    data and backup folders, its allocation and image ledger entries (never a ledger folder, which other instances
    write into without a lock); the instance tree, with the marker that proves it, goes last."""
    lay = ctx.layout
    with Lock(lay.lock(name), {"op": "selftest", "command": [brand.CLI, "selftest"], "operator": ctx.operator}):
        if steps.selftest_run(lay, name) != t.id or state.open_ops(lay, name):
            raise Refused(f"{name} changed during its teardown: it is left as it is", code="not-owned")
        for store in fs.listdir(data := _data(lay, name)):
            if not fs.listdir(path := os.path.join(data, store)):
                fs.remove_tree(path)
        for folder in (data, _bundles(lay, name)):
            if left := fs.listdir(folder):
                raise Failed(f"{folder} still holds {', '.join(left)}", code="left")
            fs.remove_tree(folder)
        for (kind, value), entry in cx.allocations(ctx).items():
            if entry.get("instance") == name:
                fs.remove(lay.allocation(kind, value))
        for path in _ledger(lay):
            if _owner(path) == name and state.read_doc(path, "ledger")["pulled_by"].get("instance") == name:
                fs.remove(path)
        fs.remove_tree(lay.inst(name))


def _files(ctx: Ctx, t: _Run, gone: list[str]) -> None:
    """The run's run files, and the plans of the instances removed; once every instance is gone, the clones and
    exports of its commits and the fixture repositories (their marker re-read first)."""
    lay = ctx.layout
    for plan_hash in t.plans:
        if fs.exists(path := lay.plan(plan_hash)) and state.read_doc(path, "plan").get("instance") in gone:
            fs.remove(path)
    for run_id in t.runs:
        fs.remove(lay.run(run_id))
    if gone != t.names:  # the records of an instance left behind name them
        raise Failed("the clones, exports and repositories stay while an instance of the run remains", code="left")
    for url in t.urls:
        fs.remove_tree(lay.cache_git(git.repo_id(url)))
    for commit in t.commits:
        fs.remove_tree(export := lay.cache_src(commit))
        for suffix in (".lock", ".lock.holder.json"):
            fs.remove(os.path.join(os.path.dirname(export), f".{commit}{suffix}"))
    if state.read_doc(os.path.join(t.dir, RUN_MARKER), steps.SELFTEST_KIND).get("run_id") != t.id:
        raise Refused(f"{t.dir} is not this run's", code="not-owned")
    fs.remove_tree(t.dir)


def _left(ctx: Ctx, t: _Run) -> None:
    """No container, network or volume of the run's instances or their projects, no instance, data or backup
    directory, allocation or ledger entry of them; no clone, export or fixture directory of the run."""
    d, lay, found = ctx.docker, ctx.layout, list[str]()
    for name in t.names:
        mine, project = {brand.label("instance"): name}, {PROJECT_LABEL: name}
        found += [c["Name"].lstrip("/") for c in [*d.containers(mine), *d.containers(project=name)]]
        found += [x["Name"] for x in [*d.networks(mine), *d.networks(project), *d.volumes(mine), *d.volumes(project)]]
        found += [p for p in _paths(lay, name) if fs.exists(p)] + [p for p in _ledger(lay) if _owner(p) == name]
        found += [f"allocation {k} {v}" for (k, v), e in cx.allocations(ctx).items() if e.get("instance") == name]
    run = [t.dir, *(lay.cache_git(git.repo_id(u)) for u in t.urls), *map(lay.cache_src, t.commits)]
    if found := sorted(set(found)) + [p for p in run if fs.exists(p)]:
        raise Failed(f"left behind: {', '.join(found)}", code="left")
