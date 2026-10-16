"""Suite 6, the version gate (ARCHITECTURE §3.6, §10.3 "Version gate"; LIFECYCLE F14, §6, §7), on a scratch host
installed by the release's install.sh and certified by `selftest --host`, driven through the real wrapper.

The fx-lite-ci instance is deployed with the tested release first. Then:

- An untested Engine: the host's wrapper runs a release whose tested.json does not list this lane, once with this
  Engine line on the other architecture only and once with another Engine line on this architecture only. Gate tier 0
  (read-only commands) runs and `status` shows `uncertified` attention; gate tier 1 (an online backup and a verify)
  runs with the gate's warning recorded in the plan, the result and the run file; every gate tier 2 command refuses
  with exit 2, code `untested-platform`, before an executor starts and without a trace; `selftest --host` cannot
  certify the build; a scheduled backup runs on and records that it skipped retention.
- An uncertified platform build: the wrapper mounts another /etc/os-release, an OS update as the CLI observes it.
  Gate tier 2 refuses with exit 2, code `uncertified`, next `selftest --host`; gate tiers 0 and 1 go on, a scheduled
  backup without retention.
- The tested release on the certified build runs gate tier 2 again: a drill of a bundle the untested release made.

The Engine API floor (1.43) is not exercised: both lanes' Engines meet it (24.0 is the floor itself)."""

import json
import os
import re
import secrets
import unittest
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.store import state
from tests.harness import host

CLI = brand.CLI
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
OP_DIR = re.compile(r"([0-9]+)-([a-z-]+)")
UNTESTED = "is not a tested combination of this release"
NO_CERT = "no host certification for this platform build"
SELFTEST = f"{CLI} selftest --host"
H: host.ScratchHost
REG: host.Registry
NAME = f"itg{secrets.token_hex(3)}"
COMMITS: list[str] = []


def setUpModule() -> None:
    global H, REG
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    REG = host.Registry()
    unittest.addModuleCleanup(REG.close)
    H = host.ScratchHost("gate")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()
    a, b = H.fixture_repo("fx-lite-ci", [{}, {"CHANGES": "B: schema 2\n"}], base="fx-lite")
    COMMITS.extend([a, b])
    REG.push(a, 1, H.claim)
    REG.push(b, 2, H.claim)
    lines = ["instance = 1", f'name = "{NAME}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
    lines += [f'repo = "{H.repo_url("fx-lite-ci")}"', "[params]", f'FXLITE_REGISTRY = "{REG.address}"']
    lines += [f'FXLITE_PORT = "{host.free_port()}"', "[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items())]
    cfg = H.inbox(f"{NAME}.toml", "\n".join(lines) + "\n")
    steps = ((("init", NAME, "--config", cfg, "--ref", a), 0), (("deploy", NAME, a), 4), (("resume", NAME), 0))
    for args, want in steps:  # the first install stops at its pause
        code, out, _ = H.cli(*args, tty=True, answer=NAME)
        if code != want:
            raise AssertionError(f"{args[0]} exited {code}, not {want}:\n{out}")


def jdoc(res: host.Result) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(res[1])
    return doc


def image_id(ref: str) -> str:
    return host.docker("image", "inspect", "--format", "{{.Id}}", ref).strip()


def untested(tag: str, **change: str) -> str:
    """The ID of a release image whose tested.json lists only this lane's entry with `change` applied."""
    return image_id(host.build_image(f"ingat:it-{tag}-{host.PROC}", tested=[host.lane_facts() | change]))


class Gate(unittest.TestCase):
    maxDiff = None

    # observation ---------------------------------------------------------------------------------------------
    def last(self, kind: str) -> tuple[int, dict[str, Any], dict[str, Any]]:
        """(seq, plan, result) of the newest closed operation of `kind`."""
        found = (OP_DIR.fullmatch(d) for d in os.listdir(H.layout.ops_dir(NAME)))
        seq = max(int(m[1]) for m in found if m and m[2] == kind)
        d = H.layout.op_dir(NAME, seq, kind)
        return seq, state.read_doc(f"{d}/plan.json", "plan"), state.read_doc(f"{d}/result.json", "result")

    def certifications(self) -> list[str]:
        return sorted(os.listdir(H.layout.certifications_dir))

    def effects(self, since: str) -> list[tuple[str, str, str]]:
        """Daemon events of this instance's objects since `since` (other suites may share the daemon): containers
        carrying its label, in its Compose projects or named after it (its executor), networks and volumes by name."""
        out = []
        for e in host.events(since, host.now()):
            attrs = e.get("Actor", {}).get("Attributes", {})
            who = attrs.get("name", "")
            mine = attrs.get(brand.label("instance")) == NAME or who.startswith(NAME)
            mine |= attrs.get("com.docker.compose.project", "").split("--")[0] == NAME
            mine |= who == brand.executor_name(NAME)
            if mine and e.get("Type") in ("container", "network", "volume"):
                out.append((e["Type"], e["Action"], who))
        return out

    def refused(self, cli: Any, *args: str, why: str, nxt: str | None = None) -> None:
        """Exit 2 and `why`, decided in the CLI's plan: no executor ran, nothing under instances/ and no Docker object
        of the instance changed (F2)."""
        self.assertTrue(host.wait_gone(brand.executor_name(NAME)))
        tree, inv, since = host.tree_hash(H.layout.instances_dir), host.inventory(NAME), host.now()
        res = cli(*args, "--json")
        doc = jdoc(res)
        self.assertEqual((res[0], doc["code"], doc.get("next")), (2, why, nxt), (args, res))
        self.assertEqual((host.tree_hash(H.layout.instances_dir), host.inventory(NAME)), (tree, inv), args)
        self.assertEqual(self.effects(since), [], args)

    def gate(self, cli: Any) -> str:
        """`status` through `cli`: exit 5, gate tier 1 and the one `uncertified` detail it shows."""
        res = cli("status", NAME, "--json")
        doc = jdoc(res)
        self.assertEqual((res[0], doc["host"]["gate_tier"]), (5, 1), res)
        [detail] = doc["attention"]["uncertified"]
        return str(detail)

    def tier1(self, cli: Any, warned: list[str]) -> None:
        """An online backup and a verify of it run; each operation records `warned` (the plan, its result, the run
        file) and the plan summary the CLI printed shows them."""
        for args, kind in ((("backup", NAME), "backup"), (("verify", NAME, "--latest"), "verify")):
            res = cli(*args, "--json")
            self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
            for w in warned:
                self.assertIn(f"warning: {w}", res[2])  # with --json, the summary goes to stderr
            _, plan, result = self.last(kind)
            self.assertEqual((plan["inputs"]["warnings"], result["warnings"]), (warned, warned))
            runs = [state.read_doc(f"{H.layout.runs_dir}/{f}", "run") for f in os.listdir(H.layout.runs_dir)]
            self.assertIn(warned, [r["warnings"] for r in runs if r.get("op") == result["op"]])
        res = cli("bundles", NAME, "--json")
        newest = max(jdoc(res)["bundles"], key=lambda b: str(b["created_at"]))
        self.assertIsNotNone(newest["verified_at"], newest)

    def scheduled(self, cli: Any, why: str) -> None:
        """A scheduled backup goes on at gate tier 1: one line, and its operation records the retention it skipped."""
        res = cli("scheduled", "backup", NAME)
        self.assertEqual((res[0], res[2]), (0, ""), res)
        self.assertRegex(res[1], rf"\Ascheduled backup {NAME}: completed \(operation [0-9]+\)\n\Z")
        _, plan, result = self.last("backup")
        self.assertFalse([s for s in plan["steps"] if s["type"] == "Delete"], plan["steps"])
        self.assertIn(f"retention skipped: {why}", result["warnings"])

    # the suites ----------------------------------------------------------------------------------------------
    def test_1_untested_engine(self) -> None:
        facts = host.lane_facts()
        other = {"amd64": "arm64"}.get(facts["arch"], "amd64")
        img = untested("untested-arch", arch=other)  # this Engine line, but only on the other architecture

        def ucli(*args: str, **kw: Any) -> host.Result:
            return host.cli_variant(H, *args, image=img, **kw)

        self.assertEqual(jdoc(ucli("version", "--json"))["image"], img)

        # gate tier 0: the read-only commands run and write nothing; status names the gate
        tree, inv = host.tree_hash(H.layout.instances_dir), host.inventory(NAME)
        self.assertIn(UNTESTED, self.gate(ucli))
        for args in (("list",), ("ps", NAME), ("bundles", NAME), ("history", NAME), ("doctor", NAME)):
            res = ucli(*args, "--json")
            self.assertIn(res[0], (0, 5), (args, res))
        self.assertTrue(any(UNTESTED in g for g in jdoc(ucli("doctor", NAME, "--json"))["checks"]["gate"]))
        self.assertEqual((host.tree_hash(H.layout.instances_dir), host.inventory(NAME)), (tree, inv))

        # gate tier 1: an online backup and its verify run, warned
        engine = host.docker("version", "--format", "{{.Server.Version}}").strip()
        warned = [f"Engine {engine} on {facts['arch']} {UNTESTED}"]
        self.tier1(ucli, warned)

        # gate tier 2 refuses, nothing written
        a, b = COMMITS
        for words in (
            ("deploy", NAME, a),
            ("deploy", NAME, b),
            ("prepare", NAME, b),
            ("start", NAME),
            ("stop", NAME),
            ("restart", NAME),
            ("resume", NAME),
            ("abandon", NAME),
            ("task", NAME, "queue-status"),
            ("backup", NAME, "--class", "final"),  # writers stop: not an online backup
            ("backup", NAME, "--prune"),  # retention is gate tier 2
            ("verify", NAME, "--latest", "--restore-test"),
            ("scheduled", "verify", NAME, "--latest", "--restore-test"),
        ):
            self.refused(ucli, *words, why="untested-platform")

        # selftest --host of a release that does not test this Engine certifies nothing
        certs = self.certifications()
        with host.daemon_lock("host-executor"):
            res = ucli("selftest", "--host", "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (2, "untested-platform"), res)
        self.assertEqual(self.certifications(), certs)

        # the nightly backup goes on and keeps every bundle
        self.scheduled(ucli, warned[0])

        # another Engine line on this architecture is just as untested
        line = f"{int(facts['engine'].split('.')[0]) + 1}.0"
        img2 = untested("untested-line", engine=line)

        def ucli2(*args: str, **kw: Any) -> host.Result:
            return host.cli_variant(H, *args, image=img2, **kw)

        self.assertIn(UNTESTED, self.gate(ucli2))
        self.refused(ucli2, "deploy", NAME, b, why="untested-platform")
        self.refused(ucli2, "verify", NAME, "--latest", "--restore-test", why="untested-platform")
        self.tier1(ucli2, warned)

        # the tested release runs gate tier 2 on the bundles the untested one made
        res = H.cli("status", NAME, "--json")
        self.assertNotIn("uncertified", jdoc(res)["attention"], res)
        res = H.cli("verify", NAME, "--latest", "--restore-test", "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        self.assertEqual(self.last("drill")[2]["warnings"], [])

    def test_2_uncertified_build(self) -> None:
        release = f"{H.base}/os-release"
        Path(release).write_text('NAME="Linux"\nID=it-updated\nVERSION_ID=99.1\nPRETTY_NAME="an updated release"\n')
        os.chmod(release, 0o644)

        def vcli(*args: str, **kw: Any) -> host.Result:
            return host.cli_variant(H, *args, os_release=release, **kw)

        self.assertIn(NO_CERT, self.gate(vcli))
        for args in (
            ("deploy", NAME, COMMITS[1]),
            ("stop", NAME),
            ("task", NAME, "queue-status"),
            ("backup", NAME, "--class", "final"),
            ("verify", NAME, "--latest", "--restore-test"),
            ("scheduled", "verify", NAME, "--latest", "--restore-test"),
        ):
            self.refused(vcli, *args, why="uncertified", nxt=SELFTEST)
        self.tier1(vcli, [])  # a tested Engine: gate tier 1 needs no certification and warns nothing
        self.scheduled(vcli, NO_CERT)

        # the build the certification names: gate tier 2 again
        res = H.cli("status", NAME, "--json")
        self.assertNotIn("uncertified", jdoc(res)["attention"], res)
        self.assertEqual(jdoc(res)["host"]["gate_tier"], 2)
        self.assertEqual([c[2] for c in host.inventory(NAME)["containers"]], ["running"])  # the live app, untouched


if __name__ == "__main__":
    unittest.main()
