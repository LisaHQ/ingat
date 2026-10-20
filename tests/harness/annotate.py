"""Turn the failing tests of a CI step's log into GitHub annotations.

The job logs of a public repository need a sign-in; annotations do not, so the run page names what failed. Each
failing unittest block becomes one annotation with the end of its traceback; a log without one (a step that stopped
before or after its tests) gives its last lines. GitHub shows at most 10 error annotations per step, so the tenth
lists the names of the rest instead of dropping them.

usage: python3 tests/harness/annotate.py <log> <title>
"""

import re
import sys

SEP = "-" * 70
SHOWN = 9  # detailed annotations; the tenth names the remaining failures
TAIL = 30  # traceback lines kept per failure


def escape(lines: list[str]) -> str:
    return "%0A".join(line.rstrip().replace("%", "%25") for line in lines)


def title(text: str) -> str:
    return re.sub(r"[,:\r\n]", " ", text).strip()[:200]


def annotations(text: str, fallback: str) -> list[str]:
    blocks = re.split(r"(?m)^={70}$", text)[1:]
    if not blocks:
        return [f"::error title={title(fallback)}::{escape(text.splitlines()[-TAIL:])}"]
    out = []
    for block in blocks[:SHOWN]:
        head, _, rest = block.partition(SEP)
        lines = [*head.strip().splitlines(), *rest.split(SEP)[0].strip().splitlines()[-TAIL:]]  # name, docstring
        out.append(f"::error title={title(lines[0])}::{escape(lines)}")
    rest_names = [block.partition(SEP)[0].strip().splitlines()[0] for block in blocks[SHOWN:]]
    if rest_names:
        out.append(f"::error title={len(rest_names)} more failing tests::{escape(rest_names)}")
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        text = "the step stopped before it wrote its log"
    print("\n".join(annotations(text, sys.argv[2])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
