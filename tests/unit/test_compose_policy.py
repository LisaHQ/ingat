"""Policy table (ARCHITECTURE §9.5, §10.3): hostile snippets refused, hardened models accepted.

The models in data/policy/ are real `docker compose config --format json --no-env-resolution` output (Compose v5.6.0,
identical on Engine 24.0.2 and 29.9.0), rendered with the generated override where a project has one; hostile.json is
one service or top-level entry per §9.5 rule. The HOSTILE snippets use the same captured shapes.
"""

import copy
import dataclasses
import json
import unittest
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.adapters import override
from ingat.policy.compose_policy import PolicyContext, check

DATA = Path(__file__).parent / "data" / "policy"
NS = brand.LABEL_NS
ROOT = "/srv/ingat"  # the samples were captured with the default root
EXPORT = f"{ROOT}/cache/src/0123456789abcdef0123456789abcdef01234567"
LITE, PG = f"{ROOT}/instances/lite-test", f"{ROOT}/instances/pg-staging"
ENV = "e" * 64 + ".env"


def _load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((DATA / f"{name}.json").read_text())
    return doc


def _own_labels(spec: dict[str, Any]) -> dict[str, set[str]]:
    """What a caller passes: the label keys the override adds, by model path."""
    kinds = ("services", "networks", "volumes")
    return {f"{k}.{name}": set(item.get("labels", {})) for k in kinds for name, item in spec.get(k, {}).items()}


def _ctx(spec: dict[str, Any], roots: tuple[str, ...], **fields: Any) -> PolicyContext:
    base: dict[str, Any] = {"store_volumes": frozenset(), "port_values": frozenset(), "cpu_cfs": True}
    return PolicyContext(
        project_dir=EXPORT, allowed_bind_roots=roots, label_ns=NS, override_labels=_own_labels(spec), **(base | fields)
    )


def _paths(violations: list[str]) -> list[str]:
    return sorted(v.split(":", 1)[0] for v in violations)


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


LITE_SPEC = override.live({"app": {}}, instance="lite-test", ns=NS, images={"app": "sha256:1"}, stores={}, networks=())
LITE_CTX = _ctx(
    LITE_SPEC,
    (f"{LITE}/data/data/g1", f"{LITE}/env/{ENV}", f"{LITE}/placeholder", f"{LITE}/secrets"),
    port_values=frozenset({"20080"}),
)
ISOLATED_SPEC = override.isolated(
    {"app": {}}, instance="lite-test", ns=NS, images={"app": "sha256:1"}, stores={}, networks=(), op=7, holds={}
)
ISOLATED_CTX = _ctx(
    ISOLATED_SPEC, (f"{LITE}/data/data/t7", f"{LITE}/ops/7-drill", f"{LITE}/placeholder"), isolated=True
)
PG_MODEL = _load("fx-pg")
PG_SPEC = override.live(
    PG_MODEL["services"],
    instance="pg-staging",
    ns=NS,
    images=dict.fromkeys(PG_MODEL["services"], "sha256:1"),
    stores={"postgres_data": "pg-staging_pgdata_g1"},
    networks=("internal", "edge"),
)
PG_CTX = _ctx(
    PG_SPEC,
    (f"{PG}/secrets", f"{PG}/placeholder", f"{PG}/env/{ENV}"),
    store_volumes=frozenset({"postgres_data"}),
    port_values=frozenset({"20081"}),
    cpus_params={
        "db/cpus": "FXPG_DB_CPUS",
        "backend/deploy.resources.limits.cpus": "FXPG_BACKEND_CPUS",
        "web/cpus": "FXPG_WEB_CPUS",
        "ops/cpus": "FXPG_OPS_CPUS",
    },
)


def svc(**keys: Any) -> dict[str, Any]:
    return {"services": {"app": keys}}


def bind(source: str, read_only: bool = False) -> dict[str, Any]:
    return svc(volumes=[{"type": "bind", "source": source, "target": "/mnt", "bind": {}, "read_only": read_only}])


def port(**keys: Any) -> dict[str, Any]:
    return svc(ports=[{"mode": "ingress", "target": 3000, "protocol": "tcp", **keys}])


def joined(**keys: Any) -> dict[str, Any]:
    """`app` shares namespaces with a second service `side` of the same model (Compose adds the dependency)."""
    side = {"command": None, "entrypoint": None, "image": "sha256:1", "networks": {"default": None}}
    started = {"condition": "service_started", "restart": True, "required": True}
    return {"services": {"app": {**keys, "depends_on": {"side": started}}, "side": side}}


# Captured `security_opt` entries that lift confinement: SELinux label options, a seccomp profile file (Compose reads
# it relative to the project), host AppArmor profiles (some ship flagged unconfined) and other daemon options. A false
# `no-new-privileges` and `seccomp=builtin` replace a daemon-wide no-new-privileges or seccomp profile (both seen on a
# daemon so configured, through Compose v5.6.0 on Engine 24.0.2).
LIFTING = (
    "label=disable",
    "label:disable",
    "label=type:spc_t",
    "label:type:spc_t",
    "label=level:s0",
    "seccomp=./prof.json",
    "seccomp:/etc/prof.json",
    "seccomp=builtin",
    "seccomp:builtin",
    "systempaths=unconfined",
    "apparmor=host-app",
    "writable-cgroups=true",
    "no-new-privileges:false",
    "no-new-privileges=0",
)


# One hostile snippet per refused rule, merged into the hardened fx-lite model: (patch, expected violation paths).
HOSTILE: list[tuple[dict[str, Any], tuple[str, ...]]] = [
    (svc(privileged=True), ("services.app.privileged",)),
    (svc(cap_add=["NET_ADMIN"]), ("services.app.cap_add",)),
    (svc(devices=[{"source": "/dev/fuse", "target": "/dev/fuse", "permissions": "rwm"}]), ("services.app.devices",)),
    (svc(device_cgroup_rules=["c 10:229 rwm"]), ("services.app.device_cgroup_rules",)),
    (svc(network_mode="host"), ("services.app.network_mode",)),
    (svc(pid="host"), ("services.app.pid",)),
    (svc(ipc="host"), ("services.app.ipc",)),
    (svc(uts="host"), ("services.app.uts",)),
    (svc(userns_mode="host"), ("services.app.userns_mode",)),
    (svc(security_opt=["no-new-privileges:true", "seccomp=unconfined"]), ("services.app.security_opt",)),
    (svc(security_opt=["apparmor:unconfined"]), ("services.app.security_opt",)),
    (svc(cgroup_parent="/system.slice"), ("services.app.cgroup_parent",)),
    (svc(container_name="app"), ("services.app.container_name",)),
    (svc(volumes_from=["container:foreign"]), ("services.app.volumes_from",)),
    ({"volumes": {"other": {"name": "foreign", "external": True}}}, ("volumes.other", "volumes.other.external")),
    ({"networks": {"default": {"name": "foreign", "external": True}}}, ("networks.default.external",)),
    ({"volumes": {"data": {"name": "lite-test_data", "driver_opts": {"device": "/"}}}}, ("volumes.data.driver_opts",)),
    (svc(labels={NS + "op": "7"}), ("services.app.labels",)),
    ({"networks": {"default": {"labels": {NS + "role": "app"}}}}, ("networks.default.labels",)),
    ({"volumes": {"data": {"name": "lite-test_data", "labels": {NS + "store": "data"}}}}, ("volumes.data.labels",)),
    (bind("/var/run/docker.sock", read_only=True), ("services.app.volumes[0]",)),
    (bind("/", read_only=True), ("services.app.volumes[0]",)),
    (bind("/etc", read_only=True), ("services.app.volumes[0]",)),
    (bind(f"{LITE}/data/data/g1/../../../../pg-staging/secrets"), ("services.app.volumes[0]",)),
    (bind(f"{LITE}/data/data/g10"), ("services.app.volumes[0]",)),
    (bind(f"{LITE}"), ("services.app.volumes[0]",)),
    (bind(f"{EXPORT}/conf"), ("services.app.volumes[0]",)),
    (svc(env_file=[{"path": f"{PG}/env/{ENV}"}]), ("services.app.env_file[0]",)),
    (svc(env_file=[{"path": f"{EXPORT}/defaults.env"}]), ("services.app.env_file[0]",)),
    ({"secrets": {"tok": {"name": "lite-test_tok", "file": f"{PG}/secrets/tok"}}}, ("secrets.tok.file",)),
    ({"configs": {"conf": {"name": "lite-test_conf", "file": "/etc/shadow"}}}, ("configs.conf.file",)),
    (port(published="20080"), ("services.app.ports[0]",)),
    (port(host_ip="0.0.0.0", published="20080"), ("services.app.ports[0]",)),
    (port(host_ip="::", published="20080"), ("services.app.ports[0]",)),
    (port(host_ip="127.0.0.1", published="20090"), ("services.app.ports[0]",)),
    (port(host_ip="127.0.0.1"), ("services.app.ports[0]",)),
    ({"volumes": {"cache": {"name": "lite-test_cache"}}}, ("volumes.cache",)),
    (svc(build={"context": "/etc", "dockerfile": "Dockerfile"}), ("services.app.build",)),
    (svc(build={"context": "https://example.invalid/app.git"}), ("services.app.build",)),
    (svc(build={"context": EXPORT, "additional_contexts": {"base": f"{EXPORT}/.."}}), ("services.app.build",)),
    (svc(cpus=0.25), ("services.app.cpus",)),
    (svc(deploy={"resources": {"limits": {"cpus": "1.5"}}}), ("services.app.deploy.resources.limits.cpus",)),
    # Keys that reach a refused rule another way, in the shape Compose v5.6.0 prints them (same on both engines).
    (svc(gpus=[{"count": -1}]), ("services.app.gpus",)),
    (
        svc(deploy={"resources": {"reservations": {"devices": [{"capabilities": ["gpu"], "driver": "nvidia"}]}}}),
        ("services.app.deploy.resources.reservations.devices",),
    ),
    (
        svc(post_start=[{"command": ["id"], "user": "root", "privileged": True}]),
        ("services.app.post_start[0].privileged",),
    ),
    (
        svc(pre_stop=[{"command": ["true"]}, {"command": ["true"], "privileged": True}]),
        ("services.app.pre_stop[1].privileged",),
    ),
    (svc(provider={"type": f"{EXPORT}/run", "options": {"x": ["1"]}}), ("services.app.provider",)),
    ({"networks": {"default": {"name": "foreign-net"}}}, ("networks.default.name",)),
    # Compose reads a label_file into `labels` even with --no-env-resolution.
    (svc(labels={NS + "op": "7"}, label_file=[f"{EXPORT}/labels"]), ("services.app.labels",)),
    # ... from any path at every Compose call: only a file of the export.
    (svc(label_file=[f"{EXPORT}/labels", "/etc/shadow"]), ("services.app.label_file[1]",)),
    (svc(label_file=[f"{EXPORT}/../other/labels"]), ("services.app.label_file[0]",)),
    (svc(label_file=[f"{LITE}/secrets/tok"]), ("services.app.label_file[0]",)),
    # Namespaces shared with a foreign container (F8) or a service the model lacks, cgroup host, network modes.
    (svc(cgroup="host"), ("services.app.cgroup",)),
    (svc(network_mode="container:foreign"), ("services.app.network_mode",)),
    (svc(pid="container:foreign"), ("services.app.pid",)),
    (svc(ipc="container:foreign"), ("services.app.ipc",)),
    (svc(uts="container:foreign"), ("services.app.uts",)),
    (svc(network_mode="service:ghost"), ("services.app.network_mode",)),
    (svc(pid="service:ghost", ipc="service:ghost"), ("services.app.ipc", "services.app.pid")),
    (svc(network_mode="foreign-net"), ("services.app.network_mode",)),
    (joined(network_mode="service:side", pid="container:foreign"), ("services.app.pid",)),
    *((svc(security_opt=["no-new-privileges:true", opt]), ("services.app.security_opt",)) for opt in LIFTING),
    (svc(runtime="runc"), ("services.app.runtime",)),
    (svc(external_links=["foreign:alias", "other"]), ("services.app.external_links",)),
    (svc(volumes=[{"type": "image", "source": "busybox", "target": "/img"}]), ("services.app.volumes[0]",)),
    (svc(volumes=[{"type": "npipe", "source": "/run/x", "target": "/x"}]), ("services.app.volumes[0]",)),
    (
        {"networks": {"default": {"driver": "macvlan", "driver_opts": {"parent": "eth0"}}}},
        ("networks.default.driver", "networks.default.driver_opts"),
    ),
    ({"networks": {"default": {"driver": "ipvlan"}}}, ("networks.default.driver",)),
    (
        {"networks": {"default": {"driver_opts": {"com.docker.network.bridge.name": "docker0"}}}},
        ("networks.default.driver_opts",),
    ),
]

# Privilege-lowering keys (ARCHITECTURE §9.5, third paragraph), each merged into the same model.
ALLOWED: list[dict[str, Any]] = [
    svc(read_only=True, cap_drop=["ALL"], user="10001:10001", tmpfs=["/tmp", "/run"], init=True),
    svc(security_opt=["no-new-privileges:true"]),
    svc(mem_limit="268435456", pids_limit=64, shm_size="67108864", stop_grace_period="30s"),
    svc(deploy={"resources": {"limits": {"memory": "268435456"}}}),
    svc(network_mode="none"),
    {"networks": {"default": {"internal": True}}},
    svc(profiles=["ops"]),
    bind(f"{EXPORT}/conf", read_only=True),
    bind(f"{LITE}/placeholder"),
    svc(volumes=[{"type": "tmpfs", "target": "/cache"}]),
    {"volumes": {"data": {"name": "lite-test_data_g1", "external": True}}},
    {"secrets": {"tok": {"name": "lite-test_tok", "file": f"{LITE}/secrets/tok"}}},
    {"configs": {"conf": {"name": "lite-test_conf", "file": f"{EXPORT}/conf/app.conf"}}},
    svc(build={"context": EXPORT, "dockerfile": "Dockerfile"}),
    svc(post_start=[{"command": ["fx-lite", "migrate"], "user": "10001:10001"}]),
    # Defaults spelled out, namespaces shared inside the project, the plain bridge driver.
    svc(security_opt=["no-new-privileges", "no-new-privileges=true", "no-new-privileges=1", "apparmor:docker-default"]),
    svc(network_mode="bridge"),
    svc(cgroup="private", ipc="shareable"),
    svc(ipc="private"),
    joined(network_mode="service:side", pid="service:side", ipc="service:side"),
    svc(volumes=[{"type": "volume", "source": "data", "target": "/data", "volume": {}}]),
    {"networks": {"default": {"driver": "bridge"}}},
]


class HardenedModels(unittest.TestCase):
    def test_real_hardened_models_pass(self) -> None:
        for name, ctx in (("fx-lite", LITE_CTX), ("fx-lite-isolated", ISOLATED_CTX), ("fx-pg", PG_CTX)):
            with self.subTest(name):
                self.assertEqual(check(_load(name), ctx), [])

    def test_samples_carry_the_allowed_hardening(self) -> None:
        keys = {key for name in ("fx-lite", "fx-pg") for s in _load(name)["services"].values() for key in s}
        allowed = {"read_only", "cap_drop", "user", "tmpfs", "init", "security_opt", "shm_size", "stop_grace_period"}
        self.assertLessEqual(allowed | {"mem_limit", "pids_limit", "profiles", "secrets", "network_mode"}, keys)
        self.assertTrue(PG_MODEL["networks"]["internal"]["internal"])
        self.assertEqual(PG_MODEL["services"]["backend"]["volumes"][0]["source"], f"{EXPORT}/config")

    def test_zero_cpus_pass_without_cfs(self) -> None:
        # Captured with every cpus param "0", the model differs only by these dropped keys (spike Q9).
        model = copy.deepcopy(PG_MODEL)
        for name in ("db", "ops"):
            del model["services"][name]["cpus"]
        del model["services"]["backend"]["deploy"]["resources"]["limits"]["cpus"]
        self.assertEqual(check(model, dataclasses.replace(PG_CTX, cpu_cfs=False)), [])

    def test_nonzero_cpus_refused_without_cfs_naming_service_key_and_param(self) -> None:
        violations = check(PG_MODEL, dataclasses.replace(PG_CTX, cpu_cfs=False))
        expected = {
            "services.backend.deploy.resources.limits.cpus": "FXPG_BACKEND_CPUS",
            "services.db.cpus": "FXPG_DB_CPUS",
            "services.ops.cpus": "FXPG_OPS_CPUS",
        }
        self.assertEqual(_paths(violations), sorted(expected))
        for v in violations:
            self.assertIn(expected[v.split(":", 1)[0]], v)

    def test_override_labels_match_exactly(self) -> None:
        # The isolated model also carries the op label, which the live override does not add.
        ctx = dataclasses.replace(ISOLATED_CTX, override_labels=LITE_CTX.override_labels)
        expected = ["networks.default.labels", "services.app.labels"]
        self.assertEqual(_paths(check(_load("fx-lite-isolated"), ctx)), expected)


class HostileSnippets(unittest.TestCase):
    ctx = dataclasses.replace(LITE_CTX, store_volumes=frozenset({"data"}), cpu_cfs=False)

    def test_each_refused_rule(self) -> None:
        self.assertEqual(check(_load("fx-lite"), self.ctx), [])
        for patch, expected in HOSTILE:
            with self.subTest(patch=patch):
                self.assertEqual(
                    _paths(check(_merge(_load("fx-lite"), copy.deepcopy(patch)), self.ctx)), list(expected)
                )

    def test_messages_name_key_and_value(self) -> None:
        volumes = [{"type": "image", "source": "busybox", "target": "/img"}]
        patch = svc(pid="container:foreign", ipc="service:ghost", security_opt=["label=disable"], volumes=volumes)
        model = _merge(_load("fx-lite"), patch | {"networks": {"default": {"driver": "macvlan"}}})
        expected = [
            "networks.default.driver: macvlan",
            "services.app.ipc: service:ghost",
            "services.app.pid: container:foreign",
            "services.app.security_opt: label=disable",
            "services.app.volumes[0]: image mount",
        ]
        self.assertEqual(sorted(v.split(" refused")[0] for v in check(model, self.ctx)), expected)

    def test_privilege_lowering_keys_pass(self) -> None:
        for patch in ALLOWED:
            with self.subTest(patch=patch):
                self.assertEqual(check(_merge(_load("fx-lite"), copy.deepcopy(patch)), self.ctx), [])

    def test_real_hostile_model_refuses_every_rule(self) -> None:
        ctx = _ctx({}, (f"{ROOT}/instances/evil",), port_values=frozenset({"19998"}), cpu_cfs=False)
        expected = [
            "configs.conf.file",
            "networks.extnet.external",
            "secrets.stolen.file",
            "services.build.build",
            "services.capadd.cap_add",
            "services.cgparent.cgroup_parent",
            "services.cpus.cpus",
            "services.cpusdeploy.deploy.resources.limits.cpus",
            "services.dev.devices",
            "services.devrule.device_cgroup_rules",
            "services.ipchost.ipc",
            "services.labels.labels",
            "services.named.container_name",
            "services.nethost.network_mode",
            "services.outside.env_file[0]",
            "services.outside.volumes[0]",
            "services.outside.volumes[1]",
            "services.pidhost.pid",
            *(f"services.ports.ports[{i}]" for i in range(4)),
            "services.priv.privileged",
            "services.sock.volumes[0]",
            "services.sock.volumes[1]",
            "services.unconf.security_opt",
            "services.unconf.security_opt",
            "services.userns.userns_mode",
            "services.utshost.uts",
            "services.volfrom.volumes_from",
            "volumes.extvol",
            "volumes.extvol.external",
            "volumes.optvol",
            "volumes.optvol.driver_opts",
            "volumes.optvol.labels",
        ]
        self.assertEqual(_paths(check(_load("hostile"), ctx)), expected)


class IsolatedRuns(unittest.TestCase):
    """F13: an isolated model leaves its internal networks through no `network_mode`."""

    def test_network_mode(self) -> None:
        for patch, expected in (
            (svc(network_mode="bridge"), ["services.app.network_mode"]),
            (svc(network_mode="container:foreign"), ["services.app.network_mode"]),
            (svc(network_mode="host"), ["services.app.network_mode"]),
            (svc(network_mode="none"), []),
            (joined(network_mode="service:side"), []),
        ):
            with self.subTest(patch=patch):
                model = _merge(_load("fx-lite-isolated"), copy.deepcopy(patch))
                self.assertEqual(_paths(check(model, ISOLATED_CTX)), expected)

    def test_message_names_service_key_and_mode(self) -> None:
        model = _merge(_load("fx-lite-isolated"), svc(network_mode="bridge"))
        [violation] = check(model, ISOLATED_CTX)
        self.assertTrue(violation.startswith("services.app.network_mode: bridge refused in an isolated run"), violation)
        self.assertEqual(check(model, dataclasses.replace(ISOLATED_CTX, isolated=False)), [])


if __name__ == "__main__":
    unittest.main()
