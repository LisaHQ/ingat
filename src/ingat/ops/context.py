"""The shared planning context (ARCHITECTURE §5.3, §6, §9): read-only observation and the concrete data plans carry.
Planning writes only the content-addressed caches (`cache/git`, `cache/src`) and temporary files under /dev/shm,
which it removes again: never anything under `instances/` and never a Docker object."""

import contextlib
import functools
import os
import re
import socket
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ingat import __version__, brand
from ingat.adapters import git, override
from ingat.adapters.compose import Compose, Project
from ingat.adapters.docker import Docker
from ingat.core.steps import in_selftest
from ingat.model import records, templates
from ingat.model.errors import CannotRun, Refused
from ingat.model.instance import NAME_RE, Instance, parse_instance, validate_against
from ingat.model.manifest import Manifest, Probe, parse_manifest
from ingat.policy import compose_policy, compose_text
from ingat.policy import gate as gates
from ingat.store import fs, state
from ingat.store.locks import Lock

GIB = 1 << 30
PORTS = range(20000, 30000)  # where `init` allocates port params the instance leaves open
SHM = "/dev/shm"
CONFIG_HASH = "com.docker.compose.config-hash"
SERVICE = "com.docker.compose.service"
PATH_KINDS = ("store", "task_dir", "secrets_dir", "env_file")  # params whose values are tool-owned bind paths
RELEASE_FILES = ("etc/os-release", "etc.defaults/VERSION")  # mounted read-only under /run/host by the wrapper
# Release and build keys only, as facts.sh keeps them: never a device model or another identity of the unit.
RELEASE_KEY = re.compile(
    r"NAME|ID|ID_LIKE|PRETTY_NAME|VARIANT_ID|major|minor|micro|nano|smallfixnumber|os_name|.*(?i:version|build).*"
)
_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)='([^'\n]*)'$", re.M)
_ALLOCATION = re.compile(r"(port|subnet)-(.+)\.json")


@dataclass
class Ctx:
    layout: state.Layout
    docker: Docker
    compose: Compose
    image: str  # the tool image an executor runs (INGAT_IMAGE)
    operator: str
    hostname: str
    tty: bool = False
    now: datetime = field(default_factory=records.utc_now)

    @functools.cached_property
    def info(self) -> dict[str, Any]:
        return self.docker.info()

    @functools.cached_property
    def version(self) -> dict[str, Any]:
        return self.docker.version()


def _env(environ: Mapping[str, str], key: str, default: str) -> str:
    return environ.get(brand.env(key)) or default


def make_ctx(environ: Mapping[str, str], *, tty: bool = False) -> Ctx:
    """The roots and identity the wrapper passes; Docker runs with the tool's own client config, which must be empty
    (a client config can add proxy variables to every container or run credential helpers). `host init` creates it."""
    layout = state.Layout(_env(environ, "ROOT", brand.DEFAULT_ROOT), _env(environ, "BACKUPS", brand.DEFAULT_BACKUPS))
    if fs.listdir(layout.docker_config):
        raise CannotRun(f"{layout.docker_config} must be an empty directory", code="docker-config")
    docker, compose = Docker(config_dir=layout.docker_config), Compose(layout.docker_config)
    hostname = _env(environ, "HOST", "") or socket.gethostname()
    return Ctx(layout, docker, compose, _env(environ, "IMAGE", ""), _env(environ, "OPERATOR", "root"), hostname, tty)


def require_host(ctx: Ctx) -> dict[str, Any]:
    """host.json, on the daemon whose engine ID it records (F1)."""
    try:
        host = state.read_doc(ctx.layout.host_json, "host")
    except FileNotFoundError:
        raise CannotRun("this host is not initialized", code="no-host", next=f"{brand.CLI} host init") from None
    if ctx.info.get("ID") != host.get("engine_id"):
        raise CannotRun("the Docker engine ID differs from the one host.json records", code="engine-mismatch")
    return host


@dataclass(frozen=True)
class Loaded:
    name: str
    inst: Instance
    record: dict[str, Any]
    deployment: dict[str, Any] | None  # the current deployment record
    manifest: Manifest | None  # the current deployment's manifest snapshot


def load(ctx: Ctx, name: str) -> Loaded:
    if not NAME_RE.fullmatch(name):
        raise CannotRun(f"{name!r} is not an instance name", code="usage")
    try:
        record = state.read_doc(ctx.layout.record_json(name), "instance")
    except FileNotFoundError:
        raise Refused(f"there is no instance {name}", code="unknown-instance") from None
    inst = parse_instance(fs.read(ctx.layout.inst_toml(name)))
    if inst.name != name or inst.disposable != record.get("disposable"):
        raise Refused("instance.toml: name and disposable must stay as initialized", code="invalid-instance")
    dep = m = None
    if (seq := record.get("current_deployment")) is not None:
        dep = state.read_doc(ctx.layout.deployment_json(name, seq), "deployment")
        snapshot = os.path.join(ctx.layout.deployment_snapshot(name, seq), brand.MANIFEST_FILE)
        m = parse_manifest(fs.read(snapshot), tool_version=__version__)
    return Loaded(name, inst, record, dep, m)


@dataclass(frozen=True)
class Source:
    commit: str
    release: str
    export: str  # cache/src/<commit>: the read-only Compose project directory
    manifest: Manifest


def source(ctx: Ctx, ld: Loaded, ref: str) -> Source:
    """Fetch, resolve `ref` once, read and validate the manifest at that commit, export it (LIFECYCLE §4.2)."""
    inst, layout = ld.inst, ctx.layout
    if inst.source_kind != "git" or inst.repo is None:
        raise Refused("image-sourced apps arrive in M2", code="not-in-this-release")
    if inst.accept is not None and not re.fullmatch(inst.accept, ref):
        raise Refused(f"ref {ref!r} does not match the instance's source.accept", code="ref-not-accepted")
    if inst.repo.startswith("file:") and not inst.repo[7:].startswith(layout.fixtures_dir + "/"):
        raise Refused(f"a file:// repository must lie under {layout.fixtures_dir}/ (ADR-0027)", code="invalid-instance")
    bare = layout.cache_git(git.repo_id(inst.repo))
    git.fetch(bare, inst.repo, key_dir=layout.keys_dir(inst.key) if inst.key else None)
    commit = git.resolve(bare, ref)
    m = parse_manifest(data := git.show(bare, commit, inst.manifest_path), tool_version=__version__)
    if errors := validate_against(inst, m):
        raise Refused("instance.toml does not fit the manifest:\n" + "\n".join(errors), code="invalid-instance")
    release = commit
    if m.release == "tag":
        if not re.fullmatch(m.tag_pattern or "", ref) or ref not in git.tag_of(bare, commit):
            raise Refused(f"{ref!r} is not a release tag matching source.tag_pattern", code="not-a-release")
        release = ref
    path = os.path.join(export := _export(ctx, bare, commit), inst.manifest_path)
    if not fs.exists(path) or fs.read(path) != data:  # deployments snapshot the exported bytes (F4)
        raise Refused(f"{inst.manifest_path} differs in the export (gitattributes)", code="unsupported-source")
    if errors := compose_files(export, m):  # before any Compose call reads them
        raise Refused("the Compose files are refused:\n" + "\n".join(errors), code="unsupported-source")
    return Source(commit, release, export, m)


def compose_files(directory: str, m: Manifest) -> list[str]:
    """The raw-text rules over the app's Compose files, runtime and build ones (`include`, `extends` files)."""
    paths = [(f, os.path.join(directory, f)) for f in dict.fromkeys((*m.files, *m.build_files))]
    return [e for f, p in paths if fs.exists(p) for e in compose_text.errors(f, fs.read(p))]


def _export(ctx: Ctx, bare: str, commit: str) -> str:
    """cache/src/<commit>: extracted into a temporary sibling under a per-commit lock, made read-only, renamed in."""
    dest = ctx.layout.cache_src(commit)
    parent = os.path.dirname(dest)
    if fs.exists(dest):
        return dest
    with Lock(os.path.join(parent, f".{commit}.lock"), {"op": "export", "operator": ctx.operator}):
        if fs.exists(dest):  # published by the planner that held the lock
            return dest
        for name in fs.listdir(parent):
            if name.startswith(f".{commit}.tmp-"):  # its planner died: it no longer holds the lock
                fs.remove_tree(os.path.join(parent, name))
        tmp = os.path.join(parent, f".{commit}.tmp-{os.urandom(6).hex()}")
        fs.make_empty_dir(tmp, 0o700)
        try:
            git.archive(bare, commit, tmp)
            fs.chmod_tree(tmp, 0o555, 0o444)
            fs.rename(tmp, dest)
        except BaseException:
            fs.remove_tree(tmp)
            raise
    return dest


def supported(m: Manifest) -> None:
    """Refuse what this release parses but cannot run yet (M2 and later)."""
    t, d, sv = m.tasks.values(), m.deploy, m.services
    used = {"image sources": m.source_kind == "image", "data services": bool(sv.data)}
    used["log_snapshot"] = bool(sv.log_snapshot)
    used["volume stores"] = any(s.kind == "volume" for s in m.stores.values())
    used["deploy prechecks, postchecks and baseline"] = bool(d.baseline or d.prechecks or d.postchecks)
    used["exec tasks"] = any(x.mode == "exec" for x in t)
    used["file and bundle streams"] = any(":" in f"{x.stdin}{x.stdout}" for x in t)
    if names := [k for k, v in used.items() if v]:
        raise Refused(f"this release cannot run {', '.join(names)} yet", code="not-in-this-release")


def exclusive(ctx: Ctx, ld: Loaded, m: Manifest) -> None:
    """`exclusive_environments` (LIFECYCLE §4.3): such an instance runs only while no other one of its app exists."""
    if ld.inst.environment not in m.exclusive_environments:
        return
    layout = ctx.layout
    others = [n for n in state.list_instances(layout) if n != ld.name]
    if same := [n for n in others if state.read_doc(layout.record_json(n), "instance").get("app") == m.app]:
        raise Refused(f"environment {ld.inst.environment} is exclusive, but {', '.join(same)} exist", code="exclusive")


def env_text(env: Mapping[str, str]) -> bytes:
    """KEY='value' lines (Compose reads single-quoted values literally); ', a line break or NUL is refused."""
    if bad := [k for k, v in env.items() if set(v) & set("'\n\r\0")]:
        raise Refused(f"the values of {', '.join(bad)} contain ', a line break or NUL", code="invalid-value")
    return "".join(f"{k}='{v}'\n" for k, v in env.items()).encode()


def env_values(data: bytes) -> dict[str, str]:
    """The KEY='value' lines of a file env_text wrote."""
    return dict(_ENV_LINE.findall(data.decode()))


def values(ctx: Ctx, ld: Loaded, release: str, commit: str) -> dict[str, str]:
    """Template values every invocation of this image set has (MANIFEST_SPEC §3)."""
    base = {"instance": ld.name, "environment": ld.inst.environment, "host": ctx.hostname, "operator": ctx.operator}
    return base | {"release": release, "commit": commit}


def params(
    m: Manifest, layout: state.Layout, name: str, given: Any, tv: Any, gens: Any, app_env: str
) -> dict[str, str]:
    """The Compose env of one invocation: `given` values (instance params, allocations, overrides), defaults and
    tool-owned paths (`gens`: store -> generation number), then `template` params rendered with `tv`."""
    paths = {"secrets_dir": layout.secrets_dir(name), "env_file": app_env, "task_dir": layout.placeholder(name)}
    out: dict[str, str] = {}
    for k, p in m.params.items():
        if k in given:
            out[k] = given[k]
        elif p.kind == "store" and p.store:
            out[k] = layout.data_gen(name, p.store, f"g{gens.get(p.store, 1)}")
        elif p.kind in paths:
            out[k] = paths[p.kind]
        elif p.kind == "accept_schema":
            out[k] = ""
        elif p.kind == "string" and p.default is not None:
            out[k] = p.default
        elif p.kind in ("port", "subnet", "image"):
            raise Refused(f"params.{k}: no {p.kind} value", code="invalid-instance")
    for k, p in m.params.items():
        if p.kind == "template" and p.value is not None:
            out[k] = templates.render(p.value, {**tv, **{f"param.{x}": v for x, v in out.items()}})
    return out


def allocations(ctx: Ctx) -> dict[tuple[str, str], dict[str, Any]]:
    folder = ctx.layout.allocations_dir
    found = [(m, f) for f in fs.listdir(folder) if (m := _ALLOCATION.fullmatch(f))]
    return {(m[1], m[2].replace("_", "/")): state.read_doc(os.path.join(folder, f), "allocation") for m, f in found}


def live_env(ctx: Ctx, ld: Loaded, m: Manifest, release: str, commit: str, app_env: str, over: Any = None) -> Any:
    """The live Compose env: ports from the instance or its allocation entries, subnets from the instance (M1)."""
    given, entries = {**ld.inst.params, **(over or {})}, allocations(ctx)
    for k, p in m.params.items():
        if p.kind == "subnet" and k not in given:
            raise Refused(f"params.{k}: set the live subnet in instance.toml", code="not-in-this-release")
        if p.kind == "port" and k in given:
            if (e := entries.get(("port", given[k]))) and e.get("instance") != ld.name:
                raise Refused(f"params.{k}: port {given[k]} is allocated to {e.get('instance')}", code="port-conflict")
        elif p.kind == "port":
            mine = ("port", ld.name, k)
            own = [v for (kind, v), e in entries.items() if (kind, e.get("instance"), e.get("param")) == mine]
            if not own:
                raise Refused(f"params.{k}: no port is allocated to {ld.name}", code="no-allocation")
            given[k] = own[0]
    if ports := [k for k, p in m.params.items() if p.kind == "port"]:  # a bound port would fail the Up mid-operation
        used = published(ctx, but=ld.name)
        for x in (k for k in ports if given[k] in used):
            raise Refused(f"params.{x}: another container publishes port {given[x]}", code="port-conflict")
    gens = ld.record.get("generations") or {}
    return params(m, ctx.layout, ld.name, given, values(ctx, ld, release, commit), gens, app_env)


def published(ctx: Ctx, but: str | None = None) -> set[str]:
    """Host ports the daemon's containers publish, stopped ones included; those of instance `but` left out."""
    out: set[str] = set()
    for c in ctx.docker.containers():
        if but is None or (c["Config"].get("Labels") or {}).get(brand.label("instance")) != but:
            out |= {b.get("HostPort") for bs in (c["HostConfig"].get("PortBindings") or {}).values() for b in bs or ()}
    return out


def allocate_ports(ctx: Ctx, name: str, m: Manifest, inst: Instance) -> dict[str, str]:
    """Port values for `init` to record: the instance's own, else the first free one in PORTS; each unique against
    every port published on the daemon and every entry but `name`'s own, which only an interrupted `init` leaves."""
    used = {v for (kind, v), e in allocations(ctx).items() if kind == "port" and e.get("instance") != name}
    used |= published(ctx)
    ports = [k for k, p in m.params.items() if p.kind == "port"]
    out = {k: inst.params[k] for k in ports if k in inst.params}
    if taken := [k for k, v in out.items() if v in used or list(out.values()).count(v) > 1]:
        raise Refused(f"params.{taken[0]}: port {out[taken[0]]} is already in use", code="port-conflict")
    free = (str(n) for n in PORTS if str(n) not in used | set(out.values()))
    for k in ports:
        if k not in out:
            if (n := next(free, None)) is None:
                raise Refused(f"no free port in {PORTS.start}-{PORTS.stop - 1}", code="port-conflict")
            out[k] = n
    return out


def app_env(ctx: Ctx, ld: Loaded, m: Manifest, *, isolated: bool = False) -> tuple[dict[str, Any] | None, bytes]:
    """(`inputs.app_env`: values inline, secrets as file references; None without an env_file param, full content
    with secrets for config hashes only, never for a plan). Isolated runs drop secret and owner-gated keys."""
    if not any(p.kind == "env_file" for p in m.params.values()):
        return None, b""
    lines: list[list[Any]] = []
    rendered = dict[str, str]()
    for key, k in m.app_env.keys.items() if m.app_env else ():
        if k.tool_managed or (isolated and (k.secret or k.owner_gated)):
            continue
        if not k.secret:
            if (value := ld.inst.app_env.get(key, k.default)) is not None:
                lines.append([key, {"value": value}])
                rendered[key] = value
            continue
        path = os.path.join(ctx.layout.secrets_dir(ld.name), "env", key)
        if not fs.exists(path):
            if k.required:
                raise Refused(f"app_env.{key}: the secret is not set", code="missing-secret")
            continue
        try:
            rendered[key] = fs.read(path).decode()
        except UnicodeDecodeError as e:
            raise Refused(f"app_env.{key}: the secret file is not UTF-8", code="invalid-value") from e
        if not rendered[key]:  # ARCHITECTURE §9.4: a regular, non-empty file
            raise Refused(f"app_env.{key}: the secret file is empty", code="missing-secret")
        lines.append([key, {"secret_file": path}])
    content = env_text(rendered)
    sha = records.sha256_hex(content)
    return {"path": os.path.join(ctx.layout.env_dir(ld.name), f"{sha}.env"), "sha256": sha, "lines": lines}, content


@contextlib.contextmanager
def _scratch() -> Iterator[str]:
    """A private temporary directory under /dev/shm, never under the tool roots; removed on exit."""
    path = os.path.join(SHM, f"{brand.CLI}-plan-{os.urandom(8).hex()}")
    fs.make_empty_dir(path, 0o700)
    try:
        yield path
    finally:
        fs.remove_tree(path)


@contextlib.contextmanager
def project(
    name: str, directory: str, files: Sequence[str], env: Mapping[str, str], ovr: str | None = None, **kw: Any
) -> Iterator[Project]:
    """A Compose project whose env file, override and (`app_env`: env_file params, content) app env file are
    temporary files; Compose reads the app env content only for config hashes, never for the model. `profiles`
    defaults to every profile."""
    with _scratch() as tmp:
        env, ovr_file = dict(env), None
        if (app_env := kw.get("app_env")) is not None:
            fs.write_once(os.path.join(tmp, "app.env"), app_env[1])
            env |= dict.fromkeys(app_env[0], os.path.join(tmp, "app.env"))
        fs.write_once(env_file := os.path.join(tmp, "compose.env"), env_text(env))
        if ovr is not None:
            fs.write_once(ovr_file := os.path.join(tmp, "override.yaml"), ovr.encode())
        yield Project(name, directory, tuple(files), ovr_file, env_file, kw.get("profiles", ("*",)))


def config(ctx: Ctx, name: str, directory: str, files: Sequence[str], env: Any, ovr: str | None = None) -> Any:
    """The merged model with every Compose profile (`config --no-env-resolution`: no env file content in it)."""
    with project(name, directory, files, env, ovr) as p:
        return ctx.compose.config(p)


def model_errors(m: Manifest, app: Mapping[str, Any], env: Mapping[str, str]) -> list[str]:
    """MANIFEST_SPEC §6.2 rules that need the app's own model (rendered with every profile, no override)."""
    services: dict[str, Any] = app.get("services") or {}
    long_running = {s for s, x in services.items() if not x.get("profiles")}
    roles = {*m.services.data, *m.services.writers, *m.services.stateless}
    errs = [f"services.{s}: a long-running service needs one role" for s in sorted(long_running - roles)]
    errs += [f"services: {s!r} has a role but is no long-running Compose service" for s in sorted(roles - long_running)]
    errs += [f"tasks.{k}.service: unknown {t.service}" for k, t in m.tasks.items() if t.service not in services]
    errs += [f"compose.build_services: unknown {s}" for s in m.build_services if s not in services]  # labels unchecked
    sources = {v.get("source") for x in services.values() for v in x.get("volumes") or () if v.get("type") == "bind"}
    stores = [k for k, s in m.stores.items() if s.param and env.get(s.param) not in sources]
    errs += [f"stores.{k}.param: the store's directory is not a bind source" for k in stores]
    sdir = next((env[k] for k, p in m.params.items() if p.kind == "secrets_dir" and k in env), None)
    for k, x in (app.get("secrets") or {}).items():
        if "file" in x and (os.path.dirname(x["file"]) != sdir or os.path.basename(x["file"]) not in m.secrets):
            errs.append(f"secrets.{k}: the file must be a [secrets.*] file in the secrets_dir param")
    return errs


def policy_errors(
    m: Manifest, model: Any, spec: Any, env: Mapping[str, str], export: str, cpu_cfs: bool, isolated: bool = False
) -> list[str]:
    """The Compose policy (ARCHITECTURE §9.5) over a model rendered with the override `spec`; `isolated` for the
    model of an isolated run (F13)."""
    kinds = ("services", "networks", "volumes")
    labels = {f"{k}.{n}": set(x.get("labels") or {}) for k in kinds for n, x in spec.get(k, {}).items()}
    roots = tuple(env[k] for k, p in m.params.items() if p.kind in PATH_KINDS and env.get(k))
    ports = frozenset(env[k] for k, p in m.params.items() if p.kind == "port" and k in env)
    volumes = frozenset(s.volume for s in m.stores.values() if s.volume)
    pctx = compose_policy.PolicyContext(
        export, roots, volumes, ports, cpu_cfs, brand.LABEL_NS, override_labels=labels, isolated=isolated
    )
    return compose_policy.check(model, pctx)


def binds(model: Mapping[str, Any]) -> list[str]:
    """Every host path the model binds (volumes, secret and config files), for the executor's no-link check."""
    services = (model.get("services") or {}).values()
    out = {v["source"] for x in services for v in x.get("volumes") or () if v.get("type") == "bind"}
    out |= {x["file"] for k in ("secrets", "configs") for x in (model.get(k) or {}).values() if "file" in x}
    return sorted(out)


def probe(p: Probe, tvalues: Mapping[str, str], env: Mapping[str, str]) -> dict[str, Any]:
    """A probe with every template rendered (contract §20.1)."""

    def r(x: Any) -> Any:
        return templates.render(x, tvalues) if isinstance(x, str) else x

    e, h = p.expect, p.http
    out: dict[str, Any] = {"name": p.name, "kind": p.kind, "service": p.service, "argv": [r(a) for a in p.argv]}
    out |= {"port": None, "path": None, "method": None, "headers": {}, "body": None}
    if h:
        out |= {"port": int(env[h.port_param]), "path": r(h.path), "method": h.method, "body": r(h.body)}
        out["headers"] = {k: r(v) for k, v in h.headers.items()}
    x = {"status": e.status, "json": {k: [r(v) for v in vs] for k, vs in e.json.items()}, "exit": e.exit}
    x |= {"body_contains": r(e.body_contains), "header_equals": {k: r(v) for k, v in e.header_equals.items()}}
    x["header_contains"] = {k: r(v) for k, v in e.header_contains.items()}
    return out | {"expect": x, "stable": p.stable, "interval": p.interval, "timeout": p.timeout}


def variant(
    ctx: Ctx, ld: Loaded, m: Manifest, *, export: str, release: str, commit: str, images: Any, env: Any, **kw: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One way to call Compose (contract §20.1) and its merged model, which must pass the policy. Options:
    `isolated` (the op seq of an isolated run), `name` (its project), `override_text` (replay a recorded override),
    `env_secrets` (the secret files of the app env file this variant renders). `secret_files` lists those and every
    Compose file secret of the model: the executor re-checks each right before a Compose call that creates a
    container (ARCHITECTURE §9.4)."""
    override_text, isolated, name = kw.get("override_text"), kw.get("isolated"), kw.get("name") or ld.name
    app = config(ctx, name, export, m.files, env)
    if missing := sorted(set(app.get("services") or {}) - set(images)):
        raise Refused(f"no prepared image for service(s) {', '.join(missing)}", code="no-candidate")
    nets = list(app.get("networks") or {})
    ov: dict[str, Any] = {"instance": ld.name, "ns": brand.LABEL_NS, "images": images, "stores": {}, "networks": nets}
    if isolated is None:
        spec = override.live(app["services"], **ov)
    else:
        spec = override.isolated(app["services"], op=isolated, holds=m.holds, **ov)
    text = override.render(spec) if override_text is None else override_text
    model = config(ctx, name, export, m.files, env, text)
    cpu = bool(ctx.info.get("CpuCfsQuota") and ctx.info.get("CpuCfsPeriod"))
    if errors := model_errors(m, app, env) + policy_errors(m, model, spec, env, export, cpu, isolated is not None):
        raise Refused(f"project {name} is refused by the Compose policy:\n" + "\n".join(errors), code="policy")
    tv = values(ctx, ld, release, commit) | {f"image.{s}": i for s, i in images.items()}
    tv |= {f"param.{k}": v for k, v in env.items()}
    out = {"project": name, "directory": export, "files": list(m.files), "override": text, "env": dict(env)}
    out |= {"profiles": [], "images": dict(images), "values": tv, "isolated": isolated is not None}
    out |= {"probes": {k: probe(p, tv, env) for k, p in m.probes.items()}, "binds": binds(model)}
    files = {x["file"] for x in (model.get("secrets") or {}).values() if "file" in x}
    out["secret_files"] = sorted(files | set(kw.get("env_secrets") or ()))
    return out | {"smoke": [probe(s.probe, tv, env) for s in m.smoke], "model_sha256": records.doc_hash(model)}, model


def model(ctx: Ctx, v: Mapping[str, Any]) -> Any:
    """A variant's merged model, rendered from the plan's own data."""
    return config(ctx, v["project"], v["directory"], v["files"], v["env"], v["override"])


def current(ctx: Ctx, ld: Loaded) -> tuple[dict[str, Any], dict[str, Any]]:
    """The variant of the current deployment (F4)."""
    dep, m = ld.deployment, ld.manifest
    if dep is None or m is None:
        raise Refused(f"{ld.name} has no deployment", code="wrong-state")
    return deployed(ctx, ld, m, dep)


def deployed(ctx: Ctx, ld: Loaded, m: Manifest, dep: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The variant of recorded deployment `dep` under the manifest `m` it ran (its snapshot), replaying its recorded
    override and Compose env (F4): the current deployment, or an earlier one a bundle records (LIFECYCLE §4.8)."""
    text = fs.read(os.path.join(ctx.layout.deployment_snapshot(ld.name, dep["seq"]), "override.yaml")).decode()
    kw = {"release": dep["release"], "commit": dep["commit"], "images": dep["images"], "env": dep["params"]}
    return variant(ctx, ld, m, export=dep["export"], override_text=text, **kw)


def tool_facts(ctx: Ctx) -> dict[str, str]:
    """The `tool` versions a bundle records (LIFECYCLE §5.3)."""
    client, server = ctx.version["Client"], ctx.version["Server"]
    plugins = {p.get("Name"): p.get("Version") for p in (ctx.info.get("ClientInfo") or {}).get("Plugins") or ()}
    out = {"version": __version__, "engine": server["Version"], "api": server["ApiVersion"], "cli": client["Version"]}
    return out | {"compose": plugins.get("compose") or "", "arch": server["Arch"], "os": server["Os"]}


def release_files() -> dict[str, dict[str, str]]:
    """The platform release files the wrapper mounts under /run/host, reduced to release and build keys."""
    out = {}
    for rel in RELEASE_FILES:
        if fs.exists(path := os.path.join(brand.HOST_FACTS_DIR, rel)):
            pairs = [line.split("=", 1) for line in fs.read(path).decode(errors="replace").splitlines() if "=" in line]
            out[rel] = {k.strip(): v.strip().strip("\"'") for k, v in pairs if RELEASE_KEY.fullmatch(k.strip())}
    return out


def build_facts(ctx: Ctx) -> dict[str, Any]:
    """The platform build a certification names (ADR-0014), observed now, never taken from host.json."""
    server, info = ctx.version["Server"], ctx.info
    parts = {c.get("Name"): c.get("Version") for c in server.get("Components") or ()}
    out = {"os_release": release_files(), "engine": server.get("Version"), "git_commit": server.get("GitCommit")}
    out |= {"build_time": server.get("BuildTime"), "containerd": parts.get("containerd"), "runc": parts.get("runc")}
    out |= {"kernel": info.get("KernelVersion"), "storage_driver": info.get("Driver")}
    return out | {"architecture": info.get("Architecture")}


def gate(ctx: Ctx, tier: int, name: str | None = None) -> list[str]:
    """The version gate (ARCHITECTURE §3.6); tier 1 warns. The running selftest's instances need no certification."""
    folder = ctx.layout.certifications_dir
    certs = [records.loads(fs.read(os.path.join(folder, f))) for f in fs.listdir(folder) if f.endswith(".json")]
    server, tested, build = ctx.version["Server"], gates.load_tested(), build_facts(ctx)
    certs += [{"kind": "selftest", "result": "PASS", "build": build}] if name and in_selftest(ctx.layout, name) else []
    kw = {"engine_version": server["Version"], "api_version": server["ApiVersion"], "arch": ctx.info["Architecture"]}
    return gates.check(tier, build=build, certifications=[c for c in certs if isinstance(c, dict)], tested=tested, **kw)


def capacity(ctx: Ctx, needs: Mapping[str, int]) -> None:
    """Free space per filesystem of INGAT_ROOT, INGAT_BACKUPS and the Docker root (the probe volume, where mounted):
    the summed `needs` of the paths on it plus a 1 GiB floor (LIFECYCLE §5.8). Ingat never deletes to make room. A
    path that does not exist cannot be measured, so nothing runs (the wrapper always mounts the probe volume)."""
    found: dict[int, list[Any]] = {}  # st_dev -> [free, needed, paths]
    for path in dict.fromkeys((ctx.layout.root, ctx.layout.backups, brand.PROBE_MOUNT, *needs)):
        if not fs.exists(path):
            raise CannotRun(f"cannot measure the free space of {path}: it does not exist", code="cannot-measure")
        dev, free = fs.statvfs(path)
        entry = found.setdefault(dev, [free, GIB, []])
        entry[1] += needs.get(path, 0)
        entry[2].append(path)
    for free, need, paths in found.values():
        if free < need:
            raise Refused(f"{free} bytes free on the filesystem of {', '.join(paths)}; {need} needed", code="capacity")


def payload_size(ctx: Ctx, ld: Loaded) -> int:
    """S of LIFECYCLE §5.8: the newest catalogued payload, else the size of the current bind generations."""
    folder = ctx.layout.catalog_dir(ld.name)
    names = [f for f in fs.listdir(folder) if f.endswith(".json") and not f.endswith(".pruned.json")]
    if docs := [state.read_doc(os.path.join(folder, f), "catalog") for f in names]:
        return int(max(docs, key=lambda d: str(d.get("created_at")))["size"])
    gens = (ld.record.get("generations") or {}).items()
    paths = [ctx.layout.data_gen(ld.name, store, f"g{n}") for store, n in gens]
    return sum(fs.tree_size(p) for p in paths if fs.exists(p))
