"""Bundle format 1 (LIFECYCLE §5.3-§5.4, ADR-0016): SHA256SUMS, the bundle hash and bundle.json."""

import re
from collections.abc import Mapping
from typing import Any

from ingat.model.errors import Refused
from ingat.model.records import sha256_hex

FORMAT = 1
# LIFECYCLE §5.4 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, anchored so that match, search and fullmatch all refuse "x\n".
ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
CLASSES = ("scheduled", "manual", "pre-change", "final")
CONSISTENCY = ("writers-stopped", "online-app", "external")
_HEX_RE = re.compile(r"[0-9a-f]{64}")
_LINE_RE = re.compile(r"([0-9a-f]{64})  (.+)")
_DEPLOYMENT = ("seq", "release", "commit", "images", "manifest_sha256", "model_sha256")
_TOOL = ("version", "engine", "api", "cli", "compose", "arch", "os")


def default_naming() -> dict[str, str]:
    """`[backup.naming]` when the manifest sets none: one id template per class."""
    return dict.fromkeys(CLASSES, "{bundle.stamp}-{class}")


def _safe(path: str) -> bool:
    """Relative, '/'-separated, no empty, '.' or '..' segment, nothing sha256sum would escape."""
    return path.isprintable() and "\\" not in path and all(s not in ("", ".", "..") for s in path.split("/"))


def sums_text(files: list[tuple[str, str]]) -> bytes:
    """SHA256SUMS (sha256sum format) for (path relative to the bundle directory, sha256) pairs, sorted by path."""
    if len(dict(files)) != len(files):
        raise Refused("SHA256SUMS would list a path twice", code="invalid-bundle")
    for path, digest in files:
        if not (_safe(path) and _HEX_RE.fullmatch(digest)):
            raise Refused(f"SHA256SUMS cannot list {path!r}: unsafe path or not a sha256", code="invalid-bundle")
    return "".join(f"{digest}  {path}\n" for path, digest in sorted(files)).encode()


def parse_sums(data: bytes) -> dict[str, str]:
    """Path -> sha256 from SHA256SUMS; anything but exactly what sums_text writes is refused."""
    lines = data.decode(errors="surrogateescape").split("\n")
    out = {m[2]: m[1] for m in map(_LINE_RE.fullmatch, lines) if m}
    if not out or sums_text(list(out.items())) != data:
        raise Refused("SHA256SUMS is not in the canonical sorted '<sha256>  <path>' form", code="invalid-bundle")
    return out


def bundle_hash(sums: bytes) -> str:
    return sha256_hex(sums)


def bundle_doc(
    *,
    bundle_id: str,
    klass: str,
    instance: str,
    app: str,
    environment: str,
    lineage: str,
    created_at: str,
    freeze_at: str | None,
    consistency: str,
    deployment: Mapping[str, Any],
    schema: Mapping[str, Any] | None,
    stores: Mapping[str, int],
    entry: str,
    files: list[tuple[str, str, int]],
    meta: list[str],
    tool: Mapping[str, str],
    host: str,
) -> dict[str, Any]:
    """bundle.json with exactly the format 1 fields; extra keys of `deployment`, `schema` and `tool` are dropped.

    `files` lists the payload files as (path relative to the bundle directory, sha256, size).
    """
    if not ID_RE.fullmatch(bundle_id):
        raise Refused(f"bundle id {bundle_id!r} must match {ID_RE.pattern}", code="bundle-id")
    if klass not in CLASSES or consistency not in CONSISTENCY:
        raise Refused(f"bundle class {klass!r} or consistency {consistency!r} is not format 1", code="invalid-bundle")
    return {
        "format": FORMAT,
        "id": bundle_id,
        "class": klass,
        "instance": instance,
        "app": app,
        "environment": environment,
        "lineage": lineage,
        "created_at": created_at,
        "freeze_at": freeze_at,
        "consistency": consistency,
        "deployment": {k: deployment[k] for k in _DEPLOYMENT},
        "schema": None if schema is None else {"expected": schema["expected"], "actual": schema["actual"]},
        "stores": dict(stores),
        "payload": {
            "entry": entry,
            "files": [{"path": p, "size": size, "sha256": h} for p, h, size in sorted(files)],
            "total_bytes": sum(size for _, _, size in files),
        },
        "meta": sorted(meta),
        "tool": {k: tool[k] for k in _TOOL},
        "host": host,
    }
