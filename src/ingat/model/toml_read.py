"""Strict typed reading of a parsed TOML document into frozen dataclasses: errors name the dotted key path, and a key
that no field reads is unknown."""

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import fields
from typing import Any, get_args

from ingat.model.errors import Refused

NAME = re.compile("[a-z][a-z0-9_-]{0,62}")  # the default pattern for the names of named tables
# re.compile: a bad, too large or too deeply nested pattern, or clashing inline flags such as (?a)(?u)
REGEX_ERRORS = (re.error, OverflowError, RecursionError, ValueError)
_TYPES = {str: "a string", bool: "true or false", int: "an integer", list: "a list", dict: "a table"}


def _flat(table: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    for k, v in table.items():
        yield from _flat(v, f"{prefix}{k}.") if isinstance(v, dict) else [(prefix + k, v)]


class Table:
    """One TOML table: typed reads record errors under the dotted key path; keys never read are unknown."""

    def __init__(self, errs: list[str], tabs: list["Table"], path: str, data: object) -> None:
        self.errs, self.tabs, self.path, self.seen, self.subs = errs, tabs, path, set[str](), dict[str, Table]()
        self.d: dict[str, Any] = data if isinstance(data, dict) else {}
        tabs.append(self)
        errs.extend([] if isinstance(data, dict) else [f"{path}: must be a table"])

    def at(self, key: str) -> str:
        key = key if re.fullmatch("[A-Za-z0-9_-]+", key) else json.dumps(key)
        return f"{self.path}.{key}" if self.path else key

    def err(self, key: str, msg: str) -> None:
        self.errs.append(f"{self.at(key) if key else self.path}: {msg}")

    def get(self, key: str, typ: type, default: Any = None, req: bool = False) -> Any:
        self.seen.add(key)
        if isinstance(v := self.d.get(key), typ) and not (typ is int and isinstance(v, bool)):
            return v
        if key in self.d or req:
            self.err(key, f"must be {_TYPES[typ]}" if key in self.d else "is required")
        return default

    def o(self, key: str, choices: tuple[str, ...] = (), req: bool = False, rx: Any = None, default: Any = None) -> Any:
        v = self.get(key, str, None, req)
        if v is not None and choices and v not in choices:
            self.err(key, f"must be one of: {', '.join(choices)}")
        elif v is not None and rx and not rx.fullmatch(v):
            self.err(key, f"{v!r} does not match {rx.pattern}")
        elif v is not None:
            return v
        return default

    def strs(self, key: str, rx: Any = None, req: bool = False) -> tuple[str, ...]:
        v = self.get(key, list, [], req)
        if all(isinstance(x, str) and (rx is None or rx.fullmatch(x)) for x in v):
            return tuple(v)
        self.err(key, "must be a list of strings" + (f" matching {rx.pattern}" if rx else ""))
        return ()

    def sub(self, key: str) -> "Table":
        if key not in self.subs:
            self.subs[key] = Table(self.errs, self.tabs, self.at(key), self.get(key, dict, {}))
        return self.subs[key]

    def named(self, key: str, rx: re.Pattern[str]) -> dict[str, "Table"]:
        (t := self.sub(key)).seen.update(t.d)
        self.errs.extend(f"{t.at(k)}: the name does not match {rx.pattern}" for k in t.d if not rx.fullmatch(k))
        return {k: Table(self.errs, self.tabs, t.at(k), v) for k, v in t.d.items()}

    def strmap(self, key: str | None = None, rx: Any = None) -> dict[str, str]:
        (t := self if key is None else self.sub(key)).seen.update(t.d)
        self.errs.extend(f"{t.at(k)}: the key does not match {rx.pattern}" for k in t.d if rx and not rx.fullmatch(k))
        self.errs.extend(f"{t.at(k)}: must be a string" for k, v in t.d.items() if not isinstance(v, str))
        return {k: v for k, v in t.d.items() if isinstance(v, str)}

    def anyof(self, key: str) -> dict[str, tuple[Any, ...]]:
        """Dotted JSON paths to a value or an any-of list of values (MANIFEST_SPEC §5)."""
        out = {p: tuple(v) if isinstance(v, list) else (v,) for p, v in _flat(self.get(key, dict, {}))}
        bad = [p for p, vs in out.items() if not vs or not all(isinstance(x, str | int | float) for x in vs)]
        self.errs.extend(f"{self.at(key)}.{p}: must be a value or a non-empty list of values" for p in bad)
        return out

    def conv(self, key: str, conv: Callable[[str], Any], default: Any = None, req: bool = False) -> Any:
        try:
            return default if (v := self.o(key, req=req)) is None else conv(v)
        except Refused as e:
            self.err(key, e.message)
            return default

    def nest(self, key: str, nest: Any, how: str = "one", rx: Any = NAME) -> Any:
        """A nested table ("one", or "opt": None when absent), array of tables ("list") or named tables ("each")."""
        if how == "list":
            items = enumerate(self.get(key, list, []))
            return tuple(Table(self.errs, self.tabs, f"{self.at(key)}[{n}]", x).read(nest) for n, x in items)
        if how == "each":
            return {n: x.read(nest, name=n) for n, x in self.named(key, rx).items()}
        return self.sub(key).read(nest) if how == "one" or key in self.d else None

    def one_of(self, *keys: str) -> str:
        if len(found := [k for k in keys if k in self.d]) != 1:
            self.err("", f"needs exactly one of {', '.join(keys)}")
        return found[0] if found else ""

    def read(self, cls: Any, **kw: Any) -> Any:
        """Build `cls` from this table: every field not in `kw` is read as its `Annotated` spec (a dict) says."""
        for f in fields(cls):
            if f.name in kw:
                continue
            typ, meta = get_args(f.type)
            if (gate := (spec := dict(meta)).pop("when", None)) and kw.get(gate[0]) not in gate[1:]:
                kw[f.name] = typ() if callable(typ) else None
                continue
            t, key = self, spec.pop("key", f.name)
            while "." in key:
                head, key = key.split(".", 1)
                t = t.sub(head)
            how = spec.pop("read", None) or (
                Table.conv if "conv" in spec else Table.nest if "nest" in spec else _READ[typ]
            )
            kw[f.name] = how(t, key, **spec)
        return cls(**kw)


_READ: dict[Any, Callable[..., Any]] = {str | None: Table.o, tuple[str, ...]: Table.strs, dict[str, str]: Table.strmap}
_READ |= {str: lambda t, k, default="", **o: t.o(k, default=default, **o), int | None: lambda t, k: t.get(k, int)}
_READ[bool] = lambda t, k, default=False: t.get(k, bool, default)


def read_doc[C](doc: object, cls: type[C], **kw: Any) -> tuple[C, list[str]]:
    """`cls` read from a whole document, and every error (unknown keys last). Deep nesting raises RecursionError."""
    errs, tabs = list[str](), list[Table]()
    obj = Table(errs, tabs, "", doc).read(cls, **kw)
    errs.extend(f"{t.at(k)}: unknown key" for t in tabs for k in t.d if k not in t.seen)
    return obj, errs
