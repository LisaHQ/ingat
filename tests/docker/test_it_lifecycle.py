"""Suite 1, the lifecycle loop (ARCHITECTURE §10.3; LIFECYCLE §4.1-§4.9, §7), on a scratch host installed by the
release's install.sh and driven through the real wrapper, class C approval typed on a pty.

fx-lite-ci, the OD-11 (b) form of fx-lite (tests/data/fx-lite-ci): its app image is a build service, pulled from a
registry by a per-commit reference and bound to the commit by its revision label (ADR-0026). install → certify →
init at A → prepare A (and a commit whose image carries another revision is refused) → deploy A: the install pauses,
the allowed terminal task bootstrap-new-code runs on a pty inside the paused operation, resume → status (attention:
no bundle yet) → backup → verify --latest → verify --latest --restore-test → status exit 0 → deploy B, data-changing
(writers frozen, a sealed and verified pre-change bundle, migrate to schema 2) → backup → a config-only change that
recreates exactly the changed service → scheduled backup twice (one line each; the second's retention deletes the one
bundle no rule keeps) → scheduled status. fx-web: init → deploy A → a config-only commit B → status exit 0.

A config-only deploy of fx-lite-ci from one commit to another cannot exist: every commit has its own app image (the
revision label binds it), and an image change of a writer is data-changing (LIFECYCLE §4.4). Its config-only change
is therefore the owner's edit of a plain app_env value in instance.toml, deployed at the same commit (§4.5); fx-web
covers a config-only commit."""

import json
import os
import re
import secrets
import unittest
import urllib.request
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.store import state
from tests.harness import background, host

CLI = brand.CLI
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
CODE_LINE = re.compile(r"^[A-Za-z0-9_-]{16}$", re.M)  # fx-lite's single-use bootstrap code
OP_DIR = re.compile(r"([0-9]+)-([a-z-]+)")
H: host.ScratchHost
REG: host.Registry


def setUpModule() -> None:
    global H, REG
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    REG = host.Registry()
    unittest.addModuleCleanup(REG.close)  # after the host's containers are gone: they run its images
    H = host.ScratchHost("life")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()


def config(name: str, app: str, params: dict[str, str]) -> str:
    """An owner's instance.toml in the inbox; [app_env] comes last, so a line appended to it joins that table."""
    lines = ["instance = 1", f'name = "{name}"', f'app = "{app}"', 'environment = "test"', "[source]"]
    lines += [f'repo = "{H.repo_url(app if app != "fx-lite" else "fx-lite-ci")}"', "[params]"]
    lines += [f'{k} = "{v}"' for k, v in params.items()]
    if app == "fx-lite":
        lines += ["[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items())]
    return H.inbox(f"{name}.toml", "\n".join(lines) + "\n")


def jdoc(res: host.Result) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(res[1])
    return doc


def get(url: str) -> dict[str, Any] | str:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=10) as r:
        body = r.read().decode()
    doc: dict[str, Any] | str = json.loads(body) if body.startswith("{") else body
    return doc


class Lifecycle(unittest.TestCase):
    maxDiff = None

    # observation through files and the Docker inventory ------------------------------------------------------
    def ops(self, name: str) -> list[tuple[int, str]]:
        found = (OP_DIR.fullmatch(d) for d in os.listdir(H.layout.ops_dir(name)))
        return sorted((int(m[1]), m[2]) for m in found if m)

    def last(self, name: str, kind: str) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
        """(seq, plan, result) of the newest operation of `kind`."""
        seq = max(s for s, k in self.ops(name) if k == kind)
        d = H.layout.op_dir(name, seq, kind)
        result = f"{d}/result.json"
        doc = state.read_doc(result, "result") if os.path.exists(result) else None
        return seq, state.read_doc(f"{d}/plan.json", "plan"), doc

    def deployment(self, name: str, seq: int) -> dict[str, Any]:
        return state.read_doc(H.layout.deployment_json(name, seq), "deployment")

    def bundles(self, name: str) -> list[dict[str, Any]]:
        res = H.cli("bundles", name, "--json")
        self.assertEqual(res[0], 0, res)
        rows: list[dict[str, Any]] = jdoc(res)["bundles"]
        return rows

    def services(self, name: str) -> dict[str, tuple[str, str]]:
        """service -> (container ID, status) of the instance's live service containers."""
        out = {}
        for c in host.inspect("container", [c[0] for c in host.inventory(name)["containers"]]):
            labels = c["Config"]["Labels"]
            if labels.get("com.docker.compose.project") == name and labels.get(brand.label("role")) == "app":
                out[labels["com.docker.compose.service"]] = (c["Id"], c["State"]["Status"])
        return out

    def stream(self) -> background.EventStream:
        """The container events from now on, streamed: replaying the daemon's buffer (`host.events`) loses the start
        of a long window once a few hundred newer events (probe execs among them) have pushed it out."""
        w = background.EventStream()
        self.addCleanup(w.close)
        return w

    def recreated(self, name: str, evs: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
        """(services created, services destroyed) of `name`'s live project among `evs` (role app), failing on any
        task container of the instance (role task)."""
        made, gone = list[str](), list[str]()
        for e in evs:
            attrs = e.get("Actor", {}).get("Attributes", {})
            if e.get("Type") != "container" or e.get("Action") not in ("create", "destroy"):
                continue
            role = attrs.get(brand.label("role"))
            self.assertNotEqual((role, attrs.get(brand.label("instance"))), ("task", name), e)
            if attrs.get("com.docker.compose.project") == name and role == "app":
                (made if e["Action"] == "create" else gone).append(attrs["com.docker.compose.service"])
        return made, gone

    def bundle_json(self, name: str, bid: str) -> dict[str, Any]:
        doc: dict[str, Any] = json.loads(Path(H.layout.bundle_dir(name, bid), "bundle.json").read_bytes())
        return doc

    def order(self, name: str, seq: int, w: background.EventStream, tasks: list[int]) -> list[int]:
        """Event positions among the streamed events: the live app container's death, the creation of operation
        `seq`'s task containers of `tasks` (step numbers), the creation of the new live app container."""
        evs = [e for e in w.events() if e.get("Type") == "container"]

        def first(action: str, want: dict[str, str]) -> int:
            hits = [
                i
                for i, e in enumerate(evs)
                if e["Action"] == action and want.items() <= e["Actor"]["Attributes"].items()
            ]
            self.assertTrue(hits, f"no {action} event with {want}")
            return hits[0]

        role, service = brand.label("role"), {"com.docker.compose.project": name, "com.docker.compose.service": "app"}
        # this instance only: parallel suites share the daemon, with operations numbered like these
        task = {role: "task", brand.label("instance"): name, brand.label("op"): str(seq)}
        tasks_made = [first("create", task | {brand.label("step"): str(n)}) for n in tasks]
        live = service | {"com.docker.compose.oneoff": "False"}
        return [first("die", {"name": f"{name}-app-1"}), *tasks_made, first("create", live)]

    def no_trace(self, name: str, *args: str, code: int, why: str) -> None:
        """A refused command: its exit and code, nothing under instances/ and no Docker object of `name` changed."""
        self.assertTrue(host.wait_gone(brand.executor_name(name)))  # the last operation's executor has exited
        tree, inv = host.tree_hash(H.layout.instances_dir), host.inventory(name)
        res = H.cli(*args, "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (code, why), res)
        self.assertEqual((host.tree_hash(H.layout.instances_dir), host.inventory(name)), (tree, inv))

    def run_tty(self, *args: str, answer: str | None = None, code: int = 0) -> str:
        res = H.cli(*args, tty=True, answer=answer)
        self.assertEqual(res[0], code, res[1])
        return res[1]

    # the loops ---------------------------------------------------------------------------------------------
    def test_1_fx_lite_ci(self) -> None:
        name, port = f"itl{secrets.token_hex(3)}", host.free_port()
        a, b, x = H.fixture_repo("fx-lite-ci", [{}, {"CHANGES": "B: schema 2\n"}, {"CHANGES": "X\n"}], base="fx-lite")
        refs = {a: REG.push(a, 1, H.claim), b: REG.push(b, 2, H.claim)}
        REG.push(x, 1, H.claim, labels={host.REVISION: a})  # an image whose revision is another commit
        cfg = config(name, "fx-lite", {"FXLITE_REGISTRY": REG.address, "FXLITE_PORT": str(port)})

        # init: class C, typed on a terminal; without one nothing is written
        self.no_trace(name, "init", name, "--config", cfg, "--ref", a, code=2, why="no-tty")
        out = self.run_tty("init", name, "--config", cfg, "--ref", a, answer=name)
        self.assertIn(f"initialized {name}: fx-lite, environment test, commit {a}", out)
        self.assertIn(f"params.FXLITE_PORT = {port}", out)
        self.assertEqual(H.record(name)["state"], "registered")

        # prepare: pulled by the rendered Compose reference, pinned by ID and digest, the revision label checked
        res = H.cli("prepare", name, a, "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        [cand] = [state.read_doc(f"{H.layout.inst(name, 'candidates')}/{f}", "candidate")
                  for f in os.listdir(H.layout.inst(name, "candidates"))]  # fmt: skip
        self.assertEqual((cand["commit"], cand["refs"], cand["labels_checked"]), (a, {"app": refs[a]}, ["app"]))
        self.assertTrue(cand["digests"]["app"].startswith(f"{REG.address}/fx-lite@sha256:"), cand)
        image = json.loads(host.docker("image", "inspect", refs[a]))[0]
        self.assertEqual((image["Id"], image["Config"]["Labels"][host.REVISION]), (cand["images"]["app"], a))
        ledger = H.layout.ledger(image["Id"].removeprefix("sha256:"), f"{name}-1")
        self.assertEqual(state.read_doc(ledger, "ledger")["digest"], cand["digests"]["app"])
        res = H.cli("prepare", name, x, "--json")  # a tag is never trusted alone
        self.assertEqual((res[0], jdoc(res)["code"]), (3, "image-labels"), res)
        self.assertEqual(len(os.listdir(H.layout.inst(name, "candidates"))), 1)

        # deploy A: no terminal, no trace; on one, the first install runs up to its pause
        self.no_trace(name, "deploy", name, a, code=2, why="no-tty")
        out = self.run_tty("deploy", name, a, answer=name, code=4)
        self.assertIn(f"deploy {name} at {a}: approval class C", out)
        self.assertIn(f"next: {CLI} resume {name}", out)
        seq, plan, result = self.last(name, "deploy")
        self.assertIsNone(result)
        self.assertEqual(
            [s["type"] for s in plan["steps"]], ["CreateGeneration", "RunTask", "Up", "Pause", "Up", "Record"]
        )
        self.assertEqual((H.record(name)["state"], H.record(name)["open_op"]["seq"]), ("registered", seq))
        self.assertEqual(self.services(name)["app"][1], "running")

        # the allowed terminal task, on a pty, journaled inside the paused operation; its code is never recorded
        out = self.run_tty("task", name, "bootstrap-new-code", answer=name)
        self.assertIn(f"next: {CLI} resume {name}", out)
        [code] = CODE_LINE.findall(out)
        lines = Path(H.layout.op_dir(name, seq, "deploy"), "steps.jsonl").read_text().splitlines()
        joined = [json.loads(x) for x in lines if json.loads(x)["step"] > 1000]
        phases = [(1001, "intent"), (1001, "done"), (1002, "intent"), (1002, "done")]  # RunTask, Record
        self.assertEqual([(j["step"], j["phase"]) for j in joined], phases, lines)
        self.assertEqual(H.record(name)["open_op"]["seq"], seq)  # still the paused install
        for top in (H.root, H.backups):
            for d, _, files in os.walk(top):
                for f in files:
                    p = os.path.join(d, f)
                    if not os.path.islink(p):
                        try:
                            data = Path(p).read_bytes()
                        except FileNotFoundError:  # the running app's SQLite -wal or -shm file went meanwhile
                            continue
                        self.assertNotIn(code.encode(), data, p)

        out = self.run_tty("resume", name, answer=name)
        rec = H.record(name)
        self.assertEqual((rec["state"], rec["open_op"], rec["current_deployment"]), ("running", None, 1))
        first = self.deployment(name, 1)
        self.assertEqual((first["origin"], first["commit"], first["refs"]), ("install", a, {"app": refs[a]}))
        self.assertEqual(first["schema"]["actual"], 1)

        # status: deployed, but no bundle yet; reading changes nothing (F9)
        tree = host.tree_hash(H.layout.instances_dir)
        res = H.cli("status", name, "--json")
        doc = jdoc(res)
        self.assertEqual((res[0], sorted(doc["attention"]), doc["next"]),
                         (5, ["backup-old", "restore-test-old"], f"{CLI} backup {name}"), res)  # fmt: skip
        self.assertEqual(host.tree_hash(H.layout.instances_dir), tree)
        res = H.cli("scheduled", "status")
        self.assertEqual(res[0], 5, res)
        new = [f"now needs attention: {name}: backup-old", f"now needs attention: {name}: restore-test-old"]
        new.append(f"next: {CLI} status")
        self.assertEqual(res[1].splitlines(), new, res)

        # backup, verify, drill: the live app keeps running (owner decision OD-6), the isolated project goes
        live = self.services(name)["app"]
        res = H.cli("backup", name, "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        [b1] = self.bundles(name)
        self.assertEqual((b1["class"], bool(b1["verified_at"]), b1["restore_tested_at"]), ("manual", True, None))
        res = H.cli("verify", name, "--latest", "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        levels = Path(H.layout.verification(name, b1["id"])).read_text().splitlines()
        self.assertEqual([(json.loads(x)["level"], json.loads(x)["ok"]) for x in levels], [("verified", True)] * 2)
        sealed = self.bundle_json(name, b1["id"])
        self.assertEqual(
            (sealed["consistency"], sealed["freeze_at"], sealed["deployment"]["seq"]), ("online-app", None, 1)
        )
        res = H.cli("verify", name, "--latest", "--restore-test", "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        drill, _, _ = self.last(name, "drill")
        [b1] = self.bundles(name)
        self.assertIsNotNone(b1["restore_tested_at"])
        self.assertEqual(self.services(name)["app"], live)
        self.assertTrue(host.wait_gone(brand.executor_name(name)))
        inv = host.inventory(name)
        self.assertEqual([c[1] for c in inv["containers"]], [f"{name}-app-1"], inv)
        self.assertFalse(any(n.startswith(f"{name}--t") for _, n in inv["networks"]), inv)
        self.assertFalse(os.path.exists(H.layout.data_gen(name, "data", f"t{drill}")))
        self.assertEqual([f for f in os.listdir(H.layout.allocations_dir) if f.startswith("subnet-")], [])
        res = H.cli("status", name, "--json")
        self.assertEqual((res[0], jdoc(res)["attention"]), (0, {}), res)

        # deploy B: data-changing (a writer's image changes): freeze, pre-change bundle sealed and verified with the
        # current release, then migrate on the candidate (the forward point) and start it at schema 2
        w = self.stream()
        out = self.run_tty("deploy", name, b, answer=name)
        self.assertIn(f"preparing {b} first", out)
        seq, plan, _ = self.last(name, "deploy")
        steps = plan["steps"]
        types = [(s["type"], s["args"].get("phase") or s["args"].get("task") or s["args"].get("kind")) for s in steps]
        stop, seal = types.index(("Stop", None)), types.index(("CaptureBundle", "seal"))
        migrate = types.index(("RunTask", "migrate"))
        self.assertEqual(steps[stop]["args"] | {"timeout": 0}, {"variant": "current", "services": ["app"],
                         "freeze": True, "timeout": 0})  # fmt: skip
        self.assertLess(stop, types.index(("RunTask", "backup")))
        self.assertLess(seal, types.index(("VerifyBundle", None)))
        self.assertLess(types.index(("VerifyBundle", None)), migrate)
        self.assertEqual((steps[migrate]["args"]["variant"], steps[migrate].get("forward_point")), ("candidate", True))
        self.assertEqual(steps[types.index(("RunTask", "backup"))]["args"]["variant"], "current")
        second = self.deployment(name, 2)
        self.assertEqual((second["origin"], second["commit"], second["rollback_target"]), ("update", b, 1))
        self.assertEqual((second["schema"]["expected"], second["schema"]["actual"]), (2, 2))
        self.assertNotEqual(second["images"], first["images"])
        pre = next(x for x in self.bundles(name) if x["id"] == second["pre_change_bundle"])
        self.assertEqual((pre["class"], bool(pre["verified_at"])), ("pre-change", True))
        sealed = self.bundle_json(name, pre["id"])  # captured by the current release, with its writers stopped
        self.assertEqual((sealed["consistency"], sealed["deployment"]["seq"], sealed["deployment"]["commit"]),
                         ("writers-stopped", 1, a))  # fmt: skip
        self.assertEqual((sealed["schema"], bool(sealed["freeze_at"])), ({"expected": 1, "actual": 1}, True))
        # the daemon's own order: the writer stops, then the backup task runs, then the migrate, then the new app
        order = self.order(name, seq, w, [types.index(("RunTask", "backup")) + 1, migrate + 1])
        self.assertEqual(order, sorted(order), order)
        self.assertEqual(H.record(name)["generations"], {"data": 1})  # migrated in place, after the bundle
        ready = get(f"http://127.0.0.1:{port}/api/ready")
        self.assertEqual(ready, {"status": "ready", "data_writable": True, "schema": {"expected": 2, "actual": 2}})
        res = H.cli("backup", name, "--json")
        self.assertEqual(res[0], 0, res)
        b3 = max(self.bundles(name), key=lambda x: str(x["created_at"]))

        # a config-only change: the owner edits a plain app_env value; exactly the service it changes is recreated
        Path(H.layout.inst_toml(name)).write_text(Path(H.layout.inst_toml(name)).read_text() + 'SESSION_HOURS = "12"\n')
        before, w = self.services(name)["app"], self.stream()
        self.run_tty("deploy", name, b, answer=name)
        made, gone = self.recreated(name, w.events())
        self.assertEqual((made, gone), (["app"], ["app"]))
        _, plan, _ = self.last(name, "deploy")
        self.assertEqual([(s["type"], s["args"]["services"]) for s in plan["steps"][:2]], [("Up", ["app"]), ("Up", [])])
        self.assertEqual(plan["steps"][2]["type"], "Record")
        third = self.deployment(name, 3)
        self.assertEqual((third["origin"], third["images"], third["schema"]["actual"]), ("config", second["images"], 2))
        self.assertNotEqual(third["env_file"], second["env_file"])
        after = self.services(name)["app"]
        self.assertNotEqual(after[0], before[0])
        self.assertEqual(after[1], "running")
        res = H.cli("status", name, "--json")
        self.assertEqual((res[0], jdoc(res)["attention"]), (0, {}), res)

        # scheduled backups: one line each; the second's retention deletes the bundle that no rule keeps any more
        for _ in range(2):
            res = H.cli("scheduled", "backup", name)
            self.assertEqual((res[0], res[2]), (0, ""), res)
            self.assertRegex(res[1], rf"\Ascheduled backup {name}: completed \(operation [0-9]+\)\n\Z")
        rows = self.bundles(name)
        ids = [x["id"] for x in rows]
        # the daily window keeps the newest verified bundle of each UTC day (created_at is UTC, the day its first 10
        # characters): b3 shares the first scheduled bundle's day unless 00:00 UTC passed between the two backups
        s1_at = min(str(x["created_at"]) for x in rows if x["class"] == "scheduled")
        if s1_at[:10] == str(b3["created_at"])[:10]:
            self.assertEqual(len(ids), 4, ids)
            self.assertNotIn(b3["id"], ids)
            self.assertFalse(os.path.exists(H.layout.bundle_dir(name, b3["id"])))
            self.assertTrue(os.path.exists(H.layout.catalog(name, f"{b3['id']}.pruned")))
        else:  # the newest of its own day: kept, and nothing is deleted
            self.assertEqual((len(ids), b3["id"] in ids), (5, True), ids)
        self.assertIn(second["pre_change_bundle"], ids)  # paired with the previous deployment

        # scheduled status: the codes it reported are cleared; a second run finds nothing new and prints nothing
        res = H.cli("scheduled", "status")
        self.assertEqual(res[0], 5, res)
        gone = [
            f"no longer needs attention: {name}: backup-old",
            f"no longer needs attention: {name}: restore-test-old",
        ]
        self.assertEqual(res[1].splitlines(), gone)
        self.assertEqual(H.cli("scheduled", "status")[:2], (0, ""))
        res = H.cli("status", "--json")
        self.assertEqual(res[0], 0, res)
        self.assertEqual(host.docker("ps", "-aq", "--filter", f"label={brand.label('role')}=task",
                                     "--filter", f"label={brand.label('instance')}={name}"), "")  # fmt: skip

        # the test-only crash hook never passes the wrapper's `env -i`; doctor flags it where it is set
        hook = {brand.env("CRASH_AT"): "1:intent:after"}
        res = H.cli("doctor", name, "--json", env=hook)
        self.assertEqual((res[0], jdoc(res)["checks"]["crash-hook"]), (0, []), res)
        res = H.cli_direct("doctor", name, "--json", env=hook)
        self.assertEqual((res[0], len(jdoc(res)["checks"]["crash-hook"])), (5, 1), res)

    def test_2_fx_web(self) -> None:
        name, port = f"itw{secrets.token_hex(3)}", host.free_port()
        compose = (host.REPO / "fixtures" / "fx-web" / "compose.yaml").read_text()
        edited = compose.replace("    environment:\n", '    environment:\n      FXWEB_NOTE: "B"\n', 1)
        self.assertNotEqual(edited, compose)
        a, b = H.fixture_repo("fx-web", [{}, {"compose.yaml": edited}])
        cfg = config(name, "fx-web", {"FXWEB_IMAGE": H.image, "FXWEB_PORT": str(port)})
        self.run_tty("init", name, "--config", cfg, "--ref", a, answer=name)
        out = self.run_tty("deploy", name, a, answer=name)
        self.assertIn(f"preparing {a} first", out)
        self.assertEqual((H.record(name)["state"], self.deployment(name, 1)["origin"]), ("running", "install"))
        self.assertIn(f"fx-web {a}", str(get(f"http://127.0.0.1:{port}/")))

        before, w = self.services(name)["site"], self.stream()
        self.run_tty("deploy", name, b, answer=name)  # a config-only commit: the image stays, the site is recreated
        self.assertEqual(self.recreated(name, w.events()), (["site"], ["site"]))
        _, plan, _ = self.last(name, "deploy")
        self.assertEqual([s["type"] for s in plan["steps"]], ["Up", "Up", "Record"])
        second = self.deployment(name, 2)
        self.assertEqual((second["origin"], second["commit"]), ("config", b))
        self.assertEqual(second["images"], self.deployment(name, 1)["images"])
        self.assertNotEqual(self.services(name)["site"][0], before[0])
        self.assertIn(f"fx-web {b}", str(get(f"http://127.0.0.1:{port}/")))
        res = H.cli("status", name, "--json")
        self.assertEqual((res[0], jdoc(res)["attention"]), (0, {}), res)


if __name__ == "__main__":
    unittest.main()
