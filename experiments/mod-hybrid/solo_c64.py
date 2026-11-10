"""Build one isolated C64 playback for each original MOD track.

The selected track keeps its current v2 arrangement unchanged. Other tracks
retain their score and cursor history but have zero volume. This is an
audition tool, not another instrument-fitting or mix revision.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def prepare(source: Path, out: Path) -> dict:
    arrangement = json.loads(source.read_text())
    if len(arrangement["ticks"][0]["sid"]) != 3 or len(arrangement["ticks"][0]["pcm"]) != 1:
        raise ValueError("Solo audition expects the current three-SID, one-PCM arrangement")
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for track in range(1, 5):
        solo = copy.deepcopy(arrangement)
        for tick in solo["ticks"]:
            for index, state in enumerate(tick["sid"]):
                if track != index + 2:
                    state["volume"] = 0
            if track != 1:
                tick["pcm"][0]["volume"] = 0
        solo["isolation"] = {"original_mod_track_1_based": track,
                             "selected_hardware_voice": "PCM 1" if track == 1 else f"SID {track - 1}",
                             "method": "Zero other tracks' volumes; preserve all selected-track values, oscillator and sample-cursor history.",
                             "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        folder = out / f"track-{track}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "arrangement.json"
        path.write_text(json.dumps(solo, separators=(",", ":")) + "\n")
        command = [sys.executable, str(Path(__file__).with_name("build_c64.py")),
                   "--input", str(path), "--out", str(folder / "c64")]
        result = subprocess.run(command, text=True, capture_output=True, timeout=60)
        (folder / "build-driver.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"Solo {track} build failed; inspect {folder / 'build-driver.log'}")
        records.append({"track": track, "arrangement": str(path.resolve()),
                        "program": str((folder / "c64/stardust.prg").resolve()),
                        "symbols": str((folder / "c64/stardust.sym").resolve()),
                        "capture_out": str((folder / "vice").resolve())})
        print(f"C64 solo track {track} built", flush=True)
    receipt = {"source": str(source.resolve()), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "duration_s": arrangement["duration_s"], "preview_start_s": 30,
               "preview_duration_s": 20, "tracks": records,
               "scope": "Independent solo playbacks. Shared D418 and SID analog behavior mean their sum need not equal the full mix."}
    (out / "solos.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=here / "results/melody-v2/short/arrangement.json")
    parser.add_argument("--out", type=Path, default=here / "results/channel-solos/c64")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.out), indent=2))


if __name__ == "__main__":
    main()
