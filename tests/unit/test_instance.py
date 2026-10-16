import hashlib
import os
import re
import unittest
from types import SimpleNamespace
from typing import Any

from ingat import __version__, brand
from ingat.model.errors import Refused
from ingat.model.instance import NAME_RE, Backups, parse_instance, validate_against
from ingat.model.manifest import AppEnv, AppEnvKey, Param, parse_manifest

DATA = os.path.join(os.path.dirname(__file__), "data")

GIT = """
instance = 1
name = "lite-test"
app = "fx-lite"
environment = "test"

[source]
repo = "ssh://git@example.com/owner/app.git"
"""

FULL = """
instance = 1
name = "lite-test"
app = "fx-lite"
environment = "test"
disposable = true

[source]
kind = "git"
repo = "https://example.com/owner/app.git"
key = "fx-lite"
manifest = "deploy/app.toml"
accept = '^v[0-9]+$'

[params]
FX_PORT = "20090"
FX_TZ = "Etc/UTC"

[app_env]
BASE_URL = "https://lite-test.example"
MODE = "capture"

[backups]
keep_daily = 7
keep_weekly = 4
keep_monthly = 6
pin_pre_change_days = 30
max_age_hours = 26
restore_test_max_age_days = 8

[monitor]
public_url = "https://lite-test.example/"
cert_warn_days = 21
"""


def parse(text: str) -> Any:
    return parse_instance(text.encode())


def errors_of(text: str) -> str:
    try:
        parse_instance(text.encode())
    except Refused as e:
        if e.code != "invalid-instance":
            raise
        return e.message
    raise AssertionError("expected Refused")


class ParseTest(unittest.TestCase):
    def test_minimal_git_instance_defaults(self) -> None:
        inst = parse(GIT)
        self.assertEqual((inst.instance, inst.name, inst.app, inst.environment), (1, "lite-test", "fx-lite", "test"))
        self.assertFalse(inst.disposable)
        self.assertEqual(inst.source_kind, "git")
        self.assertEqual(inst.repo, "ssh://git@example.com/owner/app.git")
        self.assertIsNone(inst.key)
        self.assertIsNone(inst.accept)
        self.assertEqual(inst.manifest_path, brand.MANIFEST_FILE)
        self.assertEqual(inst.params, {})
        self.assertEqual(inst.app_env, {})
        self.assertEqual(inst.backups, Backups())
        self.assertEqual(
            (inst.backups.keep_daily, inst.backups.keep_weekly, inst.backups.keep_monthly),
            (7, 4, 0),
        )
        self.assertEqual(
            (inst.backups.pin_pre_change_days, inst.backups.max_age_hours, inst.backups.restore_test_max_age_days),
            (14, 26, 8),
        )
        self.assertEqual(inst.monitor, {})
        self.assertEqual(inst.raw_sha256, hashlib.sha256(GIT.encode()).hexdigest())

    def test_full_instance(self) -> None:
        inst = parse(FULL)
        self.assertTrue(inst.disposable)
        self.assertEqual(inst.key, "fx-lite")
        self.assertEqual(inst.manifest_path, "deploy/app.toml")
        self.assertEqual(inst.accept, "^v[0-9]+$")
        self.assertEqual(inst.params, {"FX_PORT": "20090", "FX_TZ": "Etc/UTC"})
        self.assertEqual(inst.app_env["MODE"], "capture")
        self.assertEqual(inst.backups.keep_monthly, 6)
        self.assertEqual(inst.backups.pin_pre_change_days, 30)
        self.assertEqual(inst.monitor, {"public_url": "https://lite-test.example/", "cert_warn_days": 21})

    def test_image_instance(self) -> None:
        inst = parse(
            'instance = 1\nname = "site"\napp = "site"\nenvironment = "production"\n[source]\nkind = "image"\n'
        )
        self.assertEqual(inst.source_kind, "image")
        self.assertIsNone(inst.repo)
        for extra in ('repo = "https://example.com/a.git"', 'key = "k"', 'accept = "x"', 'manifest = "a.toml"'):
            text = f'instance = 1\nname = "site"\napp = "site"\nenvironment = "p"\n[source]\nkind = "image"\n{extra}\n'
            self.assertIn("not used by an image source", errors_of(text))

    def test_source_kind_values(self) -> None:
        self.assertIn("source.kind", errors_of(GIT + 'kind = "tar"\n'))
        self.assertIn(
            "source.repo: required", errors_of(GIT.replace('repo = "ssh://git@example.com/owner/app.git"', ""))
        )

    def test_name_rule(self) -> None:
        for ok in ("lite-test", "a", "a1-b2-c3", "x" * 30, "pg-prod"):
            self.assertEqual(parse(GIT.replace('"lite-test"', f'"{ok}"')).name, ok)
            self.assertIsNotNone(NAME_RE.fullmatch(ok))
        for bad in ("Lite", "1abc", "a--b", "a-", "-a", "a_b", "a.b", "x" * 31, "", "a\\n", "a b", "../x"):
            with self.subTest(bad=bad):
                self.assertIn("name: must match", errors_of(GIT.replace('"lite-test"', f'"{bad}"')))

    def test_name_regex_alone_carries_every_rule(self) -> None:
        # Callers check command-line names with NAME_RE alone: length and anchoring hold for any re function.
        for bad in ("x" * 31, "abc\n", "a--b", "../abc", "abc/../x"):
            with self.subTest(bad=bad):
                self.assertIsNone(NAME_RE.fullmatch(bad))
                self.assertIsNone(re.match(NAME_RE, bad))
                self.assertIsNone(NAME_RE.search(bad))

    def test_app_and_environment_rules(self) -> None:
        self.assertIn("app: must match", errors_of(GIT.replace('"fx-lite"', '"Fx"')))
        self.assertIn("app: must match", errors_of(GIT.replace('"fx-lite"', '"f"')))
        self.assertIn("environment: must match", errors_of(GIT.replace('"test"', '"Test"')))
        self.assertIn("environment: must match", errors_of(GIT.replace('"test"', '"e' + "x" * 32 + '"')))
        self.assertEqual(parse(GIT.replace('"test"', '"e' + "x" * 31 + '"')).environment, "e" + "x" * 31)

    def test_required_keys(self) -> None:
        message = errors_of('[source]\nrepo = "https://example.com/a.git"\n')
        for key in ("instance: must be 1", "name: required", "app: required", "environment: required"):
            self.assertIn(key, message)

    def test_schema_version(self) -> None:
        for bad in ("2", "true", '"1"', "1.0"):
            with self.subTest(bad=bad):
                self.assertIn("instance: must be 1", errors_of(GIT.replace("instance = 1", f"instance = {bad}")))

    def test_unknown_keys_are_refused_with_their_path(self) -> None:
        self.assertIn("extra: unknown key", errors_of(GIT.replace("instance = 1", "instance = 1\nextra = 1")))
        self.assertIn("source.branch: unknown key", errors_of(GIT + 'branch = "main"\n'))
        self.assertIn("backups.keep_hourly: unknown key", errors_of(GIT + "[backups]\nkeep_hourly = 1\n"))
        self.assertIn("monitor.url: unknown key", errors_of(GIT + '[monitor]\nurl = "x"\n'))

    def test_types(self) -> None:
        self.assertIn("params.FX_PORT: expected a string", errors_of(GIT + "[params]\nFX_PORT = 20090\n"))
        self.assertIn("app_env.A: expected a string", errors_of(GIT + "[app_env]\nA = true\n"))
        self.assertIn(
            "disposable: expected a boolean", errors_of(GIT.replace("instance = 1", 'instance = 1\ndisposable = "no"'))
        )
        self.assertIn("backups.keep_daily: expected an integer", errors_of(GIT + "[backups]\nkeep_daily = true\n"))
        self.assertIn("backups.keep_daily: must not be negative", errors_of(GIT + "[backups]\nkeep_daily = -1\n"))
        self.assertIn(
            "monitor.cert_warn_days: expected an integer", errors_of(GIT + '[monitor]\ncert_warn_days = "21"\n')
        )
        self.assertIn("params: expected a table", errors_of(GIT.replace("instance = 1", 'instance = 1\nparams = "x"')))

    def test_every_error_is_reported_one_per_line(self) -> None:
        message = errors_of(GIT.replace('"lite-test"', '"a--b"') + "[backups]\nkeep_daily = -1\n")
        self.assertEqual(len(message.splitlines()), 2)

    def test_repo_urls(self) -> None:
        good = (
            "ssh://git@example.com/owner/app.git",
            "ssh://git@example.com:2222/owner/app.git",
            "https://example.com/owner/app.git",
            "file:///srv/x/cache/fixtures/fx-lite.git",
        )
        for url in good:
            self.assertEqual(parse(GIT.replace("ssh://git@example.com/owner/app.git", url)).repo, url)
        bad = (
            "http://example.com/owner/app.git",
            "git@example.com:owner/app.git",
            "ftp://example.com/a.git",
            "file://example.com/srv/a.git",
            "file:relative/a.git",
            "file:/srv/a.git",
            "https://user:hunter2secret@example.com/a.git",
            "https://tok3nsecret@example.com/a.git",
            "ssh://git:hunter2secret@example.com/a.git",
            "https://example.com/a.git?x=1",
            "https://example.com/a.git#frag",
            "https://example.com/a b.git",
            "https://example.com/a\\n.git",
            "https://example.com",
            "https://example.com/",
            "ssh://example.com:99999/a.git",
            "ssh://-oProxyCommand=evil/a.git",
            "ssh://-oProxyCommand=evil@example.com/a.git",
            "ssh://git@-oProxyCommand=evil/a.git",
            "file:///srv/x/cache/fixtures/../../../etc/a.git",
            "file:///srv/x/cache/fixtures/%2e%2e/a.git",
            "file:///srv/x//a.git",
            "file:///srv/x/a.git/",
            "/srv/a.git",
            "",
        )
        for url in bad:
            with self.subTest(url=url):
                message = errors_of(GIT.replace("ssh://git@example.com/owner/app.git", url))
                self.assertIn("source.repo: must be", message)
                self.assertNotIn("secret", message)
                self.assertNotIn("example.com/a", message)

    def test_key_manifest_and_accept(self) -> None:
        self.assertIn("source.key: must match", errors_of(GIT + 'key = "../other"\n'))
        self.assertIn("source.key: must match", errors_of(GIT + 'key = "a/b"\n'))
        for bad in ("../app.toml", "/abs/app.toml", "a//b.toml", "./app.toml", "", "dir/"):
            with self.subTest(bad=bad):
                self.assertIn("source.manifest: must be", errors_of(GIT + f'manifest = "{bad}"\n'))
        # re.compile raises re.error, OverflowError (a huge repeat count), RecursionError (deep nesting) or ValueError
        # (clashing inline flags).
        for bad in ("^v([", "a{4294967296}", "(" * 2000 + ")" * 2000, "(?a)(?u)x"):
            with self.subTest(bad=bad[:16]):
                self.assertIn("source.accept: invalid regular expression", errors_of(GIT + f"accept = '{bad}'\n"))

    def test_values_that_cannot_be_rendered_single_quoted(self) -> None:
        for value in ("it's", "a\\nb", "a\\rb", "a\\u0000b"):
            for table in ("params", "app_env"):
                with self.subTest(value=value, table=table):
                    message = errors_of(GIT + f'[{table}]\nK = "{value}hunter2"\n')
                    self.assertEqual(message, f"{table}.K: must not contain ', a line break or NUL")

    def test_invalid_toml_and_encoding(self) -> None:
        deep = b"x = " + b"[" * 2000 + b"]" * 2000  # the TOML parser recurses
        for data in (b"instance = \n", b"\xff\xfe", b'name = "a"\nname = "b"\n', b'repo = "hunter2"\nx = \n', deep):
            with self.subTest(data=data[:16]), self.assertRaises(Refused) as cm:
                parse_instance(data)
            self.assertEqual(cm.exception.code, "invalid-instance")
            self.assertNotIn("hunter2", cm.exception.message)

    def test_documented_examples_parse(self) -> None:
        # MANIFEST_SPEC §9, §10, §12 and §13 are acceptance inputs.
        for name in ("pg-staging", "pg-prod", "lite-test", "site"):
            with open(os.path.join(DATA, f"{name}.instance.toml"), "rb") as f:
                self.assertEqual(parse_instance(f.read()).name, name)


def manifest(**over: Any) -> Any:
    """The parts of a Manifest that validate_against reads, built from the real Param, AppEnvKey and AppEnv."""

    def param(kind: str = "string", **kw: Any) -> Param:
        base = {"required": False, "default": None, "optional": False, "pattern": None}
        return Param(name="", kind=kind, **(base | {"value": None, "store": None, "service": None} | kw))

    def key(**kw: Any) -> AppEnvKey:
        base = {"required": False, "default": None, "allowed": None, "pattern": None}
        flags = {"secret": False, "owner_gated": False, "tool_managed": False}
        return AppEnvKey(name="", **(base | flags | kw))

    m = SimpleNamespace(
        app="fx-lite",
        source_kind="git",
        params={
            "FX_PORT": param("port"),
            "FX_SUBNET": param("subnet"),
            "FX_TZ": param(required=True, pattern="^[A-Za-z]+(/[A-Za-z0-9_+-]+)+$"),
            "FX_WORKERS": param(default="2", pattern="^[1-8]$"),
            "FX_MEMORY": param(optional=True),
            "FX_IMAGE": param("template", value="img:{commit}"),
            "FX_DATA": param("store", store="data"),
            "FX_ENV": param("env_file"),
            "FX_SECRETS": param("secrets_dir"),
            "FX_IN": param("task_dir"),
            "FX_ACCEPT": param("accept_schema"),
            "FX_SITE": param("image", service="site"),
        },
        app_env=AppEnv(
            param="FX_ENV",
            forbidden=("DATA_DIR",),
            keys={
                "BASE_URL": key(required=True),
                "MODE": key(default="capture", allowed=("capture", "smtp"), owner_gated=True),
                "SESSION_HOURS": key(pattern="^[0-9]{1,4}$"),
                "MAIL_PASSWORD": key(secret=True, required=True),
                "JOBS": key(allowed=("off",), tool_managed=True),
            },
        ),
    )
    for name, value in over.items():
        setattr(m, name, value)
    return m


def instance(params: str = "", app_env: str = "") -> Any:
    return parse(
        GIT + '[params]\nFX_TZ = "Etc/UTC"\n' + params + '[app_env]\nBASE_URL = "https://lite-test.example"\n' + app_env
    )


class ValidateAgainstTest(unittest.TestCase):
    def test_valid(self) -> None:
        inst = instance('FX_PORT = "20090"\nFX_SUBNET = "10.200.2.0/24"\nFX_WORKERS = "4"\n', 'MODE = "smtp"\n')
        self.assertEqual(validate_against(inst, manifest()), [])

    def test_app_and_source_kind_must_match(self) -> None:
        errors = validate_against(instance(), manifest(app="other", source_kind="image"))
        self.assertEqual([e.split(":")[0] for e in errors], ["app", "source.kind"])

    def test_params(self) -> None:
        cases = {
            'FX_OTHER = "x"\n': "params.FX_OTHER: not declared",
            'FX_IMAGE = "x"\n': "params.FX_IMAGE: the tool sets template params",
            'FX_DATA = "/x"\n': "params.FX_DATA: the tool sets store params",
            'FX_ENV = "/x"\n': "params.FX_ENV: the tool sets env_file params",
            'FX_SECRETS = "/x"\n': "params.FX_SECRETS: the tool sets secrets_dir params",
            'FX_IN = "/x"\n': "params.FX_IN: the tool sets task_dir params",
            'FX_ACCEPT = "1"\n': "params.FX_ACCEPT: the tool sets accept_schema params",
            'FX_SITE = "img@sha256:x"\n': "params.FX_SITE: the tool sets image params",
            'FX_WORKERS = "9"\n': "params.FX_WORKERS: does not match",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                errors = validate_against(instance(text), manifest())
                self.assertEqual(len(errors), 1, errors)
                self.assertTrue(errors[0].startswith(expected), errors)

    def test_pattern_is_a_full_match(self) -> None:
        errors = validate_against(instance('FX_WORKERS = "12"\n'), manifest())
        self.assertEqual(len(errors), 1)

    def test_port_and_subnet_values(self) -> None:
        for ok in ("1", "20090", "65535"):
            self.assertEqual(validate_against(instance(f'FX_PORT = "{ok}"\n'), manifest()), [])
        for bad in ("0", "65536", "080", "abc", "", "20090 "):
            with self.subTest(bad=bad):
                errors = validate_against(instance(f'FX_PORT = "{bad}"\n'), manifest())
                self.assertEqual(errors, ["params.FX_PORT: not a valid port"])
        for ok in ("10.200.2.0/24", "10.250.0.0/20", "fd00::/64"):
            self.assertEqual(validate_against(instance(f'FX_SUBNET = "{ok}"\n'), manifest()), [])
        for bad in ("10.200.2.1/24", "10.200.2.0", "10.200.2.0/33", "x", "10.200.2.0/255.255.255.0", "fe80::%eth0/64"):
            with self.subTest(bad=bad):
                errors = validate_against(instance(f'FX_SUBNET = "{bad}"\n'), manifest())
                self.assertEqual(errors, ["params.FX_SUBNET: not a valid subnet"])

    def test_required_params(self) -> None:
        inst = parse(GIT + '[app_env]\nBASE_URL = "u"\n')
        self.assertEqual(validate_against(inst, manifest()), ["params.FX_TZ: required"])

    def test_app_env(self) -> None:
        cases = {
            'OTHER = "x"\n': "app_env.OTHER: not declared",
            'DATA_DIR = "/x"\n': "app_env.DATA_DIR: forbidden",
            'MAIL_PASSWORD = "hunter2secret"\n': "app_env.MAIL_PASSWORD: a secret key",
            'JOBS = "off"\n': "app_env.JOBS: tool-managed",
            'MODE = "loud"\n': "app_env.MODE: must be one of capture, smtp",
            'SESSION_HOURS = "12345"\n': "app_env.SESSION_HOURS: does not match",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                errors = validate_against(instance(app_env=text), manifest())
                self.assertEqual(len(errors), 1, errors)
                self.assertTrue(errors[0].startswith(expected), errors)
                self.assertNotIn("hunter2secret", errors[0])

    def test_required_app_env_keys_except_secrets(self) -> None:
        inst = parse(GIT + '[params]\nFX_TZ = "Etc/UTC"\n')
        self.assertEqual(validate_against(inst, manifest()), ["app_env.BASE_URL: required"])

    def test_manifest_without_app_env(self) -> None:
        errors = validate_against(instance(), manifest(app_env=None))
        self.assertEqual(errors, ["app_env.BASE_URL: not declared by the manifest"])

    def test_documented_examples_against_their_manifests(self) -> None:
        # MANIFEST_SPEC §8-§10 and §13 through the real manifest parser.
        for app, names in (("fx-pg", ("pg-staging", "pg-prod")), ("site", ("site",))):
            with open(os.path.join(DATA, f"{app}.toml"), "rb") as f:
                m = parse_manifest(f.read(), tool_version=__version__)
            for name in names:
                with open(os.path.join(DATA, f"{name}.instance.toml"), "rb") as f:
                    text = f.read()
                with self.subTest(name=name):
                    self.assertEqual(validate_against(parse_instance(text), m), [])
                    extra = text.replace(b"[params]\n", b'[params]\nUNDECLARED = "x"\n') + b'[app_env]\nK = "v"\n'
                    self.assertEqual(
                        validate_against(parse_instance(extra), m),
                        ["params.UNDECLARED: not declared by the manifest", "app_env.K: not declared by the manifest"],
                    )


if __name__ == "__main__":
    unittest.main()
