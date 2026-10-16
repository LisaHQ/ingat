import contextlib
import hashlib
import os
import stat
import tempfile
import threading
import unittest
from collections.abc import Callable
from unittest import mock

from ingat.model.errors import Refused
from ingat.store import fs


def mode(path: str) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def content(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name
        self.outside = os.path.join(self.d, "outside")
        os.mkdir(self.outside)

    def p(self, *parts: str) -> str:
        return os.path.join(self.d, *parts)

    def put(self, rel: str, data: bytes = b"x", mode: int = 0o644) -> str:
        path = self.p(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        os.chmod(path, mode)
        return path

    def assert_unsafe(self, call: Callable[..., object], *args: object) -> None:
        with self.assertRaises(Refused) as cm:
            call(*args)
        self.assertEqual(cm.exception.code, "unsafe-path")


class WriteTest(Base):
    def test_write_once_publishes_whole_file_with_exact_mode_and_parents(self) -> None:
        old = os.umask(0o077)
        self.addCleanup(os.umask, old)
        path = self.p("a", "b", "rec.json")
        fs.write_once(path, b"one", 0o640)
        self.assertEqual(content(path), b"one")
        self.assertEqual(mode(path), 0o640)
        self.assertEqual((mode(self.p("a")), mode(self.p("a", "b"))), (0o700, 0o700))
        self.assertEqual(os.listdir(self.p("a", "b")), ["rec.json"])
        fs.mkdirs(self.p("m", "n"), 0o750)
        self.assertEqual((mode(self.p("m")), mode(self.p("m", "n"))), (0o750, 0o750))

    def test_write_once_never_replaces(self) -> None:
        path = self.p("rec.json")
        fs.write_once(path, b"one")
        with self.assertRaises(FileExistsError):
            fs.write_once(path, b"two")
        self.assertEqual(content(path), b"one")
        self.assertEqual(sorted(os.listdir(self.d)), ["outside", "rec.json"])

    def test_write_once_never_writes_through_a_symlink_at_the_name(self) -> None:
        target = os.path.join(self.outside, "t")
        os.symlink(target, self.p("rec.json"))
        with self.assertRaises(FileExistsError):
            fs.write_once(self.p("rec.json"), b"x")
        self.assertFalse(os.path.lexists(target))

    def test_symlinked_or_file_parent_component_is_refused(self) -> None:
        os.symlink(self.outside, self.p("link"))
        self.put("file")
        for path in (self.p("link", "x"), self.p("link", "new", "x"), self.p("file", "x")):
            with self.subTest(path=path):
                for call in (fs.write_once, fs.replace_atomic):
                    self.assert_unsafe(call, path, b"x")
                self.assert_unsafe(fs.append_line, path, b"x")
                self.assert_unsafe(fs.mkdirs, path)
        self.assertEqual(os.listdir(self.outside), [])

    def test_relative_path_is_refused(self) -> None:
        self.assert_unsafe(fs.write_once, "rel/x", b"x")

    def test_replace_atomic_replaces_and_leaves_no_temp(self) -> None:
        path = self.p("r.json")
        fs.replace_atomic(path, b"one")
        fs.replace_atomic(path, b"two", 0o644)
        self.assertEqual(content(path), b"two")
        self.assertEqual(mode(path), 0o644)
        self.assertEqual(sorted(os.listdir(self.d)), ["outside", "r.json"])

    def test_replace_atomic_replaces_a_symlink_not_its_target(self) -> None:
        target = self.put("outside/t", b"keep")
        os.symlink(target, self.p("r.json"))
        fs.replace_atomic(self.p("r.json"), b"new")
        self.assertFalse(os.path.islink(self.p("r.json")))
        self.assertEqual(content(target), b"keep")

    def test_append_line(self) -> None:
        path = self.p("j", "steps.jsonl")
        fs.append_line(path, b'{"a":1}')
        fs.append_line(path, b'{"a":2}')
        self.assertEqual(content(path), b'{"a":1}\n{"a":2}\n')
        self.assertEqual(mode(path) & 0o077, 0)
        target = self.put("outside/t", b"keep")
        os.symlink(target, self.p("j", "link.jsonl"))
        self.assert_unsafe(fs.append_line, self.p("j", "link.jsonl"), b"x")
        self.assertEqual(content(target), b"keep")

    def test_open_write_stream_is_exclusive(self) -> None:
        path = self.p("o", "out.bin")
        fd = fs.open_write(path, 0o600)
        os.write(fd, b"\x00\xffbytes")
        fs.close_fsync(fd, path)
        self.assertEqual(content(path), b"\x00\xffbytes")
        with self.assertRaises(FileExistsError):
            fs.open_write(path)

    def test_make_empty_dir_is_exclusive_with_exact_mode(self) -> None:
        path = self.p("x", "placeholder")
        fs.make_empty_dir(path, 0o555)
        self.assertEqual(mode(path), 0o555)
        with self.assertRaises(FileExistsError):
            fs.make_empty_dir(path, 0o700)
        self.assertEqual(mode(path), 0o555)

    @unittest.skipUnless(os.geteuid() == 0, "needs root: chown to another owner")
    def test_make_empty_dir_applies_the_owner(self) -> None:
        path = self.p("x", "placeholder")
        fs.make_empty_dir(path, 0o555, (1234, 2345))
        st = os.lstat(path)
        self.assertEqual((stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid), (0o555, 1234, 2345))

    def test_rename_never_replaces(self) -> None:
        self.put("s/a/f", b"1")
        fs.rename(self.p("s", "a"), self.p("d", "a"))
        self.assertEqual(content(self.p("d", "a", "f")), b"1")
        os.mkdir(self.p("s", "b"))
        os.mkdir(self.p("d", "b"))
        with self.assertRaises(FileExistsError):
            fs.rename(self.p("s", "b"), self.p("d", "b"))
        self.assertTrue(os.path.isdir(self.p("s", "b")))


class ReadTest(Base):
    def test_read_and_limit(self) -> None:
        path = self.put("f", b"12345")
        self.assertEqual(fs.read(path), b"12345")
        self.assertEqual(fs.read(path, limit=5), b"12345")
        with self.assertRaises(Refused) as cm:
            fs.read(path, limit=4)
        self.assertEqual(cm.exception.code, "too-large")

    def test_read_refuses_symlink_and_fifo_without_blocking(self) -> None:
        os.symlink(self.put("outside/t"), self.p("l"))
        os.mkfifo(self.p("fifo"))
        self.assert_unsafe(fs.read, self.p("l"))
        outcome: list[str] = []

        def attempt() -> None:
            try:
                outcome.append(repr(fs.read(self.p("fifo"))))
            except Refused as e:
                outcome.append(e.code)

        thread = threading.Thread(target=attempt, daemon=True)
        thread.start()
        thread.join(5)
        self.assertEqual(outcome, ["unsafe-path"], "reading a FIFO must refuse at once, never block")

    def test_exists_and_listdir(self) -> None:
        self.put("d/b")
        self.put("d/a")
        os.symlink("/nowhere", self.p("d", "c"))
        self.assertTrue(fs.exists(self.p("d", "a")))
        self.assertTrue(fs.exists(self.p("d", "c")))
        self.assertFalse(fs.exists(self.p("d", "z")))
        self.assertFalse(fs.exists(self.p("nope", "z")))
        self.assertEqual(fs.listdir(self.p("d")), ["a", "b", "c"])
        self.assertEqual(fs.listdir(self.p("nope")), [])

    def test_hash_file(self) -> None:
        path = self.put("f", b"payload")
        self.assertEqual(fs.hash_file(path), (hashlib.sha256(b"payload").hexdigest(), 7))
        os.link(path, self.p("hard"))
        self.assert_unsafe(fs.hash_file, path)
        os.symlink(self.p("hard"), self.p("sym"))
        self.assert_unsafe(fs.hash_file, self.p("sym"))

    def test_statvfs_and_tree_size(self) -> None:
        self.put("t/a", b"123")
        self.put("t/s/b", b"4567")
        os.symlink("/etc/hostname", self.p("t", "s", "l"))
        os.symlink("/etc", self.p("t", "dl"))
        self.assertEqual(fs.tree_size(self.p("t")), 7)
        dev, free = fs.statvfs(self.d)
        self.assertEqual(dev, os.stat(self.d).st_dev)
        self.assertGreater(free, 0)


class TreeTest(Base):
    def make_tree(self) -> str:
        self.put("src/b.txt", b"bee", 0o4777)
        self.put("src/a/x.bin", b"\x00" * 3000, 0o600)
        os.makedirs(self.p("src", "a", "empty"))
        os.chmod(self.p("src", "a"), 0o750)
        return self.p("src")

    def test_walk_is_sorted_top_down_with_relpaths(self) -> None:
        src = self.make_tree()
        found = [(rel, stat.S_ISDIR(st.st_mode)) for rel, st in fs.walk(src)]
        self.assertEqual(found, [("a", True), ("a/empty", True), ("a/x.bin", False), ("b.txt", False)])

    def test_walk_refuses_links_special_files_and_a_linked_root(self) -> None:
        cases = {
            "file link": lambda: os.symlink(self.put("outside/t"), self.p("w", "d", "l")),
            "dir link": lambda: os.symlink(self.outside, self.p("w", "d", "l")),
            "fifo": lambda: os.mkfifo(self.p("w", "d", "l")),
        }
        for name, make in cases.items():
            with self.subTest(name):
                os.makedirs(self.p("w", "d"), exist_ok=True)
                make()
                with self.assertRaises(Refused) as cm:
                    list(fs.walk(self.p("w")))
                self.assertEqual(cm.exception.code, "unsafe-path")
                os.unlink(self.p("w", "d", "l"))
        os.symlink(self.p("w"), self.p("wl"))
        self.assert_unsafe(lambda: list(fs.walk(self.p("wl"))))

    def test_copy_tree_keeps_modes_without_shared_write_or_special_bits_and_reports_hashes(self) -> None:
        src = self.make_tree()
        files = fs.copy_tree(src, self.p("dst"))
        self.assertEqual(
            files,
            [
                ("a/x.bin", hashlib.sha256(b"\x00" * 3000).hexdigest(), 3000),
                ("b.txt", hashlib.sha256(b"bee").hexdigest(), 3),
            ],
        )
        self.assertEqual(content(self.p("dst", "b.txt")), b"bee")
        self.assertEqual(mode(self.p("dst", "b.txt")), 0o755)
        self.assertEqual(mode(self.p("dst", "a")), 0o750)
        self.assertTrue(os.path.isdir(self.p("dst", "a", "empty")))

    def test_copy_tree_applies_modes(self) -> None:
        src = self.make_tree()
        fs.copy_tree(src, self.p("in"), dir_mode=0o750, file_mode=0o440)
        for path in (self.p("in"), self.p("in", "a"), self.p("in", "a", "x.bin"), self.p("in", "b.txt")):
            st = os.lstat(path)
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o750 if stat.S_ISDIR(st.st_mode) else 0o440, path)

    @unittest.skipUnless(os.geteuid() == 0, "needs root: chown to another owner, directories closed to their owner")
    def test_copy_tree_applies_owner_and_read_only_modes(self) -> None:
        src = self.make_tree()
        fs.copy_tree(src, self.p("in"), owner=(10001, 10002), dir_mode=0o550, file_mode=0o440)
        for path in (self.p("in"), self.p("in", "a"), self.p("in", "a", "x.bin"), self.p("in", "b.txt")):
            st = os.lstat(path)
            want = 0o550 if stat.S_ISDIR(st.st_mode) else 0o440
            self.assertEqual((st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)), (10001, 10002, want), path)

    def test_copy_tree_refuses_links_and_leaves_no_destination(self) -> None:
        src = self.make_tree()
        os.symlink("/etc/passwd", self.p("src", "a", "zz"))
        self.assert_unsafe(fs.copy_tree, src, self.p("dst"))
        self.assertFalse(os.path.lexists(self.p("dst")))
        os.unlink(self.p("src", "a", "zz"))
        os.link(self.p("src", "b.txt"), self.p("src", "c.txt"))
        self.assert_unsafe(fs.copy_tree, src, self.p("dst"))
        self.assertFalse(os.path.lexists(self.p("dst")))

    def test_copy_tree_never_follows_a_link_swapped_into_the_destination_mid_copy(self) -> None:
        self.put("src/a/1", b"1")
        self.put("src/a/2", b"2")
        real_fsync, swapped = os.fsync, []

        def fsync(fd: int) -> None:  # a concurrent writer replaces dst/a with a link once dst/a/1 is written
            real_fsync(fd)
            if not swapped and os.path.isfile(self.p("dst", "a", "1")):
                os.rename(self.p("dst", "a"), self.p("dst", "moved"))
                os.symlink(self.outside, self.p("dst", "a"))
                swapped.append(fd)

        with mock.patch("os.fsync", fsync), contextlib.suppress(Refused):
            fs.copy_tree(self.p("src"), self.p("dst"))
        self.assertTrue(swapped)
        self.assertEqual(os.listdir(self.outside), [])

    def test_copy_tree_never_merges_into_an_existing_destination(self) -> None:
        src = self.make_tree()
        os.mkdir(self.p("dst"))
        with self.assertRaises(FileExistsError):
            fs.copy_tree(src, self.p("dst"))
        self.assertEqual(os.listdir(self.p("dst")), [])

    def test_remove_tree(self) -> None:
        src = self.make_tree()
        fs.remove_tree(src)
        self.assertFalse(os.path.lexists(src))
        fs.remove_tree(src)  # absent is done

    @unittest.skipUnless(os.geteuid() == 0, "needs root: a directory closed to its owner")
    def test_remove_tree_removes_a_read_only_directory(self) -> None:
        src = self.make_tree()
        os.chmod(self.p("src", "a"), 0o500)
        fs.remove_tree(src)
        self.assertFalse(os.path.lexists(src))

    def test_remove_tree_refuses_a_link_before_removing_anything(self) -> None:
        src = self.make_tree()
        target = self.put("outside/t", b"keep")
        os.symlink(self.outside, self.p("src", "a", "zz"))
        self.assert_unsafe(fs.remove_tree, src)
        self.assertTrue(os.path.exists(self.p("src", "b.txt")))
        self.assertEqual(content(target), b"keep")
        os.symlink(self.outside, self.p("rootlink"))
        self.assert_unsafe(fs.remove_tree, self.p("rootlink"))
        self.assertTrue(os.path.exists(target))

    def test_chmod_tree(self) -> None:
        src = self.make_tree()
        fs.chmod_tree(src, 0o700, 0o600)
        for rel in ("", "a", "a/empty", "a/x.bin", "b.txt"):
            st = os.lstat(os.path.join(src, rel))
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o700 if stat.S_ISDIR(st.st_mode) else 0o600, rel)
        os.symlink("/etc/passwd", self.p("src", "l"))
        before = os.stat("/etc/passwd")
        self.assert_unsafe(fs.chmod_tree, src, 0o777, 0o777)
        after = os.stat("/etc/passwd")
        self.assertEqual((after.st_uid, after.st_gid, after.st_mode), (before.st_uid, before.st_gid, before.st_mode))
        self.assertEqual(mode(self.p("src", "a", "x.bin")), 0o600, "refused before any change")

    @unittest.skipUnless(os.geteuid() == 0, "needs root: chown to another owner")
    def test_chown_tree(self) -> None:
        src = self.make_tree()
        fs.chown_tree(src, 4321, 4322)
        for rel in ("", "a", "a/empty", "a/x.bin", "b.txt"):
            st = os.lstat(os.path.join(src, rel))
            self.assertEqual((st.st_uid, st.st_gid), (4321, 4322), rel)
        os.symlink("/etc/passwd", self.p("src", "l"))
        before = os.stat("/etc/passwd")
        self.assert_unsafe(fs.chown_tree, src, 1, 1)
        after = os.stat("/etc/passwd")
        self.assertEqual((after.st_uid, after.st_gid), (before.st_uid, before.st_gid))
        self.assertEqual(os.lstat(self.p("src", "a", "x.bin")).st_uid, 4321, "refused before any change")


if __name__ == "__main__":
    unittest.main()
