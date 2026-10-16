import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from ingat.model import templates
from ingat.model.bundle import (
    CLASSES,
    ID_RE,
    bundle_doc,
    bundle_hash,
    default_naming,
    parse_sums,
    sums_text,
)
from ingat.model.errors import Refused
from ingat.model.records import dumps

H1 = "a" * 64
H2 = "0123456789abcdef" * 4


class IdAndNamingTest(unittest.TestCase):
    def test_classes(self) -> None:
        self.assertEqual(CLASSES, ("scheduled", "manual", "pre-change", "final"))

    def test_id_rule(self) -> None:
        for ok in ("20261015T010203Z-manual", "a", "A.b_c-1", "9" + "x" * 127):
            self.assertIsNotNone(ID_RE.fullmatch(ok), ok)
        for bad in ("", ".hidden", "-x", "_x", "a/b", "a b", "a\n", "9" + "x" * 128, "a:b", "..", "../a"):
            self.assertIsNone(ID_RE.fullmatch(bad), bad)
            self.assertIsNone(re.match(ID_RE, bad), bad)
            self.assertIsNone(ID_RE.search(bad), bad)

    def test_default_naming_covers_every_class_with_a_valid_naming_template(self) -> None:
        naming = default_naming()
        self.assertEqual(sorted(naming), sorted(CLASSES))
        for template in naming.values():
            self.assertEqual(template, "{bundle.stamp}-{class}")
            self.assertEqual(templates.check(template, templates.CONTEXTS["naming"]), [])
        rendered = templates.render(naming["pre-change"], {"bundle.stamp": "20261015T010203Z", "class": "pre-change"})
        self.assertIsNotNone(ID_RE.fullmatch(rendered))

    def test_default_naming_returns_a_fresh_dict(self) -> None:
        default_naming()["manual"] = "x"
        self.assertEqual(default_naming()["manual"], "{bundle.stamp}-{class}")


class SumsTest(unittest.TestCase):
    def test_sorted_sha256sum_lines(self) -> None:
        text = sums_text([("payload/e/b.db", H1), ("meta/manifest.toml", H2), ("payload/e/a", H2)])
        self.assertEqual(
            text,
            f"{H2}  meta/manifest.toml\n{H2}  payload/e/a\n{H1}  payload/e/b.db\n".encode(),
        )

    def test_round_trip(self) -> None:
        files = [("payload/x/y z.json", H1), ("meta/compose.yaml", H2), ("payload/x/ü.txt", H1)]
        self.assertEqual(parse_sums(sums_text(files)), dict(files))

    def test_sums_text_refuses_unsafe_input(self) -> None:
        bad = [
            [("a", H1), ("a", H2)],
            [("/abs", H1)],
            [("a/../b", H1)],
            [("./a", H1)],
            [("a//b", H1)],
            [("a/", H1)],
            [("", H1)],
            [("a\\b", H1)],
            [("a\nb", H1)],
            [("a\rb", H1)],
            [("a\x00b", H1)],
            [("a\udcff", H1)],  # an undecodable file name as os.walk returns it
            [("a", H1.upper())],
            [("a", "abc")],
        ]
        for files in bad:
            with self.subTest(files=files), self.assertRaises(Refused) as cm:
                sums_text(files)
            self.assertEqual(cm.exception.code, "invalid-bundle")

    def test_parse_refuses_non_canonical_or_unsafe_text(self) -> None:
        good = f"{H1}  a\n{H2}  b\n"
        bad = [
            "",
            "\n",
            f"{H1}  a",
            f"{H1}  a\n\n",
            f"{H2}  b\n{H1}  a\n",
            f"{H1}  a\n{H2}  a\n",
            f"{H1}  /etc/passwd\n",
            f"{H1}  x/../../y\n",
            f"{H1} a\n",
            f"{H1} *a\n",
            f"{H1.upper()}  a\n",
            f"{H1[:-1]}  a\n",
            f"{H1}  a\r\n",
            good.replace("\n", "\r\n"),
            f"\\{H1}  a\\\\b\n",  # sha256sum's escaped form for a name with a backslash
            f"{H1}  a\n{H2}  b\nnot a sums line\n",
            f"{H1}  ./a\n",
            f"{H1}  a//b\n",
            f"{H1}  a/\n",
        ]
        self.assertEqual(parse_sums(good.encode()), {"a": H1, "b": H2})
        for text in bad:
            with self.subTest(text=text), self.assertRaises(Refused) as cm:
                parse_sums(text.encode())
            self.assertEqual(cm.exception.code, "invalid-bundle")
        for data in (H1.encode() + b"  \xff\n", H1[:-1].encode() + b"\xff  a\n"):
            with self.subTest(data=data), self.assertRaises(Refused) as cm:
                parse_sums(data)
            self.assertEqual(cm.exception.code, "invalid-bundle")

    @unittest.skipUnless(shutil.which("sha256sum"), "needs coreutils sha256sum")
    def test_sha256sum_checks_the_written_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            files = {"payload/e/data.bin": b"\x00\x01data", "meta/deployment.json": b"{}", "payload/e/x y": b""}
            pairs = []
            for rel, content in files.items():
                os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(d, rel), "wb") as f:
                    f.write(content)
                pairs.append((rel, hashlib.sha256(content).hexdigest()))
            with open(os.path.join(d, "SHA256SUMS"), "wb") as f:
                f.write(sums_text(pairs))
            done = subprocess.run(["sha256sum", "--strict", "-c", "SHA256SUMS"], cwd=d, capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(os.path.join(d, "payload/e/data.bin"), "ab") as f:
                f.write(b"!")
            done = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=d, capture_output=True)
            self.assertNotEqual(done.returncode, 0)

    def test_bundle_hash_is_sha256_of_the_sums_bytes(self) -> None:
        sums = sums_text([("a", H1)])
        self.assertEqual(bundle_hash(sums), hashlib.sha256(sums).hexdigest())
        self.assertNotEqual(bundle_hash(sums), bundle_hash(sums_text([("a", H2)])))


class BundleDocTest(unittest.TestCase):
    def args(self, **changes: object) -> dict[str, object]:
        args: dict[str, object] = {
            "bundle_id": "20261015T010203Z-pre-change",
            "klass": "pre-change",
            "instance": "lite-test",
            "app": "fx-lite",
            "environment": "test",
            "lineage": "0" * 32,
            "created_at": "2026-10-15T01:02:03Z",
            "freeze_at": "2026-10-15T01:02:00Z",
            "consistency": "writers-stopped",
            "deployment": {
                "seq": 3,
                "release": "abc",
                "commit": "c" * 40,
                "images": {"app": "sha256:" + H1},
                "manifest_sha256": H1,
                "model_sha256": H2,
                "env_file": "/private/env/x.env",
                "params": {"FX_PORT": "20090"},
                "state_schema": 1,
            },
            "schema": {"expected": "5", "actual": "5", "at": "2026-10-15T00:00:00Z"},
            "stores": {"data": 1},
            "entry": "20261015T010203Z",
            "files": [("payload/e/b", H2, 5), ("payload/e/a", H1, 7)],
            "meta": ["deployment.json", "compose.yaml"],
            "tool": {
                "version": "0.1.0",
                "engine": "24.0.2",
                "api": "1.43",
                "cli": "29.0.0",
                "compose": "2.40.0",
                "arch": "amd64",
                "os": "linux",
                "kernel": "6.1",
            },
            "host": "h1",
        }
        args.update(changes)
        return args

    def test_exact_format_1_fields(self) -> None:
        doc = bundle_doc(**self.args())  # type: ignore[arg-type]
        self.assertEqual(
            sorted(doc),
            sorted(
                "format id class instance app environment lineage created_at freeze_at consistency deployment"
                " schema stores payload meta tool host".split()
            ),
        )
        self.assertEqual(doc["format"], 1)
        self.assertEqual(doc["class"], "pre-change")
        self.assertEqual(
            sorted(doc["deployment"]), sorted("seq release commit images manifest_sha256 model_sha256".split())
        )
        self.assertEqual(doc["schema"], {"expected": "5", "actual": "5"})
        self.assertEqual(sorted(doc["tool"]), sorted("version engine api cli compose arch os".split()))
        self.assertEqual(
            doc["payload"],
            {
                "entry": "20261015T010203Z",
                "files": [
                    {"path": "payload/e/a", "size": 7, "sha256": H1},
                    {"path": "payload/e/b", "size": 5, "sha256": H2},
                ],
                "total_bytes": 12,
            },
        )
        self.assertEqual(doc["meta"], ["compose.yaml", "deployment.json"])
        self.assertEqual(doc["stores"], {"data": 1})
        dumps(doc)

    def test_never_copies_env_files_or_params(self) -> None:
        text = dumps(bundle_doc(**self.args())).decode()  # type: ignore[arg-type]
        self.assertNotIn("env_file", text)
        self.assertNotIn("/private/env", text)
        self.assertNotIn("FX_PORT", text)
        self.assertNotIn("kernel", text)

    def test_online_bundle_without_schema(self) -> None:
        doc = bundle_doc(**self.args(freeze_at=None, schema=None, consistency="online-app"))  # type: ignore[arg-type]
        self.assertIsNone(doc["freeze_at"])
        self.assertIsNone(doc["schema"])
        self.assertEqual(doc["consistency"], "online-app")

    def test_refuses_a_class_or_consistency_outside_format_1(self) -> None:
        for change in ({"klass": "daily"}, {"consistency": "crash-consistent"}):
            with self.subTest(change=change), self.assertRaises(Refused) as cm:
                bundle_doc(**self.args(**change))  # type: ignore[arg-type]
            self.assertEqual(cm.exception.code, "invalid-bundle")
        for klass in CLASSES:
            self.assertEqual(bundle_doc(**self.args(klass=klass))["class"], klass)  # type: ignore[arg-type]

    def test_refuses_an_invalid_id(self) -> None:
        for bad in ("", "../x", "a/b", "x" * 129):
            with self.subTest(bad=bad), self.assertRaises(Refused) as cm:
                bundle_doc(**self.args(bundle_id=bad))  # type: ignore[arg-type]
            self.assertEqual(cm.exception.code, "bundle-id")


if __name__ == "__main__":
    unittest.main()
