"""App manifest schema 1: the documented examples parse, and the value parsers. The validation rules, each
refusing with its key path, are tests/unit/test_manifest_rules.py."""

import hashlib
import unittest
from pathlib import Path

from ingat.model.errors import Refused
from ingat.model.manifest import Manifest, parse_duration, parse_manifest, parse_size, task_outcome

DATA = Path(__file__).parent / "data"
VERSION = "0.1.0"
BUILD_ENV = 'build_env = { FXLITE_IMAGE = "fx-lite:{commit}" }\n'
LABELS = 'expect_labels = { "org.opencontainers.image.revision" = "{commit}" }\n'


def example(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


def edit(src: str, old: str, new: str, after: str = "") -> str:
    """Replace the first `old` at or after the anchor `after`."""
    at = src.index(old, src.index(after))
    return src[:at] + new + src[at + len(old) :]


def lite() -> str:
    """MANIFEST_SPEC §11 plus the label that binds {commit}, which OD-11 (b) requires for build_services."""
    return edit(example("fx-lite.toml"), BUILD_ENV, BUILD_ENV + LABELS)


def parse(src: str, version: str = VERSION) -> Manifest:
    return parse_manifest(src.encode(), tool_version=version)


class Examples(unittest.TestCase):
    def test_fx_pg(self) -> None:
        raw = example("fx-pg.toml").encode()
        m = parse_manifest(raw, tool_version=VERSION)
        self.assertEqual(m.raw_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual((m.manifest, m.app, m.source_kind, m.release), (1, "fx-pg", "git", "tag"))
        self.assertEqual(m.exclusive_environments, ("production",))
        self.assertEqual(m.build_services, ("backend", "web"))
        self.assertEqual(m.expect_labels["org.opencontainers.image.revision"], "{commit}")
        self.assertEqual(m.params["FXPG_RELEASE"].value, "{release}")
        self.assertEqual(m.params["POSTGRES_USER"].default, "fx_owner")
        self.assertTrue(m.params["FXPG_TIMEZONE"].required)
        self.assertTrue(m.params["FXPG_DB_MEMORY"].optional)
        self.assertEqual(m.params["FXPG_HTTP_PORT"].kind, "port")
        self.assertEqual((m.secrets["app_password"].generate, m.secrets["app_password"].mode), ("alnum32", 0o444))
        store = m.stores["pgdata"]
        self.assertEqual(
            (store.kind, store.volume, store.param, store.service, store.ready),
            ("volume", "postgres_data", None, "db", "db-ready"),
        )
        self.assertTrue(store.online_backup)
        self.assertEqual(m.services.writers, ("backend",))
        self.assertEqual(m.services.log_snapshot, ("db", "backend", "web"))
        self.assertEqual(
            (m.schema.task, m.schema.expected, m.schema.migrates_on_start), ("revision", "expected_revision", False)
        )
        ready = m.probes["db-ready"]
        self.assertEqual(
            (ready.kind, ready.service, ready.stable, ready.interval, ready.timeout), ("exec", "db", 15, 2, 180)
        )
        self.assertEqual(
            m.probes["backend-ready"].expect.json,
            {"status": ("ok",), "release": ("{release}",), "schema": ("current",)},
        )
        self.assertEqual(m.probes["web-healthy"].kind, "health")
        edge = m.probes["edge-ready"]
        self.assertEqual(
            (edge.http.port_param, edge.http.path, edge.http.method), ("FXPG_HTTP_PORT", "/api/health", "GET")
        )
        self.assertEqual(edge.expect.status, 200)
        self.assertEqual([g.reopens_writes for g in m.activate], [False, False, True])
        self.assertEqual(len(m.smoke), 7)
        gate = m.smoke[5]
        self.assertEqual(
            (gate.name, gate.probe.kind, gate.probe.http.method, gate.probe.http.body),
            ("write-gate-refuses-missing-release", "http", "POST", "{}"),
        )
        self.assertEqual(m.smoke[0].probe.expect.header_equals, {"cache-control": "no-cache"})
        self.assertEqual(
            [s.kind for s in m.install], ["start", "task", "task", "start", "start", "pause", "start", "task"]
        )
        self.assertEqual(
            (m.install[3].params, m.install[3].log_snapshot, m.install[0].log_snapshot),
            ({"FXPG_BACKEND_WORKERS": "1"}, False, True),
        )
        self.assertEqual((m.deploy.prechecks, m.deploy.migrate), (("check", "check-compat-candidate"), "migrate"))
        self.assertEqual(m.backup.naming["pre-change"], "{bundle.stamp}-pre-release-{target.release}")
        self.assertEqual(
            (m.restore.start, m.restore.post, m.restore.activate), (("db",), ("db-roles", "db-grants"), False)
        )
        self.assertEqual(m.drill.min_free_memory, 2 << 30)
        self.assertEqual(m.holds, {"web": {"FXPG_PROXY_ADDRESS": "127.0.0.1"}})
        migrate = m.tasks["migrate"]
        self.assertEqual(migrate.exit, {0: "ok", 1: "refused", 2: "unknown"})
        self.assertEqual(
            (migrate.image, migrate.timeout, migrate.operator, migrate.observe), ("candidate", 3600, False, "schema")
        )
        self.assertEqual(migrate.mounts, {"FXPG_BACKUP_DIR": "bundle"})
        dump = m.tasks["pg-dump"]
        self.assertEqual(
            (dump.mode, dump.stdout, dump.nonempty, dump.env),
            ("exec", "file:.partial/{bundle.id}/db.dump", True, {"TZ": "UTC"}),
        )
        self.assertEqual(m.tasks["reset-password"].args, {"user": "^[A-Za-z0-9._@-]{1,64}$"})
        self.assertTrue(m.tasks["reset-password"].operator)

    def test_fx_lite_as_written_misses_the_od11_label(self) -> None:
        with self.assertRaises(Refused) as cm:
            parse(example("fx-lite.toml"))
        self.assertEqual(cm.exception.code, "invalid-manifest")
        self.assertEqual(
            cm.exception.message.splitlines()[1:],
            ["compose.expect_labels: must bind {commit}: build_services are pulled"],
        )

    def test_fx_lite_with_the_label(self) -> None:
        m = parse(lite())
        keys = m.app_env.keys
        self.assertEqual(m.app_env.param, "FXLITE_ENV_FILE")
        self.assertIn("SEED_PASSWORD", m.app_env.forbidden)
        self.assertEqual(
            (keys["DELIVERY_MODE"].default, keys["DELIVERY_MODE"].allowed), ("capture", ("capture", "smtp"))
        )
        self.assertTrue(
            keys["DELIVERY_MODE"].owner_gated and keys["MAIL_PASSWORD"].secret and keys["JOBS"].tool_managed
        )
        self.assertEqual((keys["SESSION_HOURS"].pattern, keys["SESSION_HOURS"].allowed), ("^[0-9]{1,4}$", None))
        store = m.stores["data"]
        self.assertEqual(
            (store.kind, store.param, store.owner, store.mode, store.local_only),
            ("bind", "FXLITE_DATA_DIR", (10001, 10001), 0o700, True),
        )
        self.assertEqual((m.schema.probe, m.schema.task), ("ready", None))
        self.assertEqual(m.install[2].allow_tasks, ("bootstrap-config", "bootstrap-new-code"))
        self.assertEqual(
            m.backup.naming, dict.fromkeys(("scheduled", "manual", "pre-change", "final"), "{bundle.stamp}-{class}")
        )
        self.assertIsNone(m.backup.payload)
        self.assertEqual(m.rollback_env, {"JOBS": "off"})
        self.assertEqual(m.drill.min_free_memory, 512 << 20)
        se = m.side_effects
        self.assertEqual(
            (se.kind, se.restore_via_app, se.after_restore, se.clear_hold, se.single_active),
            ("outbound", True, "held", "queue-resume", True),
        )
        self.assertEqual(m.tasks["queue-held"].expect, {"outcome": ("preview",)})
        self.assertEqual(m.tasks["restore"].mounts, {"/in": "bundle", "/restore": "generation:data"})
        self.assertEqual(m.tasks["bootstrap-config"].max_input_bytes, 262144)
        self.assertIsNone(m.tasks["backup"].expect)

    def test_fx_lite_m1_form(self) -> None:
        # One Compose file that also carries `build: .`, and no FXLITE_SUBNET (MANIFEST_SPEC §11).
        src = "".join(line for line in lite().splitlines(True) if not line.startswith("FXLITE_SUBNET"))
        src = edit(src, '["compose.yaml", "compose.build.yaml"]', '["compose.yaml"]')
        m = parse(src)
        self.assertNotIn("FXLITE_SUBNET", m.params)
        self.assertEqual((m.files, m.build_files), (("compose.yaml",), ("compose.yaml",)))

    def test_site(self) -> None:
        m = parse(example("site.toml"))
        self.assertEqual((m.source_kind, m.release, m.source_images), ("image", None, {"site": "SITE_IMAGE"}))
        self.assertEqual((m.params["SITE_IMAGE"].kind, m.params["SITE_IMAGE"].service), ("image", "site"))
        self.assertEqual((m.backup.strategy, m.backup.steps, m.side_effects.kind), ("none", (), "none"))
        self.assertEqual((m.schema, m.app_env, m.stores, m.tasks, m.build_services), (None, None, {}, {}, ()))


class Values(unittest.TestCase):
    def test_durations(self) -> None:
        for text, seconds in (("15s", 15), ("2m", 120), ("1h", 3600), ("60m", 3600), ("120s", 120), ("0s", 0)):
            self.assertEqual(parse_duration(text), seconds)
        for text in ("15", "1d", "-1s", " 5s", "5S", "1.5h", ""):
            with self.subTest(text=text), self.assertRaises(Refused):
                parse_duration(text)

    def test_sizes(self) -> None:
        for text, size in (("512m", 512 << 20), ("2g", 2 << 30), ("1024k", 1 << 20)):
            self.assertEqual(parse_size(text), size)
        for text in ("2G", "2gb", "512", "", "1.5g"):
            with self.subTest(text=text), self.assertRaises(Refused):
                parse_size(text)

    def test_task_outcome(self) -> None:
        lite_tasks, pg_tasks = parse(lite()).tasks, parse(example("fx-pg.toml")).tasks
        cases = [
            (
                lite_tasks["migrate"],
                {0: "ok", 1: "unknown", 2: "unknown"},
            ),  # data effect: undeclared non-zero is unknown
            (lite_tasks["queue-held"], {2: "ok", 0: "ok", 1: "unknown"}),  # an undeclared 0 is ok
            (pg_tasks["revision"], {0: "ok", 1: "finding", 2: "failed", 3: "failed", 137: "failed"}),  # read
            (pg_tasks["migrate"], {1: "refused", 2: "unknown", 3: "unknown"}),
        ]
        for task, outcomes in cases:
            for code, outcome in outcomes.items():
                with self.subTest(task=task.name, code=code):
                    self.assertEqual(task_outcome(task, code), outcome)


if __name__ == "__main__":
    unittest.main()
