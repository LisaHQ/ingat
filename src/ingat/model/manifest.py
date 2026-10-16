"""App manifest schema 1 (MANIFEST_SPEC §2-§5): strict parse plus every validation rule that needs no Compose."""

import operator as op
import re
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from ingat.brand import CLI
from ingat.model.bundle import default_naming
from ingat.model.errors import Refused
from ingat.model.records import sha256_hex
from ingat.model.templates import CONTEXTS, TASK_EXTRAS, check, variables
from ingat.model.toml_read import NAME as _ID
from ingat.model.toml_read import REGEX_ERRORS, Table, read_doc

REQUIRES = "requires_" + CLI
PARAM_KINDS = tuple("string template port subnet secrets_dir env_file store task_dir accept_schema image".split())
OUTCOMES = ("ok", "finding", "refused", "failed", "unknown")
_GIT = ("source_kind", "git")
_AnyOf = dict[str, tuple[Any, ...]]
_Holds = dict[str, dict[str, str]]
_NAMING = default_naming()
_ENV = re.compile("[A-Za-z_][A-Za-z0-9_]*")
_SVC = re.compile("[A-Za-z0-9][A-Za-z0-9_.-]*")
_MNT = re.compile("(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)+")  # a container path for `-v src:target`: no ':', ',', '..'
_COMPOSE = ("COMPOSE_", "DOCKER_")  # Compose reads its own settings from the --env-file (ARCHITECTURE §9.5)
_REQ = "required = true takes no default{} (the instance must set it)"  # one meaning: the instance sets the value
_CMP = {">=": op.ge, "<=": op.le, ">": op.gt, "<": op.lt, "==": op.eq, "!=": op.ne}
_LISTS = tuple("deploy.baseline deploy.prechecks deploy.migrate deploy.postchecks backup.steps backup.verify".split())
_LISTS += tuple("restore.steps restore.post restore.checks drill.checks drill.record side_effects.clear_hold".split())
# Task lists whose tasks may use extra template variables (MANIFEST_SPEC §3).
_EXTRA = {"backup.steps": "backup", "backup.verify": "verify", "deploy.migrate": "migrate"}
_EXTRA |= {"restore.steps": "restore", "restore.post": "restore", "restore.checks": "restore"}
# A field's spec `Annotated[type, _k(...)]`: `key` (dotted path, default the field name); `when` = (field, values…)
# reads it only if that earlier field took one of the values; `read`, `conv`, `nest`, else typed-reader options.
_k = dict


def _match(pattern: str, text: str, what: str) -> re.Match[str]:
    if (m := re.fullmatch(pattern, text)) is None:
        raise Refused(f"{text!r} is not {what}", code="invalid-manifest")
    return m


def parse_duration(text: str) -> int:
    m = _match("([0-9]+)([smh])", text, "a duration such as 15s, 2m or 1h")
    return int(m[1]) * {"s": 1, "m": 60, "h": 3600}[m[2]]


def parse_size(text: str) -> int:
    m = _match("([0-9]+)([kmg])", text, "a size such as 1024k, 512m or 2g")
    return int(m[1]) << {"k": 10, "m": 20, "g": 30}[m[2]]


def _mode(text: str) -> int:
    return int(_match("0[0-7]{3}", text, 'a file mode such as "0700"')[0], 8)


def _owner(text: str) -> tuple[int, int]:
    m = _match("([0-9]+):([0-9]+)", text, '"uid:gid"')
    return int(m[1]), int(m[2])


def _exit_map(t: Table, key: str) -> dict[int, str]:
    raw, msg = t.strmap(key), f"must map an exit code 0-255 to one of: {', '.join(OUTCOMES)}"
    good = {k for k, v in raw.items() if re.fullmatch("0|[1-9][0-9]{0,2}", k) and int(k) < 256 and v in OUTCOMES}
    t.errs.extend(f"{t.at(key)}: {k} = {v!r} {msg}" for k, v in raw.items() if k not in good)
    return {int(k): raw[k] for k in good}


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    kind: Annotated[str, _k(default="string", choices=PARAM_KINDS)]
    required: Annotated[bool, _k(when=("kind", "string"))]
    default: Annotated[str | None, _k(when=("kind", "string"))]
    optional: Annotated[bool, _k(when=("kind", "string"))]
    pattern: Annotated[str | None, _k(when=("kind", "string"))]
    value: Annotated[str | None, _k(when=("kind", "template"), req=True)]
    store: Annotated[str | None, _k(when=("kind", "store"), req=True)]
    service: Annotated[str | None, _k(when=("kind", "image"), req=True, rx=_SVC)]


@dataclass(frozen=True, slots=True)
class AppEnvKey:
    name: str
    required: Annotated[bool, _k()]
    default: Annotated[str | None, _k()]
    allowed: Annotated[tuple[str, ...] | None, _k(read=lambda t, k: t.strs(k) if k in t.d else None)]
    pattern: Annotated[str | None, _k()]
    secret: Annotated[bool, _k()]
    owner_gated: Annotated[bool, _k()]
    tool_managed: Annotated[bool, _k()]


@dataclass(frozen=True, slots=True)
class AppEnv:
    param: Annotated[str, _k(req=True)]
    forbidden: Annotated[tuple[str, ...], _k(rx=_ENV)]
    keys: Annotated[dict[str, AppEnvKey], _k(nest=AppEnvKey, how="each", rx=_ENV)]


@dataclass(frozen=True, slots=True)
class Secret:
    name: str
    generate: Annotated[str | None, _k(choices=("alnum32",))]
    mode: Annotated[int, _k(conv=_mode, default=0o400)]


@dataclass(frozen=True, slots=True)
class Store:
    name: str
    kind: Annotated[str, _k(req=True, choices=("volume", "bind"))]
    volume: Annotated[str | None, _k(when=("kind", "volume"), req=True)]
    param: Annotated[str | None, _k(when=("kind", "bind"), req=True)]
    service: Annotated[str | None, _k(rx=_SVC)]
    ready: Annotated[str | None, _k()]
    owner: Annotated[tuple[int, int] | None, _k(when=("kind", "bind"), conv=_owner)]
    mode: Annotated[int | None, _k(when=("kind", "bind"), conv=_mode)]
    local_only: Annotated[bool, _k()]
    online_backup: Annotated[bool, _k()]


@dataclass(frozen=True, slots=True)
class Services:
    data: Annotated[tuple[str, ...], _k(rx=_SVC)]
    writers: Annotated[tuple[str, ...], _k(rx=_SVC)]
    stateless: Annotated[tuple[str, ...], _k(rx=_SVC)]
    log_snapshot: Annotated[tuple[str, ...], _k(rx=_SVC)]


@dataclass(frozen=True, slots=True)
class Schema:
    task: Annotated[str | None, _k()]
    probe: Annotated[str | None, _k()]
    expected: Annotated[str, _k(req=True)]
    actual: Annotated[str, _k(req=True)]
    migrates_on_start: Annotated[bool, _k()]


@dataclass(frozen=True, slots=True)
class HttpSpec:
    port_param: Annotated[str, _k(req=True)]
    path: Annotated[str, _k(req=True, rx=re.compile(r"/\S*"))]
    method: Annotated[str, _k(default="GET", rx=re.compile("[A-Z]+"))]
    headers: Annotated[dict[str, str], _k(rx=_SVC)]
    body: Annotated[str | None, _k()]


@dataclass(frozen=True, slots=True)
class Expect:
    status: Annotated[int | None, _k()]
    json: Annotated[_AnyOf, _k(read=Table.anyof)]
    body_contains: Annotated[str | None, _k()]
    header_equals: Annotated[dict[str, str], _k(rx=_SVC)]
    header_contains: Annotated[dict[str, str], _k(rx=_SVC)]
    exit: Annotated[int | None, _k()]


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    kind: Annotated[str, _k(read=lambda t, _: t.one_of("health", "exec", "http"))]
    service: Annotated[
        str | None, _k(when=("kind", "health", "exec"), read=lambda t, _: t.o("health", default=t.o("exec")))
    ]
    argv: Annotated[tuple[str, ...], _k(when=("kind", "exec"), req=True)]
    http: Annotated[HttpSpec | None, _k(when=("kind", "http"), nest=HttpSpec)]
    expect: Annotated[Expect, _k(nest=Expect)]
    stable: Annotated[int, _k(conv=parse_duration, default=0)]
    interval: Annotated[int, _k(conv=parse_duration, default=2)]
    timeout: Annotated[int, _k(conv=parse_duration, default=60)]


@dataclass(frozen=True, slots=True)
class Smoke:
    name: Annotated[str, _k(req=True, rx=_ID)]
    probe: Annotated[Probe, _k(read=lambda t, _: t.read(Probe, name=str(t.d.get("name")), kind="http"))]


@dataclass(frozen=True, slots=True)
class Activate:
    services: Annotated[tuple[str, ...], _k(rx=_SVC)]
    wait: Annotated[tuple[str, ...], _k()]
    reopens_writes: Annotated[bool, _k()]


@dataclass(frozen=True, slots=True)
class InstallStep:
    kind: Annotated[str, _k(read=lambda t, _: t.one_of("start", "task", "pause"))]
    services: Annotated[tuple[str, ...], _k(key="start", when=("kind", "start"), rx=_SVC)]
    wait: Annotated[tuple[str, ...], _k(when=("kind", "start"))]
    params: Annotated[dict[str, str], _k(when=("kind", "start"), rx=_ENV)]
    log_snapshot: Annotated[bool, _k(when=("kind", "start"), default=True)]
    task: Annotated[str | None, _k(when=("kind", "task"))]
    text: Annotated[str | None, _k(key="pause", when=("kind", "pause"))]
    allow_tasks: Annotated[tuple[str, ...], _k(when=("kind", "pause"))]


@dataclass(frozen=True, slots=True)
class Deploy:
    baseline: Annotated[tuple[str, ...], _k()]
    prechecks: Annotated[tuple[str, ...], _k()]
    migrate: Annotated[str | None, _k()]
    postchecks: Annotated[tuple[str, ...], _k()]


@dataclass(frozen=True, slots=True)
class Backup:
    strategy: Annotated[str, _k(default="none", choices=("tasks", "none"))]
    steps: Annotated[tuple[str, ...], _k()]
    verify: Annotated[tuple[str, ...], _k()]
    payload: Annotated[str | None, _k()]
    naming: Annotated[dict[str, str], _k(read=lambda t, k: {c: t.sub(k).o(c, default=d) for c, d in _NAMING.items()})]


@dataclass(frozen=True, slots=True)
class Restore:
    start: Annotated[tuple[str, ...], _k(rx=_SVC)]
    steps: Annotated[tuple[str, ...], _k()]
    post: Annotated[tuple[str, ...], _k()]
    checks: Annotated[tuple[str, ...], _k()]
    activate: Annotated[bool, _k()]


@dataclass(frozen=True, slots=True)
class Drill:
    checks: Annotated[tuple[str, ...], _k()]
    record: Annotated[tuple[str, ...], _k()]
    activate: Annotated[bool, _k()]
    min_free_memory: Annotated[int, _k(conv=parse_size, default=0)]


@dataclass(frozen=True, slots=True)
class SideEffects:
    kind: Annotated[str, _k(default="none", choices=("none", "outbound"))]
    restore_via_app: Annotated[bool, _k()]
    after_restore: Annotated[str | None, _k(choices=("held",))]
    clear_hold: Annotated[str | None, _k()]
    single_active: Annotated[bool, _k()]
    restore_notice: Annotated[str | None, _k()]


@dataclass(frozen=True, slots=True)
class Task:
    name: str
    service: Annotated[str, _k(req=True, rx=_SVC)]
    mode: Annotated[str, _k(req=True, choices=("run", "exec"))]
    image: Annotated[str, _k(default="current", choices=("current", "candidate", "bundle"))]
    argv: Annotated[tuple[str, ...], _k()]
    env: Annotated[dict[str, str], _k(rx=_ENV)]
    user: Annotated[str | None, _k(rx=re.compile("[0-9]+:[0-9]+"))]
    stdin: Annotated[str | None, _k(rx=re.compile("(file|bundle):.+|terminal"))]
    stdout: Annotated[str | None, _k(rx=re.compile("json|record|terminal|file:.+"))]
    nonempty: Annotated[bool, _k()]
    mounts: Annotated[dict[str, str], _k()]
    effect: Annotated[str, _k(req=True, choices=("read", "app-write", "data"))]
    idempotent: Annotated[bool, _k()]
    observe: Annotated[str | None, _k(choices=("schema",))]
    exit: Annotated[dict[int, str], _k(read=_exit_map)]
    expect: Annotated[_AnyOf | None, _k(read=lambda t, k: t.sub(k).anyof("json") if k in t.d else None)]
    args: Annotated[dict[str, str], _k(rx=_ID)]
    clears_hold: Annotated[bool, _k()]
    operator: Annotated[bool, _k(default=True)]
    max_input_bytes: Annotated[int | None, _k()]
    timeout: Annotated[int, _k(conv=parse_duration, req=True)]


@dataclass(frozen=True, slots=True)
class Manifest:
    manifest: Annotated[int, _k(read=lambda t, k: t.get(k, int, 1, True))]
    app: Annotated[str, _k(req=True, rx=re.compile("[a-z][a-z0-9-]{1,30}"))]
    requires_ingat: Annotated[str, _k(key=REQUIRES, req=True, default=">=0")]  # default: no follow-on error
    exclusive_environments: Annotated[tuple[str, ...], _k(rx=re.compile("[a-z][a-z0-9-]{0,31}"))]
    source_kind: Annotated[str, _k(key="source.kind", req=True, choices=("git", "image"))]
    release: Annotated[str | None, _k(key="source.release", when=_GIT, req=True, choices=("tag", "commit"))]
    tag_pattern: Annotated[str | None, _k(key="source.tag_pattern", when=("release", "tag"), req=True)]
    source_images: Annotated[dict[str, str], _k(key="source.images", when=("source_kind", "image"), rx=_SVC)]
    files: Annotated[tuple[str, ...], _k(key="compose.files")]
    build_files: Annotated[tuple[str, ...], _k(key="compose.build_files", when=_GIT)]
    build_services: Annotated[tuple[str, ...], _k(key="compose.build_services", when=_GIT, rx=_SVC)]
    build_env: Annotated[dict[str, str], _k(key="compose.build_env", when=_GIT, rx=_ENV)]
    expect_labels: Annotated[dict[str, str], _k(key="compose.expect_labels")]
    params: Annotated[dict[str, Param], _k(nest=Param, how="each", rx=_ENV)]
    secrets: Annotated[dict[str, Secret], _k(nest=Secret, how="each")]
    app_env: Annotated[AppEnv | None, _k(nest=AppEnv, how="opt")]
    stores: Annotated[dict[str, Store], _k(nest=Store, how="each")]
    services: Annotated[Services, _k(nest=Services)]
    schema: Annotated[Schema | None, _k(nest=Schema, how="opt")]
    probes: Annotated[dict[str, Probe], _k(nest=Probe, how="each")]
    activate: Annotated[tuple[Activate, ...], _k(nest=Activate, how="list")]
    smoke: Annotated[tuple[Smoke, ...], _k(nest=Smoke, how="list")]
    install: Annotated[tuple[InstallStep, ...], _k(nest=InstallStep, how="list")]
    deploy: Annotated[Deploy, _k(nest=Deploy)]
    backup: Annotated[Backup, _k(nest=Backup)]
    restore: Annotated[Restore, _k(nest=Restore)]
    rollback_env: Annotated[dict[str, str], _k(key="rollback.env", rx=_ENV)]
    drill: Annotated[Drill, _k(nest=Drill)]
    holds: Annotated[_Holds, _k(read=lambda t, k: {s: x.strmap(rx=_ENV) for s, x in t.named(k, _SVC).items()})]
    side_effects: Annotated[SideEffects, _k(nest=SideEffects)]
    tasks: Annotated[dict[str, Task], _k(nest=Task, how="each")]
    raw_sha256: str


def task_outcome(task: Task, exit_code: int) -> str:
    """The exit map; an undeclared 0 is ok, an undeclared non-zero is failed for read and unknown otherwise."""
    if exit_code in task.exit:
        return task.exit[exit_code]
    return "ok" if exit_code == 0 else "failed" if task.effect == "read" else "unknown"


def _satisfies(spec: str, version: str) -> bool | None:
    """Whether `version` (its leading dotted digits) meets a comparator list such as ">=0.1,<1"; None if malformed."""
    v = (*map(int, re.findall("[0-9]+", re.split("[^0-9.]", version, maxsplit=1)[0])), 0, 0, 0, 0)[:4]
    parts = [re.fullmatch(r"\s*(>=|<=|==|!=|>|<)\s*([0-9]+(\.[0-9]+)*)\s*", p) for p in spec.split(",")]
    return all(_CMP[m[1]](v, (*map(int, m[2].split(".")), 0, 0, 0, 0)[:4]) for m in parts if m) if all(parts) else None


def _rel(path: str) -> bool:
    return bool(path) and not path.startswith("/") and ".." not in path.split("/")


def _check(m: Manifest, version: str, errs: list[str]) -> None:
    def bad(cond: object, path: str, msg: str) -> None:
        errs.extend([f"{path}: {msg}"] if cond else [])

    def kind(table: Mapping[str, Any], name: str | None) -> Any:
        return getattr(table.get(name or ""), "kind", None)

    def regex(path: str, pattern: str | None) -> re.Pattern[str] | None:
        try:
            return None if pattern is None else re.compile(pattern)
        except REGEX_ERRORS as e:
            errs.append(f"{path}: invalid regex: {e}")
            return None

    def tpl(path: str, texts: Iterable[str | None], ctx: str | frozenset[str], **names: set[str]) -> None:
        declared = {"param.": set(m.params), **{k + ".": v for k, v in names.items()}}
        allowed = CONTEXTS[ctx] if isinstance(ctx, str) else ctx
        errs.extend(f"{path}: {e}" for x in texts for e in check(x or "", allowed, declared))

    def compose_name(path: str, name: str) -> None:
        bad(name.startswith(_COMPOSE), path, "COMPOSE_* and DOCKER_* names are Compose's own settings")

    sv, data, se, b, keys = m.services, m.services.data, m.side_effects, m.backup, m.app_env.keys if m.app_env else {}
    roles = [*data, *sv.writers, *sv.stateless]
    ok = _satisfies(m.requires_ingat, version)
    bad(not ok, REQUIRES, f"{m.requires_ingat!r} " + ("is malformed" if ok is None else f"excludes version {version}"))
    bad(m.manifest != 1, "manifest", "must be 1")
    bad(m.source_kind == "image" and not m.source_images, "source.images", "is required for an image source")
    bad(not m.files, "compose.files", "must name at least one Compose file")
    bad(any(not _rel(f) for f in m.files + m.build_files), "compose", "files must be relative paths without '..'")
    labels = any("{commit}" in v for v in m.expect_labels.values())
    bad(m.build_services and not labels, "compose.expect_labels", "must bind {commit}: build_services are pulled")
    bad(m.app_env and kind(m.params, m.app_env.param) != "env_file", "app_env.param", "must name an env_file param")
    bad(m.stores and not sv.writers, "services.writers", "is required when stores exist")
    bad(sum(g.reopens_writes for g in m.activate) != bool(sv.writers), "activate", "needs one reopens_writes group")
    if sc := m.schema:
        one = (sc.task is None) != (sc.probe is None) and kind(m.probes, sc.probe) != "health"
        bad(not one, "schema", "needs exactly one of task or probe (an exec or http probe)")
    bad(b.strategy == "tasks" and not b.steps, "backup.steps", 'are required with strategy = "tasks"')
    bad(b.strategy == "none" and (b.steps or b.verify or b.payload), "backup", 'strategy "none" takes no tasks')
    outbound = se.kind == "outbound" and not (m.holds and m.restore.steps and se.restore_via_app)
    bad(outbound, "side_effects.kind", "outbound requires [holds], a restore task and restore_via_app = true")
    regex("source.tag_pattern", m.tag_pattern)
    for svc, name in m.source_images.items():
        bad(getattr(m.params.get(name), "service", None) != svc, f"source.images.{svc}", "must name its image param")
    pats = {k: regex(f"params.{k}.pattern", p.pattern) for k, p in m.params.items()}
    for k, p in m.params.items():
        rx, at = pats[k], f"params.{k}"
        compose_name(at, k)
        bad(p.required and (p.default is not None or p.optional), at, _REQ.format(" or optional = true"))
        bad(rx and p.default is not None and not rx.fullmatch(p.default), f"{at}.default", "does not match the pattern")
        bad(p.store is not None and kind(m.stores, p.store) != "bind", f"{at}.store", "must name a bind store")
        tpl(f"{at}.value", [p.value], "param")
    for k, key in keys.items():
        rx, d = regex(f"app_env.keys.{k}.pattern", key.pattern), key.default
        bad(m.app_env and k in m.app_env.forbidden, f"app_env.keys.{k}", "is a forbidden key")
        req = key.required and (d is not None or key.tool_managed)  # the instance never sets a tool-managed key
        bad(req, f"app_env.keys.{k}", _REQ.format(" or tool_managed = true"))
        wrong = d is not None and (d not in (key.allowed or (d,)) or (rx and not rx.fullmatch(d)))
        bad(wrong, f"app_env.keys.{k}.default", "is not an allowed value")
    errs.extend(f"services: {x!r} has more than one role" for x, n in Counter(roles).items() if n > 1)
    errs.extend(f"smoke: the name {x!r} is used twice" for x, n in Counter(s.name for s in m.smoke).items() if n > 1)
    started = {x for g in m.activate for x in g.services}
    errs.extend(f"activate: no group starts the service {x!r}" for x in roles if x not in started)
    refs: list[tuple[str, Iterable[str | None], Iterable[str], str]] = [
        ("services.log_snapshot", sv.log_snapshot, roles, "service with a role"),
        ("restore.start", m.restore.start, data, "data service"),
        ("rollback.env", m.rollback_env, keys, "app_env key"),
        ("schema.probe", [m.schema.probe if m.schema else None], m.probes, "probe"),
    ]
    for k, s in m.stores.items():
        wrong = s.param is not None and getattr(m.params.get(s.param), "store", None) != k
        bad(wrong, f"stores.{k}.param", f"must name a store param with store = {k!r}")
        bad(s.service and not s.ready, f"stores.{k}.ready", "is required with service")
        bad(kind(m.probes, s.ready) == "http", f"stores.{k}.ready", "must be an exec or health probe (isolated runs)")
        refs += [(f"stores.{k}.service", [s.service], data, "data service")]
        refs += [(f"stores.{k}.ready", [s.ready], m.probes, "probe")]
    for n, g in enumerate(m.activate):
        bad(not g.services, f"activate[{n}].services", "must name at least one service")
        refs += [(f"activate[{n}].services", g.services, roles, "service with a role")]
        refs += [(f"activate[{n}].wait", g.wait, m.probes, "probe")]
    for n, st in enumerate(m.install):
        refs += [(f"install[{n}].start", st.services, roles, "service with a role")]
        refs += [(f"install[{n}].wait", st.wait, m.probes, "probe")]
        for k, v in st.params.items():
            compose_name(f"install[{n}].params.{k}", k)
            match = kind(m.params, k) == "string" and not ((rx := pats[k]) and not rx.fullmatch(v))
            bad(not match, f"install[{n}].params.{k}", "must set a string param to a value matching its pattern")
        tpl(f"install[{n}].pause", [st.text], "text")
    refs += [(f"probes.{k}", [x.service], roles, "service with a role") for k, x in m.probes.items()]
    refs += [(f"tasks.{k}", [t.service], roles, "service with a role") for k, t in m.tasks.items() if t.mode == "exec"]
    errs.extend(f"{p}: names an unknown {what} {x!r}" for p, xs, ys, what in refs for x in xs if x not in (None, *ys))
    probes = [(f"probes.{k}", x) for k, x in m.probes.items()]
    for path, pr in probes + [(f"smoke[{n}]", s.probe) for n, s in enumerate(m.smoke)]:
        e = pr.expect
        http_keys = e.status is not None or e.body_contains is not None or e.header_equals or e.header_contains
        odd = http_keys if pr.kind != "http" else e.exit is not None
        bad(odd or (pr.kind == "health" and e.json), f"{path}.expect", f"has a key a {pr.kind} probe cannot use")
        bad(not (pr.interval and pr.timeout), path, "interval and timeout must be positive")
        bad(pr.http and kind(m.params, pr.http.port_param) != "port", f"{path}.http.port_param", "is not a port param")
        texts = [*pr.argv, *(v for vs in e.json.values() for v in vs if isinstance(v, str)), e.body_contains]
        texts += [*e.header_equals.values(), *e.header_contains.values()]
        tpl(path, texts + ([pr.http.path, *pr.http.headers.values(), pr.http.body] if pr.http else []), "probe")
    tpl("compose", [*m.build_env.values(), *m.expect_labels.values()], "build")
    tpl("backup.payload", [b.payload], "payload")
    for c, text in b.naming.items():  # only a pre-change bundle has a target release
        tpl(f"backup.naming.{c}", [text], CONTEXTS["naming"] - {"target.release"} if c != "pre-change" else "naming")
    tpl("side_effects.restore_notice", [se.restore_notice], "text")
    # Task rules (MANIFEST_SPEC §4): first per list that uses a task, then per task.
    lists: dict[str, Any] = {w: op.attrgetter(w)(m) for w in _LISTS}
    lists |= {"install": [s.task for s in m.install], "schema.task": m.schema.task if m.schema else None}
    lists["install.allow_tasks"] = [x for s in m.install for x in s.allow_tasks]
    uses: dict[str, set[str]] = {k: set() for k in m.tasks}
    for where, names in lists.items():
        for x in (names,) if isinstance(names, str | None) else names:
            if (t := m.tasks.get(x or "")) is None:
                bad(x is not None, where, f"names an unknown task {x!r}")
                continue
            uses[t.name].add(where)
            say, writes = f"task {t.name!r}", t.effect != "read"
            redo = where == "deploy.migrate" or (where == "install" and writes)  # live forward steps (LIFECYCLE §3.3)
            by_exec = writes and t.mode == "exec" and where not in ("restore.steps", "restore.post")
            bad(by_exec, where, f"{say} mutates by exec: only restore.steps and restore.post may use it")
            bad(redo and not (t.idempotent or t.observe), where, f"{say} must be idempotent or declare observe")
            bad(where[:7] == "backup." and writes and not t.idempotent, where, f"{say} must be idempotent (scratch)")
            term = "terminal" in (t.stdin, t.stdout) and where not in ("install.allow_tasks", "side_effects.clear_hold")
            bad(term, where, f"{say} uses the terminal, so it runs only in the foreground CLI")
            reads = where in ("deploy.baseline", "deploy.prechecks", "deploy.postchecks", "schema.task")
            bad(writes and reads, where, f"{say} must have effect read")
            bad(where == "schema.task" and t.stdout not in ("json", "record"), where, f"{say} must print JSON")
    for k, t in m.tasks.items():
        tp, texts = f"tasks.{k}", [*t.argv, *t.env.values(), t.stdin, t.stdout]
        bad(t.effect != "read" and t.mode == "exec" and t.operator, tp, "a mutating exec task needs operator = false")
        bad(t.expect is not None and t.stdout not in ("json", "record"), tp, 'expect needs stdout = "json" or "record"')
        bad(t.nonempty and not (t.stdout or "").startswith("file:"), tp, 'nonempty needs stdout = "file:<path>"')
        bad(t.observe and m.schema is None, tp, 'observe = "schema" needs [schema]')
        bad(t.timeout == 0, f"{tp}.timeout", "must be positive")
        bad(t.mounts and t.mode == "exec", tp, 'mounts need mode = "run"')
        for io in (t.stdin, t.stdout):
            how, _, path = (io or "").partition(":")
            bad(how in ("file", "bundle") and not _rel(path), tp, f"{io!r} must name a relative path without '..'")
        inputs = {x[6:] for x in t.mounts.values() if x[:6] == "input:" and _ID.fullmatch(x[6:])}
        sources = {"stage", "bundle", *(f"generation:{x}" for x in m.stores), *(f"input:{x}" for x in inputs)}
        for target, source in t.mounts.items():
            to_ok = _MNT.fullmatch(target) or kind(m.params, target) in ("task_dir", "store")
            bad(not to_ok or source not in sources, f"{tp}.mounts", f"{target} = {source!r} is not a valid mount")
        for a, pattern in t.args.items():
            regex(f"{tp}.args.{a}", pattern)
        images = {v[6:] for x in texts for v in variables(x or "") if v[:6] == "image."}  # checked against Compose
        extras = [TASK_EXTRAS[_EXTRA[w]] if w in _EXTRA else frozenset() for w in uses[k]]  # at every use
        ctx = CONTEXTS["task"] | (frozenset.intersection(*extras) if extras else frozenset())
        tpl(tp, texts, ctx, image=images, arg=set(t.args), input=inputs)


def parse_manifest(data: bytes, *, tool_version: str) -> Manifest:
    """Strictly parse and validate an app manifest; Refused(code="invalid-manifest") lists every error."""
    try:  # deep nesting: the TOML parser and the reader of nested JSON paths both recurse
        m, errs = read_doc(tomllib.loads(data.decode("utf-8")), Manifest, raw_sha256=sha256_hex(data))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError) as e:
        raise Refused(f"invalid app manifest: {e}", code="invalid-manifest") from e
    _check(m, tool_version, errs)
    if errs:
        raise Refused("invalid app manifest:\n" + "\n".join(errs), code="invalid-manifest")
    return m
