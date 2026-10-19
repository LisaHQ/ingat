"""T1: the diagnostics against a real daemon on both engines (dt.sh): an fx-lite instance deployed the way a first
install leaves it (records, snapshot, content-addressed env file, generation g1 and the service started by Compose
from the snapshot), then a clean status and doctor, changes made outside (a stopped container, a foreign container in
the project, an operation without a result), and that no diagnostic writes anything while scheduled status writes only
host/attention.json and exits 5 only when the attention set changed."""

import hashlib
import json
import os
import shutil
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ingat import brand
from ingat.adapters.compose import Project
from ingat.adapters.docker import PROJECT_LABEL, EffectToken
from ingat.core.journal import Journal
from ingat.model import records
from ingat.ops import context as cx
from ingat.ops import status as st
from ingat.policy import gate
from ingat.store import fs, state
from tests.docker.helpers import COMMIT, IMAGE, RELEASE, Lab

SKIP = not os.path.exists("/var/run/docker.sock")
DOWN = "service app is not running, although the app should be running"
FOREIGN = "sits in this app's Docker project but does not belong to this instance"


def tree_hash(root: str) -> str:
    """Every path, mode and content under `root`."""
    h = hashlib.sha256()
    for d, dirs, files in sorted(os.walk(root)):
        dirs.sort()
        for name in sorted(files + dirs):
            path = os.path.join(d, name)
            st_ = os.lstat(path)
            h.update(f"{os.path.relpath(path, root)} {st_.st_mode} {st_.st_size}\n".encode())
            if os.path.isfile(path):
                h.update(Path(path).read_bytes())
    return h.hexdigest()


@unittest.skipIf(SKIP, "needs a scratch Docker daemon")
class StatusTest(unittest.TestCase):
    lab: Lab
    environ: dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        cls.lab = lab = Lab("tst")
        try:
            cls.deploy(lab)
        except BaseException:
            lab.close()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.lab.close()

    @classmethod
    def deploy(cls, lab: Lab) -> None:
        """What the executor leaves after a first install, plus a fresh verified and restore-tested bundle."""
        lay, n = lab.layout, lab.name
        facts = f"{lab.base}/facts"
        os.makedirs(f"{facts}/etc")
        Path(f"{facts}/etc/os-release").write_text('NAME="Test"\nVERSION_ID="1"\n')
        for d in (lay.docker_config, lay.backups):
            os.makedirs(d, 0o700, exist_ok=True)
        for d in (lay.root, lay.backups, lay.secrets_dir(n)):
            os.chmod(d, 0o700)
        os.chmod(lab.secret_file, 0o600)
        cls.environ = {brand.env("ROOT"): lay.root, brand.env("BACKUPS"): lay.backups, brand.env("HOST"): "h"}
        ctx = cx.make_ctx(cls.environ)
        server = ctx.version["Server"]
        tested = [{"engine": ".".join(server["Version"].split(".")[:2]), "arch": server["Arch"]}]
        for patch in (
            mock.patch.object(brand, "HOST_FACTS_DIR", facts),
            mock.patch.object(gate, "load_tested", return_value=tested),
        ):
            patch.start()
            cls.addClassCleanup(patch.stop)
        cert = {"kind": "selftest", "result": "PASS", "build": cx.build_facts(ctx)}
        state.write_doc_once(f"{lay.certifications_dir}/x-selftest.json", cert)
        plain = dict(cx.env_values(lab.isolated_env.encode()))
        lines = ["instance = 1", f'name = "{n}"', 'app = "fx-lite"', 'environment = "test"', "disposable = true"]
        lines += [
            "[source]",
            f'repo = "file://{lay.fixtures_dir}/fx-lite"',
            "[params]",
            f'FXLITE_IMAGE = "{lab.image}"',
        ]
        lines += ["[app_env]", *(f'{k} = "{v}"' for k, v in plain.items())]
        Path(lay.inst_toml(n)).write_text("\n".join(lines) + "\n")
        os.makedirs(lab.g1, 0o700)
        os.chown(lab.g1, 10001, 10001)
        os.makedirs(lay.env_dir(n), 0o700)
        Path(lab.app_env["path"]).write_text(lab.isolated_env + f"MAIL_PASSWORD='{lab.secret}'\n")
        v = lab.variant()
        doc = {"seq": 1, "instance": n, "op": 1, "origin": "install", "release": RELEASE, "commit": COMMIT}
        doc |= {"export": lab.export, "images": {"app": lab.image}, "refs": {"app": IMAGE}, "digests": {"app": None}}
        doc |= {"manifest_sha256": lab.manifest_sha(), "model_sha256": "0" * 64, "params": v["env"]}
        doc |= {"app_env_sha256": lab.app_env["sha256"], "env_file": lab.app_env["path"], "generations": {"data": 1}}
        at = records.iso(records.utc_now())
        doc |= {"schema": {"expected": 1, "actual": 1, "at": at}, "writes_reopened_at": at, "created_at": at}
        state.write_doc_once(lay.deployment_json(n, 1), records.new_doc("deployment", **doc))
        snap = lay.deployment_snapshot(n, 1)
        os.makedirs(snap)
        Path(snap, brand.MANIFEST_FILE).write_bytes(Path(lab.manifest).read_bytes())
        Path(snap, "override.yaml").write_text(v["override"])
        Path(snap, "compose.env").write_bytes(cx.env_text(v["env"]))
        result = {"op": 1, "op_kind": "deploy", "instance": n, "outcome": "completed", "exit": 0, "code": "completed"}
        result |= {"message": "completed", "next": None, "started_at": at, "finished_at": at, "warnings": []}
        state.write_doc_once(f"{lab.op_dir(1, 'deploy')}/result.json", records.new_doc("result", **result))
        rec = state.read_doc(lay.record_json(n), "instance")
        rec |= {"state": "running", "current_deployment": 1, "generations": {"data": 1}, "next_seq": 2}
        rec["last_op"] = {"seq": 1, "kind": "deploy", "outcome": "completed", "at": at}
        state.replace_doc(lay.record_json(n), rec)
        digest = "a" * 64
        entry = {"bundle_id": "b1", "bundle_hash": digest, "class": "manual", "size": 1, "created_at": at}
        state.write_doc_once(lay.catalog(n, "b1"), records.new_doc("catalog", **entry, path="", imported=False))
        for level in ("verified", "restore-tested"):
            ver = {"bundle_id": "b1", "bundle_hash": digest, "level": level, "ok": True, "op": 1, "at": at}
            fs.append_line(
                lay.verification(n, "b1"), records.dumps(records.new_doc("verification", **ver, evidence={}))
            )
        p = Project(n, lab.export, ("compose.yaml",), f"{snap}/override.yaml", f"{snap}/compose.env")
        res = lab.compose.up(EffectToken(0, 0), p, ["app"], timeout=120)  # the test stands in for the executor
        if res.code != 0:
            raise AssertionError(res.err)
        cls.wait_running(lab)

    @staticmethod
    def wait_running(lab: Lab) -> None:
        """Running, and still running a moment later (no restart loop)."""
        labels = {brand.label("instance"): lab.name}
        for i in range(60):
            time.sleep(0.5)
            found = lab.docker.containers(labels)
            if i > 4 and found and all(c["State"]["Running"] for c in found):
                return
        raise AssertionError("the deployed app does not keep running")

    def status(self, fn: Any = st.status, *args: Any) -> dict[str, Any]:
        ctx = cx.make_ctx(self.environ)
        rep: dict[str, Any] = fn(ctx, *args)
        return rep

    def container(self) -> str:
        found = self.lab.docker.containers({brand.label("instance"): self.lab.name}, project=self.lab.name)
        self.assertEqual(len(found), 1)
        return str(found[0]["Id"])

    def test_a_container_recreated_outside_is_drift(self) -> None:
        """Compose run by hand on other settings (as a vendor GUI may do) recreates the container with another
        config hash; status names it, and the recorded files bring it back."""
        lab, n = self.lab, self.lab.name
        snap, other = lab.layout.deployment_snapshot(n, 1), f"{lab.base}/other.env"
        env = cx.env_values(Path(snap, "compose.env").read_bytes()) | {"FXLITE_RELEASE": "other"}
        Path(other).write_bytes(cx.env_text(env))
        files, ovr = ("compose.yaml",), f"{snap}/override.yaml"
        try:
            res = lab.compose.up(EffectToken(0, 0), Project(n, lab.export, files, ovr, other), ["app"], timeout=120)
            self.assertEqual(res.code, 0, res.err)
            self.wait_running(lab)
            rep = self.status(st.status, n)
            self.assertEqual(
                rep["attention"],
                {
                    "drift": [
                        "service app is running with settings that differ from deployment 1; restart the app to put "
                        "the deployed settings back"
                    ]
                },
            )
            self.assertEqual((rep["exit"], rep["next"]), (5, f"{brand.CLI} restart {n}"))
        finally:
            back = Project(n, lab.export, files, ovr, f"{snap}/compose.env")
            lab.compose.up(EffectToken(0, 0), back, ["app"], timeout=120)
            self.wait_running(lab)
            os.remove(other)
        self.assertEqual(self.status(st.status, n)["exit"], 0)

    def test_logs_are_redacted(self) -> None:
        lab, name = self.lab, f"{self.lab.name}-echo"
        labels = {PROJECT_LABEL: lab.name, brand.label("instance"): lab.name, cx.SERVICE: "echo"}
        script = f"echo out {lab.secret}; echo err {lab.secret} >&2"
        argv = ["run", "--name", name, *(x for k, v in labels.items() for x in ("--label", f"{k}={v}"))]
        made = lab.cli(*argv, "--entrypoint", "sh", IMAGE, "-c", script)
        try:
            self.assertEqual((made.returncode, made.stdout.strip()), (0, f"out {lab.secret}"), made.stderr)
            rep = self.status(st.logs, lab.name, "echo")
            self.assertEqual(rep["lines"], [f"{name} | out ***", f"{name} ! err ***"])
            self.assertNotIn(lab.secret, json.dumps(rep))
        finally:
            lab.cli("rm", name)

    def test_clean_status_and_doctor_write_nothing(self) -> None:
        lab = self.lab
        before, since = (tree_hash(lab.base), tree_hash(lab.layout.backups)), f"{time.time():.6f}"
        rep = self.status(st.status, lab.name)
        self.assertEqual((rep["exit"], rep["attention"], rep["next"]), (0, {}, None), rep["lines"])
        self.assertEqual(rep["instance"]["services"][0]["state"], "running")
        self.assertEqual(rep["host"]["gate_tier"], 2)
        rep = self.status(st.doctor, lab.name)
        self.assertEqual((rep["exit"], {k: v for k, v in rep["checks"].items() if v}), (0, {}), rep["lines"])
        self.assertEqual(self.status(st.status, None)["exit"], 0)
        row = next(r for r in self.status(st.list_)["instances"] if r["name"] == lab.name)
        self.assertEqual((row["state"], row["release"]), ("running", RELEASE))
        ps = self.status(st.ps, lab.name)["containers"]
        self.assertEqual([(r["service"], r["owned"]) for r in ps], [("app", True)])
        logs = self.status(st.logs, lab.name, "app")
        self.assertEqual(logs["exit"], 0)
        self.assertNotIn(lab.secret, json.dumps(logs))
        self.assertEqual([r["outcome"] for r in self.status(st.history, lab.name)["operations"]], ["completed"])
        self.assertEqual([b["id"] for b in self.status(st.bundles, lab.name)["bundles"]], ["b1"])
        self.assertEqual((tree_hash(lab.base), tree_hash(lab.layout.backups)), before)
        events = lab.docker.events(since, f"{time.time() + 0.5:.6f}")
        self.assertEqual([e for e in events if lab.name in json.dumps(e)], [])

    def test_stopped_container_is_changed_outside(self) -> None:
        cid = self.container()
        self.lab.cli("stop", cid)
        try:
            rep = self.status(st.status, self.lab.name)
            self.assertEqual(rep["attention"], {"changed-outside": [DOWN]})
            self.assertEqual((rep["exit"], rep["next"]), (5, f"{brand.CLI} restart {self.lab.name}"))
        finally:
            self.lab.cli("start", cid)
            self.wait_running(self.lab)
        self.assertEqual(self.status(st.status, self.lab.name)["exit"], 0)

    def test_foreign_container_and_network_in_the_project(self) -> None:
        n, name = self.lab.name, f"{self.lab.name}-intruder"
        project = f"{PROJECT_LABEL}={n}"
        made = self.lab.cli("create", "--name", name, "--label", project, IMAGE, "true")
        self.assertEqual(made.returncode, 0, made.stderr)
        net = self.lab.cli("network", "create", "--label", project, "--label", f"{brand.label('instance')}={n}x", name)
        try:
            self.assertEqual(net.returncode, 0, net.stderr)
            rep = self.status(st.status, n)
            foreign = f"{FOREIGN} ({brand.PRODUCT} did not create it for {n}); it is left untouched"
            why = [f"container {name} {foreign}", f"Docker network {name} {foreign}"]
            self.assertEqual(rep["attention"], {"foreign": why})
            self.assertEqual((rep["exit"], rep["next"]), (5, f"{brand.CLI} ps {n}"))
            ps = self.status(st.ps, n)["containers"]
            self.assertEqual([r["name"] for r in ps if not r["owned"]], [name])
        finally:
            self.lab.cli("rm", name)
            self.lab.cli("network", "rm", name)

    def test_an_operation_runs_while_its_executor_or_task_container_does(self) -> None:
        """Found by their labels on the daemon: the instance's executor, or a task container of the operation while
        the CLI has a step of it in flight (a terminal task); the host executor runs only selftest instances'
        operations, and a task container that outlived the detached executor runs none."""
        lab, n, role = self.lab, self.lab.name, brand.label("role")
        op, made = lab.op_dir(5, "task"), []

        def plan(foreground: bool) -> None:
            if os.path.exists(f"{op}/plan.json"):
                os.remove(f"{op}/plan.json")
            step = {"n": 1, "type": "RunTask", "klass": "scratch", "args": {"effect": "read"}}
            state.write_doc_once(
                f"{op}/plan.json", records.new_doc("plan", steps=[step], inputs={"foreground": foreground})
            )

        def run(name: str, **labels: str) -> None:
            made.append(name)
            argv = ["run", "-d", "--name", name, *(x for k, v in labels.items() for x in ("--label", f"{k}={v}"))]
            res = lab.cli(*argv, "--entrypoint", "sleep", IMAGE, "300")
            self.assertEqual(res.returncode, 0, res.stderr)

        def states() -> tuple[str, str]:
            rep = self.status(st.status, n)
            return rep["instance"]["operations"][0]["state"], self.status(st.history, n)["operations"][-1]["state"]

        try:
            plan(False)  # the detached executor runs it
            Journal(op, 5).intent(1, 1)
            run(f"{n}-host", **{role: "exec"})
            self.assertEqual(states(), ("interrupted", "interrupted"))
            run(f"{n}-exec", **{role: "exec", brand.label("instance"): n})
            self.assertEqual(states(), ("running", "running"))
            lab.cli("rm", "-f", made.pop())
            task = {role: "task", brand.label("instance"): n, brand.label("op"): "5", brand.label("step"): "1"}
            run(f"{n}-x5-1-a1", **task)  # it outlived the executor
            self.assertEqual(states(), ("interrupted", "interrupted"))
            plan(True)  # the CLI runs it
            self.assertEqual(states(), ("running", "running"))
            self.assertEqual(self.status(st.status, n)["exit"], 0)
        finally:
            lab.cli("rm", "-f", *made)
            shutil.rmtree(op)

    def test_a_partial_stop_is_no_change_outside(self) -> None:
        """`stop <i> <service>` leaves the instance running; the container that stopped within that completed stop
        is stopped as asked, while one stopped again later, outside, is changed-outside."""
        lab, n, cid = self.lab, self.lab.name, self.container()
        d = lab.op_dir(6, "stop")
        stop = {"n": 1, "type": "Stop", "klass": "reversible", "args": {"variant": "current", "services": ["app"]}}
        state.write_doc_once(f"{d}/plan.json", records.new_doc("plan", steps=[stop]))
        try:
            started = records.iso(records.utc_now())
            self.assertEqual(lab.cli("stop", cid).returncode, 0)
            span = {"started_at": started, "finished_at": records.iso(records.utc_now())}
            state.write_doc_once(f"{d}/result.json", records.new_doc("result", outcome="completed", **span))
            rep = self.status(st.status, n)
            self.assertEqual((rep["exit"], rep["instance"]["services"][0]["state"]), (0, "exited"), rep["lines"])
            lab.cli("start", cid)
            time.sleep(1.1)  # the next second: past the stop's span
            lab.cli("stop", cid)
            rep = self.status(st.status, n)
            self.assertEqual(rep["attention"], {"changed-outside": [DOWN]})
        finally:
            lab.cli("start", cid)
            self.wait_running(lab)
            for f in ("plan.json", "result.json"):
                if os.path.exists(f"{d}/{f}"):
                    os.remove(f"{d}/{f}")
            os.rmdir(d)
        self.assertEqual(self.status(st.status, n)["exit"], 0)

    def test_open_operation_and_scheduled_status(self) -> None:
        lab, att = self.lab, self.lab.layout.attention_json
        rep = self.status(st.scheduled_status)
        self.assertEqual((rep["exit"], rep["lines"], os.path.exists(att)), (0, [], False))
        op = lab.op_dir(5, "backup")
        os.makedirs(op)
        try:
            rep = self.status(st.status, lab.name)
            self.assertEqual(
                rep["attention"], {"open-operation": ["operation 5 (backup) was interrupted before it finished"]}
            )
            self.assertEqual((rep["exit"], rep["next"]), (5, f"{brand.CLI} resume {lab.name}"))
            history = self.status(st.history, lab.name)["operations"]
            self.assertEqual([(r["seq"], r["outcome"]) for r in history], [(1, "completed"), (5, "open")])
            before = tree_hash(lab.base)
            rep = self.status(st.scheduled_status)
            self.assertEqual((rep["exit"], rep["lines"]), (5, [f"now needs attention: {lab.name}: open-operation"]))
            doc = state.read_doc(att, "attention")
            self.assertEqual(doc["codes"], {lab.name: ["open-operation"]})
            os.remove(att)
            self.assertEqual(tree_hash(lab.base), before)  # attention.json was the only file written
            self.status(st.scheduled_status)
            written = tree_hash(lab.base)
            rep = self.status(st.scheduled_status)
            self.assertEqual((rep["exit"], rep["lines"], tree_hash(lab.base)), (0, [], written))
        finally:
            os.rmdir(op)
        rep = self.status(st.scheduled_status)
        self.assertEqual((rep["exit"], rep["lines"]), (5, [f"no longer needs attention: {lab.name}: open-operation"]))
        self.assertEqual(state.read_doc(att, "attention")["codes"], {})
        self.assertEqual(self.status(st.scheduled_status)["exit"], 0)


if __name__ == "__main__":
    unittest.main()
