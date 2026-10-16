"""The generated Compose override (ARCHITECTURE §6.2, ADR-0006): data in, a deterministic YAML subset out."""

import enum
import json
import re
from collections.abc import Collection, Iterable, Iterator, Mapping
from typing import Any

LOGGING = {"driver": "local", "options": {"max-size": "10m", "max-file": "3"}}


class Reset(enum.Enum):
    """Compose's `!reset` tag: drops the app file's value for that key."""

    NULL = "!reset null"
    LIST = "!reset []"


RESET_NULL = Reset.NULL
RESET_LIST = Reset.LIST
_UNPRINTABLE = re.compile(r"[^\x20-\x7e]")


def _json(v: object) -> str:
    # YAML refuses JSON's surrogate escapes; \UXXXXXXXX also makes Compose refuse a lone surrogate.
    return _UNPRINTABLE.sub(lambda m: f"\\U{ord(m[0]):08x}", json.dumps(v, ensure_ascii=False, allow_nan=False))


def _scalar(v: object) -> str:
    if isinstance(v, Reset):
        return v.value
    return _json(v.replace("$", "$$") if isinstance(v, str) else v)


def _lines(m: Mapping[str, Any], indent: str) -> Iterator[str]:
    for key in sorted(m):
        v = m[key]
        if isinstance(v, Mapping) and v:
            yield f"{indent}{_json(key)}:"
            yield from _lines(v, indent + "  ")
        elif isinstance(v, Mapping):
            yield f"{indent}{_json(key)}: {{}}"
        elif isinstance(v, list | tuple):
            yield f"{indent}{_json(key)}: [{', '.join(map(_scalar, v))}]"
        else:
            yield f"{indent}{_json(key)}: {_scalar(v)}"


def render(spec: Mapping[str, Any]) -> str:
    """Sorted JSON-quoted keys; string values are literal (`$` doubled, so Compose never interpolates them)."""
    return "".join(line + "\n" for line in _lines(spec, ""))


def live(
    services: Mapping[str, Mapping[str, Any]],
    *,
    instance: str,
    ns: str,
    images: Mapping[str, str],
    stores: Mapping[str, str],
    networks: Iterable[str],
    extra_env: Mapping[str, Mapping[str, str]] | None = None,
    none_logging: Collection[str] = (),
) -> dict[str, Any]:
    """`services`: every service of the app's own model (all profiles, no override); `stores`: volume key -> name."""
    out: dict[str, Any] = {}
    for name, svc in services.items():
        item: dict[str, Any] = {
            "image": images[name],
            "pull_policy": "never",
            "labels": {ns + "instance": instance, ns + "role": "app"},
        }
        if "build" in svc:
            item["build"] = RESET_NULL
        if name in none_logging:
            item["logging"] = {"driver": "none"}
        elif "logging" not in svc:
            item["logging"] = LOGGING
        if extra_env and extra_env.get(name):
            item["environment"] = dict(extra_env[name])
        out[name] = item
    spec: dict[str, Any] = {
        "services": out,
        "networks": {n: {"labels": {ns + "instance": instance}} for n in {*networks, "default"}},
    }
    if stores:
        spec["volumes"] = {key: {"name": name, "external": True} for key, name in stores.items()}
    return spec


def isolated(
    services: Mapping[str, Mapping[str, Any]],
    *,
    instance: str,
    ns: str,
    images: Mapping[str, str],
    stores: Mapping[str, str],
    networks: Iterable[str],
    op: int,
    holds: Mapping[str, Mapping[str, str]],
    extra_env: Mapping[str, Mapping[str, str]] | None = None,
    none_logging: Collection[str] = (),
) -> dict[str, Any]:
    """Live override plus isolation (LIFECYCLE §5.7): internal networks, no published ports, op label, holds.

    Network names are reset so an app network with a fixed `name:` is never shared with the live project (F13).
    """
    env = {name: {**(extra_env or {}).get(name, {}), **holds.get(name, {})} for name in services}
    spec = live(
        services,
        instance=instance,
        ns=ns,
        images=images,
        stores=stores,
        networks=networks,
        extra_env=env,
        none_logging=none_logging,
    )
    for item in spec["services"].values():
        item["ports"] = RESET_LIST
        item["labels"][ns + "op"] = str(op)
    for item in spec["networks"].values():
        item.update(internal=True, name=RESET_NULL)
        item["labels"][ns + "op"] = str(op)
    return spec
