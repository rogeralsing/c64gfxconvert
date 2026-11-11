"""Regenerate the three verified full-song PRGs from checked MOD sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from contextual_banks import combine
from fetch_sources import fetch_sources
from pcm4_build import build
from pcm4_prepare import prepare


HERE = Path(__file__).resolve().parent
EXPECTED = {
    "stardust-memories": "ee0b7514369a9e1d55a4523500d21c87d901a76b92a65c3d18b988b379e0e29b",
    "hyperbased": "0434f8171b94a1c6f44d9923b2143fc91b8688443061f5db3b49090297a4a980",
    "4mats-madness": "3961595a2efa07e0338f058dd7d56ae1006aac6210aed397c104e0884f590df6",
}


def set_gain(path: Path, value: float) -> None:
    arrangement = json.loads(path.read_text())
    arrangement["mixing"]["output_gain"] = value
    path.write_text(json.dumps(arrangement, separators=(",", ":")) + "\n")


def build_release(out: Path) -> dict:
    sources = fetch_sources()
    out = out.resolve()
    players = out / "players"
    players.mkdir(parents=True, exist_ok=True)
    records = []
    for name, expected in EXPECTED.items():
        folder = out / name
        source = HERE / "sources" / f"{name}.mod"
        if name == "4mats-madness":
            fallback, preferred = folder / "fallback", folder / "preferred"
            prepare(source, fallback, bank_scope="score")
            prepare(source, preferred, seconds=50, bank_scope="score")
            set_gain(preferred / "arrangement.json", 3.0)
            result = combine(fallback / "arrangement.json", preferred / "arrangement.json", folder / "contextual")
            if result["preferred_prefix_dac_mismatches"]:
                raise ValueError("Madness no longer preserves its preferred short score")
            arrangement = folder / "contextual/arrangement.json"
        else:
            prepare(source, folder)
            arrangement = folder / "arrangement.json"
            if name == "hyperbased":
                set_gain(arrangement, 3.0)
        built = build(arrangement, folder / "c64", score_codec="dictionary8")
        program = Path(built["program"])
        digest = hashlib.sha256(program.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"Release program changed for {name}: {digest}; expected {expected}")
        target = players / f"{name}-full.prg"
        shutil.copyfile(program, target)
        records.append({"song": name, "program": target.relative_to(out).as_posix(),
                        "bytes": target.stat().st_size, "sha256": digest,
                        "duration_s": built["duration_s"], "ticks": built["ticks"],
                        "program_end": built["program_end"], "matches_verified_release": True})
        print(f"Verified {name}: {records[-1]['bytes']} bytes", flush=True)
    manifest = {"status": "all_release_programs_reproduced", "sources": sources,
                "programs": records,
                "scope": "Complete PRG hashes match the previously verified PAL/6581 release. Generated build inputs contain local paths and are recreated on each checkout."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/rebuild")
    args = parser.parse_args()
    print(json.dumps(build_release(args.out), indent=2))


if __name__ == "__main__":
    main()
