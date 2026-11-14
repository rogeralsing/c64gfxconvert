"""Build a native SID arrangement and capture it in VICE."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from native_playback import run

HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--song", choices=("hyperbased", "cream"), default="hyperbased")
    parser.add_argument("--full", action="store_true", help="Build the song through its chosen musical ending; preserve the bounded reference")
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()
    if args.song == "cream":
        from cream_playback import run as cream_run
        destination = HERE / "work/cream" / ("full-linus-mix" if args.full else "linus-mix")
        result = cream_run(args.out or destination, assemble_only=args.assemble_only, full=args.full)
        print(json.dumps({"program": result["program"], "duration_s": result["duration_s"],
                          "source_interval_s": result["source_interval_s"],
                          "audio": result.get("audio", {}), "native_verified": "native" in result}, indent=2))
        return
    if args.full:
        from full_length_playback import run as full_run
        result = full_run(args.out or HERE / "work/hyperbased/full-linus-mix", assemble_only=args.assemble_only)
        print(json.dumps({"program": result["program"], "duration_s": result.get("nominal_duration_s", result["duration_s"]),
                          "audio": result.get("audio", {}), "native_verified": "native" in result}, indent=2))
        return
    result = run(args.out or HERE / "work/hyperbased/linus-mix", assemble_only=args.assemble_only)
    print(json.dumps({"program_sha256": result["program_sha256"],
                      "audio": {name: {"file": value["file"], "sha256": value["sha256"]}
                                for name, value in result.get("audio", {}).items()},
                      "nmi_cpu_fraction": result.get("budget", {}).get("nmi_cpu_fraction"),
                      "minimum_foreground_slack": result.get("budget", {}).get("minimum_deadline_slack_foreground_cycles"),
                      "ring_proof_passed": result.get("ring", {}).get("passed")}, indent=2))


if __name__ == "__main__":
    main()
