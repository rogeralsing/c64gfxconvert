"""Build the canonical twenty-second native Hyperbased arrangement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from native_playback import run

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "work/hyperbased/linus-mix")
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()
    result = run(args.out, assemble_only=args.assemble_only)
    print(json.dumps({"program_sha256": result["program_sha256"],
                      "audio": {name: {"file": value["file"], "sha256": value["sha256"]}
                                for name, value in result.get("audio", {}).items()},
                      "nmi_cpu_fraction": result.get("budget", {}).get("nmi_cpu_fraction"),
                      "minimum_foreground_slack": result.get("budget", {}).get("minimum_deadline_slack_foreground_cycles"),
                      "ring_proof_passed": result.get("ring", {}).get("passed")}, indent=2))


if __name__ == "__main__":
    main()
