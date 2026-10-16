"""Suite 6, upgrade (ARCHITECTURE §3.4, §3.5, §10.3 "Upgrade"; ADR-0023), on a scratch host: release N-1 installed by
its install.sh and certified, then upgraded by the next release's install.sh, as an owner upgrades a host before M5.

- With an operation open (the fx-lite first install at its pause) the upgrade refuses with exit 2 and changes neither
  the wrapper nor the instance; after `resume` it runs `selftest --host` with the new image (a new certification),
  replaces the wrapper atomically and keeps the old one as `bin/ingat.prev`.
- Release N reads the state N-1 wrote; N writes (a backup); `bin/ingat.prev` reads that state and writes too.
- Record compatibility (ADR-0023): a field a later release adds within state schema 1 survives rewrites of
  record.json by either release; a record of a newer state schema refuses with exit 2 and leaves no trace.
- An upgrade to a release whose tested.json does not list this lane fails its `selftest --host` and keeps the current
  wrapper and `bin/ingat.prev` (a FAIL keeps the old wrapper).

No release precedes this one, so N-1 is this source's own image and N the same image plus one label layer (another
image ID, so the wrappers differ); the cross-version part of the suite is reported BLOCKED-partial by
`test_2_previous_release` until a previous release exists."""

import json
import os
import secrets
import unittest
from pathlib import Path
from typing import Any

from ingat import brand
from ingat.model import records
from ingat.store import state
from tests.harness import host

CLI = brand.CLI
APP_ENV = {"ALLOWED_ORIGINS": "http://127.0.0.1", "BASE_URL": "http://127.0.0.1", "MAIL_SENDER": "fx@example.invalid"}
APP_ENV["PROXY_ADDRESS"] = "127.0.0.1"
LATER = {"note": "an optional field a later release of state schema 1 adds"}
BLOCKED = (
    "BLOCKED-partial: no previous release exists, so release N-1 is this source's own image; install a real N-1 "
    "(the previous tag) and read each version's state with the other once one exists (ARCHITECTURE §10.3)"
)
H: host.ScratchHost
PREV_IMAGE = ""


def setUpModule() -> None:
    global H, PREV_IMAGE
    if not os.path.exists(host.SOCK):
        raise unittest.SkipTest("needs a scratch Docker daemon")
    H = host.ScratchHost("upg")
    unittest.addModuleCleanup(H.close)
    code, out, err = H.install()
    if code:
        raise AssertionError(f"install.sh exited {code}:\n{out}{err}")
    H.certify()
    PREV_IMAGE = H.image


def next_release() -> tuple[str, str]:
    """(tag, ID) of release N: the image under test plus one label layer, removed after the module."""
    tag = f"ingat:it-next-{host.PROC}"
    host.docker("build", "-q", "-t", tag, "-", stdin=f"FROM {H.claim}\nLABEL {host.SCRATCH}=release-n\n")
    unittest.addModuleCleanup(host.docker, "rmi", tag, check=False)
    return tag, host.docker("image", "inspect", "--format", "{{.Id}}", tag).strip()


def jdoc(res: host.Result) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(res[1])
    return doc


class Upgrade(unittest.TestCase):
    maxDiff = None

    def files(self) -> tuple[bytes, bytes | None, bool]:
        """The wrapper, bin/ingat.prev (None when missing) and whether bin/ingat.new exists."""
        prev = Path(f"{H.wrapper}.prev")
        return (
            Path(H.wrapper).read_bytes(),
            prev.read_bytes() if prev.exists() else None,
            os.path.exists(f"{H.wrapper}.new"),
        )

    def prev(self, *args: str, tty: bool = False, answer: str | None = None) -> host.Result:
        return host.run(["sh", f"{H.wrapper}.prev", *args], tty=tty, answer=answer)

    def reads(self, cli: Any, name: str) -> dict[str, tuple[int, Any]]:
        """What the read-only commands answer, without the times that move on their own."""
        out: dict[str, tuple[int, Any]] = {}
        for args in (("status", name), ("bundles", name), ("history", name), ("list",)):
            res = cli(*args, "--json")
            doc = jdoc(res)
            if args[0] == "status":
                doc = {k: doc["instance"][k] for k in ("state", "deployment", "generations", "last_op", "operations")}
                doc |= {"attention": sorted(jdoc(res)["attention"])}
            out[args[0]] = (res[0], doc if args[0] != "list" else doc["instances"])
        return out

    def certifications(self) -> list[str]:
        return sorted(os.listdir(H.layout.certifications_dir))

    def rewrite_record(self, name: str, **fields: Any) -> bytes:
        """Replace record.json with `fields` merged in, as another release would write it; returns the old bytes."""
        path = H.layout.record_json(name)
        old = Path(path).read_bytes()
        doc = state.read_doc(path, "instance") if "state_schema" not in fields else json.loads(old)
        self.put(path, records.pretty(doc | fields))
        return old

    def put(self, path: str, data: bytes) -> None:
        mode = os.stat(path).st_mode & 0o7777
        tmp = f"{path}.it-{secrets.token_hex(4)}"
        Path(tmp).write_bytes(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)

    def test_1_upgrade(self) -> None:
        name, port = f"itu{secrets.token_hex(3)}", host.free_port()
        [a] = H.fixture_repo("fx-lite", [{}])
        lines = ["instance = 1", f'name = "{name}"', 'app = "fx-lite"', 'environment = "test"', "[source]"]
        lines += [f'repo = "{H.repo_url("fx-lite")}"', "[params]", f'FXLITE_IMAGE = "{PREV_IMAGE}"']
        lines += [f'FXLITE_PORT = "{port}"', "[app_env]", *(f'{k} = "{v}"' for k, v in APP_ENV.items())]
        cfg = H.inbox(f"{name}.toml", "\n".join(lines) + "\n")
        res = H.cli("init", name, "--config", cfg, "--ref", a, tty=True, answer=name)
        self.assertEqual(res[0], 0, res[1])
        res = H.cli("deploy", name, a, tty=True, answer=name)  # the first install stops at its pause: open
        self.assertEqual(res[0], 4, res[1])
        nxt, nxt_id = next_release()
        self.assertNotEqual(nxt_id, PREV_IMAGE)

        # an open operation refuses the upgrade: exit 2, neither the wrapper nor the instance changes
        old, tree = self.files(), host.tree_hash(H.layout.instances_dir)
        self.assertEqual(old[1:], (None, False))
        with host.daemon_lock("host-executor"):
            res = host.install_release(H, nxt)
        self.assertEqual(res[0], 2, res)
        self.assertIn("an operation is open", res[2])
        self.assertIn(f"{H.layout.ops_dir(name)}/", res[2])
        self.assertEqual((self.files(), host.tree_hash(H.layout.instances_dir)), (old, tree))

        # closed, the upgrade certifies the new image on this daemon, then replaces the wrapper and keeps the old one
        res = H.cli("resume", name, tty=True, answer=name)
        self.assertEqual(res[0], 0, res[1])
        before, certs = self.reads(H.cli, name), self.certifications()
        with host.daemon_lock("host-executor"):
            res = host.install_release(H, nxt)
        self.assertEqual(res[0], 0, res)
        self.assertIn(f"installed version {H.version} ({nxt_id}) at {H.wrapper}", res[1])
        _, prev, new = self.files()
        self.assertEqual((prev, new, H.image), (old[0], False, nxt_id))
        made = sorted(set(self.certifications()) - set(certs))
        self.assertEqual(len(made), 1, made)
        cert = state.read_doc(f"{H.layout.certifications_dir}/{made[0]}", "selftest")
        self.assertEqual((cert["result"], cert["tool_version"]), ("PASS", H.version))
        self.assertEqual(jdoc(H.cli("version", "--json"))["image"], nxt_id)
        self.assertEqual(jdoc(self.prev("version", "--json"))["image"], PREV_IMAGE)

        # N reads the state N-1 wrote; N writes; N-1 reads it and writes; N reads that
        self.assertEqual(self.reads(H.cli, name), before)
        res = H.cli("backup", name, "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        after = self.reads(H.cli, name)
        self.assertEqual(self.reads(self.prev, name), after)
        [bundle] = after["bundles"][1]["bundles"]
        self.assertIsNotNone(bundle["verified_at"])
        res = self.prev("verify", name, bundle["id"], "--json")
        self.assertEqual((res[0], jdoc(res)["code"]), (0, "completed"), res)
        self.assertEqual(self.reads(H.cli, name), self.reads(self.prev, name))
        history = jdoc(H.cli("history", name, "--json"))
        self.assertIn("verify", json.dumps(history))

        # ADR-0023: a field a later release adds within schema 1 survives a rewrite of record.json by either release
        self.rewrite_record(name, it_later_field=LATER)
        for cli in (H.cli, self.prev):
            res = cli("verify", name, "--latest", "--json")  # opens and closes an operation: record.json rewritten
            self.assertEqual(res[0], 0, res)
            self.assertEqual(H.record(name)["it_later_field"], LATER)
            self.assertIsNone(H.record(name)["open_op"])

        # a record of a newer state schema: both releases refuse, exit 2, and nothing changes
        kept = self.rewrite_record(name, state_schema=records.STATE_SCHEMA + 1)
        try:
            for cli in (H.cli, self.prev):
                for args in (("status", name), ("backup", name), ("deploy", name, a)):
                    tree, inv = host.tree_hash(H.layout.instances_dir), host.inventory(name)
                    res = cli(*args, "--json")
                    self.assertEqual((res[0], jdoc(res)["code"]), (2, "newer-state"), (args, res))
                    self.assertEqual((host.tree_hash(H.layout.instances_dir), host.inventory(name)), (tree, inv))
        finally:
            self.put(H.layout.record_json(name), kept)
        self.assertEqual(H.cli("status", name, "--json")[0], 5)  # restore-test-old: no drill ran

        # an upgrade to a release that does not test this Engine fails its selftest and keeps both wrappers
        facts = host.lane_facts()
        other = {"amd64": "arm64"}.get(facts["arch"], "amd64")
        bad = host.build_image(f"ingat:it-untested-upg-{host.PROC}", tested=[facts | {"arch": other}])
        kept_files, certs = self.files(), self.certifications()
        with host.daemon_lock("host-executor"):
            res = host.install_release(H, bad)
        self.assertEqual(res[0], 3, res)
        self.assertIn("selftest --host failed; kept the current version", res[2])
        self.assertEqual((self.files(), self.certifications()), (kept_files, certs))
        self.assertEqual(H.image, nxt_id)

    def test_2_previous_release(self) -> None:
        self.skipTest(BLOCKED)


if __name__ == "__main__":
    unittest.main()
