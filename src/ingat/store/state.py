"""The on-disk layout (ARCHITECTURE §7.1) and record access; the only code that knows state paths."""

import os
import re
from collections.abc import Mapping
from typing import Any

from ingat.model.errors import Refused
from ingat.model.records import check_schema, dumps, loads, pretty, sha256_hex
from ingat.store import fs

_OP_DIR = re.compile(r"([1-9][0-9]*)-([a-z][a-z0-9-]*)")


def _join(base: str, *parts: object) -> str:
    """`base/part/...`, refusing a part that could leave its directory."""
    out = [base]
    for part in map(str, parts):
        if part in ("", ".", "..") or "/" in part or "\0" in part:
            raise Refused(f"unsafe path component {part!r}", code="unsafe-path")
        out.append(part)
    return "/".join(out)


class Layout:
    def __init__(self, root: str, backups: str) -> None:
        self.root = root = os.path.normpath(root)
        self.backups = os.path.normpath(backups)
        self.host_json = _join(root, "host.json")
        self.host_lock = _join(root, "host.lock")
        self.plans_dir = _join(root, "plans")
        self.fixtures_dir = _join(root, "cache", "fixtures")
        self.docker_config = _join(root, "cache", "docker-config")  # the tool's own empty DOCKER_CONFIG
        self.inbox = _join(root, "inbox")
        self.runs_dir = _join(root, "host", "runs")
        self.allocations_dir = _join(root, "host", "allocations")
        self.attention_json = _join(root, "host", "attention.json")
        self.certifications_dir = _join(root, "host", "certifications")
        self.instances_dir = _join(root, "instances")

    def plan(self, plan_hash: str) -> str:
        return _join(self.plans_dir, f"{plan_hash}.json")

    def cache_git(self, repo_id: str) -> str:
        return _join(self.root, "cache", "git", f"{repo_id}.git")

    def cache_src(self, commit: str) -> str:
        return _join(self.root, "cache", "src", commit)

    def keys_dir(self, name: str) -> str:
        return _join(self.root, "keys", name)

    def ledger(self, image_id_hex: str, name: str) -> str:
        """`name` is the entry's stem, `<instance>-<seq>`."""
        return _join(self.root, "host", "images", image_id_hex, f"{name}.json")

    def inst(self, name: str, *parts: object) -> str:
        return _join(self.instances_dir, name, *parts)

    def inst_toml(self, name: str) -> str:
        return self.inst(name, "instance.toml")

    def record_json(self, name: str) -> str:
        return self.inst(name, "record.json")

    def lock(self, name: str) -> str:
        return self.inst(name, "lock")

    def secrets_dir(self, name: str) -> str:
        return self.inst(name, "secrets")

    def placeholder(self, name: str) -> str:
        return self.inst(name, "placeholder")

    def app_dir(self, name: str) -> str:
        return self.inst(name, "app")

    def candidates(self, name: str, commit: str, refs: Mapping[str, str]) -> str:
        """The candidate of `commit` prepared for the image references `refs` (service -> reference): an instance
        param that changes a reference makes a new candidate, never a stale one."""
        return self.inst(name, "candidates", f"{commit}-{sha256_hex(dumps(dict(refs)))[:12]}.json")

    def env_dir(self, name: str) -> str:
        return self.inst(name, "env")

    def deployments_dir(self, name: str) -> str:
        return self.inst(name, "deployments")

    def deployment_json(self, name: str, seq: int) -> str:
        return self.inst(name, "deployments", f"{seq}.json")

    def deployment_snapshot(self, name: str, seq: int) -> str:
        return self.inst(name, "deployments", seq)

    def ops_dir(self, name: str) -> str:
        return self.inst(name, "ops")

    def op_dir(self, name: str, seq: int, kind: str) -> str:
        return self.inst(name, "ops", f"{seq}-{kind}")

    def catalog_dir(self, name: str) -> str:
        return self.inst(name, "catalog")

    def catalog(self, name: str, bundle_id: str) -> str:
        return self.inst(name, "catalog", f"{bundle_id}.json")

    def verifications_dir(self, name: str, bundle_id: str) -> str:
        return self.inst(name, "verifications", bundle_id)

    def verification(self, name: str, bundle_id: str) -> str:
        """The append-only JSON Lines file of a bundle's verification records (ARCHITECTURE §7.1)."""
        return self.inst(name, "verifications", f"{bundle_id}.json")

    def run(self, run_id: str) -> str:
        return _join(self.runs_dir, f"{run_id}.json")

    def allocation(self, kind: str, value: str) -> str:
        return _join(self.allocations_dir, f"{kind}-{value.replace('/', '_')}.json")

    def reports_dir(self, name: str) -> str:
        return self.inst(name, "reports")

    def data_gen(self, name: str, store: str, gen: str) -> str:
        """A bind-store generation directory; `gen` is `g<N>` (live) or `t<seq>` (drill)."""
        return _join(self.root, "data", name, store, gen)

    def bundle_dir(self, name: str, bundle_id: str) -> str:
        return _join(self.backups, name, bundle_id)

    def incoming_dir(self, name: str, bundle_id: str) -> str:
        return _join(self.backups, name, f".incoming-{bundle_id}")


def read_doc(path: str, kind: str) -> dict[str, Any]:
    """A record of `kind`, unknown fields kept; a newer state_schema refuses (ADR-0023)."""
    return check_schema(loads(fs.read(path)), kind)


def write_doc_once(path: str, doc: Mapping[str, Any]) -> None:
    fs.write_once(path, pretty(doc))


def replace_doc(path: str, doc: Mapping[str, Any]) -> None:
    fs.replace_atomic(path, pretty(doc))


def list_instances(layout: Layout) -> list[str]:
    """Initialized instances (those with a record), sorted."""
    return [n for n in fs.listdir(layout.instances_dir) if fs.exists(layout.record_json(n))]


def _ops(layout: Layout, name: str) -> list[tuple[int, str]]:
    found = [_OP_DIR.fullmatch(entry) for entry in fs.listdir(layout.ops_dir(name))]
    return sorted((int(m[1]), m[2]) for m in found if m)


def open_ops(layout: Layout, name: str) -> list[tuple[int, str]]:
    """(seq, kind) of operations without a result, oldest first."""
    return [(s, k) for s, k in _ops(layout, name) if not fs.exists(_join(layout.op_dir(name, s, k), "result.json"))]


def next_seq(layout: Layout, name: str) -> int:
    """The next operation number: above the record's and above every operation directory, so never reused."""
    record = read_doc(layout.record_json(name), "instance")
    return max([int(record.get("next_seq", 1)), *(seq + 1 for seq, _ in _ops(layout, name))])
