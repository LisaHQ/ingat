"""Build tested.json from the lane verdict files of one CI run: only lanes with result PASS enter it (ADR-0014)."""

import json
import pathlib
import sys


def main(out_dir: str) -> None:
    entries = []
    for path in sorted(pathlib.Path(out_dir).glob("lane-*.json")):
        lane = json.loads(path.read_text())
        if lane.get("result") == "PASS":
            entries.append({k: lane[k] for k in ("engine", "arch", "cli", "compose")})
    print(json.dumps(sorted(entries, key=lambda e: (e["engine"], e["arch"])), indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
