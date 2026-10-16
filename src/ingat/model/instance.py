"""Instance config schema 1 (MANIFEST_SPEC §6): the owner's values for one instance; the tool never rewrites it."""

import ipaddress
import re
import tomllib
from dataclasses import dataclass, fields
from typing import Any
from urllib.parse import urlsplit

from ingat import brand
from ingat.model.errors import Refused
from ingat.model.manifest import Manifest
from ingat.model.records import sha256_hex
from ingat.model.toml_read import REGEX_ERRORS

# MANIFEST_SPEC §6.1 `^[a-z][a-z0-9]*(-[a-z0-9]+)*$` plus the 30-character limit; safe with match, search, fullmatch.
NAME_RE = re.compile(r"\A(?=.{1,30}\Z)[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
APP_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
ENVIRONMENT_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PORT_RE = re.compile(r"[1-9][0-9]{0,4}")
SETTABLE_KINDS = frozenset({"string", "port", "subnet"})

_TOP = ("instance", "name", "app", "environment", "disposable", "source", "params", "app_env", "backups", "monitor")
_SOURCE = ("kind", "repo", "key", "manifest", "accept")
_MONITOR: dict[str, type] = {"public_url": str, "cert_warn_days": int, "resolve_to": str, "ca_file": str}
_TYPE_NAMES: dict[type, str] = {str: "a string", int: "an integer", bool: "a boolean", dict: "a table"}


@dataclass(frozen=True, slots=True)
class Backups:
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 0
    pin_pre_change_days: int = 14
    max_age_hours: int = 26
    restore_test_max_age_days: int = 8


_BACKUP_KEYS = tuple(f.name for f in fields(Backups))


@dataclass(frozen=True, slots=True)
class Instance:
    instance: int
    name: str
    app: str
    environment: str
    disposable: bool
    source_kind: str
    repo: str | None
    key: str | None
    manifest_path: str
    accept: str | None
    params: dict[str, str]
    app_env: dict[str, str]
    backups: Backups
    monitor: dict[str, Any]
    raw_sha256: str


def _get(table: dict[str, Any], path: str, key: str, typ: type, errors: list[str], default: Any = None) -> Any:
    """`table[key]` when its type is exactly `typ` (a bool is not an int), else `default`."""
    if key not in table:
        return default
    if type(table[key]) is not typ:
        errors.append(f"{path}{key}: expected {_TYPE_NAMES[typ]}")
        return default
    return table[key]


def _unknown(table: dict[str, Any], path: str, allowed: tuple[str, ...], errors: list[str]) -> None:
    errors.extend(f"{path}{k}: unknown key" for k in sorted(set(table) - set(allowed)))


def _strings(doc: dict[str, Any], key: str, errors: list[str]) -> dict[str, str]:
    """String values, rendered single-quoted later: ', a line break or NUL is refused (MANIFEST_SPEC §2.3)."""
    table: dict[str, Any] = _get(doc, "", key, dict, errors, {})
    errors.extend(f"{key}.{k}: expected a string" for k, v in table.items() if type(v) is not str)
    errors.extend(
        f"{key}.{k}: must not contain ', a line break or NUL"
        for k, v in table.items()
        if type(v) is str and set(v) & set("'\n\r\0")
    )
    return {k: v for k, v in table.items() if type(v) is str}


def _relative_ok(path: str) -> bool:
    return path.isprintable() and all(s not in ("", ".", "..") for s in path.split("/"))


def _repo_ok(url: str) -> bool:
    """ssh://[user@]host/path, https://host/path or file:///absolute/path.

    Never a password, https userinfo (tokens sit there), an option-like user or host, or a file path that git's
    percent-decoding or a '..' segment could move out of the directory the caller checks.
    """
    if not url.isprintable() or " " in url:
        return False
    try:
        u = urlsplit(url)
        _ = u.port
    except ValueError:
        return False
    if u.query or u.fragment or u.password is not None or any(s.startswith("-") for s in u.netloc.split("@")):
        return False
    if u.scheme == "file":
        return url.startswith("file:///") and "%" not in url and _relative_ok(u.path[1:])
    if u.scheme == "https" and u.username is not None:
        return False
    return u.scheme in ("ssh", "https") and bool(u.hostname) and len(u.path) > 1


def _source(doc: dict[str, Any], errors: list[str]) -> tuple[str, str | None, str | None, str, str | None]:
    src: dict[str, Any] = _get(doc, "", "source", dict, errors, {})
    _unknown(src, "source.", _SOURCE, errors)
    kind = _get(src, "source.", "kind", str, errors, "git")
    repo = _get(src, "source.", "repo", str, errors)
    key = _get(src, "source.", "key", str, errors)
    manifest_path = _get(src, "source.", "manifest", str, errors, brand.MANIFEST_FILE)
    accept = _get(src, "source.", "accept", str, errors)
    if kind == "image":
        errors.extend(f"source.{k}: not used by an image source" for k in _SOURCE[1:] if k in src)
    elif kind != "git":
        errors.append('source.kind: must be "git" or "image"')
    else:
        if "repo" not in src:
            errors.append("source.repo: required for a git source")
        elif repo is not None and not _repo_ok(repo):
            errors.append(
                "source.repo: must be ssh://[user@]host/path, https://host/path or file:///absolute/path,"
                " without a password, an https user, a query, a fragment, a leading '-',"
                " or '%', '.', '..' or empty segments in a file path"
            )
        if key is not None and not KEY_RE.fullmatch(key):
            errors.append(f"source.key: must match {KEY_RE.pattern}")
        if not _relative_ok(manifest_path):
            errors.append("source.manifest: must be a relative path without empty, '.' or '..' segments")
        if accept is not None:
            try:
                re.compile(accept)
            except REGEX_ERRORS as e:
                errors.append(f"source.accept: invalid regular expression ({e})")
    return kind, repo, key, manifest_path, accept


def parse_instance(data: bytes) -> Instance:
    """Strict parse; Refused(code="invalid-instance") lists every error, one per line, by key path."""
    try:
        doc = tomllib.loads(data.decode())
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError) as e:  # the TOML parser recurses
        raise Refused(f"instance config: {e}", code="invalid-instance") from e
    errors: list[str] = []
    _unknown(doc, "", _TOP, errors)
    if type(doc.get("instance")) is not int or doc["instance"] != 1:
        errors.append("instance: must be 1")
    for item, regex in (("name", NAME_RE), ("app", APP_RE), ("environment", ENVIRONMENT_RE)):
        value = _get(doc, "", item, str, errors)
        if item not in doc:
            errors.append(f"{item}: required")
        elif value is not None and not regex.fullmatch(value):
            errors.append(f"{item}: must match {regex.pattern}")
    disposable = _get(doc, "", "disposable", bool, errors, False)
    source = _source(doc, errors)
    params = _strings(doc, "params", errors)
    app_env = _strings(doc, "app_env", errors)
    table: dict[str, Any] = _get(doc, "", "backups", dict, errors, {})
    _unknown(table, "backups.", _BACKUP_KEYS, errors)
    defaults = Backups()
    retention = {k: _get(table, "backups.", k, int, errors, getattr(defaults, k)) for k in _BACKUP_KEYS}
    errors.extend(f"backups.{k}: must not be negative" for k, v in retention.items() if v < 0)
    monitor: dict[str, Any] = _get(doc, "", "monitor", dict, errors, {})
    _unknown(monitor, "monitor.", tuple(_MONITOR), errors)
    for k, typ in _MONITOR.items():
        _get(monitor, "monitor.", k, typ, errors)
    if errors:
        raise Refused("\n".join(errors), code="invalid-instance")
    name, app, environment = doc["name"], doc["app"], doc["environment"]
    rest = params, app_env, Backups(**retention), monitor, sha256_hex(data)
    return Instance(1, name, app, environment, disposable, *source, *rest)


def _value_ok(kind: str, value: str) -> bool:
    if kind == "port":
        return PORT_RE.fullmatch(value) is not None and int(value) <= 65535
    try:  # the canonical CIDR form Docker's IPAM takes: no netmask notation, no IPv6 zone
        return str(ipaddress.ip_network(value)) == value and "%" not in value
    except ValueError:
        return False


def validate_against(inst: Instance, m: Manifest) -> list[str]:
    """Errors (key path first) where the instance's values do not fit the manifest; values are never echoed."""
    errors: list[str] = []
    if inst.app != m.app:
        errors.append(f"app: the manifest's app is {m.app!r}")
    if inst.source_kind != m.source_kind:
        errors.append(f"source.kind: the manifest's source kind is {m.source_kind!r}")
    for name, value in sorted(inst.params.items()):
        p = m.params.get(name)
        if p is None:
            errors.append(f"params.{name}: not declared by the manifest")
        elif p.kind not in SETTABLE_KINDS:
            errors.append(f"params.{name}: the tool sets {p.kind} params, not the instance")
        elif p.kind != "string" and not _value_ok(p.kind, value):
            errors.append(f"params.{name}: not a valid {p.kind}")
        elif p.pattern is not None and not re.fullmatch(p.pattern, value):
            errors.append(f"params.{name}: does not match the manifest's pattern")
    errors.extend(
        f"params.{name}: required"
        for name, p in sorted(m.params.items())
        if p.kind == "string" and p.required and name not in inst.params
    )
    keys = m.app_env.keys if m.app_env is not None else {}
    forbidden = m.app_env.forbidden if m.app_env is not None else ()
    for name, value in sorted(inst.app_env.items()):
        k = keys.get(name)
        if name in forbidden:
            errors.append(f"app_env.{name}: forbidden by the manifest")
        elif k is None:
            errors.append(f"app_env.{name}: not declared by the manifest")
        elif k.secret:
            errors.append(f"app_env.{name}: a secret key; its value is set with `secret set`, never here")
        elif k.tool_managed:
            errors.append(f"app_env.{name}: tool-managed; only holds and [rollback] env set it")
        elif k.allowed is not None and value not in k.allowed:
            errors.append(f"app_env.{name}: must be one of {', '.join(k.allowed)}")
        elif k.pattern is not None and not re.fullmatch(k.pattern, value):
            errors.append(f"app_env.{name}: does not match the manifest's pattern")
    errors.extend(
        f"app_env.{name}: required"
        for name, k in sorted(keys.items())
        if k.required and not k.secret and name not in inst.app_env
    )
    return errors
