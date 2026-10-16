"""Suite 6, isolation (ARCHITECTURE §6.2, §7.4, §10.3 "Isolation" and "Generation safety"; LIFECYCLE F13, §3.4,
§4.9, §5.7), on a scratch host installed by the release's install.sh and certified, driven through the real wrapper.

The instance is fx-lite with a file secret through a `secrets_dir` param and a live network on a fixed `subnet` param
(the fixture's own files, edited by the test), in the outbound mode that really sends (the owner-gated keys set at
init) and with a seeded app-env secret. The live app sends a job; a job queued while it is stopped is in the bundle,
and the live app sends it once started again. A drill of that bundle is then killed by the test-only crash hook right
after its activation step, which leaves the isolated project `<i>--t<seq>` running. In it:

- every network is internal, labelled with the operation, on a /24 of the isolation pool held by an allocation entry;
- no port is published;
- the holds are in the container's environment, the owner-gated and secret app-env keys are not;
- the live secrets directory and the live generation are not mounted: a throwaway secret and the t<seq> generation are;
- no `sent/` (nor `captured/`) marker appears in the drill generation;
- the live container is untouched.

The next `scheduled backup` auto-abandons the drill: its teardown removes the isolated project, the t<seq>
generation and the subnet allocation, and the backup completes. Restore isolation (`<i>--r<seq>`) is M2."""

import ipaddress
import json
import os
import re
import secrets
import time
import unittest
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.store import state
from tests.harness import host

CLI = brand.CLI
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV |= {"PROXY_ADDRESS": "127.0.0.1", "DELIVERY_MODE": "smtp", "DELIVERY_ENABLED": "true"}
HOLDS = {"DELIVERY_MODE": "capture", "JOBS": "off"}
OP_DIR = re.compile(r"([0-9]+)-([a-z-]+)")
H: host.ScratchHost


def setUpModule() -> None:
    global H
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    H = host.ScratchHost("iso")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()


def edited(rel: str, edits: list[tuple[str, str]], tail: str) -> str:
    """fixtures/fx-lite/<rel> with each (old, new) replaced exactly once, then `tail` appended."""
    text = (host.REPO / "fixtures" / "fx-lite" / rel).read_text()
    for old, new in edits:
        if text.count(old) != 1:
            raise AssertionError(f"fixtures/fx-lite/{rel}: {old!r} is not there exactly once")
        text = text.replace(old, new)
    return text + tail


PORT_PARAM = 'FXLITE_PORT     = { kind = "port" }\n'
PARAMS = 'FXLITE_SUBNET   = { kind = "subnet" }\nFXLITE_SECRETS  = { kind = "secrets_dir" }\n'
MANIFEST = edited("ingat.toml", [(PORT_PARAM, PORT_PARAM + PARAMS)], '\n[secrets.session_key]\ngenerate = "alnum32"\n')
COMPOSE = edited(
    "compose.yaml",
    [("    restart: unless-stopped\n", '    restart: unless-stopped\n    secrets: ["session_key"]\n')],
    "secrets:\n  session_key:\n    file: ${FXLITE_SECRETS:?}/session_key\n"
    "networks:\n  default:\n    ipam:\n      config:\n        - subnet: ${FXLITE_SUBNET:?}\n",
)


def jdoc(res: host.Result) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(res[1])
    return doc


def eventually(path: str, timeout: float = 30) -> bool:
    end = time.monotonic() + timeout
    while not os.path.exists(path):
        if time.monotonic() > end:
            return False
        time.sleep(0.5)
    return True


class Isolation(unittest.TestCase):
    maxDiff = None

    def ops(self, name: str) -> list[tuple[int, str]]:
        found = (OP_DIR.fullmatch(d) for d in os.listdir(H.layout.ops_dir(name)))
        return sorted((int(m[1]), m[2]) for m in found if m)

    def live(self, name: str) -> dict[str, Any]:
        [c] = [c for c in host.inspect("container", [c[0] for c in host.inventory(name)["containers"]])
               if c["Config"]["Labels"].get("com.docker.compose.project") == name]  # fmt: skip
        self.assertEqual(c["State"]["Status"], "running")
        return c

    def tty(self, *args: str, code: int = 0) -> None:
        res = H.cli(*args, tty=True, answer=args[1])
        self.assertEqual(res[0], code, res[1])

    def pool_free(self, pool: ipaddress.IPv4Network) -> None:
        """A drill needs a pool /24 that no network of the daemon overlaps (host.pool_free); the shared scratch daemon
        may have none for a while, which blocks this suite rather than failing it."""
        if not host.pool_free(str(pool)):
            self.skipTest(f"BLOCKED: every /24 of the isolation pool {pool} overlaps a network of the scratch daemon")

    def project(self, project: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(containers, networks) of a Compose project."""
        f = f"label=com.docker.compose.project={project}"
        containers = host.docker("ps", "-aq", "--no-trunc", "--filter", f).split()
        networks = host.docker("network", "ls", "-q", "--no-trunc", "--filter", f).split()
        return host.inspect("container", containers), host.inspect("network", networks)

    def test_drill_runs_isolated_and_auto_abandon_tears_it_down(self) -> None:
        name, port = f"iti{secrets.token_hex(3)}", host.free_port()
        subnet = f"10.{200 + secrets.randbelow(50)}.{secrets.randbelow(256)}.0/24"
        [a] = H.fixture_repo("fx-lite", [{"ingat.toml": MANIFEST, "compose.yaml": COMPOSE}])
        lines = ["instance = 1", f'name = "{name}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
        lines += [f'repo = "{H.repo_url("fx-lite")}"', "[params]", f'FXLITE_IMAGE = "{H.image}"']
        lines += [f'FXLITE_PORT = "{port}"', f'FXLITE_SUBNET = "{subnet}"', "[app_env]"]
        lines += [f'{k} = "{v}"' for k, v in APP_ENV.items()]
        cfg = H.inbox(f"{name}.toml", "\n".join(lines) + "\n")
        self.tty("init", name, "--config", cfg, "--ref", a)
        secrets_dir = H.layout.secrets_dir(name)
        live_secret = Path(secrets_dir, "session_key").read_text()
        canary = f"canary{secrets.token_hex(12)}"  # the owner's mail password, as `secret set` (M2) stores it
        Path(secrets_dir, "env", "MAIL_PASSWORD").write_text(canary)
        os.chmod(Path(secrets_dir, "env", "MAIL_PASSWORD"), 0o600)
        self.tty("deploy", name, a, code=4)
        self.tty("resume", name)
        g1 = H.layout.data_gen(name, "data", "g1")

        # the live project: the live secret, the live generation, and an outbound mode that really sends
        c = self.live(name)
        self.assertIn((f"{secrets_dir}/session_key", "/run/secrets/session_key"),
                      [(m["Source"], m["Destination"]) for m in c["Mounts"]])  # fmt: skip
        job = json.loads(host.docker("exec", c["Id"], "fx-lite", "enqueue"))["job"]
        self.assertTrue(eventually(f"{g1}/sent/{job}"), "the live app does not send")

        # a job queued while the app is stopped is in the bundle; once started again, the live app sends it
        self.tty("stop", name)
        run = ["run", "--rm", "--label", f"{host.SCRATCH}=enqueue", "--network", "none", "--user", "10001:10001"]
        run += ["-v", f"{g1}:/data", "-e", "DATA_DIR=/data", "--entrypoint", "fx-lite", H.image, "enqueue"]
        queued = json.loads(host.docker(*run))["job"]
        res = H.cli("backup", name, "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        self.tty("start", name)
        self.assertTrue(eventually(f"{g1}/sent/{queued}"), "the live app does not send the queued job")
        live = self.live(name)

        # a drill of that bundle completes; its activation step is the last Up before the record
        pool = ipaddress.IPv4Network(state.read_doc(H.layout.host_json, "host")["pools"]["isolation"])
        self.pool_free(pool)
        res = H.cli("verify", name, "--latest", "--restore-test", "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        seq, _ = max(o for o in self.ops(name) if o[1] == "drill")
        plan = state.read_doc(f"{H.layout.op_dir(name, seq, 'drill')}/plan.json", "plan")
        up = max(n for n, s in enumerate(plan["steps"], 1) if s["type"] == "Up")
        self.assertEqual(plan["steps"][up]["type"], "Record")

        # the same drill, killed right after its activation step: the isolated project stays up to be inspected
        crash = {brand.env("CRASH_AT"): f"{up}:done:after"}
        self.pool_free(pool)
        res = H.cli_direct("verify", name, "--latest", "--restore-test", "--json", env=crash)
        self.assertEqual((res[0], jdoc(res)["code"]), (4, "executor-vanished"), res)
        seq, kind = self.ops(name)[-1]
        op = H.layout.op_dir(name, seq, kind)
        self.assertEqual((kind, os.path.exists(f"{op}/result.json")), ("drill", False))
        gen = H.layout.data_gen(name, "data", f"t{seq}")
        project = f"{name}--t{seq}"
        containers, networks = self.project(project)
        self.assertEqual([x["Config"]["Labels"]["com.docker.compose.service"] for x in containers], ["app"])
        [iso] = containers
        mine = {brand.label("instance"): name, brand.label("op"): str(seq)}
        self.assertEqual(iso["State"]["Status"], "running")
        self.assertLessEqual(mine.items(), iso["Config"]["Labels"].items())

        # no published port
        self.assertFalse(iso["HostConfig"].get("PortBindings"), iso["HostConfig"].get("PortBindings"))
        self.assertFalse([p for p in (iso["NetworkSettings"].get("Ports") or {}).values() if p])

        # internal networks only, on a pool /24 held by this operation's allocation entry (ARCHITECTURE §7.4)
        self.assertEqual(sorted(iso["NetworkSettings"]["Networks"]), sorted(n["Name"] for n in networks))
        nets = [ipaddress.IPv4Network(cfg["Subnet"]) for n in networks for cfg in n["IPAM"]["Config"] or ()]
        for n in networks:
            self.assertEqual((n["Internal"], mine.items() <= n["Labels"].items()), (True, True), n["Name"])
        self.assertEqual(len(nets), len(networks))
        self.assertTrue(all(x.subnet_of(pool) for x in nets), nets)
        held = [state.read_doc(H.layout.allocation("subnet", str(x)), "allocation") for x in nets]
        self.assertEqual([(d["instance"], d["op"], d["param"]) for d in held], [(name, seq, "FXLITE_SUBNET")])

        # the holds are in the environment; owner-gated and secret keys are not, nor the seeded secret anywhere
        env = dict(x.split("=", 1) for x in iso["Config"]["Env"])
        self.assertLessEqual(HOLDS.items(), env.items())
        self.assertFalse({"DELIVERY_ENABLED", "MAIL_PASSWORD"} & set(env), env)
        self.assertNotIn(canary, json.dumps(iso))
        for d, _, files in os.walk(op):
            for f in files:
                self.assertNotIn(canary.encode(), Path(d, f).read_bytes(), f)

        # the live secrets and the live generation are not mounted: a throwaway secret and t<seq> are
        mounts = {m["Destination"]: m["Source"] for m in iso["Mounts"]}
        self.assertEqual(mounts["/data"], gen)
        self.assertTrue(mounts["/run/secrets/session_key"].startswith(f"{op}/"), mounts)
        self.assertNotEqual(Path(mounts["/run/secrets/session_key"]).read_text(), live_secret)
        for src in mounts.values():
            self.assertFalse(src in (g1, secrets_dir) or src.startswith((f"{g1}/", f"{secrets_dir}/")), src)

        # nothing is delivered from the drill generation; the live container is untouched
        time.sleep(3)  # well over the job runner's cadence (0.2 s), were it running
        self.assertEqual([x for x in ("sent", "captured") if os.path.exists(f"{gen}/{x}")], [])
        self.assertEqual(self.live(name)["Id"], live["Id"])
        self.assertEqual(self.live(name)["State"]["StartedAt"], live["State"]["StartedAt"])
        res = H.cli("status", name, "--json")
        self.assertEqual(res[0], 5, res)
        self.assertIn("open-operation", jdoc(res)["attention"])

        # the next scheduled backup auto-abandons the drill: closed teardown, then the backup
        res = H.cli("scheduled", "backup", name)
        self.assertEqual((res[0], res[2]), (0, ""), res)
        self.assertRegex(res[1], rf"\Ascheduled backup {name}: completed \(operation [0-9]+\); "
                                 rf"operation {seq} \(drill\) abandoned-auto\n\Z")  # fmt: skip
        self.assertEqual(state.read_doc(f"{op}/result.json", "result")["outcome"], "abandoned-auto")
        steps = [json.loads(x) for x in Path(op, "steps.jsonl").read_text().splitlines()]
        teardown = len(plan["steps"])
        self.assertIn((teardown, "done"), [(x["step"], x["phase"]) for x in steps])
        self.assertEqual(self.project(project), ([], []))
        self.assertFalse(os.path.exists(gen) or os.path.exists(f"{gen}.json"))
        self.assertEqual([x for x in nets if os.path.exists(H.layout.allocation("subnet", str(x)))], [])
        self.assertTrue(os.path.exists(H.layout.allocation("subnet", subnet)))  # the live network's own, from init
        self.assertEqual(self.live(name)["Id"], live["Id"])
        res = H.cli("status", name, "--json")
        self.assertEqual((res[0], jdoc(res)["attention"]), (0, {}), res)


if __name__ == "__main__":
    unittest.main()
