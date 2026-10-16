"""The raw-text rules over app Compose files (policy/compose_text.py, ARCHITECTURE §9.5): every way Compose v5.6.0
reads an `include` or an `extends` file is refused (tests/docker/test_planning.py shows Compose reading each hostile
form below), and the fixtures and ordinary Compose files pass."""

import unittest
from pathlib import Path

from ingat.policy.compose_text import errors

REPO = Path(__file__).resolve().parents[2]
SVC = "services:\n  app:\n    image: busybox\n"
INDENTED = "".join(f"  {line}\n" for line in SVC.splitlines())  # a root mapping at column 2
OTHER = "{file: other.yaml, service: base}"
NEL, LS, BOM = chr(0x85), chr(0x2028), chr(0xFEFF)
# Each form makes Compose read inc.yaml (include) or other.yaml (extends with a file).
HOSTILE = {
    "include": "include:\n  - inc.yaml\n" + SVC,
    "quoted include": '"include": [inc.yaml]\n' + SVC,
    "top-level flow mapping": '{"include": [inc.yaml], "services": {"app": {"image": "busybox"}}}\n',
    "merge key at the top": "x-a: &a\n  include: [inc.yaml]\n<<: *a\n" + SVC,
    "second document": SVC + "---\ninclude: [inc.yaml]\n",
    "explicit key": "? include\n: [inc.yaml]\n" + SVC,
    "CRLF": (SVC + "include: [inc.yaml]\n").replace("\n", "\r\n"),
    "CR": SVC + "\rinclude: [inc.yaml]\n",
    "NEL": SVC + NEL + "include: [inc.yaml]\n",
    "line separator": SVC + LS + "include: [inc.yaml]\n",
    "extends block": SVC + "    extends:\n      file: other.yaml\n      service: base\n",
    "extends flow": SVC + '    "extends": {file: other.yaml, service: base}\n',
    "escaped key": SVC + '    "ext\\x65nds": {file: other.yaml, service: base}\n',
    "alias key": "x-k: &k extends\n" + SVC + "    *k : {file: other.yaml, service: base}\n",
    "binary key": SVC + "    !!binary ZXh0ZW5kcw==: {file: other.yaml, service: base}\n",
    "explicit key in extends": SVC + "    extends:\n      ? file\n      : other.yaml\n      service: base\n",
    "merge into extends": "x-f: &f\n  file: other.yaml\n" + SVC + "    extends:\n      <<: *f\n      service: base\n",
    "alias as extends": "x-e: &e {file: other.yaml, service: base}\n" + SVC + "    extends: *e\n",
    "indented root": "  include:\n    - inc.yaml\n" + INDENTED,
    "indented root after its services": INDENTED + "  include: [inc.yaml]\n",
    "indented flow root": ' {"include": ["inc.yaml"], "services": {"app": {"image": "busybox"}}}\n',
    "indented second document": SVC + "---\n  include: [inc.yaml]\n",
    "indented merge at the root": "  x-a: &a\n    include: [inc.yaml]\n  <<: *a\n" + INDENTED,
    "second extends on a line": f"services:\n  app: {{labels: {{extends: base}}, extends: {OTHER}}}\n",
    "flow extends value below": f"services:\n  app: {{image: busybox, extends:\n  {OTHER}}}\n",
    "flow extends value further left": f"services:\n  app: {{image: busybox, extends:\n {OTHER}}}\n",
    "alias key with a dot": "x-k: &k.x extends\n" + SVC + "    *k.x : {file: other.yaml, service: base}\n",
}
BENIGN = {
    "same-file extends": SVC + "  x:\n    image: busybox\n    extends: app\n",
    "same-file extends block": SVC + "  x:\n    image: busybox\n    extends:\n      service: app  # base\n",
    "same-file extends flow": SVC + "  x: {image: busybox, extends: {service: app}}\n",
    "merge key in a service": 'x-common: &common\n  restart: "no"\n' + SVC + "    <<: *common\n",
    "markers and comments": "# app\n---\nname: x  # project\n" + SVC + "x-list:\n- a\n...\n",
    "leading byte-order mark": BOM + SVC,
    "include in a string": SVC + '    command: ["sh", "-c", "echo include: x"]\n    labels:\n      x-include: "1"\n',
    "a second document of services": SVC + "---\nservices:\n  b:\n    image: busybox\n",
    "indented comment first": "  # app\n" + SVC,
    "same-file extends in a flow mapping": SVC + "  x: {image: busybox, labels: {a: b}, extends: app}\n",
    "same-file extends block, then a key": SVC + "  x:\n    extends:\n      service: app\n    image: busybox\n",
}


class ComposeTextTest(unittest.TestCase):
    def test_every_include_and_extends_file_form_is_refused(self) -> None:
        for what, text in HOSTILE.items():
            with self.subTest(what):
                found = errors("compose.yaml", text.encode())
                self.assertTrue(found, what)
                self.assertTrue(all(e.startswith("compose.yaml") for e in found), found)

    def test_ordinary_files_and_the_fixtures_pass(self) -> None:
        self.assertFalse(set(HOSTILE) & set(BENIGN))  # the T1 test runs both sets under their names
        for what, text in BENIGN.items():
            with self.subTest(what):
                self.assertEqual(errors("compose.yaml", text.encode()), [])
        for path in sorted(REPO.glob("fixtures/*/compose*.yaml")):
            self.assertEqual(errors(path.name, path.read_bytes()), [], path)

    def test_errors_name_the_file_and_line(self) -> None:
        self.assertEqual(
            errors("c.yaml", (SVC + "include: [inc.yaml]\n").encode()),
            [
                "c.yaml:4: only the top-level keys version, name, services, networks, volumes, secrets, configs and"
                " x-* are allowed (include is refused)"
            ],
        )
        self.assertEqual(errors("c.yaml", b"\xff"), ["c.yaml: not UTF-8 text"])
        self.assertEqual(errors("c.yaml", (SVC + "\tx: 1\n").encode()), ["c.yaml:4: a tab in the indentation"])


if __name__ == "__main__":
    unittest.main()
