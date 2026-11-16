#!/usr/bin/env python3
"""Build a standalone PAL C64 display from an uncompressed True Paint MCI."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def build(source, output, assembler, force=False, wave=False, borders=False):
    if wave and borders:
        raise ValueError("Choose either the rubber wave or the open-border test.")
    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise ValueError("The output must not replace the source MCI file.")
    data = source.read_bytes()
    if len(data) != 19434 or data[:2] != b"\x00\x9c":
        raise ValueError("Expected a 19,434-byte uncompressed True Paint MCI loading at $9c00.")
    if data[1002] > 15 or any(color > 15 for color in data[18434:19434]):
        raise ValueError("MCI background and shared color RAM must use C64 color indices 0–15.")
    targets = [output, output.with_suffix(".sym"), output.with_suffix(".vs"),
               output.with_suffix(".json")]
    if len(set(targets)) != len(targets):
        raise ValueError("Use a .prg extension for the output.")
    for target in targets:
        if target == source:
            raise ValueError("Build artifacts must not replace the source MCI file.")
        if target.exists() and not force:
            raise FileExistsError(f"Refusing to replace {target}; use --force to replace build artifacts.")

    player_name = "border-player.asm" if borders else "wave-player.asm" if wave else "player.asm"
    player = Path(__file__).with_name(player_name)
    with tempfile.TemporaryDirectory(prefix="c64-mci-") as temporary:
        stage = Path(temporary)
        (stage / "image.mci").write_bytes(data)
        shutil.copyfile(player, stage / "player.asm")
        subprocess.run([str(assembler.expanduser()), "player.asm", "-o", "image.prg",
                        "-odir", str(stage), "-symbolfile", "-vicesymbols"],
                       cwd=stage, check=True)
        program = (stage / "image.prg").read_bytes()
        if program[:2] != b"\x01\x08" or len(program) != 46913:
            raise ValueError("Unexpected standalone MCI PRG layout.")
        receipt = {
            "format": "standalone PAL C64 MCI PRG",
            "source": str(source),
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "program_sha256": hashlib.sha256(program).hexdigest(),
            "player_sha256": hashlib.sha256(player.read_bytes()).hexdigest(),
            "bytes": len(program),
            "display": {"width": 320, "height": 200, "phase_count": 2,
                        "phase_b_offset_pixels": 1, "phase_rate": "one phase per PAL video frame"},
            "memory": {"screen_a": "$4000", "bitmap_a": "$6000",
                       "screen_b": "$8000", "bitmap_b": "$a000", "color_ram": "$d800"},
        }
        if wave:
            receipt["effect"] = {
                "name": "vertical rubber wave",
                "method": "extra early badlines repeat row zero of each eight-line cell",
                "motion_rate": "one update per MCI phase pair",
                "maximum_extra_lines_per_cell": 4,
                "amplitude_step_phase_pairs": 64,
                "crop": "normal 200-line viewport clips the stretched picture at the bottom",
            }
        if borders:
            receipt["effect"] = {
                "name": "PAL open-border checker sprites",
                "bitmap": "original 320x200 MCI picture with its original phase offset",
                "top_bottom_sprite_count": 8,
                "horizontal_sprite_expansion": 2,
                "side_sprite_slots": [3, 4],
                "placeholder": "checkerboard sprites multiplexed around the picture",
                "extent": "PAL border area; sprite coverage is measured separately in native VICE",
                "audio": "none; standalone graphics test",
            }
        payloads = [program, (stage / "player.sym").read_bytes(),
                    (stage / "player.vs").read_bytes(),
                    (json.dumps(receipt, indent=2) + "\n").encode()]
        output.parent.mkdir(parents=True, exist_ok=True)
        for target, payload in zip(targets, payloads):
            with target.open("wb" if force else "xb") as stream:
                stream.write(payload)
    print(f"Created {output} ({len(program):,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assembler", type=Path, default=Path.home() / ".local/bin/kickass")
    parser.add_argument("--force", action="store_true", help="replace existing build artifacts")
    effect = parser.add_mutually_exclusive_group()
    effect.add_argument("--wave", action="store_true", help="add a growing vertical rubber wave")
    effect.add_argument("--borders", action="store_true", help="test open PAL borders with checkerboard sprites")
    args = parser.parse_args()
    build(args.source, args.output, args.assembler, args.force, args.wave, args.borders)
