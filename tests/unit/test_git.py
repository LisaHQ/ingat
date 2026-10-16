import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from ingat.adapters import git
from ingat.model.errors import CannotRun, Refused

_ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main"]


class RepoIdTest(unittest.TestCase):
    def test_repo_id_is_stable_and_distinct(self) -> None:
        a = git.repo_id("ssh://git@example.invalid/app.git")
        self.assertEqual(a, git.repo_id("ssh://git@example.invalid/app.git"))
        self.assertRegex(a, r"^[0-9a-f]{16}$")
        self.assertNotEqual(a, git.repo_id("https://example.invalid/app.git"))


@unittest.skipUnless(shutil.which("git") and shutil.which("tar"), "git or tar is not installed")
class GitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.src = os.path.join(self.tmp, "src")
        self.bare = os.path.join(self.tmp, "cache", "git", "r.git")
        self.url = "file://" + self.src
        self.sh("init", "-q", self.src)
        self.put("compose.yaml", b"services: {}\n")
        self.put("data.bin", b"\xff\x00raw\r\n")
        self.put("app/deep/file.txt", b"deep\n")
        self.a = self.commit("first")
        self.sh("tag", "-a", "-m", "v1", "v1")
        self.put("second.txt", b"2\n")
        self.b = self.commit("second")
        self.sh("branch", "feature")
        git.fetch(self.bare, self.url, key_dir=None)

    def sh(self, *args: str) -> str:
        argv = ["git", *_ID, *args] if args[0] == "init" else ["git", "-C", self.src, *_ID, *args]
        return subprocess.run(argv, env=_ENV, check=True, capture_output=True, text=True).stdout.strip()

    def put(self, rel: str, data: bytes) -> None:
        path = os.path.join(self.src, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def commit(self, message: str) -> str:
        self.sh("add", "-A")
        self.sh("commit", "-q", "-m", message)
        return self.sh("rev-parse", "HEAD")

    def export(self, commit: str) -> str:
        dest = tempfile.mkdtemp(dir=self.tmp)
        git.archive(self.bare, commit, dest)
        return dest

    def test_resolve_tag_branch_and_full_sha(self) -> None:
        self.assertEqual(git.resolve(self.bare, "v1"), self.a)
        self.assertEqual(git.resolve(self.bare, "main"), self.b)
        self.assertEqual(git.resolve(self.bare, "feature"), self.b)
        self.assertEqual(git.resolve(self.bare, self.a), self.a)

    def test_resolve_refuses_abbreviations_expressions_and_unknown_refs(self) -> None:
        for ref in (self.a[:12], "main~1", "v1^{tree}", "-main", "main@{0}", "nope", "0" * 40, "", "v1..main"):
            with self.subTest(ref=ref), self.assertRaises(Refused) as cm:
                git.resolve(self.bare, ref)
            self.assertEqual(cm.exception.code, "invalid-ref")

    def test_resolve_refuses_a_tag_and_branch_naming_different_commits(self) -> None:
        self.sh("branch", "v1", self.b)
        git.fetch(self.bare, self.url, key_dir=None)
        with self.assertRaises(Refused):
            git.resolve(self.bare, "v1")

    def test_fetch_follows_moved_and_deleted_branches(self) -> None:
        self.sh("branch", "-D", "feature")
        self.sh("commit", "-q", "--amend", "-m", "second, amended")
        moved = self.sh("rev-parse", "HEAD")
        git.fetch(self.bare, self.url, key_dir=None)
        self.assertEqual(git.resolve(self.bare, "main"), moved)
        with self.assertRaises(Refused):
            git.resolve(self.bare, "feature")
        self.assertEqual(git.resolve(self.bare, self.b), self.b)

    def test_fetch_mirrors_moved_and_deleted_tags(self) -> None:
        self.sh("tag", "v0", self.a)
        git.fetch(self.bare, self.url, key_dir=None)
        self.sh("tag", "-d", "v0")
        self.sh("tag", "-f", "-a", "-m", "v1 moved", "v1", self.b)
        git.fetch(self.bare, self.url, key_dir=None)
        self.assertEqual(git.resolve(self.bare, "v1"), self.b)
        with self.assertRaises(Refused):
            git.resolve(self.bare, "v0")

    def test_tag_of(self) -> None:
        self.assertEqual(git.tag_of(self.bare, self.a), ["v1"])
        self.assertEqual(git.tag_of(self.bare, self.b), [])

    def test_show_is_byte_exact(self) -> None:
        self.assertEqual(git.show(self.bare, self.a, "data.bin"), b"\xff\x00raw\r\n")
        self.assertEqual(git.show(self.bare, self.a, "app/deep/file.txt"), b"deep\n")
        with self.assertRaises(Refused):
            git.show(self.bare, self.a, "second.txt")

    def test_archive_exports_the_tree_of_the_commit(self) -> None:
        dest = self.export(self.a)
        self.assertEqual(sorted(os.listdir(dest)), ["app", "compose.yaml", "data.bin"])
        with open(os.path.join(dest, "data.bin"), "rb") as f:
            self.assertEqual(f.read(), b"\xff\x00raw\r\n")
        with open(os.path.join(dest, "app", "deep", "file.txt"), "rb") as f:
            self.assertEqual(f.read(), b"deep\n")

    def test_archive_of_a_commit_dated_in_the_future(self) -> None:
        self.put("later.txt", b"later\n")
        self.sh("add", "-A")
        when = {"GIT_AUTHOR_DATE": "2099-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2099-01-01T00:00:00Z"}
        subprocess.run(["git", "-C", self.src, *_ID, "commit", "-q", "-m", "later"], env=_ENV | when, check=True)
        git.fetch(self.bare, self.url, key_dir=None)
        self.assertIn("later.txt", os.listdir(self.export(git.resolve(self.bare, "main"))))

    def test_archive_refuses_a_non_empty_destination(self) -> None:
        dest = self.export(self.a)
        with self.assertRaises(Refused):
            git.archive(self.bare, self.b, dest)
        self.assertNotIn("second.txt", os.listdir(dest))

    def test_archive_refuses_submodules_lfs_and_symlinks_before_writing(self) -> None:
        cases = {
            "gitmodules": lambda: self.put(".gitmodules", b'[submodule "s"]\n\tpath = s\n\turl = ../s\n'),
            "gitlink": lambda: self.sh("update-index", "--add", "--cacheinfo", f"160000,{self.a},vendor/s"),
            "lfs": lambda: self.put("assets/.gitattributes", b"*.bin filter=lfs diff=lfs merge=lfs -text\n"),
            "symlink": lambda: os.symlink("/", os.path.join(self.src, "app", "host")),  # a bind through it is host /
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.sh("reset", "-q", "--hard", self.b)
                change()
                if name != "gitlink":
                    self.sh("add", "-A")
                self.sh("commit", "-q", "-m", name)
                commit = self.sh("rev-parse", "HEAD")
                git.fetch(self.bare, self.url, key_dir=None)
                dest = tempfile.mkdtemp(dir=self.tmp)
                with self.assertRaises(Refused) as cm:
                    git.archive(self.bare, commit, dest)
                self.assertEqual(cm.exception.code, "unsupported-source")
                self.assertEqual(os.listdir(dest), [])

    def test_archive_and_show_refuse_a_non_sha_commit(self) -> None:
        with self.assertRaises(Refused):
            git.archive(self.bare, "--output=/tmp/x", tempfile.mkdtemp(dir=self.tmp))
        with self.assertRaises(Refused):
            git.show(self.bare, "main", "compose.yaml")

    def test_fetch_refuses_other_protocols(self) -> None:
        marker = os.path.join(self.tmp, "ext-ran")
        for url in (self.src, f"ext::sh -c touch% {marker}", "git://127.0.0.1:1/r.git", "http://127.0.0.1:1/r.git"):
            with self.subTest(url=url), self.assertRaises(CannotRun) as cm:
                git.fetch(os.path.join(self.tmp, "other.git"), url, key_dir=None)
            self.assertIn("not allowed", cm.exception.message)  # refused by policy, not by a failed connection
        self.assertFalse(os.path.exists(marker))
        with self.assertRaises(CannotRun) as cm:
            git.fetch(os.path.join(self.tmp, "other.git"), "https://127.0.0.1:1/r.git", key_dir=None)
        self.assertNotIn("not allowed", cm.exception.message)

    def test_ssh_fetch_pins_the_host_key_and_uses_only_the_deploy_key(self) -> None:
        bin_dir, log = os.path.join(self.tmp, "bin"), os.path.join(self.tmp, "ssh-argv")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "ssh"), "w") as f:
            f.write(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{log}'\nexit 255\n")
        os.chmod(os.path.join(bin_dir, "ssh"), 0o755)
        keys = os.path.join(self.tmp, "keys dir", "app")
        url = "ssh://git@example.invalid/app.git"
        with mock.patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"]}):
            for key_dir in (keys, None):
                with self.subTest(key_dir=key_dir), self.assertRaises(CannotRun):
                    git.fetch(os.path.join(self.tmp, "ssh.git"), url, key_dir=key_dir)
                with open(log) as f:
                    argv = f.read().splitlines()
                self.assertIn("StrictHostKeyChecking=yes", argv)
                self.assertIn("BatchMode=yes", argv)
                self.assertIn("git@example.invalid", argv)
                if key_dir:
                    self.assertIn(f"UserKnownHostsFile={keys}/known_hosts", argv)
                    self.assertEqual(argv[argv.index("-i") + 1], f"{keys}/id_ed25519")
                    self.assertIn("IdentitiesOnly=yes", argv)
                else:
                    self.assertIn("UserKnownHostsFile=/dev/null", argv)  # no pinned key: no host is ever trusted
                    self.assertNotIn("-i", argv)

    def test_fetch_never_runs_hooks_of_the_clone(self) -> None:
        marker = os.path.join(self.tmp, "hook-ran")
        hook = os.path.join(self.bare, "hooks", "reference-transaction")
        os.makedirs(os.path.dirname(hook), exist_ok=True)
        with open(hook, "w") as f:
            f.write(f"#!/bin/sh\ntouch {marker}\n")
        os.chmod(hook, 0o755)
        self.put("third.txt", b"3\n")
        third = self.commit("third")
        git.fetch(self.bare, self.url, key_dir=None)
        self.assertEqual(git.resolve(self.bare, "main"), third)
        self.assertFalse(os.path.exists(marker))
        # the same hook does run for a plain git command, so the check above is meaningful
        subprocess.run(["git", "--git-dir", self.bare, "update-ref", "refs/heads/x", third], env=_ENV, check=True)
        self.assertTrue(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
