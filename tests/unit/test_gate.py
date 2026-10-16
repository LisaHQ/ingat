import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ingat import brand
from ingat.model.errors import CannotRun
from ingat.policy import gate

TESTED = [
    {"engine": "24.0", "arch": "amd64", "cli": "29.1.0", "compose": "2.40.0"},
    {"engine": "29.1", "arch": "amd64", "cli": "29.1.0", "compose": "2.40.0"},
    {"engine": "29.1", "arch": "arm64", "cli": "29.1.0", "compose": "2.40.0"},
]
HOST = {
    "versions": {
        "engine": "24.0.2",
        "api": "1.43",
        "cli": "29.1.0",
        "compose": "2.40.0",
        "containerd": "1.7.1",
        "runc": "1.1.7",
        "git_commit": "abc1234",
        "build_time": "2023-06-01T00:00:00Z",
    },
    "facts": {
        "storage_driver": "overlay2",
        "logging_driver": "json-file",
        "cgroup_version": "2",
        "kernel": "6.1.0-test",
        "architecture": "x86_64",
        "os": "linux",
        "os_release": {"ID": "debian", "VERSION_ID": "12"},
    },
}
BUILD = gate.platform_build(HOST)


def cert(build: Any = None, **fields: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"kind": "selftest", "result": "PASS", "build": dict(BUILD) if build is None else build}
    doc.update(fields)
    return doc


def run(tier: int, *, certs: list[dict[str, Any]] | None = None, **kw: Any) -> list[str]:
    args: dict[str, Any] = {
        "engine_version": "24.0.2",
        "api_version": "1.43",
        "arch": "x86_64",
        "build": BUILD,
        "certifications": [] if certs is None else certs,
        "tested": TESTED,
    }
    args.update(kw)
    return gate.check(tier, **args)


class PlatformBuild(unittest.TestCase):
    def test_takes_exactly_the_build_keys_from_versions_and_facts(self) -> None:
        self.assertEqual(
            BUILD,
            {
                "os_release": {"ID": "debian", "VERSION_ID": "12"},
                "engine": "24.0.2",
                "git_commit": "abc1234",
                "build_time": "2023-06-01T00:00:00Z",
                "containerd": "1.7.1",
                "runc": "1.1.7",
                "kernel": "6.1.0-test",
                "storage_driver": "overlay2",
                "architecture": "x86_64",
            },
        )

    def test_missing_facts_are_none(self) -> None:
        build = gate.platform_build({"versions": {"engine": "24.0.2"}})
        self.assertEqual(build["engine"], "24.0.2")
        self.assertIsNone(build["kernel"])


class Tier0(unittest.TestCase):
    def test_any_reachable_daemon(self) -> None:
        self.assertEqual(run(gate.TIER0, engine_version="20.10.23", api_version="1.41", tested=[]), [])


class Tier1(unittest.TestCase):
    def test_tested_engine_has_no_warning(self) -> None:
        self.assertEqual(run(gate.TIER1), [])

    def test_untested_engine_with_api_floor_warns(self) -> None:
        warnings = run(gate.TIER1, engine_version="25.0.5", api_version="1.44")
        self.assertEqual(len(warnings), 1)
        self.assertIn("25.0.5", warnings[0])

    def test_untested_architecture_warns(self) -> None:
        warnings = run(gate.TIER1, arch="aarch64")
        self.assertEqual(len(warnings), 1)
        self.assertIn("arm64", warnings[0])

    def test_uncertified_build_still_runs(self) -> None:
        self.assertEqual(run(gate.TIER1, certs=[], build={k: None for k in gate.BUILD_KEYS}), [])

    def test_api_below_floor_cannot_run(self) -> None:
        for api in ("1.41", "1.9", "0.99", "garbage", ""):
            with self.subTest(api=api), self.assertRaises(CannotRun) as ctx:
                run(gate.TIER1, engine_version="20.10.23", api_version=api)
            self.assertEqual(ctx.exception.code, "untested-platform")
            self.assertEqual(ctx.exception.exit_code, 2)

    def test_api_comparison_is_numeric(self) -> None:
        self.assertEqual(run(gate.TIER1, engine_version="29.1.3", api_version="1.100"), [])

    def test_unparseable_engine_version_warns(self) -> None:
        self.assertEqual(len(run(gate.TIER1, engine_version="dev")), 1)


class Tier2(unittest.TestCase):
    def assert_cannot(self, code: str, **kw: Any) -> CannotRun:
        with self.assertRaises(CannotRun) as ctx:
            run(gate.TIER2, **kw)
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(ctx.exception.exit_code, 2)
        return ctx.exception

    def test_tested_and_certified_runs(self) -> None:
        self.assertEqual(run(gate.TIER2, certs=[cert()]), [])

    def test_untested_engine_line_refused(self) -> None:
        self.assert_cannot("untested-platform", engine_version="25.0.5", api_version="1.44", certs=[cert()])

    def test_untested_architecture_refused(self) -> None:
        self.assert_cannot("untested-platform", arch="aarch64", certs=[cert()])

    def test_api_below_floor_refused(self) -> None:
        self.assert_cannot("untested-platform", engine_version="20.10.23", api_version="1.41")

    def test_engine_patch_level_does_not_matter_for_tested(self) -> None:
        for version in ("24.0.0", "24.0.9", "24.0.2-1", "24.0.7+dfsg1"):
            with self.subTest(version=version):
                build = dict(BUILD, engine=version)
                self.assertEqual(run(gate.TIER2, engine_version=version, build=build, certs=[cert(build)]), [])

    def test_engine_minor_must_match(self) -> None:
        self.assert_cannot("untested-platform", engine_version="24.1.0", certs=[cert()])
        self.assert_cannot("untested-platform", engine_version="29.10.0", certs=[cert()])

    def test_architecture_names_are_normalised(self) -> None:
        tested = [{"engine": "29.1", "arch": "aarch64"}]
        build = dict(BUILD, engine="29.1.3", architecture="aarch64")
        self.assertEqual(
            run(gate.TIER2, engine_version="29.1.3", arch="arm64", build=build, certs=[cert(build)], tested=tested), []
        )
        self.assertEqual(run(gate.TIER2, arch="amd64", certs=[cert(dict(BUILD, architecture="amd64"))]), [])

    def test_no_certification_refused_with_selftest_next(self) -> None:
        error = self.assert_cannot("uncertified", certs=[])
        self.assertEqual(error.next, f"{brand.CLI} selftest --host")

    def test_failed_or_blocked_certification_does_not_count(self) -> None:
        for result in ("FAIL", "BLOCKED", "pass", None):
            with self.subTest(result=result):
                self.assert_cannot("uncertified", certs=[cert(result=result)])

    def test_host_check_record_does_not_certify(self) -> None:
        self.assert_cannot("uncertified", certs=[cert(kind="host-check")])

    def test_any_build_difference_refused(self) -> None:
        changes: dict[str, Any] = {
            "os_release": {"ID": "debian", "VERSION_ID": "13"},
            "engine": "24.0.7",
            "git_commit": "def5678",
            "build_time": "2023-07-01T00:00:00Z",
            "containerd": "1.7.2",
            "runc": "1.1.12",
            "kernel": "6.1.0-next",
            "storage_driver": "btrfs",
            "architecture": "aarch64",
        }
        self.assertEqual(set(changes), set(gate.BUILD_KEYS))
        for key, value in changes.items():
            with self.subTest(key=key):
                self.assert_cannot("uncertified", certs=[cert(dict(BUILD, **{key: value}))])

    def test_certification_missing_a_build_key_does_not_count(self) -> None:
        build = dict(BUILD)
        del build["kernel"]
        self.assert_cannot("uncertified", certs=[cert(build)])

    def test_certification_without_build_does_not_count(self) -> None:
        self.assert_cannot("uncertified", certs=[{"kind": "selftest", "result": "PASS"}, cert(build="x")])

    def test_extra_certification_fields_are_ignored(self) -> None:
        self.assertEqual(run(gate.TIER2, certs=[cert(dict(BUILD, package_build="x"), facts={"a": 1})]), [])

    def test_missing_host_facts_refused_even_with_matching_certification(self) -> None:
        build = dict(BUILD, kernel=None)
        error = self.assert_cannot("uncertified", build=build, certs=[cert(build)])
        self.assertIn("kernel", error.message)

    def test_empty_host_facts_refused_even_with_matching_certification(self) -> None:
        for key, empty in (("os_release", {}), ("git_commit", ""), ("build_time", "")):
            with self.subTest(key=key):
                build = dict(BUILD, **{key: empty})
                error = self.assert_cannot("uncertified", build=build, certs=[cert(build)])
                self.assertIn(key, error.message)

    def test_unparseable_engine_version_refused(self) -> None:
        build = dict(BUILD, engine="dev")
        self.assert_cannot("untested-platform", engine_version="dev", build=build, certs=[cert(build)])

    def test_one_matching_certification_among_others_is_enough(self) -> None:
        certs = [cert(result="FAIL"), cert(dict(BUILD, kernel="old")), cert()]
        self.assertEqual(run(gate.TIER2, certs=certs), [])


class ReleaseData(unittest.TestCase):
    def test_release_tested_json_is_a_list(self) -> None:
        self.assertIsInstance(gate.load_tested(), list)

    def test_release_committed_certifications_load(self) -> None:
        self.assertIsInstance(gate.committed_certifications(), list)


class PackageData(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(gate, "files", lambda anchor: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_tested_reads_package_data(self) -> None:
        (self.root / "tested.json").write_text(json.dumps(TESTED))
        self.assertEqual(gate.load_tested(), TESTED)

    def test_load_tested_refuses_a_non_list(self) -> None:
        for text in ('{"engine": "24.0"}', '["24.0"]'):
            with self.subTest(text=text):
                (self.root / "tested.json").write_text(text)
                with self.assertRaises(CannotRun):
                    gate.load_tested()

    def test_no_committed_certifications(self) -> None:
        self.assertEqual(gate.committed_certifications(), [])

    def test_committed_certification_counts(self) -> None:
        hosts = self.root / "support" / "hosts"
        hosts.mkdir(parents=True)
        (hosts / "readme.txt").write_text("not a certification")
        (hosts / "platform-build-x86_64.json").write_text(json.dumps(cert()))
        self.assertEqual(len(gate.committed_certifications()), 1)
        self.assertEqual(run(gate.TIER2, certs=[]), [])

    def test_committed_certification_of_another_build_does_not_count(self) -> None:
        hosts = self.root / "support" / "hosts"
        hosts.mkdir(parents=True)
        (hosts / "other.json").write_text(json.dumps(cert(dict(BUILD, kernel="other"))))
        with self.assertRaises(CannotRun) as ctx:
            run(gate.TIER2, certs=[])
        self.assertEqual(ctx.exception.code, "uncertified")

    def test_committed_certification_that_is_not_an_object_cannot_run(self) -> None:
        hosts = self.root / "support" / "hosts"
        hosts.mkdir(parents=True)
        (hosts / "good.json").write_text(json.dumps(cert()))
        (hosts / "bad.json").write_text(json.dumps([cert()]))
        with self.assertRaises(CannotRun) as ctx:
            run(gate.TIER2, certs=[])
        self.assertEqual(ctx.exception.code, "uncertified")


if __name__ == "__main__":
    unittest.main()
