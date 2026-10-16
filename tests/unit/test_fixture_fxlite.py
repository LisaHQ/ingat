"""The fx-lite fixture app (fixtures/fx-lite/app/fxlite.py), driven as a subprocess on scratch data directories."""

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parents[2] / "fixtures" / "fx-lite" / "app" / "fxlite.py"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str) -> tuple[int, bytes]:
    try:
        with OPENER.open(url, timeout=2) as r:
            return int(r.status), bytes(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class FxLiteTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()

    def env(self, schema: int, extra: dict[str, str]) -> dict[str, str]:
        base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DATA_DIR": str(self.data)}
        return base | {"FXLITE_SCHEMA": str(schema), "RELEASE": "r1"} | extra

    def app(self, *args: str, schema: int = 1, **extra: str) -> tuple[int, Any]:
        p = subprocess.run(
            [sys.executable, "-I", str(APP), *args],
            env=self.env(schema, extra),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return p.returncode, json.loads(p.stdout) if p.stdout.startswith("{") else p.stdout

    def start(self, command: str, **extra: str) -> tuple[str, subprocess.Popen[bytes]]:
        port = free_port()
        p = subprocess.Popen(
            [sys.executable, "-I", str(APP), command],
            env=self.env(1, extra | {"PORT": str(port)}),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(p.wait, 10)
        self.addCleanup(p.terminate)
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 15
        while True:
            try:
                get(url + "/")
                return url, p
            except OSError:
                if time.monotonic() > deadline or p.poll() is not None:
                    raise
                time.sleep(0.1)

    def backup(self, schema: int = 1) -> Path:
        out = self.root / "out"
        out.mkdir(exist_ok=True)
        code, doc = self.app("backup", "--to", str(out), schema=schema)
        self.assertEqual((code, doc["outcome"]), (0, "ok"), doc)
        return out / str(doc["name"])

    def empty_dir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir()
        return path

    def markers(self, job: str) -> list[str]:
        return [kind for kind in ("sent", "captured") if (self.data / kind / job).exists()]

    def wait_markers(self, job: str, expected: list[str]) -> None:
        deadline = time.monotonic() + (1.5 if not expected else 15)
        while time.monotonic() < deadline and not self.markers(job):
            time.sleep(0.1)
        self.assertEqual(self.markers(job), expected)

    def test_migrate_is_idempotent_and_a_newer_schema_is_refused(self) -> None:
        self.assertEqual(self.app("migrate"), (0, {"outcome": "ok", "from": 0, "to": 1}))
        self.assertEqual(self.app("migrate"), (0, {"outcome": "ok", "from": 1, "to": 1}))
        self.assertEqual(self.app("migrate", schema=3), (0, {"outcome": "ok", "from": 1, "to": 3}))
        code, doc = self.app("migrate", schema=2)
        self.assertEqual((code, doc["outcome"]), (2, "refused"))
        code, doc = self.app("serve", schema=2)
        self.assertEqual((code, doc["outcome"]), (2, "refused"))

    def test_serve_reports_health_and_readiness_and_stops_on_sigterm(self) -> None:
        url, p = self.start("serve")
        self.assertEqual(get(url + "/api/health"), (200, b'{"status": "ok", "release": "r1"}'))
        status, body = get(url + "/api/ready")
        ready = {"status": "ready", "data_writable": True, "schema": {"expected": 1, "actual": 1}}
        self.assertEqual((status, json.loads(body)), (200, ready))
        self.assertEqual(get(url + "/nope")[0], 404)
        code, out = self.app("probe", url + "/api/ready")
        self.assertEqual((code, out), (0, ready))
        self.assertEqual(self.app("probe", url + "/nope")[0], 1)
        self.assertEqual(self.app("probe", f"http://127.0.0.1:{free_port()}/")[0], 1)
        self.assertEqual(self.app("migrate", schema=2)[0], 0)  # a newer release migrated under the running one
        status, body = get(url + "/api/ready")
        doc = json.loads(body)
        self.assertEqual((status, doc["status"], doc["schema"]), (503, "not-ready", {"expected": 1, "actual": 2}))
        self.assertEqual(self.app("probe", url + "/api/ready"), (1, doc))
        p.terminate()
        self.assertEqual(p.wait(10), 0)

    def test_web_mode_serves_a_static_page(self) -> None:
        url, _ = self.start("web")
        status, body = get(url + "/")
        self.assertEqual(status, 200)
        self.assertIn(b"fx-web r1", body)
        self.assertEqual(json.loads(get(url + "/health")[1]), {"status": "ok", "release": "r1"})

    def test_delivery_honours_jobs_and_both_delivery_keys(self) -> None:
        smtp = {"DELIVERY_MODE": "smtp", "DELIVERY_ENABLED": "true"}
        cases: list[tuple[dict[str, str], list[str]]] = [
            ({}, ["captured"]),
            ({"DELIVERY_MODE": "smtp"}, ["captured"]),
            ({"DELIVERY_ENABLED": "true"}, ["captured"]),
            (smtp, ["sent"]),
            (smtp | {"JOBS": "off"}, []),
        ]
        for n, (extra, expected) in enumerate(cases):
            with self.subTest(env=extra):
                self.data = self.empty_dir(f"d{n}")
                _, p = self.start("serve", **extra)
                code, doc = self.app("enqueue")
                self.assertEqual(code, 0)
                self.wait_markers(doc["job"], expected)
                p.terminate()
                p.wait(10)

    def test_backup_restore_round_trip_holds_outbound_until_resumed(self) -> None:
        self.app("migrate")
        job = self.app("enqueue")[1]["job"]
        (self.data / "files" / "a.txt").write_bytes(b"attachment")
        payload = self.backup()
        manifest = json.loads((payload / "manifest.json").read_text())
        self.assertEqual(sorted(manifest["files"]), ["db.sqlite", "files/a.txt"])
        con = sqlite3.connect(self.data / "app.db")
        self.addCleanup(con.close)
        self.assertEqual(con.execute("SELECT name, outcome FROM backups").fetchall(), [(payload.name, "ok")])

        for d, _, names in os.walk(payload):  # read-only, like the private bundle copy a restore task gets
            for n in names:
                os.chmod(os.path.join(d, n), 0o440)
            os.chmod(d, 0o550)
        self.data = self.empty_dir("gen")
        code, doc = self.app("restore", "--from", str(payload), "--to", str(self.data))
        self.assertEqual((code, doc), (0, {"outcome": "ok", "schema": 1, "held": 1}))
        self.assertEqual((self.data / "files" / "a.txt").read_bytes(), b"attachment")
        for path in (self.data / "app.db", self.data / "files", self.data / "files" / "a.txt"):
            self.assertTrue(path.stat().st_mode & 0o200, f"{path} is not writable by its owner")

        _, p = self.start("serve", DELIVERY_MODE="smtp", DELIVERY_ENABLED="true")
        late = self.app("enqueue")[1]["job"]
        self.wait_markers(job, [])
        self.assertEqual(self.markers(late), [])
        code, doc = self.app("queue", "release")
        self.assertEqual((code, doc["outcome"], doc["paused"]), (2, "preview", "restored"))
        self.assertEqual([j["id"] for j in doc["held"]], [job])
        code, doc = self.app("queue", "resume", "--confirm")
        self.assertEqual((code, doc["outcome"]), (1, "refused"))
        self.assertEqual(self.app("queue", "release", "--job", job, "--confirm")[0], 0)
        code, doc = self.app("queue", "resume")
        self.assertEqual((code, doc["outcome"], doc["held"], doc["queued"]), (2, "preview", 0, 2))
        self.assertEqual(self.app("queue", "resume", "--confirm")[0], 0)
        self.wait_markers(job, ["sent"])
        self.wait_markers(late, ["sent"])
        p.terminate()
        p.wait(10)

    def test_queue_drop_and_usage_errors(self) -> None:
        self.app("migrate")
        self.app("enqueue")
        payload = self.backup()
        self.data = self.empty_dir("gen")
        self.assertEqual(self.app("restore", "--from", str(payload), "--to", str(self.data))[0], 0)
        held = self.app("queue", "drop")[1]["held"][0]["id"]
        for args in (["release", "--confirm"], ["drop", "--job", held, "--all"], ["resume", "--all"], ["purge"], []):
            with self.subTest(args=args):
                code, doc = self.app("queue", *args)
                self.assertEqual((code, doc["outcome"]), (2, "usage-error"))
        self.assertEqual(self.app("queue", "release", "--job", "unknown", "--confirm")[0], 1)
        code, doc = self.app("queue", "drop", "--all", "--confirm")
        self.assertEqual((code, doc["jobs"]), (0, [held]))
        self.assertEqual(self.app("queue", "release", "--all", "--confirm")[0], 1)
        self.assertEqual(self.app("queue", "resume", "--confirm")[0], 0)

    def test_backup_and_restore_refusals(self) -> None:
        self.app("migrate", schema=2)
        code, doc = self.app("backup", "--to", str(self.data / "files"), schema=2)
        self.assertEqual((code, doc["outcome"]), (2, "refused"))
        self.assertEqual(self.app("backup", "--to", str(self.root / "missing"), schema=2)[0], 2)
        self.assertEqual(self.app("backup", schema=2)[0], 2)
        payload = self.backup(schema=2)
        manifest = json.loads((payload / "manifest.json").read_text())
        busy = self.empty_dir("busy")
        (busy / "x").write_text("x")
        self.assertEqual(self.app("restore", "--from", str(payload), "--to", str(busy), schema=2)[0], 2)
        self.assertEqual(self.app("restore", "--from", str(payload), "--to", str(self.root / "none"), schema=2)[0], 2)
        empty = self.empty_dir("empty")
        code, doc = self.app("restore", "--from", str(payload), "--to", str(empty), schema=1)
        self.assertEqual((code, doc["outcome"]), (2, "refused"))
        (payload / "files" / "extra").write_text("x")
        code, doc = self.app("restore", "--from", str(payload), "--to", str(empty), schema=2)
        self.assertEqual((code, doc["outcome"]), (1, "failed"))
        (payload / "files" / "extra").unlink()
        with open(payload / "db.sqlite", "r+b") as f:  # a damaged page under a matching manifest hash
            f.seek(4096)
            f.write(b"\xff" * 16)
        manifest["files"]["db.sqlite"] = hashlib.sha256((payload / "db.sqlite").read_bytes()).hexdigest()
        (payload / "manifest.json").write_text(json.dumps(manifest))
        code, doc = self.app("restore", "--from", str(payload), "--to", str(empty), schema=2)
        self.assertEqual((code, doc["outcome"]), (1, "failed"))
        self.assertIn("database", doc["message"])
        self.assertEqual(os.listdir(empty), [])

    def test_links_are_never_followed_by_backup_or_restore(self) -> None:
        self.app("migrate")
        payload = self.backup()
        os.symlink("/etc", self.data / "files" / "etc")
        code, doc = self.app("backup", "--to", str(self.empty_dir("out2")))
        self.assertEqual((code, doc["outcome"]), (1, "failed"))
        self.assertIn("not a regular file", doc["message"])
        con = sqlite3.connect(self.data / "app.db")
        self.addCleanup(con.close)
        self.assertEqual([r[0] for r in con.execute("SELECT outcome FROM backups")], ["ok", "failed"])
        os.symlink("/etc", payload / "files" / "etc")
        empty = self.empty_dir("gen")
        code, doc = self.app("restore", "--from", str(payload), "--to", str(empty))
        self.assertEqual((code, doc["outcome"]), (1, "failed"))
        self.assertIn("not a regular file", doc["message"])
        self.assertEqual(os.listdir(empty), [])

    def test_backup_refuses_a_missing_database(self) -> None:
        out = self.empty_dir("out")
        code, doc = self.app("backup", "--to", str(out))
        self.assertEqual((code, doc["outcome"]), (2, "refused"))
        self.assertEqual(os.listdir(out), [])

    def test_bootstrap_prints_a_fresh_single_use_code(self) -> None:
        config = self.root / "boot.json"
        config.write_text("{}")
        first = self.app("bootstrap", "--new-code")
        second = self.app("bootstrap", "--config", str(config))
        self.assertEqual((first[0], second[0]), (0, 0))
        self.assertRegex(first[1], r"^[A-Za-z0-9_-]{16}\n$")
        self.assertNotEqual(first[1], second[1])
        stored = b"".join(p.read_bytes() for p in self.data.glob("app.db*"))
        for code in (first[1].strip(), second[1].strip()):  # only the hash of a code is kept
            self.assertNotIn(code.encode(), stored)
            self.assertIn(hashlib.sha256(code.encode()).hexdigest().encode(), stored)
        (self.root / "blank").write_bytes(b"")
        self.assertEqual(self.app("bootstrap", "--config", str(self.root / "blank"))[0], 1)
        self.assertEqual(self.app("bootstrap", "--config", str(self.root / "none"))[0], 1)
        self.assertEqual(self.app("bootstrap")[1]["outcome"], "usage-error")
        self.assertEqual(self.app("bogus")[0], 2)


if __name__ == "__main__":
    unittest.main()
