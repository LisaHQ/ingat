"""App manifest schema 1: every validation rule refuses, naming the key path (the documented examples and the
value parsers are tests/unit/test_manifest.py)."""

import unittest

from ingat.model.errors import Refused
from ingat.model.manifest import parse_manifest
from tests.unit.test_manifest import LABELS, VERSION, edit, example, lite, parse

TASK = '\n[tasks.extra]\nservice = "app"\nmode = "run"\neffect = "read"\ntimeout = "1m"\n'


class Rules(unittest.TestCase):
    def refused(self, src: str, version: str = VERSION) -> list[str]:
        with self.assertRaises(Refused) as cm:
            parse(src, version)
        self.assertEqual(cm.exception.code, "invalid-manifest")
        return cm.exception.message.splitlines()[1:]

    def assertRefused(self, src: str, *lines: str) -> None:
        errors = self.refused(src)
        for line in lines:
            self.assertIn(line, errors)

    def test_unknown_keys_at_every_level_all_reported(self) -> None:
        src = "colour = 1\n" + lite()
        src = edit(src, "[tasks.migrate]\n", "[tasks.migrate]\nretries = 3\n")
        src = edit(src, 'path = "/api/health" }', 'path = "/api/health", verb = "GET" }', after="[probes.edge-live]")
        src = edit(src, '"/out" = "stage" }', '"/out" = "stage" }\nexpect = { json = { ok = true }, status = 0 }')
        src = edit(src, 'FXLITE_PORT     = { kind = "port" }', 'FXLITE_PORT = { kind = "port", pattern = "^[0-9]+$" }')
        src = edit(src, "[stores.data]\n", '[stores.data]\nvolume = "x"\n')
        src = edit(src, "[backup]\n", '[backup.naming]\nnightly = "x"\n[backup]\n')
        self.assertEqual(
            self.refused(src),
            [
                "colour: unknown key",
                "params.FXLITE_PORT.pattern: unknown key",
                "stores.data.volume: unknown key",
                "probes.edge-live.http.verb: unknown key",
                "backup.naming.nightly: unknown key",
                "tasks.migrate.retries: unknown key",
                "tasks.backup.expect.status: unknown key",
            ],
        )

    def test_key_paths_quote_keys_that_are_not_bare(self) -> None:
        src = edit(lite(), '"/out" = "stage" }', '"/out" = 1 }')
        self.assertRefused(src, 'tasks.backup.mounts."/out": must be a string')

    def test_types_are_checked(self) -> None:
        src = edit(lite(), "manifest = 1", 'manifest = "1"')
        src = edit(src, 'timeout = "15m"', 'timeout = "15 minutes"', after="[tasks.migrate]")
        src = edit(src, "reopens_writes = true", 'reopens_writes = "yes"')
        src = edit(src, 'mode = "0700"', "mode = 448")
        self.assertRefused(
            src,
            "manifest: must be an integer",
            "tasks.migrate.timeout: '15 minutes' is not a duration such as 15s, 2m or 1h",
            "activate[0].reopens_writes: must be true or false",
            "stores.data.mode: must be a string",
        )

    def test_required_keys_and_choices(self) -> None:
        src = edit(lite(), 'effect = "data"\n', "", after="[tasks.migrate]")
        src = edit(src, 'kind = "git"', 'kind = "svn"')
        self.assertRefused(src, "tasks.migrate.effect: is required", "source.kind: must be one of: git, image")

    def test_exit_maps(self) -> None:
        src = lite() + TASK + 'exit = { 300 = "ok", 1 = "maybe", x = "ok", 2 = "failed" }\n'
        errors = self.refused(src)
        exit_errors = [e for e in errors if e.startswith("tasks.extra.exit: ")]
        self.assertEqual(len(exit_errors), 3, errors)
        self.assertTrue(
            all(any(e.startswith(f"tasks.extra.exit: {k} = ") for e in exit_errors) for k in ("300", "1", "x"))
        )

    def test_mutating_exec_outside_restore(self) -> None:
        src = edit(lite(), 'mode = "run"', 'mode = "exec"', after="[tasks.migrate]")
        errors = self.refused(src)
        for where in ("install", "deploy.migrate"):
            self.assertTrue(any(e.startswith(f"{where}: task 'migrate' mutates by exec") for e in errors), errors)

    def test_mutating_exec_in_restore_must_not_be_an_operator_task(self) -> None:
        src = edit(lite(), "post = []", 'post = ["extra"]', after="[restore]")
        src += TASK.replace('mode = "run"', 'mode = "exec"').replace('"read"', '"data"')
        self.assertEqual(self.refused(src), ["tasks.extra: a mutating exec task needs operator = false"])
        parse(src + "operator = false\n")

    def test_non_idempotent_migrate(self) -> None:
        src = edit(lite(), "idempotent = true", "idempotent = false", after="[tasks.migrate]")
        self.assertRefused(
            src,
            "install: task 'migrate' must be idempotent or declare observe",
            "deploy.migrate: task 'migrate' must be idempotent or declare observe",
        )
        parse(edit(src, "idempotent = false", 'idempotent = false\nobserve = "schema"', after="[tasks.migrate]"))

    def test_non_idempotent_app_write_backup_task(self) -> None:
        src = edit(lite(), "idempotent = true", "idempotent = false", after="[tasks.backup]")
        self.assertEqual(self.refused(src), ["backup.steps: task 'backup' must be idempotent (scratch)"])

    def test_terminal_task_in_backup_steps(self) -> None:
        src = edit(lite(), 'steps = ["backup"]', 'steps = ["backup", "bootstrap-new-code"]')
        errors = self.refused(src)
        msg = "backup.steps: task 'bootstrap-new-code' uses the terminal, so it runs only in the foreground CLI"
        self.assertIn(msg, errors)

    def test_expect_needs_json_or_record_stdout(self) -> None:
        src = edit(lite(), 'stdout = "record"', 'stdout = "terminal"', after="[tasks.queue-held]")
        self.assertEqual(self.refused(src), ['tasks.queue-held: expect needs stdout = "json" or "record"'])

    def test_outbound_needs_holds(self) -> None:
        src = edit(lite(), '[holds.app]\nDELIVERY_MODE = "capture"\nJOBS = "off"\n', "")
        msg = "side_effects.kind: outbound requires [holds], a restore task and restore_via_app = true"
        self.assertEqual(self.refused(src), [msg])

    def test_exactly_one_reopens_writes_group(self) -> None:
        two = lite() + '\n[[activate]]\nservices = ["app"]\nreopens_writes = true\n'
        none = edit(lite(), "reopens_writes = true", "reopens_writes = false")
        for src in (two, none):
            self.assertEqual(self.refused(src), ["activate: needs one reopens_writes group"])

    def test_unknown_template_variable(self) -> None:
        src = edit(lite(), '["fx-lite", "migrate"]', '["fx-lite", "migrate", "{nonsense}"]')
        self.assertEqual(self.refused(src), ["tasks.migrate: unknown template variable {nonsense}"])

    def test_variable_outside_its_context(self) -> None:
        src = edit(lite(), '"--to", "/out"]', '"--to", "/out", "{freeze_at}"]')
        src = edit(src, '"http://127.0.0.1:3000/api/ready"]', '"http://127.0.0.1:3000/api/ready", "{bundle.id}"]')
        src = edit(src, '"--job", "{arg.job}"', '"--job", "{arg.nope}"', after="[tasks.queue-drop-job]")
        self.assertEqual(
            self.refused(src),
            [
                "probes.ready: template variable {bundle.id} is not allowed here",
                "tasks.backup: template variable {freeze_at} is not allowed here",
                "tasks.queue-drop-job: template variable {arg.nope} names an undeclared arg",
            ],
        )
        # Allowed per use: a backup task may name the bundle, a restore task the target release.
        src = edit(lite(), '"--to", "/out"]', '"--to", "/out", "{bundle.id}", "{schema.expected}", "{image.app}"]')
        parse(edit(src, '"--to", "/restore"]', '"--to", "/restore", "{target.release}"]'))

    def test_requires_ingat(self) -> None:
        for version in ("0.1.0", "0.9.3", "0.1"):
            parse(lite(), version)
        for version in ("1.0.0", "0.0.9"):
            with self.subTest(version=version):
                self.assertEqual(
                    self.refused(lite(), version), [f"requires_ingat: '>=0.1,<1' excludes version {version}"]
                )
        src = edit(lite(), 'requires_ingat = ">=0.1,<1"', 'requires_ingat = "0.1+"')
        self.assertEqual(self.refused(src), ["requires_ingat: '0.1+' is malformed"])
        src = edit(lite(), 'requires_ingat = ">=0.1,<1"', 'requires_ingat = ""')
        self.assertEqual(self.refused(src), ["requires_ingat: '' is malformed"])
        src = edit(lite(), 'requires_ingat = ">=0.1,<1"\n', "")
        self.assertEqual(self.refused(src), ["requires_ingat: is required"])
        for version in ("1.0.0rc1", "1.0.0-rc.1", "dev"):  # a suffix is ignored (1.0.0rc1 counts as 1.0.0); "dev" as 0
            with self.subTest(version=version):
                self.assertEqual(len(self.refused(lite(), version)), 1)

    def test_a_task_variable_must_hold_at_every_use(self) -> None:
        # migrate is used by [[install]] and as deploy.migrate: {freeze_at} exists only for the latter.
        src = edit(lite(), '["fx-lite", "migrate"]', '["fx-lite", "migrate", "{freeze_at}"]')
        self.assertEqual(self.refused(src), ["tasks.migrate: template variable {freeze_at} is not allowed here"])
        parse(edit(src, 'task = "migrate"', 'start = ["app"]', after="[[install]]"))

    def test_install_tasks_that_write_must_be_redoable(self) -> None:
        src = edit(lite(), 'task = "migrate"', 'task = "queue-release-all"', after="[[install]]")
        self.assertEqual(self.refused(src), ["install: task 'queue-release-all' must be idempotent or declare observe"])

    def test_only_pre_change_naming_has_a_target_release(self) -> None:
        naming = '[backup.naming]\n{} = "{{bundle.stamp}}-{{target.release}}"\n[backup]\n'
        for klass in ("scheduled", "manual", "final"):
            with self.subTest(klass=klass):
                self.assertEqual(
                    self.refused(edit(lite(), "[backup]\n", naming.format(klass))),
                    [f"backup.naming.{klass}: template variable {{target.release}} is not allowed here"],
                )
        m = parse(edit(lite(), "[backup]\n", naming.format("pre-change")))
        self.assertEqual(m.backup.naming["pre-change"], "{bundle.stamp}-{target.release}")
        self.assertEqual(m.backup.naming["manual"], "{bundle.stamp}-{class}")

    def test_references(self) -> None:
        src = edit(lite(), 'wait = ["ready", "edge-live"]', 'wait = ["ready", "nope"]')
        src = edit(src, 'migrate = "migrate"', 'migrate = "nope"', after="[deploy]")
        src = edit(src, 'clear_hold = "queue-resume"', 'clear_hold = "nope"')
        self.assertRefused(
            src,
            "activate[0].wait: names an unknown probe 'nope'",
            "deploy.migrate: names an unknown task 'nope'",
            "side_effects.clear_hold: names an unknown task 'nope'",
        )

    def test_build_services_need_a_commit_label(self) -> None:
        src = edit(lite(), LABELS, 'expect_labels = { "org.opencontainers.image.revision" = "{release}" }\n')
        self.assertEqual(self.refused(src), ["compose.expect_labels: must bind {commit}: build_services are pulled"])

    def test_probe_and_install_step_kinds(self) -> None:
        src = edit(lite(), 'exec = "app"\n', 'exec = "app"\nhealth = "app"\n', after="[probes.ready]")
        src = edit(src, 'task = "migrate"', 'task = "migrate"\npause = "x"', after="[[install]]")
        self.assertRefused(
            src,
            "probes.ready: needs exactly one of health, exec, http",
            "install[0]: needs exactly one of start, task, pause",
        )

    def test_more_rules(self) -> None:
        site = example("site.toml")
        cases: list[tuple[str, str, str, str, str]] = [
            # (base, after, old, new, expected error line)
            (lite(), "[app_env.keys]", "\n", "\nPORT = {}\n", "app_env.keys.PORT: is a forbidden key"),
            (
                lite(),
                "",
                'default = "capture"',
                'default = "mail"',
                "app_env.keys.DELIVERY_MODE.default: is not an allowed value",
            ),
            (
                lite(),
                "[stores.data]",
                '"FXLITE_DATA_DIR"',
                '"FXLITE_PORT"',
                "stores.data.param: must name a store param with store = 'data'",
            ),
            (
                lite(),
                "[schema]",
                "\n",
                '\ntask = "revision"\n',
                "schema: needs exactly one of task or probe (an exec or http probe)",
            ),
            (
                lite(),
                "[[install]]\nstart",
                "]\n",
                ']\nparams = { FXLITE_PORT = "1" }\n',
                "install[1].params.FXLITE_PORT: must set a string param to a value matching its pattern",
            ),
            (
                lite(),
                "[tasks.backup]",
                '"stage"',
                '"elsewhere"',
                "tasks.backup.mounts: /out = 'elsewhere' is not a valid mount",
            ),
            (
                lite(),
                "[tasks.backup]",
                "\n",
                '\nstdin = "file:../x"\n',
                "tasks.backup: 'file:../x' must name a relative path without '..'",
            ),
            (
                lite(),
                "[tasks.backup]",
                "\n",
                "\nnonempty = true\n",
                'tasks.backup: nonempty needs stdout = "file:<path>"',
            ),
            (
                site + TASK,
                "",
                "[tasks.extra]\n",
                '[tasks.extra]\nobserve = "schema"\n',
                'tasks.extra: observe = "schema" needs [schema]',
            ),
            (
                site + TASK,
                "",
                'mode = "run"',
                'mode = "exec"\nmounts = { "/x" = "stage" }',
                'tasks.extra: mounts need mode = "run"',
            ),
            (
                lite(),
                "[backup]",
                'steps = ["backup"]',
                "steps = []",
                'backup.steps: are required with strategy = "tasks"',
            ),
            (
                lite(),
                "[restore]",
                "start = []",
                'start = ["app"]',
                "restore.start: names an unknown data service 'app'",
            ),
            (lite(), "[rollback]", 'JOBS = "off"', 'NOPE = "1"', "rollback.env: names an unknown app_env key 'NOPE'"),
            (lite(), "[services]", "\n", '\nstateless = ["app"]\n', "services: 'app' has more than one role"),
            (lite(), "[services]", "writers", "stateless", "services.writers: is required when stores exist"),
            (
                lite(),
                "[probes.edge-live]",
                '"FXLITE_PORT"',
                '"FXLITE_ENV_FILE"',
                "probes.edge-live.http.port_param: is not a port param",
            ),
            (
                lite(),
                "[deploy]",
                "prechecks = []",
                'prechecks = ["queue-resume"]',
                "deploy.prechecks: task 'queue-resume' must have effect read",
            ),
            (site, "", "images = { site", "images = { web", "source.images.web: must name its image param"),
            (site, "", 'kind = "image"', 'kind = "image"\nrelease = "tag"', "source.release: unknown key"),
            (
                site,
                "",
                '["compose.yaml"]',
                '["compose.yaml"]\nbuild_services = ["site"]',
                "compose.build_services: unknown key",
            ),
            (
                site,
                "",
                '["compose.yaml"]',
                '["/srv/compose.yaml"]',
                "compose: files must be relative paths without '..'",
            ),
            (site, "", '["compose.yaml"]', '["../compose.yaml"]', "compose: files must be relative paths without '..'"),
            # Probes run in a running container: their service has a role.
            (
                lite(),
                "[probes.ready]",
                'exec = "app"',
                'exec = "tools"',
                "probes.ready: names an unknown service with a role 'tools'",
            ),
            (
                lite(),
                "",
                "[probes.edge-live]",
                '[probes.x]\nhealth = ""\n[probes.edge-live]',
                "probes.x: names an unknown service with a role ''",
            ),
            (lite(), "[probes.ready]", "argv = [", "xargv = [", "probes.ready.argv: is required"),
            (
                lite(),
                "[probes.ready]",
                "expect = { json",
                "expect = { status = 200, json",
                "probes.ready.expect: has a key a exec probe cannot use",
            ),
            (
                lite(),
                "[probes.ready]",
                'stable = "5s"',
                'interval = "0s"',
                "probes.ready: interval and timeout must be positive",
            ),
            (
                lite(),
                "[probes.edge-live]",
                'path = "/api',
                'path = "api',
                "probes.edge-live.http.path: 'api/health' does not match /\\S*",
            ),
            (
                lite(),
                "[probes.edge-live]",
                'path = "/api/health"',
                'path = "/api/health", headers = { "X Y" = "1" }',
                'probes.edge-live.http.headers."X Y": the key does not match [A-Za-z0-9][A-Za-z0-9_.-]*',
            ),
            (
                lite(),
                "",
                "[[smoke]]",
                '[[smoke]]\nname = "live"\nhttp = { port_param = "FXLITE_PORT", path = "/" }\n[[smoke]]',
                "smoke: the name 'live' is used twice",
            ),
            # A store's readiness probe also runs in isolated projects, where http probes do not run.
            (
                lite(),
                "[stores.data]",
                "local_only",
                'ready = "edge-live"\nlocal_only',
                "stores.data.ready: must be an exec or health probe (isolated runs)",
            ),
            (
                example("fx-pg.toml"),
                "[stores.pgdata]",
                'ready = "db-ready"\n',
                "",
                "stores.pgdata.ready: is required with service",
            ),
            (lite(), "[services]", "\n", '\nstateless = ["web"]\n', "activate: no group starts the service 'web'"),
            (
                lite(),
                "[services]",
                'log_snapshot = ["app"]',
                'log_snapshot = ["app", "web"]',
                "services.log_snapshot: names an unknown service with a role 'web'",
            ),
            (lite(), "[backup]", 'strategy = "tasks"', 'strategy = "none"', 'backup: strategy "none" takes no tasks'),
            (
                lite(),
                "[backup]",
                'steps = ["backup"]',
                'steps = ["backup", ""]',
                "backup.steps: names an unknown task ''",
            ),
            (
                lite(),
                "[schema]",
                'probe = "ready"',
                'task = "queue-resume"',
                "schema.task: task 'queue-resume' must have effect read",
            ),
            (
                lite() + TASK,
                "[schema]",
                'probe = "ready"',
                'task = "extra"',
                "schema.task: task 'extra' must print JSON",
            ),
            (
                lite(),
                "[[install]]",
                'task = "migrate"',
                'task = "bootstrap-new-code"',
                "install: task 'bootstrap-new-code' uses the terminal, so it runs only in the foreground CLI",
            ),
            (lite(), "[[install]]", 'task = "migrate"', 'task = "migrate"\nwait = []', "install[0].wait: unknown key"),
            # An exec task runs in a running container; a run task may use a task-only service (below).
            (
                lite() + TASK,
                "[tasks.extra]",
                'service = "app"\nmode = "run"',
                'service = "tools"\nmode = "exec"',
                "tasks.extra: names an unknown service with a role 'tools'",
            ),
            (lite(), "[tasks.migrate]", 'timeout = "15m"', 'timeout = "0s"', "tasks.migrate.timeout: must be positive"),
            (
                lite(),
                "[tasks.bootstrap-config]",
                "max_input_bytes = 262144",
                'max_input_bytes = "256k"',
                "tasks.bootstrap-config.max_input_bytes: must be an integer",
            ),
            # Mount targets become `-v <source>:<target>`: a ':' or '..' in a target is refused.
            (
                lite(),
                "[tasks.backup]",
                '"/out" = "stage"',
                '"/out:shared" = "stage"',
                "tasks.backup.mounts: /out:shared = 'stage' is not a valid mount",
            ),
            (
                lite(),
                "[tasks.backup]",
                '"/out" = "stage"',
                '"/in/../out" = "stage"',
                "tasks.backup.mounts: /in/../out = 'stage' is not a valid mount",
            ),
        ]
        for base, after, old, new, line in cases:
            with self.subTest(line=line):
                self.assertIn(line, self.refused(edit(base, old, new, after)))
        parse(lite() + TASK.replace('service = "app"', 'service = "tools"'))

    def test_every_regex_compiles(self) -> None:
        # re.compile raises re.error, OverflowError (a huge repeat count), RecursionError (deep nesting) or ValueError
        # (clashing inline flags).
        paths = ("params.FXLITE_TZ.pattern", "app_env.keys.SESSION_HOURS.pattern", "tasks.queue-release-job.args.job")
        for bad in ("(", "a{4294967296}", "(" * 2000 + ")" * 2000, "(?a)(?u)x"):
            with self.subTest(bad=bad[:16]):
                src = edit(lite(), "[params]\n", f"[params]\nFXLITE_TZ = {{ pattern = '{bad}' }}\n")
                src = edit(src, "pattern = '^[0-9]{1,4}$'", f"pattern = '{bad}'", after="SESSION_HOURS")
                src = edit(src, "job = '^[A-Za-z0-9-]{1,64}$'", f"job = '{bad}'")
                errors = self.refused(src)
                self.assertEqual([e.split(": invalid regex: ")[0] for e in errors], list(paths))
                errors = self.refused(edit(example("fx-pg.toml"), "tag_pattern = '^v", f"tag_pattern = '{bad}^v"))
                self.assertTrue(any(e.startswith("source.tag_pattern: invalid regex: ") for e in errors), errors)

    def test_compose_settings_are_not_param_names(self) -> None:
        # Compose reads its own COMPOSE_* and DOCKER_* settings from the --env-file (ARCHITECTURE §9.5).
        params = '[params]\nCOMPOSE_PROFILES = { default = "x" }\nDOCKER_HOST = {}\nMY_DOCKER_HOST = {}\n'
        src = edit(lite(), "[params]\n", params)
        src = edit(
            src, "]\n", ']\nparams = { COMPOSE_PROFILES = "y", MY_DOCKER_HOST = "z" }\n', after="[[install]]\nstart"
        )
        msg = "COMPOSE_* and DOCKER_* names are Compose's own settings"
        self.assertEqual(
            self.refused(src),
            [
                f"params.COMPOSE_PROFILES: {msg}",
                f"params.DOCKER_HOST: {msg}",
                f"install[1].params.COMPOSE_PROFILES: {msg}",
            ],
        )

    def test_required_takes_no_default(self) -> None:
        # required = true means the instance must set the value; a default or optional = true would make it optional,
        # and the instance may never set a tool_managed key.
        params = '[params]\nA = { required = true, default = "x" }\nB = { required = true, optional = true }\nC = {}\n'
        src = edit(lite(), "[params]\n", params)
        src = edit(src, "{ required = true }", '{ required = true, default = "x" }', after="BASE_URL")
        src = edit(src, "tool_managed = true", "tool_managed = true, required = true", after="JOBS")
        key = "required = true takes no default or tool_managed = true (the instance must set it)"
        self.assertEqual(
            self.refused(src),
            [
                "params.A: required = true takes no default or optional = true (the instance must set it)",
                "params.B: required = true takes no default or optional = true (the instance must set it)",
                f"app_env.keys.BASE_URL: {key}",
                f"app_env.keys.JOBS: {key}",
            ],
        )
        src = edit(
            lite(), "[params]\n", '[params]\nA = { required = true }\nB = { default = "x" }\nC = { optional = true }\n'
        )
        self.assertEqual(sorted(k for k, p in parse(src).params.items() if p.kind == "string"), ["A", "B", "C"])

    def test_not_toml_or_not_utf8(self) -> None:
        deep = b"x = " + b"[" * 2000 + b"]" * 2000  # the TOML parser recurses
        # tomllib builds dotted keys without recursion, but the reader of expect.json paths walks them.
        parts = b".".join([b"a"] * 990)
        deep_keys = b"[probes.x.expect.json." + parts + b"]\n" + parts + b" = 1\n"
        for raw in (b"manifest = ", b"\xff\xfe", b"[a]\n[a]\n", deep, deep_keys):
            with self.subTest(raw=raw[:12]), self.assertRaises(Refused) as cm:
                parse_manifest(raw, tool_version=VERSION)
            self.assertEqual(cm.exception.code, "invalid-manifest")
            self.assertNotIn("\n", cm.exception.message)  # refused by the parse, before any key is read


if __name__ == "__main__":
    unittest.main()
