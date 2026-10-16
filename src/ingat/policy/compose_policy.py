"""Compose model policy (ARCHITECTURE §9.5): a deny-list over the merged model, plus the CPU capability rule.

The model is `compose config --format json --no-env-resolution` output rendered with the generated override, so
every path in it is absolute. Each violation starts with the model path it names (`services.web.cap_add`).
"""

import posixpath
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# `gpus` and device reservations are device access like `devices`; `provider` makes Compose run an executable the
# app names inside the calling (executor) container, which holds the Docker socket (§9.7: no host executables);
# `use_api_socket` makes Compose bind the Docker socket into the service (§9.3); `external_links` reach containers
# outside the project (F8); `runtime` swaps the OCI runtime that confines the container.
REFUSED = (
    "privileged cap_add devices device_cgroup_rules gpus deploy.resources.reservations.devices cgroup_parent"
    " container_name volumes_from external_links provider use_api_socket runtime"
).split()
# `host` is refused; `container:<x>` joins a container outside the project (F8); `service:<x>` must name a service.
NAMESPACES = ("network_mode", "pid", "ipc", "uts", "userns_mode", "cgroup")
NETWORK_MODES = {False: ("none", "bridge"), True: ("none",)}  # by isolation: bridge skips the internal networks (F13)
# The only allowed `security_opt` entries (option -> values; the bare `no-new-privileges` too). Every other entry can
# lift confinement: a false `no-new-privileges` or any `seccomp` (even `builtin`) replaces the daemon-wide setting,
# `label` options relax SELinux, and any other AppArmor profile may be a host profile flagged unconfined.
TRUE = ("1", "t", "T", "true", "True", "TRUE")  # the daemon parses the value with Go's strconv.ParseBool
SECURITY_OPTS = {"no-new-privileges": TRUE, "apparmor": ("docker-default",)}
MOUNT_TYPES = ("bind", "volume", "tmpfs")  # `image` mounts an image the override does not pin
HOOKS = ("post_start", "pre_stop")  # Compose runs them as exec in the service container, privileged on request
NEVER_BOUND = ("/", "/var/run/docker.sock", "/run/docker.sock")
CPU_KEYS = ("cpus", "deploy.resources.limits.cpus")
OUTSIDE = "is outside the instance's store generations, task dirs, placeholder, secrets and rendered env file"


@dataclass(frozen=True, slots=True)
class PolicyContext:
    project_dir: str  # the export: read-only binds inside it are allowed
    allowed_bind_roots: tuple[str, ...]  # bind, env_file and secret sources (prefix match on normalized paths)
    store_volumes: frozenset[str]  # top-level volume keys declared as stores
    port_values: frozenset[str]  # the values of the port params
    cpu_cfs: bool  # host capability (host.json)
    label_ns: str
    cpus_params: Mapping[str, str] = field(default_factory=dict)  # "<service>/<key>" -> param name, for messages
    # Label keys the override adds, by model path ("services.<name>", "networks.<name>", "volumes.<name>").
    override_labels: Mapping[str, Collection[str]] = field(default_factory=dict)
    isolated: bool = False  # an isolated run (F13): `network_mode` only none or service:<name>


def _inside(path: str, roots: Iterable[str]) -> bool:
    p = posixpath.normpath(path)
    return any(p == r or p.startswith(r + "/") for r in map(posixpath.normpath, roots))


def _dig(item: Any, dotted: str) -> Any:
    for key in dotted.split("."):
        item = (item or {}).get(key)
    return item


def _labels(at: str, item: Mapping[str, Any], ctx: PolicyContext) -> list[str]:
    own = ctx.override_labels.get(at, ())
    keys = [k for k in item.get("labels") or {} if k.startswith(ctx.label_ns) and k not in own]
    return [f"{at}.labels: {k} is in the tool's label namespace" for k in keys]


def _binds(at: str, svc: Mapping[str, Any], ctx: PolicyContext) -> list[str]:
    out: list[str] = []
    for i, vol in enumerate(svc.get("volumes") or ()):
        where, kind = f"{at}.volumes[{i}]", vol.get("type")
        if kind not in MOUNT_TYPES:
            out.append(f"{where}: {kind} mount refused")
        if kind != "bind":
            continue
        src = posixpath.normpath(vol["source"])
        if src in NEVER_BOUND:
            out.append(f"{where}: bind of {src} refused")
        elif not _inside(src, ctx.allowed_bind_roots):
            if not _inside(src, (ctx.project_dir,)):
                out.append(f"{where}: bind source {src} {OUTSIDE}")
            elif not vol.get("read_only"):
                out.append(f"{where}: bind source {src} is inside the export and must be read_only")
    for i, env_file in enumerate(svc.get("env_file") or ()):
        if not _inside(env_file["path"], ctx.allowed_bind_roots):
            out.append(f"{at}.env_file[{i}]: {env_file['path']} {OUTSIDE}")
    for i, path in enumerate(svc.get("label_file") or ()):  # Compose reads it into the labels at every call
        if not _inside(path, (ctx.project_dir,)):
            out.append(f"{at}.label_file[{i}]: {path} is outside the export")
    return out


def _namespaces(at: str, svc: Mapping[str, Any], services: Collection[str], isolated: bool) -> list[str]:
    out: list[str] = []
    for key in NAMESPACES:
        kind, _, target = (mode := str(svc.get(key) or "")).partition(":")
        if not mode or (kind == "service" and target in services):
            continue
        if mode == "host":
            out.append(f"{at}.{key}: host namespace refused")
        elif kind in ("container", "service"):
            out.append(f"{at}.{key}: {mode} refused, only a service of this project can share its namespace")
        elif key == "network_mode" and mode not in (allowed := NETWORK_MODES[isolated]):
            run = " in an isolated run" if isolated else ""
            out.append(f"{at}.{key}: {mode} refused{run}, only {', '.join(allowed)} or service:<name>")
    return out


def _confining(opt: str) -> bool:
    key, sep, value = opt.partition("=")  # split as the daemon does: at the first `=`, else at the first `:`
    if not sep:
        key, _, value = opt.partition(":")
    return opt == "no-new-privileges" or value in SECURITY_OPTS.get(key, ())


def _service(name: str, svc: Mapping[str, Any], services: Collection[str], ctx: PolicyContext) -> list[str]:
    at = f"services.{name}"
    out = [f"{at}.{key}: refused" for key in REFUSED if _dig(svc, key)]
    out += _namespaces(at, svc, services, ctx.isolated)
    hooks = [(f"{at}.{k}[{i}]", h) for k in HOOKS for i, h in enumerate(svc.get(k) or ())]
    out += [f"{where}.privileged: refused" for where, h in hooks if h.get("privileged")]
    out += [f"{at}.security_opt: {opt} refused" for opt in svc.get("security_opt") or () if not _confining(opt)]
    out += _labels(at, svc, ctx) + _binds(at, svc, ctx)
    for i, port in enumerate(svc.get("ports") or ()):
        ip, published = port.get("host_ip", "*"), str(port.get("published", "*"))
        if ip != "127.0.0.1" or published not in ctx.port_values:
            out.append(f"{at}.ports[{i}]: {ip}:{published} refused: only 127.0.0.1 and a port param value")
    if build := svc.get("build"):
        for source in (build["context"], *(build.get("additional_contexts") or {}).values()):
            if not _inside(source, (ctx.project_dir,)):
                out.append(f"{at}.build: context {source} is outside the export")
    if not ctx.cpu_cfs:  # Compose drops a zero `cpus` from the model, so any value here is a real limit
        for key in CPU_KEYS:
            if (value := _dig(svc, key)) and float(value) != 0:
                param = ctx.cpus_params.get(f"{name}/{key}")
                hint = f"; set param {param} to 0" if param else ""
                out.append(f"{at}.{key}: CPU limit {value} needs CPU CFS quota support, which this host lacks{hint}")
    return out


def check(model: Mapping[str, Any], ctx: PolicyContext) -> list[str]:
    """Violation messages, each naming the model path it refuses; [] means the model passes."""
    out: list[str] = []
    services = model.get("services") or {}
    for name, svc in services.items():
        out += _service(name, svc, services, ctx)
    for kind in ("volumes", "networks"):
        for name, item in (model.get(kind) or {}).items():
            at, store = f"{kind}.{name}", kind == "volumes" and name in ctx.store_volumes
            out += _labels(at, item, ctx)
            if item.get("external") and not store:
                out.append(f"{at}.external: app-declared external {kind[:-1]} refused")
            elif kind == "networks" and item.get("name") != f"{model.get('name')}_{name}":
                # Compose joins an existing network of that name with only a warning: the same as `external`.
                out.append(f"{at}.name: fixed network name {item.get('name')} refused, it would join a foreign one")
            if kind == "volumes" and not store:
                out.append(f"{at}: named volume that is not a declared store")
            if item.get("driver_opts"):
                out.append(f"{at}.driver_opts: refused")
            if kind == "networks" and item.get("driver", "bridge") != "bridge":  # macvlan, ipvlan: the host's LAN
                out.append(f"{at}.driver: {item['driver']} refused, only bridge")
    for kind in ("secrets", "configs"):  # outside Swarm both are binds of their file; a config is always read-only
        roots = ctx.allowed_bind_roots + ((ctx.project_dir,) if kind == "configs" else ())
        for name, item in (model.get(kind) or {}).items():
            if "file" in item and not _inside(item["file"], roots):
                out.append(f"{kind}.{name}.file: {item['file']} {OUTSIDE}")
    return out
