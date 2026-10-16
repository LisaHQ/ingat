import json
import re
import unittest
from typing import Any

from ingat.adapters.override import LOGGING, RESET_LIST, RESET_NULL, isolated, live, render

NS = "x."
MODEL: dict[str, dict[str, Any]] = {
    "app": {"image": "fx-lite:dev", "build": {"context": "/src", "dockerfile": "Dockerfile"}, "ports": ["3000"]},
    "web": {"image": "fx-web:dev", "logging": {"driver": "json-file"}},
}
IMAGES = {"app": "sha256:aa", "web": "sha256:bb"}
TAGS = {"!reset null": RESET_NULL, "!reset []": RESET_LIST}

LIVE_TEXT = """\
"networks":
  "default":
    "labels":
      "x.instance": "lite-test"
  "edge":
    "labels":
      "x.instance": "lite-test"
"services":
  "app":
    "build": !reset null
    "image": "sha256:aa"
    "labels":
      "x.instance": "lite-test"
      "x.role": "app"
    "logging":
      "driver": "local"
      "options":
        "max-file": "3"
        "max-size": "10m"
    "pull_policy": "never"
  "web":
    "image": "sha256:bb"
    "labels":
      "x.instance": "lite-test"
      "x.role": "app"
    "pull_policy": "never"
"volumes":
  "data":
    "external": true
    "name": "lite-test_data_g1"
"""

ISOLATED_TEXT = """\
"networks":
  "default":
    "internal": true
    "labels":
      "x.instance": "lite-test"
      "x.op": "7"
    "name": !reset null
"services":
  "app":
    "environment":
      "JOBS": "off"
    "image": "sha256:aa"
    "labels":
      "x.instance": "lite-test"
      "x.op": "7"
      "x.role": "app"
    "logging":
      "driver": "local"
      "options":
        "max-file": "3"
        "max-size": "10m"
    "ports": !reset []
    "pull_policy": "never"
"""


def _unescape(text: str) -> str:
    """YAML's \\UXXXXXXXX escapes back to characters, honouring escaped backslashes."""
    return re.sub(r"\\(?:U([0-9a-f]{8})|.)", lambda m: chr(int(m[1], 16)) if m[1] else m[0], text)


def _value(text: str) -> Any:
    """One value as Compose sees it: tags, JSON scalars or flow lists, `$$` read back as `$`."""
    if text in TAGS:
        return TAGS[text]
    v = json.loads(_unescape(text))
    if isinstance(v, str):
        return v.replace("$$", "$")
    if isinstance(v, list):
        return [x.replace("$$", "$") if isinstance(x, str) else x for x in v]
    return v


LINE = re.compile(r'( *)("(?:[^"\\]|\\.)*"):(?: (.+))?')


def read(text: str) -> dict[str, Any]:
    """A strict reader for the override's YAML subset: two-space block mappings of JSON-quoted keys."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-2, root)]
    for line in text.splitlines():
        m = LINE.fullmatch(line)
        if not m:
            raise ValueError(f"bad line: {line!r}")
        indent, key = len(m[1]), json.loads(_unescape(m[2]))
        while stack[-1][0] >= indent:
            stack.pop()
        if indent != stack[-1][0] + 2 or key in stack[-1][1]:
            raise ValueError(f"bad indent or duplicate key: {line!r}")
        if m[3] is None:
            child: dict[str, Any] = {}
            stack[-1][1][key] = child
            stack.append((indent, child))
        else:
            stack[-1][1][key] = _value(m[3])
    return root


def spec_live(**kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "instance": "lite-test",
        "ns": NS,
        "images": IMAGES,
        "stores": {"data": "lite-test_data_g1"},
        "networks": ["edge"],
    }
    return live(MODEL, **(args | kw))


def spec_isolated(**kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "instance": "lite-test",
        "ns": NS,
        "images": IMAGES,
        "stores": {"data": "lite-test_data_t7"},
        "networks": ["edge"],
        "op": 7,
        "holds": {"app": {"JOBS": "off", "MODE": "capture"}},
    }
    return isolated(MODEL, **(args | kw))


class RenderTest(unittest.TestCase):
    def test_live_text_is_exact(self) -> None:
        self.assertEqual(render(spec_live()), LIVE_TEXT)

    def test_round_trip_and_sorted_keys(self) -> None:
        for spec in (spec_live(), spec_isolated(), spec_live(none_logging={"app"}, extra_env={"web": {"A": "1"}})):
            self.assertEqual(read(render(spec)), spec)

    def test_deterministic_regardless_of_insertion_order(self) -> None:
        a = {"b": {"y": "1", "x": "2"}, "a": "3"}
        b = {"a": "3", "b": {"x": "2", "y": "1"}}
        self.assertEqual(render(a), render(b))
        self.assertEqual(render(a), '"a": "3"\n"b":\n  "x": "2"\n  "y": "1"\n')

    def test_scalars_are_literal_and_valid_yaml_escapes(self) -> None:
        weird = 'q"b\\n\nt\t$HOME ${X} $$ é \x7f \U0001f600'
        spec = {
            "s": {"env": {"K": weird}, "flag": True, "n": 3, "none": None, "empty": {}, "list": ["a$", 1, False]},
            "r": {"build": RESET_NULL, "ports": RESET_LIST},
        }
        text = render(spec)
        self.assertEqual(read(text), spec)
        self.assertIn('"q\\"b\\\\n\\nt\\t$$HOME $${X} $$$$ \\U000000e9 \\U0000007f \\U0001f600"', text)
        self.assertNotIn("\\u", text)
        self.assertTrue(text.isascii())
        self.assertIn('"empty": {}\n', text)
        self.assertIn('"list": ["a$$", 1, false]\n', text)
        self.assertIn('"build": !reset null\n', text)
        self.assertIn('"ports": !reset []\n', text)

    def test_escapes_never_merge_across_an_escaped_backslash(self) -> None:
        # A literal backslash, the text "ud83d" and a lone low surrogate stay three separate pieces; the lone
        # surrogate is written as an escape that YAML refuses, so the value can never silently change.
        text = render({"k": "\\ud83d\udc00", "\U0001f600": "x"})
        self.assertEqual(text, '"k": "\\\\ud83d\\U0000dc00"\n"\\U0001f600": "x"\n')
        self.assertEqual(read(text), {"k": "\\ud83d\udc00", "\U0001f600": "x"})


class LiveTest(unittest.TestCase):
    def test_pins_images_and_stable_labels_only(self) -> None:
        services = spec_live()["services"]
        for name, item in services.items():
            self.assertEqual(item["image"], IMAGES[name])
            self.assertEqual(item["pull_policy"], "never")
            self.assertEqual(item["labels"], {"x.instance": "lite-test", "x.role": "app"})
            self.assertNotIn("ports", item)
            self.assertNotIn("environment", item)

    def test_every_service_must_have_an_image_pin(self) -> None:
        with self.assertRaises(KeyError):
            spec_live(images={"app": "sha256:aa"})

    def test_build_reset_only_where_declared(self) -> None:
        services = spec_live()["services"]
        self.assertIs(services["app"]["build"], RESET_NULL)
        self.assertNotIn("build", services["web"])

    def test_logging_default_own_and_none(self) -> None:
        services = spec_live()["services"]
        self.assertEqual(services["app"]["logging"], LOGGING)
        self.assertNotIn("logging", services["web"])
        terminal = spec_live(none_logging={"app", "web"})["services"]
        self.assertEqual(terminal["app"]["logging"], {"driver": "none"})
        self.assertEqual(terminal["web"]["logging"], {"driver": "none"})

    def test_stores_are_external_generation_volumes(self) -> None:
        self.assertEqual(spec_live()["volumes"], {"data": {"name": "lite-test_data_g1", "external": True}})
        self.assertNotIn("volumes", spec_live(stores={}))

    def test_networks_include_default_once(self) -> None:
        nets = spec_live(networks=["default", "edge"])["networks"]
        self.assertEqual(nets, {n: {"labels": {"x.instance": "lite-test"}} for n in ("default", "edge")})
        self.assertEqual(list(spec_live(networks=[])["networks"]), ["default"])

    def test_extra_env(self) -> None:
        services = spec_live(extra_env={"web": {"A": "1"}, "app": {}})["services"]
        self.assertEqual(services["web"]["environment"], {"A": "1"})
        self.assertNotIn("environment", services["app"])


class IsolatedTest(unittest.TestCase):
    def test_isolated_text_is_exact(self) -> None:
        spec = isolated(
            {"app": {"ports": ["3000"]}},
            instance="lite-test",
            ns=NS,
            images={"app": "sha256:aa"},
            stores={},
            networks=[],
            op=7,
            holds={"app": {"JOBS": "off"}},
        )
        self.assertEqual(render(spec), ISOLATED_TEXT)

    def test_isolation(self) -> None:
        spec = spec_isolated()
        for item in spec["services"].values():
            self.assertIs(item["ports"], RESET_LIST)
            self.assertEqual(item["labels"], {"x.instance": "lite-test", "x.role": "app", "x.op": "7"})
            self.assertEqual(item["pull_policy"], "never")
        self.assertEqual(set(spec["networks"]), {"default", "edge"})
        for net in spec["networks"].values():
            # A fixed app network name would be shared with the live project; the reset makes it project-scoped.
            expected = {"labels": {"x.instance": "lite-test", "x.op": "7"}, "internal": True, "name": RESET_NULL}
            self.assertEqual(net, expected)
        self.assertEqual(spec["volumes"], {"data": {"name": "lite-test_data_t7", "external": True}})

    def test_holds_beat_extra_env(self) -> None:
        spec = spec_isolated(extra_env={"app": {"JOBS": "on", "B": "2"}, "web": {"C": "3"}})
        self.assertEqual(spec["services"]["app"]["environment"], {"JOBS": "off", "MODE": "capture", "B": "2"})
        self.assertEqual(spec["services"]["web"]["environment"], {"C": "3"})
        self.assertNotIn("environment", spec_isolated(holds={})["services"]["web"])

    def test_does_not_leak_into_live(self) -> None:
        before = render(spec_live())
        spec_isolated()
        self.assertEqual(render(spec_live()), before)
        self.assertEqual(LOGGING, {"driver": "local", "options": {"max-size": "10m", "max-file": "3"}})


if __name__ == "__main__":
    unittest.main()
