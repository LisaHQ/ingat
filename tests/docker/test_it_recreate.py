"""Suite 6, recreate scope (ARCHITECTURE §6.2 "Stable config hashes", §10.3 "Recreate scope"; LIFECYCLE §4.5), on a
scratch host installed by the release's install.sh and certified, driven through the real wrapper on a pty.

fx-web2 (tests/data/fx-web2) is fx-web with a second stateless service, `docs`, in the same activation group as
`site`, and no per-commit value in either service. From the first install at commit A:

- commit B edits only `docs`: the plan ups exactly `docs`; the daemon creates and destroys only the `docs` container;
  `site` keeps its container ID and start time and has no event at all;
- commit C edits no service: a deployment is recorded (the commit changed) and no container is touched;
- deploying C again: nothing to do, exit 0, no operation and no trace;
- commit D edits only `site`: the converse.

Every update records origin `config` with the images of the deployment before it. The data-service half of the
suite (a code-only deploy of fx-pg keeps the data service's container) needs fx-pg (M2): not covered here."""

import json
import os
import re
import secrets
import unittest
from typing import Any

from ingat import brand
from ingat.store import state
from tests.harness import host

OP_DIR = re.compile(r"([0-9]+)-([a-z-]+)")
TOUCH = ("create", "start", "restart", "kill", "stop", "die", "destroy", "pause", "unpause")
H: host.ScratchHost


def setUpModule() -> None:
    global H
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    H = host.ScratchHost("recr")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()


def jdoc(res: host.Result) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(res[1])
    return doc


class RecreateScope(unittest.TestCase):
    maxDiff = None
    name = ""

    def ops(self) -> list[tuple[int, str]]:
        found = (OP_DIR.fullmatch(d) for d in os.listdir(H.layout.ops_dir(self.name)))
        return sorted((int(m[1]), m[2]) for m in found if m)

    def services(self) -> dict[str, tuple[str, str]]:
        """service -> (container ID, start time) of the live project's service containers."""
        out = {}
        for c in host.inspect("container", [c[0] for c in host.inventory(self.name)["containers"]]):
            labels = c["Config"]["Labels"]
            if labels.get("com.docker.compose.project") == self.name and labels.get(brand.label("role")) == "app":
                self.assertEqual(c["State"]["Status"], "running", c["Name"])
                out[labels["com.docker.compose.service"]] = (c["Id"], c["State"]["StartedAt"])
        return out

    def touched(self, since: str) -> dict[str, list[str]]:
        """service -> the daemon's lifecycle events on the live project's containers since `since`."""
        out: dict[str, list[str]] = {}
        for e in host.events(since, host.now()):
            attrs = e.get("Actor", {}).get("Attributes", {})
            own = e.get("Type") == "container" and attrs.get("com.docker.compose.project") == self.name
            if own and e.get("Action") in TOUCH:
                out.setdefault(attrs.get("com.docker.compose.service", ""), []).append(e["Action"])
        return out

    def deploy(self, commit: str, changed: list[str]) -> None:
        """Deploy `commit` and check that exactly `changed` were recreated, in the plan and on the daemon."""
        before, since = self.services(), host.now()
        res = H.cli("deploy", self.name, commit, tty=True, answer=self.name)
        self.assertEqual(res[0], 0, res[1])
        seq, kind = self.ops()[-1]
        plan = state.read_doc(f"{H.layout.op_dir(self.name, seq, kind)}/plan.json", "plan")
        steps = [(s["type"], s["args"].get("services")) for s in plan["steps"]]
        want = [("Up", changed)] if changed else []
        self.assertEqual((kind, steps[:-1]), ("deploy", [*want, ("Up", [])]), steps)  # then the identity and smoke
        self.assertEqual(steps[-1][0], "Record")
        touched = self.touched(since)
        self.assertEqual(sorted(touched), sorted(changed), touched)
        for s in changed:
            self.assertIn("create", touched[s])
            self.assertIn("destroy", touched[s])
        after = self.services()
        self.assertEqual(sorted(after), ["docs", "site"])
        for s, was in before.items():
            (self.assertNotEqual if s in changed else self.assertEqual)(after[s][0], was[0], s)
            if s not in changed:
                self.assertEqual(after[s][1], was[1], s)  # never restarted
        rec = H.record(self.name)
        dep = state.read_doc(H.layout.deployment_json(self.name, rec["current_deployment"]), "deployment")
        prev = state.read_doc(H.layout.deployment_json(self.name, dep["rollback_target"]), "deployment")
        self.assertEqual((dep["origin"], dep["commit"], dep["images"]), ("config", commit, prev["images"]))

    def test_config_only_change_recreates_exactly_the_changed_service(self) -> None:
        self.name = name = f"itr{secrets.token_hex(3)}"
        compose = (host.REPO / "tests" / "data" / "fx-web2" / "compose.yaml").read_text()
        docs_b = compose.replace('DOCS_NOTE: "a"', 'DOCS_NOTE: "b"')
        site_d = docs_b.replace('SITE_NOTE: "a"', 'SITE_NOTE: "d"')
        self.assertEqual(len({compose, docs_b, site_d}), 3)
        edits: list[dict[str, str | bytes | None]] = [{}, {"compose.yaml": docs_b}, {"CHANGES": "C\n"}]
        a, b, c, d = H.fixture_repo("fx-web2", [*edits, {"compose.yaml": site_d}], base="fx-web")
        ports = {"FXWEB_PORT": host.free_port(), "FXWEB_DOCS_PORT": host.free_port()}
        self.assertNotEqual(*ports.values())
        lines = ["instance = 1", f'name = "{name}"', 'app = "fx-web"', 'environment = "test"', "[source]"]
        lines += [f'repo = "{H.repo_url("fx-web2")}"', "[params]", f'FXWEB_IMAGE = "{H.image}"']
        lines += [f'{k} = "{v}"' for k, v in ports.items()]
        cfg = H.inbox(f"{name}.toml", "\n".join(lines) + "\n")
        for args in (("init", name, "--config", cfg, "--ref", a), ("deploy", name, a)):
            res = H.cli(*args, tty=True, answer=name)
            self.assertEqual(res[0], 0, res[1])
        self.assertEqual(sorted(self.services()), ["docs", "site"])

        self.deploy(b, ["docs"])
        self.deploy(c, [])

        # the deployed commit again: nothing to do, no operation, no trace (F2)
        self.assertTrue(host.wait_gone(brand.executor_name(name)))
        tree, inv, ops, since = host.tree_hash(H.layout.instances_dir), host.inventory(name), self.ops(), host.now()
        res = H.cli("deploy", name, c, "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "nothing-to-do"), res)
        self.assertEqual((host.tree_hash(H.layout.instances_dir), host.inventory(name), self.ops()), (tree, inv, ops))
        self.assertEqual(self.touched(since), {})

        self.deploy(d, ["site"])
        res = H.cli("status", name, "--json")
        self.assertEqual((res[0], jdoc(res)["attention"]), (0, {}), res)


if __name__ == "__main__":
    unittest.main()
