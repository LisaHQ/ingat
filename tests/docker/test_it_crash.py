"""Suite 3, the crash matrix (ARCHITECTURE §10.3; LIFECYCLE §3.2-§3.5; ARCHITECTURE §4.2-§4.5).

The test-only hook INGAT_CRASH_AT (`<step>:<intent|done>:<before|after>` or `<step>:task`) SIGKILLs the process that
journals an operation (the executor, or the CLI of a terminal task) at that point; the wrapper's `env -i` never passes
it, so a crash run is `ScratchHost.cli_direct`. Then the suite does what the owner does: `status --json` and the `next`
it prints (typed on a pty for class C) until status is clean or in its documented state (no bundle yet after a first
install). Convergence: the crashed operation closed as its last command decided; every durable file kept (records,
plans, catalog, sealed bundles, generation markers, append-only journals and verification logs, the app's data: the
files of the outbound jobs it delivered), a bundle removed only by a planned deletion with its tombstone; no task
container, executor, isolated project, drill generation, subnet entry or operation scratch left; the live app ready on
its recorded schema. M1 migrates the live generation in place after the pre-change bundle, so "the previous generation
intact" is that bundle sealed, verified and kept, and the live data kept. The fixture's tasks run behind a one-second
sleep (`sh -c 'sleep 1 && exec "$@"' sh fx-lite ...`), so the executor's half-second tick sees each task container
alive and `<n>:task` fires mid-task.

T1 (class Named, one fx-lite-ci instance, each case starting where the last one converged): an install killed at its
pause and in its allowed terminal task, then resumed; an online backup killed in its task, auto-abandoned by the next
`scheduled backup`; data-changing updates killed before the forward point (abandoned: unchanged), in the migrate task
(resumed: Compose's `run --rm` leaves no exit code, so the idempotent migrate runs again), with an exited task
container the daemon kept (its exit code is the step's evidence), and after the forward point (abandoned: frozen,
then the way forward); a backup killed right after its seal (resumed on that one bundle, LIFECYCLE §3.3). The
generated matrix over every M1 plan, nightly with INGAT_TEST_FULL_MATRIX=1, is tests/docker/test_it_crash_matrix.py, on
this module's machinery and a scratch host of its own."""

import hashlib
import json
import os
import re
import secrets
import shlex
import time
import unittest
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.store import state
from tests.harness import host

CLI = brand.CLI
CRASH = brand.env("CRASH_AT")
FULL = os.environ.get(brand.env("TEST_FULL_MATRIX")) == "1"
TYPED = ("deploy", "start", "stop", "restart", "resume", "abandon", "task")  # run on a pty, the name typed if asked
SLOW = ("migrate", "backup", "restore", "bootstrap-new-code", "queue-status", "queue-resume")
WAIT = 'sleep 1 && exec "$@"'
FIRST_INSTALL = frozenset({"backup-old", "restore-test-old"})  # status right after a first install (§4.15)
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
STEP = re.compile(r"^ *([0-9]+)\. ([A-Za-z]+)([^\n]*?) +\[([^\]\n]*)\]$", re.M)  # a plan summary line
CODE_LINE = re.compile(r"^[A-Za-z0-9_-]{16}$", re.M)  # fx-lite's single-use bootstrap code
SCRATCH = ("stage", "in", "bundle")  # operation scratch; dot entries (.opening, .incoming-*) are scratch too
SKIP = ("lock.holder.json", "record.json", "cancel")
LOGS = ("steps.jsonl", "progress.log")
COMPOSE = {"service": "app", "oneoff": "True"}  # how `compose run` labels a task container, beside its project
H: host.ScratchHost
REG: host.Registry
COMMITS: list[str] = []
PUSHED: set[str] = set()
PORTS: dict[str, int] = {}
Durable = dict[str, tuple[str, bytes]]
Plan = list[dict[str, Any]]


def setUpModule() -> None:
    global H, REG, COMMITS
    PUSHED.clear()  # images of an earlier host's registry
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    edits: list[Mapping[str, str | bytes | None]] = [{"ingat.toml": manifest()}]
    edits += [{"CHANGES": f"commit {i}\n"} for i in range(2, (48 if FULL else 4) + 1)]
    REG = host.Registry()
    unittest.addModuleCleanup(REG.close)  # after the host's containers are gone: they run its images
    H = host.ScratchHost("crash")
    unittest.addModuleCleanup(H.close)
    must(H.install())
    H.certify()
    COMMITS = H.fixture_repo("fx-lite-ci", edits, base="fx-lite")


def manifest() -> str:
    """tests/data/fx-lite-ci's manifest with every task of SLOW behind WAIT."""
    text, old = (host.REPO / "tests" / "data" / "fx-lite-ci" / "ingat.toml").read_text(), 'argv = ["fx-lite", '
    for task in SLOW:
        head = re.compile(rf"^\[tasks\.{task}\][ \t]*(#.*)?$", re.M).search(text).start()  # type: ignore[union-attr]
        at = text.index(old, head)
        if at > (text.find("\n[", head) % (len(text) + 1)):  # -1: the last section
            raise AssertionError(f"tasks.{task} has no fx-lite argv")
        text = text[:at] + f'argv = ["sh", "-c", {json.dumps(WAIT)}, "sh", "fx-lite", ' + text[at + len(old) :]
    return text


def image(i: int) -> str:
    """COMMITS[i], its image pushed (once) with schema i + 1: every later commit migrates further."""
    if COMMITS[i] not in PUSHED:
        REG.push(COMMITS[i], i + 1, H.claim)
        PUSHED.add(COMMITS[i])
    return COMMITS[i]


def must(res: host.Result, code: int = 0) -> str:
    if res[0] != code:
        raise AssertionError(f"exit {res[0]}, not {code}:\n{res[1]}{res[2]}")
    return res[1]


def typed(name: str, *argv: str, code: int = 0) -> str:
    """A class C command on a pty, the instance name typed at its approval prompt."""
    return must(H.cli(*argv, tty=True, answer=name), code)


def get(url: str) -> Any:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=10) as r:
        body = r.read().decode()
    return json.loads(body) if body.startswith("{") else body


def instance(prefix: str, app: str = "fx-lite", ref: str = "") -> str:
    """`init` (typed) of a new instance at `ref` (default: the first commit) on a port of its own."""
    name, port = f"{prefix}{secrets.token_hex(3)}", host.free_port()
    while os.path.exists(H.layout.allocation("port", str(port))):  # an instance whose containers are gone holds it
        port = host.free_port()
    lines = ["instance = 1", f'name = "{name}"', f'app = "{app}"', 'environment = "test"', "[source]"]
    if app == "fx-lite":
        params = {"FXLITE_REGISTRY": REG.address, "FXLITE_PORT": str(port)}
        lines += [f'repo = "{H.repo_url("fx-lite-ci")}"', "[params]", *(f'{k} = "{v}"' for k, v in params.items())]
        lines += ["[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items())]  # last: an appended line joins it
    else:
        lines += [f'repo = "{H.repo_url(app)}"', "[params]", f'FXWEB_IMAGE = "{H.image}"', f'FXWEB_PORT = "{port}"']
    typed(name, "init", name, "--config", H.inbox(f"{name}.toml", "\n".join(lines) + "\n"), "--ref", ref or image(0))
    PORTS[name] = port
    return name


def enqueue(name: str, count: int = 3) -> None:
    """Data the app holds from here on: outbound jobs it delivers in capture mode, a file each under captured/."""
    for _ in range(count):
        host.docker("exec", f"{name}-app-1", "fx-lite", "enqueue")
    path, end = f"{H.layout.data_gen(name, 'data', 'g1')}/captured", time.monotonic() + 60
    while len(os.listdir(path) if os.path.isdir(path) else []) < count:
        if time.monotonic() > end:
            raise AssertionError(f"{name} delivered no {count} jobs")
        time.sleep(0.5)


def op_dir(name: str, seq: int) -> str:
    [d] = [e for e in os.listdir(H.layout.ops_dir(name)) if e.partition("-")[0] == str(seq)]
    return os.path.join(H.layout.ops_dir(name), d)


def newest(name: str, kind: str) -> int:
    return max(int(e.partition("-")[0]) for e in os.listdir(H.layout.ops_dir(name)) if e.partition("-")[2] == kind)


def plan_steps(name: str, seq: int) -> Plan:
    steps: Plan = state.read_doc(f"{op_dir(name, seq)}/plan.json", "plan")["steps"]
    return steps


def journal(name: str, seq: int, step: int | None = None) -> list[dict[str, Any]]:
    recs = [json.loads(x) for x in Path(op_dir(name, seq), "steps.jsonl").read_text().splitlines() if x]
    return [r for r in recs if step is None or r["step"] == step]


def result(name: str, seq: int) -> dict[str, Any]:
    path = f"{op_dir(name, seq)}/result.json"
    return state.read_doc(path, "result") if os.path.exists(path) else {}


def deployment(name: str) -> dict[str, Any]:
    return state.read_doc(H.layout.deployment_json(name, H.record(name)["current_deployment"]), "deployment")


def sealed(name: str, seq: int) -> str:
    """The bundle the capture group of operation `seq` sealed."""
    seal = next(s["n"] for s in plan_steps(name, seq) if s["type"] == "CaptureBundle" and s["args"]["phase"] == "seal")
    return str(next(r["evidence"]["bundle_id"] for r in journal(name, seq, seal) if r["phase"] == "done"))


def points(plan: Plan, start: bool = True, close: bool = True) -> list[str]:
    """`1:intent:before`, per step `intent:after`, `task` and `done:before` (a Pause's done is its resume's), then
    the close decision (journal step 0) before and after it is written."""
    out = ["1:intent:before"] if start else []
    for s in plan:
        out += [f"{s['n']}:intent:after"] + [f"{s['n']}:task"] * (s["type"] == "RunTask")
        out += [f"{s['n']}:done:before"] * (s["type"] != "Pause")
    return out + (["0:done:before", "0:done:after"] if close else [])


def durable(name: str) -> Durable:
    """What a crash and its recovery must keep: `hash` of write-once files, the bytes of append-only `log`s, the
    presence (`seen`) of secret-bearing files and generation directories, and the app's captured/ files."""
    out: Durable = {}
    tops = {"inst": H.layout.inst(name), "bundle": f"{H.backups}/{name}", "data": f"{H.root}/data/{name}"}
    for key, top in tops.items():
        for d, dirs, files in os.walk(top):
            dirs[:] = sorted(x for x in dirs if x not in SCRATCH and not x.startswith("."))
            rel = os.path.relpath(d, top).replace(os.sep, "/") + "/" if d != top else ""
            if key == "data":  # <store>/<gen>.json, <store>/<gen>/ and <store>/<gen>/captured/*
                out |= {f"data/{rel}": ("seen", b"")} if rel.count("/") == 2 else {}
                if not (rel.count("/") == 1 or (rel.count("/") == 3 and rel.endswith("/captured/"))):
                    continue
            for f in (x for x in files if x not in SKIP):
                path, k = os.path.join(d, f), f"{key}/{rel}{f}"
                if "/secrets/" in k or k.startswith("inst/env/"):
                    out[k] = ("seen", b"")
                elif f in LOGS or k.startswith("inst/verifications/"):
                    out[k] = ("log", Path(path).read_bytes())
                else:
                    out[k] = ("hash", hashlib.sha256(Path(path).read_bytes()).hexdigest().encode())
    return out


def lost(before: Durable, after: Durable) -> list[str]:
    """Entries of `before` that `after` does not keep; a bundle whose tombstone exists was deleted as planned."""
    pruned = {k.rsplit("/", 1)[1].removesuffix(".pruned.json") for k in after if k.endswith(".pruned.json")}
    out = []
    for k, (how, value) in before.items():
        if k.startswith("bundle/") and k.split("/")[1] in pruned:
            continue
        if k not in after:
            out.append(f"{k} deleted")
        elif (how == "log" and not after[k][1].startswith(value)) or (how == "hash" and after[k][1] != value):
            out.append(f"{k} changed")
    return out


class Crashes(unittest.TestCase):
    """Crash, observe, converge, check."""

    maxDiff = None

    def status(self, name: str) -> tuple[int, dict[str, Any]]:
        res = H.cli("status", name, "--json")
        return res[0], json.loads(res[1])

    def settle(self, name: str) -> None:
        """Until the executor is gone and no task container of the instance runs or awaits its auto-removal (one
        created but never started stays: it is evidence of nothing)."""
        self.assertTrue(host.wait_gone(brand.executor_name(name), 300))
        flt = ["--filter", f"label={brand.label('role')}=task", "--filter", f"label={brand.label('instance')}={name}"]
        end = time.monotonic() + 300
        while True:
            found = host.inspect("container", host.docker("ps", "-aq", "--no-trunc", *flt).split())
            st = [(c["Name"], c["State"], c["HostConfig"].get("AutoRemove")) for c in found]
            if not (busy := [n for n, s, auto in st if s["Running"] or (auto and s["Status"] != "created")]):
                return
            self.assertLess(time.monotonic(), end, f"task containers still run: {busy}")
            time.sleep(0.5)

    def preview(self, name: str, *argv: str) -> list[tuple[int, str, str, str]]:
        """(n, type, arguments, marks) of the plan a class C command shows before its approval, refused here by a
        wrong name, which writes nothing (F2)."""
        tree = host.tree_hash(H.layout.inst(name))
        out = must(H.cli(*argv, tty=True, answer="-"), 1)
        self.assertIn("not approved; nothing was changed", out)
        self.assertEqual(host.tree_hash(H.layout.inst(name)), tree)
        found = [(int(n), t, args, marks) for n, t, args, marks in STEP.findall(out)]
        self.assertEqual([n for n, *_ in found], list(range(1, len(found) + 1)), out)
        return found

    def crash(self, name: str, argv: list[str], point: str, *, tty: bool, cli: bool = False) -> int:
        """Run `argv` with the hook at `point`: the executor (with `cli`: the CLI of a terminal task) is killed there
        and the operation stays open; returns its seq."""
        code, out, err = H.cli_direct(*argv, env={CRASH: point}, tty=tty, answer=name if tty else None)
        self.settle(name)
        if cli:
            self.assertEqual(code, 137, f"{point}: the CLI was not killed\n{out}{err}")
        else:
            gone = "The background worker that was running this operation disappeared" in out + err
            self.assertEqual((code, gone), (4, True), f"{point}:\n{out}{err}")
        opened = H.record(name)["open_op"]
        self.assertIsNotNone(opened, f"{point}: no operation is open\n{out}{err}")
        return int(opened["seq"])

    def converge(self, name: str, settled: frozenset[str] = frozenset()) -> list[str]:
        """Run what `status --json` names next until it is clean (or shows only `settled` codes); each must succeed
        (exit 0, or 4 where an install pauses again). Returns those commands."""
        trail: list[str] = []
        for _ in range(6):
            code, doc = self.status(name)
            if code == 0 or (code == 5 and set(doc["attention"]) <= settled):
                return trail
            nxt = doc["next"]
            self.assertTrue(isinstance(nxt, str) and nxt.startswith(f"{CLI} "), doc)
            argv = shlex.split(nxt)[1:]
            res = H.cli(*argv, tty=argv[0] in TYPED, answer=name if argv[0] in TYPED else None)
            trail.append(nxt)
            self.assertIn(res[0], (0, 4), f"{nxt} after {trail[:-1]}:\n{res[1]}{res[2]}")
            if res[0] == 4:
                self.settle(name)
                ops = self.status(name)[1]["instance"]["operations"]
                self.assertEqual([o["state"] for o in ops], ["paused"], f"{nxt} ended 4:\n{res[1]}{res[2]}")
        self.fail(f"{name} did not converge: {trail}")

    def converged(self, name: str, seq: int, before: Durable, trail: list[str], outcome: str = "") -> None:
        want = outcome or ("abandoned" if any(t.split()[1] == "abandon" for t in trail) else "completed")
        self.assertEqual(result(name, seq).get("outcome"), want, (trail, result(name, seq)))
        self.assertEqual(lost(before, durable(name)), [], trail)
        self.clean(name)
        if H.record(name)["state"] == "running":
            self.ready(name)

    def clean(self, name: str) -> None:
        """No task container, executor, isolated project, drill generation, subnet entry, unpublished bundle copy or
        operation scratch (stage, input copy, bundle being built) left; no operation open."""
        flt = ["--filter", f"label={brand.label('role')}=task", "--filter", f"label={brand.label('instance')}={name}"]
        self.assertEqual(host.docker("ps", "-aq", *flt), "")
        self.assertFalse(host.present("container", brand.executor_name(name)))
        inv = host.inventory(name)
        iso = [c[1] for c in inv["containers"]] + [n for _, n in inv["networks"]]
        self.assertEqual([x for x in iso if x.startswith(f"{name}--")], [])
        data, alloc, bdir = f"{H.root}/data/{name}", H.layout.allocations_dir, f"{H.backups}/{name}"
        stores, ops = os.listdir(data) if os.path.isdir(data) else [], H.layout.ops_dir(name)
        self.assertEqual([f"{s}/{g}" for s in stores for g in os.listdir(f"{data}/{s}") if g.startswith("t")], [])
        subnets = [f for f in os.listdir(alloc) if f.startswith("subnet-")]
        self.assertEqual([f for f in subnets if state.read_doc(f"{alloc}/{f}", "allocation")["instance"] == name], [])
        self.assertEqual([f for f in os.listdir(bdir) if f.startswith(".")] if os.path.isdir(bdir) else [], [])
        self.assertEqual([f"{e}/{x}" for e in os.listdir(ops) for x in SCRATCH if os.path.exists(f"{ops}/{e}/{x}")], [])
        self.assertEqual(state.open_ops(H.layout, name), [])

    def ready(self, name: str) -> None:
        """The live app answers on its recorded release (fx-lite: ready, on the schema of the deployment)."""
        url, dep = f"http://127.0.0.1:{PORTS[name]}", deployment(name)
        if H.record(name)["app"] != "fx-lite":
            self.assertIn(f"fx-web {dep['release']}", str(get(f"{url}/")))
            return
        doc = get(f"{url}/api/ready")
        self.assertEqual((doc["status"], doc["schema"]["actual"]), ("ready", doc["schema"]["expected"]), doc)
        self.assertEqual(doc["schema"]["actual"], dep["schema"]["actual"])

    def case(self, name: str, argv: list[str], point: str, ref: list[str], tty: bool = False, cli: bool = False,
             settled: frozenset[str] = frozenset()) -> list[str]:  # fmt: skip
        """One generated case from a converged state: crash at `point` (where the plan has a step of the reference's
        type), converge, check; returns the commands status named."""
        before = durable(name)
        seq = self.crash(name, argv, point, tty=tty, cli=cli)
        if 0 < (n := int(point.split(":")[0])) < 1000:
            self.assertEqual(plan_steps(name, seq)[n - 1]["type"], ref[n - 1], f"{point}: the plan changed")
        trail = self.converge(name, settled)
        self.converged(name, seq, before, trail)
        return trail


class Named(Crashes):
    """T1: the named cases of ARCHITECTURE §10.3 on one fx-lite-ci instance; each starts where the last converged."""

    name: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.name = instance("itc")
        for i in range(4):  # prepared first: a deploy that prepares would run a second executor with the hook
            must(H.cli("prepare", cls.name, image(i)))

    def forward(self, ref: str) -> tuple[list[tuple[int, str, str, str]], int]:
        """The data-changing update's plan to `ref` and its forward point (the migrate)."""
        plan = self.preview(self.name, "deploy", self.name, ref)
        return plan, next(n for n, _, args, marks in plan if "forward point" in marks and "task=migrate" in args)

    def interrupted(self, argv: list[str], point: str) -> tuple[int, Durable]:
        """The crash of a class C command at `point`: status names its resume. Returns its seq and the state before."""
        before = durable(self.name)
        seq = self.crash(self.name, argv, point, tty=True)
        self.assertEqual(self.status(self.name)[1]["next"], f"{CLI} resume {self.name}")
        return seq, before

    def test_1_install_killed_at_its_pause_and_in_its_allowed_task(self) -> None:
        name, a = self.name, COMMITS[0]
        before = durable(name)
        pause = next(n for n, t, _, _ in self.preview(name, "deploy", name, a) if t == "Pause")
        seq = self.crash(name, ["deploy", name, a], f"{pause}:intent:after", tty=True)
        code, doc = self.status(name)
        [op] = doc["instance"]["operations"]
        self.assertEqual((code, op["seq"], op["state"], doc["next"]), (5, seq, "paused", f"{CLI} resume {name}"))

        # the allowed terminal task joins the paused install in the CLI, killed after the task printed its code and
        # before the step's done: the install stays paused and resumes
        res = H.cli_direct("task", name, "bootstrap-new-code", env={CRASH: "1001:done:before"}, tty=True, answer=name)
        self.assertEqual(res[0], 137, res[1])
        [token] = CODE_LINE.findall(res[1])
        self.settle(name)
        self.assertEqual([(r["step"], r["phase"]) for r in journal(name, seq) if r["step"] > 1000], [(1001, "intent")])
        code, doc = self.status(name)
        self.assertEqual((doc["instance"]["operations"][0]["state"], doc["next"]), ("paused", f"{CLI} resume {name}"))
        trail = self.converge(name, FIRST_INSTALL)
        self.assertEqual(trail, [f"{CLI} resume {name}"])
        self.converged(name, seq, before, trail)
        self.assertEqual([deployment(name)[k] for k in ("seq", "origin", "commit")], [1, "install", a])
        for top in (H.root, H.backups):  # terminal output is never captured (F12)
            for d, _, files in os.walk(top):
                for f in (os.path.join(d, x) for x in files if not os.path.islink(os.path.join(d, x))):
                    try:
                        data = Path(f).read_bytes()
                    except FileNotFoundError:  # a running app's own temporary file (SQLite -wal, -shm) went meanwhile
                        continue
                    self.assertNotIn(token.encode(), data, f)
        enqueue(name)
        must(H.cli("backup", name))
        must(H.cli("verify", name, "--latest", "--restore-test"))
        self.assertEqual(self.status(name)[0], 0)

    def test_2_online_backup_killed_in_its_task_is_auto_abandoned_by_the_next_scheduled_backup(self) -> None:
        name = self.name
        n = next(s["n"] for s in plan_steps(name, newest(name, "backup")) if s["type"] == "RunTask")
        live, before = host.inspect("container", [f"{name}-app-1"])[0]["State"], durable(name)
        seq = self.crash(name, ["backup", name], f"{n}:task", tty=False)
        code, doc = self.status(name)
        [op] = doc["instance"]["operations"]
        want = (5, "backup", "interrupted", f"{CLI} resume {name}")
        self.assertEqual((code, op["kind"], op["state"], doc["next"]), want)
        res = H.cli("scheduled", "backup", name)
        self.assertEqual((res[0], res[2]), (0, ""), res)
        line = (f"scheduled backup {name}: completed (operation {seq + 1}); the earlier unfinished operation {seq} "
                "(backup) was undone and closed automatically first\n")  # fmt: skip
        self.assertEqual(res[1], line)
        self.assertEqual(self.converge(name), [])
        self.converged(name, seq, before, [], "abandoned-auto")
        self.assertEqual(result(name, seq + 1).get("outcome"), "completed")
        self.assertEqual(host.inspect("container", [f"{name}-app-1"])[0]["State"], live)  # online: never stopped

    def test_3_update_killed_before_the_forward_point_is_abandoned_unchanged(self) -> None:
        name, b = self.name, COMMITS[1]
        plan, fwd = self.forward(b)
        last = max(n for n, t, args, _ in plan if t == "Record" and "kind=verification" in args and n < fwd)
        was = deployment(name)
        seq, before = self.interrupted(["deploy", name, b], f"{last}:done:before")
        self.assertEqual([s["type"] for s in plan_steps(name, seq)], [t for _, t, _, _ in plan])
        typed(name, "abandon", name)  # the other way out of an interrupted operation (LIFECYCLE §3.2)
        self.assertEqual(self.converge(name), [])
        self.converged(name, seq, before, [], "abandoned")
        self.assertEqual((H.record(name)["state"], deployment(name)), ("running", was))  # writers back, not frozen
        [kept] = [x for x in json.loads(H.cli("bundles", name, "--json")[1])["bundles"] if x["id"] == sealed(name, seq)]
        self.assertEqual((kept["class"], bool(kept["verified_at"])), ("pre-change", True))

    def test_4_update_killed_in_its_migrate_task_is_resumed(self) -> None:
        name, b = self.name, COMMITS[1]
        _, fwd = self.forward(b)
        seq, before = self.interrupted(["deploy", name, b], f"{fwd}:task")
        trail = self.converge(name)
        self.assertEqual(trail, [f"{CLI} resume {name}"])
        self.converged(name, seq, before, trail)
        # the daemon removed the killed attempt's container once it exited (`run --rm`): no exit code is left, so the
        # idempotent migrate (forward) runs again, as attempt 2 (ARCHITECTURE §4.5; LIFECYCLE §3.4)
        self.assertEqual([r["attempt"] for r in journal(name, seq, fwd) if r["phase"] == "intent"], [1, 2])
        [done] = [r for r in journal(name, seq, fwd) if r["phase"] == "done"]
        self.assertEqual(done["evidence"]["container"], f"{name}-x{seq}-{fwd}-a2")
        dep = deployment(name)
        self.assertEqual(
            [dep["commit"], dep["origin"], dep["schema"]["expected"], dep["schema"]["actual"]], [b, "update", 2, 2]
        )

    def test_5_an_exited_task_container_is_the_evidence_of_its_step(self) -> None:
        name, c = self.name, COMMITS[2]
        _, fwd = self.forward(c)
        seq, before = self.interrupted(["deploy", name, c], f"{fwd}:intent:after")
        # Fault injection: the attempt's task container, named and labelled as `compose run` makes it, ran the migrate
        # on the live generation to its end and the daemon kept it (its auto-removal failed)
        task, doc = f"{name}-x{seq}-{fwd}-a1", state.read_doc(f"{op_dir(name, seq)}/plan.json", "plan")
        own = {"instance": name, "op": str(seq), "step": str(fwd), "role": "task"}
        labels = {brand.label(k): v for k, v in own.items()}
        labels |= {f"com.docker.compose.{k}": v for k, v in {**COMPOSE, "project": name}.items()}
        run = ["run", "--name", task, *(x for k, v in labels.items() for x in ("--label", f"{k}={v}"))]
        run += ["--user", "10001:10001", "--network", "none", "-e", "DATA_DIR=/data", "--entrypoint", "env"]
        run += ["-v", f"{H.layout.data_gen(name, 'data', 'g1')}:/data"]
        host.docker(*run, doc["inputs"]["variants"]["candidate"]["images"]["app"], "fx-lite", "migrate")
        trail = self.converge(name)
        self.assertEqual(trail, [f"{CLI} resume {name}"])
        self.converged(name, seq, before, trail)
        self.assertFalse(host.present("container", task))  # removed once its exit was journaled
        self.assertEqual([r["attempt"] for r in journal(name, seq, fwd) if r["phase"] == "intent"], [1])  # not rerun
        [done] = [r for r in journal(name, seq, fwd) if r["phase"] == "done"]
        self.assertEqual((done["evidence"]["orphan"]["container"], done["evidence"]["orphan"]["exit_code"]), (task, 0))
        self.assertEqual((deployment(name)["commit"], deployment(name)["schema"]["actual"]), (c, 3))

    def test_6_update_abandoned_past_the_forward_point_freezes_then_moves_forward(self) -> None:
        name, d = self.name, COMMITS[3]
        plan, fwd = self.forward(d)
        up = next(n for n, t, _, _ in plan if t == "Up" and n > fwd)  # the activation after the migrate
        seq, before = self.interrupted(["deploy", name, d], f"{up}:intent:after")
        typed(name, "abandon", name)  # past the forward point the writers stay stopped (LIFECYCLE §3.4)
        self.assertEqual((result(name, seq).get("outcome"), H.record(name)["state"]), ("abandoned", "frozen"))
        self.assertFalse(host.inspect("container", [f"{name}-app-1"])[0]["State"]["Running"])
        code, doc = self.status(name)
        self.assertEqual((code, sorted(doc["attention"])), (5, ["frozen"]), doc)
        with self.subTest("status names the exact way forward (LIFECYCLE §3.2, §4.15)"):
            self.assertEqual(doc["next"], f"{CLI} deploy {name} {d}")
        typed(name, "deploy", name, d)  # the way forward: the same candidate, on the bundle that update sealed
        self.assertEqual(self.converge(name), [])
        self.converged(name, seq, before, [], "abandoned")
        dep = deployment(name)
        self.assertEqual((dep["commit"], dep["origin"], dep["pre_change_bundle"]), (d, "update", sealed(name, seq)))
        self.assertEqual((dep["schema"]["expected"], dep["schema"]["actual"]), (4, 4))

    def test_7_backup_killed_right_after_its_seal_resumes_on_that_one_bundle(self) -> None:
        name = self.name
        plan = plan_steps(name, newest(name, "backup"))
        seal = next(s["n"] for s in plan if s["type"] == "CaptureBundle" and s["args"]["phase"] == "seal")
        had, before = {b["id"] for b in json.loads(H.cli("bundles", name, "--json")[1])["bundles"]}, durable(name)
        seq = self.crash(name, ["backup", name], f"{seal}:done:before", tty=False)
        trail = self.converge(name)
        self.assertEqual(trail, [f"{CLI} resume {name}"])  # no second bundle left unverified for `verify` to name
        self.converged(name, seq, before, trail)
        # the seal's observe (LIFECYCLE §3.3): its bundle is catalogued with its hash, so it is done, never sealed again
        self.assertEqual([r["phase"] for r in journal(name, seq, seal)], ["intent", "done"])
        new = [b for b in json.loads(H.cli("bundles", name, "--json")[1])["bundles"] if b["id"] not in had]
        self.assertEqual([(b["id"], bool(b["verified_at"])) for b in new], [(sealed(name, seq), True)])


if __name__ == "__main__":
    unittest.main()
