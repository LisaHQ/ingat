"""Strict, canonical JSON and the record rules shared by every persisted document (ARCHITECTURE §7.3, ADR-0023)."""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ingat.model.errors import CannotRun, Refused

STATE_SCHEMA = 1
ISO = "%Y-%m-%dT%H:%M:%SZ"
STAMP = "%Y%m%dT%H%M%SZ"


def dumps(doc: object) -> bytes:
    """Canonical bytes: sorted keys, compact, UTF-8, no NaN."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def pretty(doc: object) -> bytes:
    return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode() + b"\n"


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise Refused(f"duplicate JSON key {key!r}", code="invalid-json")
        out[key] = value
    return out


def _no_constant(name: str) -> None:
    raise Refused(f"JSON constant {name} is not allowed", code="invalid-json")


def loads(data: bytes) -> Any:
    try:
        return json.loads(data.decode(), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Refused(f"invalid JSON: {e}", code="invalid-json") from e


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def doc_hash(doc: object) -> str:
    return sha256_hex(dumps(doc))


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime(ISO)


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, ISO).replace(tzinfo=UTC)


def stamp(t: datetime) -> str:
    return t.astimezone(UTC).strftime(STAMP)


def new_doc(kind: str, **fields: Any) -> dict[str, Any]:
    return {"state_schema": STATE_SCHEMA, "kind": kind, **fields}


def check_schema(doc: object, kind: str) -> dict[str, Any]:
    """Accept a record of this kind and of a state schema this tool reads; unknown fields stay in the dict."""
    if not isinstance(doc, dict) or doc.get("kind") != kind:
        raise Refused(f"expected a {kind} record", code="invalid-record")
    schema = doc.get("state_schema")
    if not isinstance(schema, int) or isinstance(schema, bool):
        raise Refused(f"{kind} record has no state_schema", code="invalid-record")
    if schema > STATE_SCHEMA:
        raise CannotRun(f"{kind} record has state_schema {schema}; this tool reads {STATE_SCHEMA}", code="newer-state")
    return doc


def merged(doc: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    """A rewrite that keeps every field it does not own (ADR-0023)."""
    out = dict(doc)
    out.update(changes)
    return out
