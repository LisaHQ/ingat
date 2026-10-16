"""Suite 3, part 2: the generated crash matrix (ARCHITECTURE §10.3), run nightly with INGAT_TEST_FULL_MATRIX=1.

Every crash point of every M1 plan, each case from a converged state, crashed, converged and checked by the machinery
of tests/docker/test_it_crash.py (whose module docstring defines convergence) on a scratch host of its own: prepare,
first install (the deploy up to its pause, its resume, the allowed terminal task joined to the paused install),
data-changing update, config-only change, backup, verify, drill, stop, start, restart, write tasks (idempotent and
not), prune --apply and scheduled backup's retention, and fx-web's first install and config-only commit. The points
come from the plan a reference run of the same command wrote (`plans/<hash>.json`, copied into the operation's
plan.json): `1:intent:before`, per step `intent:after`, `task` (RunTask) and `done:before`, then the close decision
(journal step 0) before and after it is written. Retention plans list a varying number of Delete steps, so their
points are the first and the last Delete step, found after a dry run listed what the plan deletes."""

import json
import os
import re
import unittest
from collections.abc import Callable
from pathlib import Path

from ingat import brand
from ingat.store import state
from tests.docker import test_it_crash as crash
from tests.docker.test_it_crash import (
    FIRST_INSTALL,
    Crashes,
    deployment,
    durable,
    enqueue,
    image,
    instance,
    must,
    newest,
    plan_steps,
    points,
    typed,
)
from tests.harness import host


def retire(name: str) -> None:
    """Remove the containers and networks of a throwaway instance whose case is over, as ScratchHost.close does at the
    end: one project network per instance would soon exhaust the daemon's few default address pools."""
    own, project = f"label={brand.label('instance')}={name}", f"label=com.docker.compose.project={name}"
    if ids := sorted({i for f in (own, project) for i in host.docker("ps", "-aq", "--filter", f).split()}):
        host.docker("rm", "-f", *ids)
    if nets := sorted({i for f in (own, project) for i in host.docker("network", "ls", "-q", "--filter", f).split()}):
        host.docker("network", "rm", *nets)


def setUpModule() -> None:
    if not crash.FULL:
        raise unittest.SkipTest(f"the generated crash matrix runs nightly ({brand.env('TEST_FULL_MATRIX')}=1)")
    crash.setUpModule()


class Nightly(Crashes):
    """One fx-lite-ci instance for its operations, a new instance per first-install case, fx-web instances."""

    name: str
    turn = 0  # the newest commit in use
    hours = 0
    web: list[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.name = instance("itm", ref=image(cls.turn))
        must(crash.H.cli("prepare", cls.name, crash.COMMITS[cls.turn]))
        typed(cls.name, "deploy", cls.name, crash.COMMITS[cls.turn], code=4)  # the install pauses for its bootstrap
        typed(cls.name, "resume", cls.name)
        enqueue(cls.name)
        must(crash.H.cli("backup", cls.name))
        must(crash.H.cli("verify", cls.name, "--latest", "--restore-test"))
        compose, at = (host.REPO / "fixtures" / "fx-web" / "compose.yaml").read_text(), "    environment:\n"
        notes = [compose.replace(at, f'{at}      FXWEB_NOTE: "{i}"\n', 1) for i in range(12)]
        cls.web = crash.H.fixture_repo("fx-web", [{}, *({"compose.yaml": x} for x in notes)])

    @classmethod
    def commit(cls) -> str:
        cls.turn += 1
        return image(cls.turn)

    def recover(self, name: str) -> None:
        """A failed case may leave its operation open: go on as status says, else abandon it."""
        self.settle(name)
        if state.open_ops(crash.H.layout, name):
            try:
                self.converge(name, FIRST_INSTALL)
            except AssertionError:
                crash.H.cli("abandon", name, tty=True, answer=name)

    def family(self, label: str, argv: Callable[[], list[str]], tty: bool = False,
               check: Callable[[list[str]], object] | None = None, name: str = "") -> None:  # fmt: skip
        """A reference run of the command, then one case per point of the plan it wrote."""
        name = name or self.name
        self.recover(name)
        first = argv()  # its precondition may run an operation (a prepare, a start) before the reference one
        seq = state.next_seq(crash.H.layout, name)
        must(crash.H.cli(*first, tty=tty, answer=name if tty else None))
        plan = plan_steps(name, seq)
        for point in points(plan):
            with self.subTest(label, point=point):
                self.recover(name)
                self.case(name, run := argv(), point, [s["type"] for s in plan], tty=tty)
                if check:
                    check(run)

    def cycle(self, want: str, verb: str) -> list[str]:
        if crash.H.record(self.name)["state"] != want:
            typed(self.name, "start" if want == "running" else "stop", self.name)
        return [verb, self.name]

    def advance(self, name: str, ref: str) -> list[str]:
        must(crash.H.cli("prepare", name, ref))
        return ["deploy", name, ref]

    def edit(self) -> list[str]:
        """A config-only change: the owner sets another plain app_env value (LIFECYCLE §4.5)."""
        Nightly.hours += 1
        path = crash.H.layout.inst_toml(self.name)
        text = re.sub(r'SESSION_HOURS = "[0-9]+"\n', "", Path(path).read_text())
        Path(path).write_text(text + f'SESSION_HOURS = "{Nightly.hours}"\n')
        return ["deploy", self.name, deployment(self.name)["commit"]]

    def test_backup_verify_drill(self) -> None:
        self.family("backup", lambda: ["backup", self.name])
        self.family("verify", lambda: ["verify", self.name, "--latest"])
        self.family("drill", lambda: ["verify", self.name, "--latest", "--restore-test"])

    def test_prepare(self) -> None:
        def candidate(run: list[str]) -> None:
            found = os.listdir(crash.H.layout.inst(self.name, "candidates"))
            self.assertTrue([f for f in found if f.startswith(run[2])], found)

        self.family("prepare", lambda: ["prepare", self.name, self.commit()], check=candidate)

    def test_update_and_config_change(self) -> None:
        def update(run: list[str]) -> None:
            self.assertEqual([deployment(self.name)[k] for k in ("commit", "origin")], [run[2], "update"])

        self.family("update", lambda: self.advance(self.name, self.commit()), True, update)
        self.family("config", self.edit, True, lambda run: self.assertEqual(deployment(self.name)["origin"], "config"))

    def test_stop_start_restart(self) -> None:
        self.family("stop", lambda: self.cycle("running", "stop"), tty=True)
        self.family("start", lambda: self.cycle("stopped", "start"), tty=True)
        self.family("restart", lambda: self.cycle("running", "restart"), tty=True)

    def test_write_tasks(self) -> None:
        for task in ("queue-status", "queue-resume"):  # idempotent; not, so status names abandon once it may have run
            self.family(f"task {task}", lambda t=task: ["task", self.name, t], tty=True)  # type: ignore[misc]

    def deletable(self) -> list[str]:
        """Back up until retention would delete two bundles; their ids, in the order the plan deletes them."""
        for _ in range(5):
            if len(ids := json.loads(crash.H.cli("prune", self.name, "--bundles", "--json")[1])["delete"]) >= 2:
                return list(ids)
            must(crash.H.cli("backup", self.name))
        self.fail("retention never deletes two bundles")

    def test_retention(self) -> None:
        name, every = self.name, ["first:intent:after", "first:done:before", "last:intent:after", "last:done:before"]
        for argv in (["prune", name, "--bundles", "--apply"], ["scheduled", "backup", name]):
            self.recover(name)
            self.deletable()
            seq = state.next_seq(crash.H.layout, name)
            must(crash.H.cli(*argv))
            base = len([s for s in plan_steps(name, seq) if s["type"] != "Delete"])
            for which in ["first:intent:before"] * (base == 0) + every + ["close:done:before", "close:done:after"]:
                with self.subTest(argv[0], point=which):
                    self.recover(name)
                    ids, (where, _, phase) = self.deletable(), which.partition(":")
                    n = {"first": base + 1, "last": base + len(ids), "close": 0}[where]
                    before = durable(name)
                    seq = self.crash(name, argv, f"{n}:{phase}", tty=False)
                    self.assertEqual([s["args"]["item"]["id"] for s in plan_steps(name, seq)[base:]], ids)
                    self.converged(name, seq, before, self.converge(name))
                    left = {b["id"] for b in json.loads(crash.H.cli("bundles", name, "--json")[1])["bundles"]}
                    self.assertFalse(left & set(ids), left)

    def test_first_install(self) -> None:
        """A new instance per case: the points of the deploy up to its pause, of the resume after it, and of the
        allowed terminal task that joins the paused install in the CLI."""
        a = image(0)

        def fresh(paused: bool) -> str:
            name = instance("iti")
            must(crash.H.cli("prepare", name, a))
            if paused:
                out = typed(name, "deploy", name, a, code=4)
                self.assertEqual([o["state"] for o in self.status(name)[1]["instance"]["operations"]], ["paused"], out)
            return name

        name = fresh(True)
        typed(name, "resume", name)
        plan = plan_steps(name, newest(name, "deploy"))
        retire(name)
        pause = next(s["n"] for s in plan if s["type"] == "Pause")
        runs = [(p, "deploy") for p in points(plan[:pause], close=False)]
        runs += [(p, "resume") for p in [f"{pause}:done:before", *points(plan[pause:], start=False)]]
        joined = ["1001:intent:before", "1001:intent:after", "1001:task", "1001:done:before", "1002:intent:after"]
        runs += [(p, "task") for p in [*joined, "1002:done:before"]]
        for point, verb in runs:
            with self.subTest("install", point=point, by=verb):
                name = fresh(verb != "deploy")
                run = {"deploy": ["deploy", name, a], "resume": ["resume", name]}.get(verb)
                run = run or ["task", name, "bootstrap-new-code"]
                self.case(name, run, point, [s["type"] for s in plan], True, verb == "task", FIRST_INSTALL)
                retire(name)

    def test_web(self) -> None:
        """fx-web: a first install without [[install]] steps (a new instance per case), then config-only commits."""
        a, web = self.web[0], iter(self.web[1:])
        name = instance("itw", "fx-web", a)
        must(crash.H.cli("prepare", name, a))
        typed(name, "deploy", name, a)
        plan = plan_steps(name, newest(name, "deploy"))
        for point in points(plan):
            with self.subTest("web install", point=point):
                other = instance("itw", "fx-web", a)
                must(crash.H.cli("prepare", other, a))
                self.case(other, ["deploy", other, a], point, [s["type"] for s in plan], tty=True)
                retire(other)

        def config(run: list[str]) -> None:
            self.assertEqual([deployment(name)[k] for k in ("commit", "origin")], [run[2], "config"])

        self.family("web config", lambda: self.advance(name, next(web)), True, config, name)


if __name__ == "__main__":
    unittest.main()
