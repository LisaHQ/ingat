"""The closed template vocabulary (MANIFEST_SPEC §3): argv elements and env values only, never shell text."""

import re
from collections.abc import Mapping

from ingat.model.errors import Refused

VAR_RE = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_-]+)?)\}")

# Heads of variables; heads ending in "." take a suffix (a param, service, argument or input name).
SIMPLE = frozenset(
    "instance environment host operator reason op.seq release commit target.release schema.expected"
    " bundle.id bundle.payload bundle.stamp class freeze_at".split()
)
PREFIXED = frozenset({"param.", "image.", "arg.", "input."})

_ALL = {"instance", "environment", "host", "release", "commit", "param."}
CONTEXTS: dict[str, frozenset[str]] = {
    "task": frozenset(_ALL | {"operator", "reason", "op.seq", "image.", "arg.", "input."}),
    "probe": frozenset(_ALL),
    "param": frozenset(_ALL),
    "build": frozenset(_ALL),
    "naming": frozenset(_ALL | {"bundle.stamp", "class", "target.release"}),
    "payload": frozenset(_ALL | {"bundle.id", "bundle.stamp", "class"}),
    "text": frozenset({"instance", "environment", "host"}),
}
# Extra task heads by where a task is used (manifest validation adds them per use).
TASK_EXTRAS: dict[str, frozenset[str]] = {
    "backup": frozenset({"schema.expected", "bundle.id", "bundle.payload"}),
    "verify": frozenset({"bundle.id", "bundle.payload"}),
    "restore": frozenset({"bundle.id", "bundle.payload", "target.release"}),
    "migrate": frozenset({"bundle.id", "bundle.payload", "freeze_at", "target.release"}),
}


def variables(template: str) -> list[str]:
    return VAR_RE.findall(template)


def _head(name: str) -> str:
    if name in SIMPLE:
        return name
    prefix, _, _ = name.partition(".")
    return prefix + "." if prefix + "." in PREFIXED else name


def check(template: str, allowed: frozenset[str], names: Mapping[str, set[str]] | None = None) -> list[str]:
    """Error messages for unknown variables, variables outside `allowed`, or unknown suffixes.

    `names` maps a prefixed head ("param.", "image.", "arg.", "input.") to its declared suffixes.
    """
    errors = []
    for name in variables(template):
        head = _head(name)
        if head not in SIMPLE and head not in PREFIXED:
            errors.append(f"unknown template variable {{{name}}}")
        elif head not in allowed:
            errors.append(f"template variable {{{name}}} is not allowed here")
        elif head in PREFIXED and names is not None and name[len(head) :] not in names.get(head, set()):
            errors.append(f"template variable {{{name}}} names an undeclared {head[:-1]}")
    return errors


def render(template: str, values: Mapping[str, str]) -> str:
    def one(m: re.Match[str]) -> str:
        if m.group(1) not in values:
            raise Refused(f"template variable {{{m.group(1)}}} has no value here", code="template")
        return values[m.group(1)]

    out = VAR_RE.sub(one, template)
    if "\x00" in out or "\n" in out or "\r" in out:
        raise Refused("a rendered template contains NUL or a line break", code="template")
    return out
