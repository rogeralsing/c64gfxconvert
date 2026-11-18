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
    parser.add_argument("--sid2-repair", action="store_true",
                        help="Audition original Cream drums on SID2 over source time 17.92–37.92; not a full-song replacement")
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()
    if args.sid2_repair:
        if args.song != "cream" or args.full:
            parser.error("--sid2-repair requires --song cream without --full; this is a bounded repair audition")
        from cream_drum_repair import run as repair_run
        result = repair_run(args.out or HERE / "work/cream/sid2-repair",
                            assemble_only=args.assemble_only)
        print(json.dumps({"program": result["program"], "duration_s": result["duration_s"],
                          "source_interval_s": result["source_interval_s"],
                          "full_song": False, "audio": result.get("audio", {}),
                          "native_verified": "native" in result}, indent=2))
        return
    if args.song == "cream":
        if args.full:
            from cream_three_minute import run as cream_full_run
            from cream_sid1_melody import profile as cream_sid1_profile
            result = cream_full_run(args.out or HERE / "work/cream/sid1-repair",
                                    assemble_only=args.assemble_only,
                                    sid1_profile=cream_sid1_profile())
            print(json.dumps({"program": result["program"], "duration_s": result["duration_s"],
                              "source_interval_s": result["source_interval_s"],
                              "audio": result.get("audio", {}), "native_verified": "native" in result}, indent=2))
            return
        from cream_playback import run as cream_run
        destination = HERE / "work/cream/linus-mix"
        result = cream_run(args.out or destination, assemble_only=args.assemble_only)
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
