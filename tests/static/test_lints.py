"""T0 static lints over src/ (ARCHITECTURE §5.2, §10.1; CLAUDE.md, Architecture Rules): layering, budgets,
literals, effects."""

import ast
import functools
import os
import re
import textwrap
import unittest
from collections.abc import Callable
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PKG = SRC / "ingat"
NAMES_ENV = "INGAT_FORBIDDEN_NAMES"  # CI secret: comma-separated consumer names, never printed
FORBIDDEN = ("postgres", "pg_", "sqlite", "alembic", "backend", "frontend", "uvicorn", "node")
MAX_LINES = 600
RUNNER = "adapters/runner.py"
EXECUTOR = "core/executor.py"

TOP = {"__init__": "root", "__main__": "main"}  # top-level modules other than brand.py
# Layer -> lower layers it may import; every layer may also import itself, `brand` and the package root.
ALLOWED: dict[str, set[str]] = {
    "main": {"cli"},
    "cli": {"ops", "core", "model", "policy", "adapters", "store"},
    "ops": {"core", "model", "policy", "adapters", "store"},
    "core": {"model", "policy", "adapters", "store"},
    "policy": {"model"},
    "adapters": {"model"},
    "store": {"model"},
    "model": set(),
    "brand": set(),
    "root": set(),
}
SPAWN = ("subprocess", "ProcessPool")  # any reference containing these (asyncio.create_subprocess_exec included)
SPAWN_MODULES = {"pty", "multiprocessing"}
SPAWN_OS = {"setsid", "setpgid", "setpgrp", "killpg", "system", "popen", "fork", "forkpty"}  # + exec*, *spawn*
WRITE_MODULES = {"shutil", "tempfile"}
WRITE_OS = {
    "open", "fdopen", "mkdir", "makedirs", "mkfifo", "mknod", "rename", "renames", "replace", "unlink", "remove",
    "removedirs", "rmdir", "symlink", "link", "chmod", "lchmod", "fchmod", "chown", "lchown", "fchown", "truncate",
    "ftruncate", "utime", "setxattr", "removexattr", "O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND",
}  # fmt: skip
WRITE_METHODS = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "touch", "chmod", "lchmod"}
WRITE_METHODS |= {"symlink_to", "hardlink_to", "extract", "extractall"}  # plus Path.replace(target): one argument
OPENERS = ("open", "FileIO", "ZipFile", "TarFile")  # write when the mode argument has w, a, x or +
SYNC_ARGV = ("sync", "/bin/sync", "/usr/bin/sync")


def _norm(name: str) -> str:
    return "os" + name[5:] if name.split(".")[0] == "posix" else name


def _os(name: str) -> str:
    """The function name of an `os.<name>` reference, else ""."""
    head, _, attr = name.partition(".")
    return attr if head == "os" and "." not in attr else ""


class Mod:
    """One source module: its layer, the names it imports and the imported names' attributes it references."""

    def __init__(self, rel: str, text: str) -> None:
        self.rel, self.text, self.tree = rel, text, ast.parse(text, rel)
        parts = rel.removesuffix(".py").split("/")
        self.layer = parts[0] if len(parts) > 1 else TOP.get(parts[0], parts[0])
        package = ["ingat", *parts[:-1]]  # for an __init__ module this is the package itself
        self.aliases: dict[str, str] = {}
        self.imports: list[tuple[int, str]] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.imports.append((node.lineno, _norm(a.name)))
                    self.aliases[a.asname or a.name.split(".")[0]] = _norm(a.name if a.asname else a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                base = _norm(node.module or "")
                if node.level:
                    base = ".".join(package[: len(package) - node.level + 1] + ([node.module] if node.module else []))
                for a in node.names:
                    self.imports.append((node.lineno, f"{base}.{a.name}"))
                    self.aliases[a.asname or a.name] = f"{base}.{a.name}"
        attrs = [(n.lineno, q) for n in ast.walk(self.tree) if isinstance(n, ast.Attribute) and (q := self.qual(n))]
        self.refs = self.imports + attrs

    def qual(self, node: ast.expr) -> str | None:
        """Dotted name of an imported name or an attribute chain on one; None otherwise."""
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        if isinstance(node, ast.Attribute) and (base := self.qual(node.value)):
            return f"{base}.{node.attr}"
        return None


Rule = Callable[[Mod], list[str]]


@functools.cache
def modules() -> tuple[Mod, ...]:
    paths = sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)
    return tuple(Mod(p.relative_to(PKG).as_posix(), p.read_text("utf-8")) for p in paths)


def text_files() -> list[tuple[str, str]]:
    def wanted(p: Path) -> bool:
        parts = p.relative_to(SRC).parts
        return (
            p.is_file() and p.suffix != ".pyc" and not any(x == "__pycache__" or x.endswith(".egg-info") for x in parts)
        )

    return [
        (p.relative_to(SRC).as_posix(), p.read_bytes().decode("utf-8", "replace"))
        for p in sorted(SRC.rglob("*"))
        if wanted(p)
    ]


def hits(files: list[tuple[str, str]], needles: list[str] | tuple[str, ...]) -> list[tuple[str, int, int]]:
    """(file, line, needle index) for each case-insensitive match; line 0 is the file's own path."""
    return [
        (rel, no, i)
        for rel, text in files
        for no, line in enumerate([rel, *text.splitlines()])
        for i, needle in enumerate(needles)
        if needle in line.lower()
    ]


def layer_of(name: str) -> str | None:
    parts = name.split(".")
    if parts[0] != "ingat":
        return None
    if len(parts) == 1 or (parts[1].startswith("__") and parts[1] != "__main__"):
        return "root"  # the package itself or one of its dunder attributes
    return TOP.get(parts[1], parts[1])


def import_violations(m: Mod) -> list[str]:
    allowed = ALLOWED.get(m.layer)
    if allowed is None:
        return [f"{m.rel}: not in a known layer"]
    allowed = allowed | {m.layer, "brand", "root"}
    out = [f"{m.rel}:{ln}: imports {n}" for ln, n in m.imports if (t := layer_of(n)) is not None and t not in allowed]
    out += [f"{m.rel}:{ln}: dynamic import" for ln, n in m.refs if n == "importlib.import_module"]
    return out + [
        f"{m.rel}:{n.lineno}: dynamic import"
        for n in ast.walk(m.tree)
        if isinstance(n, ast.Name) and n.id == "__import__"
    ]


def size_violations(m: Mod) -> list[str]:
    lines = len(m.text.splitlines())
    return [f"{m.rel}: {lines} lines > {MAX_LINES}"] if lines > MAX_LINES else []


def spawn_violations(m: Mod) -> list[str]:
    if m.rel == RUNNER:
        return []
    return [
        f"{m.rel}:{ln}: {n}"
        for ln, n in m.refs
        if any(s in n for s in SPAWN)
        or n.split(".")[0] in SPAWN_MODULES
        or _os(n) in SPAWN_OS
        or _os(n).startswith(("exec", "spawn", "posix_spawn"))
    ]


def write_violations(m: Mod) -> list[str]:
    if m.layer == "store":
        return []
    out = [
        f"{m.rel}:{ln}: {n}"
        for ln, n in m.refs
        if n.split(".")[0] in WRITE_MODULES or (_os(n) in WRITE_OS and not (m.rel == RUNNER and n == "os.open"))
    ]
    for n in ast.walk(m.tree):
        if not isinstance(n, ast.Call):
            continue
        f, q = n.func, m.qual(n.func)
        if q and q.startswith(("os.", "ingat.store.")):
            continue  # os functions are checked above; store is the sanctioned writer
        method = isinstance(f, ast.Attribute) and q is None  # a call on an object, e.g. a Path
        attr = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        if attr in OPENERS:
            at = 0 if method else 1  # Path(p).open(mode) / open(file, mode), io.open, Path.open(p, mode)
            mode = next((k.value for k in n.keywords if k.arg == "mode"), n.args[at] if len(n.args) > at else None)
            literal = isinstance(mode, ast.Constant) and isinstance(mode.value, str)
            if mode is None or (method and not literal) or (literal and not set(mode.value) & set("wax+")):
                continue  # read mode, or an unknown object's open(x)
        elif not isinstance(f, ast.Attribute) or not (
            attr in WRITE_METHODS
            or (  # Path.replace(target) has one argument; str.replace two, datetime.replace keywords
                attr == "replace"
                and len(n.args) + len(n.keywords) == 1
                and not isinstance((n.args or [None])[0], ast.Starred)
                and all(k.arg == "target" for k in n.keywords)
            )
        ):
            continue
        out.append(f"{m.rel}:{n.lineno}: {attr}() writes a file")
    return out


def brand_violations(m: Mod) -> list[str]:
    if m.rel == "brand.py":
        return []
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    docs = {
        id(s.body[0].value)
        for s in ast.walk(m.tree)
        if isinstance(s, scopes)
        and s.body
        and isinstance(s.body[0], ast.Expr)
        and isinstance(s.body[0].value, ast.Constant)
    }
    return [
        f"{m.rel}:{n.lineno}: string constant names the product; use brand"
        for n in ast.walk(m.tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str | bytes)
        and id(n) not in docs
        and "ingat" in (n.value.decode("latin-1") if isinstance(n.value, bytes) else n.value).lower()
    ]


def token_violations(m: Mod) -> list[str]:
    if m.rel == EXECUTOR:
        return []
    out = []
    for n in ast.walk(m.tree):
        if isinstance(n, ast.Call):
            name = m.qual(n.func) or getattr(n.func, "id", None) or getattr(n.func, "attr", "")
            if name.rpartition(".")[2] == "EffectToken":
                out.append(f"{m.rel}:{n.lineno}: constructs EffectToken")
    return out


def sync_violations(m: Mod) -> list[str]:
    out = [f"{m.rel}:{ln}: {n}" for ln, n in m.refs if n == "os.sync"]
    return out + [
        f"{m.rel}:{n.lineno}: runs sync"
        for n in ast.walk(m.tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in SYNC_ARGV
    ]


def consumer_findings(files: list[tuple[str, str]], raw: str) -> list[str] | None:
    """None when no name is configured. A finding names the entry's index, never the name, even inside a path."""
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    if not names:
        return None
    mask = re.compile("|".join(map(re.escape, names)), re.IGNORECASE)
    return [f"{mask.sub('***', rel)}:{no}: consumer name #{i + 1}" for rel, no, i in hits(files, names)]


class StaticLints(unittest.TestCase):
    def assert_clean(self, rule: Rule) -> None:
        found = [v for m in modules() for v in rule(m)]
        self.assertFalse(found, "\n" + "\n".join(found))

    def test_tree_is_scanned(self) -> None:
        self.assertLessEqual({"brand.py", "__main__.py", "model/records.py"}, {m.rel for m in modules()})
        self.assertLessEqual({"ingat/brand.py", "ingat/tested.json"}, {rel for rel, _ in text_files()})

    def test_import_direction(self) -> None:
        self.assert_clean(import_violations)

    def test_module_size(self) -> None:
        self.assert_clean(size_violations)

    def test_forbidden_literals(self) -> None:
        found = [f"{rel}:{no}: {FORBIDDEN[i]!r}" for rel, no, i in hits(text_files(), FORBIDDEN)]
        self.assertFalse(found, "\n" + "\n".join(found))

    def test_consumer_names(self) -> None:
        found = consumer_findings(text_files(), os.environ.get(NAMES_ENV, ""))
        if found is None:
            self.skipTest(f"{NAMES_ENV} is not set: consumer-name check skipped")
        self.assertFalse(found, "\n" + "\n".join(found))

    def test_process_control_only_in_runner(self) -> None:
        self.assert_clean(spawn_violations)

    def test_file_writes_only_in_store(self) -> None:
        self.assert_clean(write_violations)

    def test_product_literals_only_in_brand(self) -> None:
        self.assert_clean(brand_violations)

    def test_effect_token_only_in_executor(self) -> None:
        self.assert_clean(token_violations)

    def test_no_sync(self) -> None:
        self.assert_clean(sync_violations)


class LintsDetect(unittest.TestCase):
    """Each lint flags what it forbids, so a clean tree is evidence rather than a vacuous pass."""

    def check(self, rule: Rule, rel: str, flagged: list[str], clean: list[str]) -> None:
        for src in flagged:
            with self.subTest(rel=rel, flagged=src):
                self.assertTrue(rule(Mod(rel, textwrap.dedent(src))))
        for src in clean:
            with self.subTest(rel=rel, clean=src):
                self.assertEqual(rule(Mod(rel, textwrap.dedent(src))), [])

    def test_imports(self) -> None:
        self.check(
            import_violations,
            "store/x.py",
            [
                "from ingat.core import plan",
                "from ..adapters import runner",
                "import ingat.cli.commands",
                "from ingat import ops",
                "import importlib\nimportlib.import_module(n)",
                "__import__(n)",
            ],
            ["from ..model import errors\nfrom ingat import brand, __version__\nfrom . import fs\nimport os"],
        )
        self.check(import_violations, "ops/x.py", ["from ingat.cli import render"], ["from ingat.core import plan"])
        self.check(import_violations, "util.py", [""], [])
        self.check(import_violations, "model/__init__.py", ["from ingat.policy import gate"], ["from . import errors"])
        self.check(import_violations, "__main__.py", [], ["from ingat.cli.commands import main"])
        core_ok = "from ingat.adapters.docker import Docker\nfrom ingat.store import fs\nfrom ingat.policy import gate"
        self.check(import_violations, "core/x.py", ["from ingat.ops import context"], [core_ok])

    def test_size(self) -> None:
        self.check(size_violations, "core/x.py", ["x = 1\n" * 601], ["x = 1\n" * 600])

    def test_spawn(self) -> None:
        flagged = [
            "import subprocess",
            "from subprocess import run",
            "import os\nos.killpg(1, 9)",
            "from os import setsid",
        ]
        flagged += ["import posix\nposix.execv(a, b)", "import os as o\no.system(c)", "import multiprocessing.pool"]
        flagged += ["import asyncio\nasyncio.create_subprocess_exec(a)", "from asyncio import subprocess"]
        flagged += ["from concurrent.futures import ProcessPoolExecutor", "import os\nos.setpgrp()"]
        flagged += ["import os\nos.posix_spawnp(a, b, c)"]
        flagged += ["from ingat.adapters import runner\nrunner.subprocess.run(a)"]
        self.check(spawn_violations, "core/x.py", flagged, ["import os\nos.kill(os.getpid(), 9)"])
        self.check(spawn_violations, RUNNER, [], ["import subprocess\nimport os\nos.setsid()\nos.killpg(1, 9)"])

    def test_writes(self) -> None:
        flagged = ['open(p, "w")', 'open(p, mode="ab")', 'open(p, "r+")', "open(p, m)", "import os\nos.replace(a, b)"]
        flagged += ["from os import unlink", "import os\nos.open(p, 0)", "import os\nos.fdopen(fd)", "import shutil"]
        flagged += ["import tempfile", 'Path(p).write_text("x")', "p.mkdir()", "p.replace(q)", 'p.open("w")']
        flagged += ["from pathlib import Path\nPath.touch(p)", 'import io\nio.open(p, "wb")', "p.replace(target=q)"]
        flagged += ['import zipfile\nzipfile.ZipFile(p, "w")', "import tarfile\ntarfile.open(p).extractall(d)"]
        flagged += ['import tarfile\ntarfile.open(p, mode="w:gz")', "import os\nos.setxattr(p, k, v)"]
        clean = [
            "open(p)",
            'open(p, "rb")',
            'a.replace("x", "y")',
            "t.replace(tzinfo=u)",
            "import os\nos.path.join(a, b)",
        ]
        clean += ["from ingat.store import fs\nfs.mkdir(p)", "journal.open(seq)", 'open(p, mode="r")']
        self.check(write_violations, "core/x.py", flagged, clean)
        runner_bad = ["import os\nos.unlink(p)", "import os\nos.open(p, os.O_WRONLY | os.O_CREAT)"]
        self.check(write_violations, RUNNER, runner_bad, ["import os\nos.open(p, os.O_RDONLY)"])
        self.check(write_violations, "store/fs.py", [], ["import os, shutil\nos.replace(a, b)\nopen(p, 'w')"])

    def test_brand(self) -> None:
        flagged = ['X = "INGAT_ROOT"', 'f"ingat-{x}"', "X = b'ingat'", 'def f():\n    x = 1\n    "ingat"']
        clean = [
            '"""Ingat docs."""\nclass A:\n    """Ingat."""\n    def f(self):\n        """ingat"""\n        return "x"'
        ]
        self.check(brand_violations, "cli/x.py", flagged, clean)
        self.check(brand_violations, "brand.py", [], ['CLI = "ingat"'])

    def test_token(self) -> None:
        flagged = ["EffectToken(1, 2)", "from ingat.adapters.docker import EffectToken as T\nT(1, 2)"]
        flagged += ["docker.EffectToken(1, 2)", "from ..adapters import docker\ndocker.EffectToken(1, 2)"]
        clean = ["from ingat.adapters.docker import EffectToken\ndef f(t: EffectToken) -> None: ..."]
        self.check(token_violations, "core/steps.py", flagged, clean)
        self.check(token_violations, EXECUTOR, [], ["EffectToken(1, 2)"])

    def test_sync(self) -> None:
        flagged = ["import os\nos.sync()", "from os import sync", 'run(["sync"])', 'run(["/bin/sync", "-f"])']
        self.check(sync_violations, "store/fs.py", flagged, ['import os\nos.fsync(f)\nx = "fsync"'])

    def test_consumer_names(self) -> None:
        files = [("ingat/zqxv/x.py", "a = 1\nB = 'ZQXV'\n"), ("ingat/y.py", "zz\n")]
        self.assertIsNone(consumer_findings(files, ""))
        self.assertIsNone(consumer_findings(files, " , "))
        found = consumer_findings(files, "qq, Zqxv ,")
        self.assertEqual(found, ["ingat/***/x.py:0: consumer name #2", "ingat/***/x.py:2: consumer name #2"])
        self.assertNotIn("zqxv", "".join(found or []).lower())

    def test_hits(self) -> None:
        found = hits([("a/inode.py", "x = 1\n# Backend\n")], FORBIDDEN)
        self.assertEqual(
            found, [("a/inode.py", 0, FORBIDDEN.index("node")), ("a/inode.py", 2, FORBIDDEN.index("backend"))]
        )
