#!/usr/bin/env python3
"""Build Lillen's native PAL MCI picture from its unchanged bitmap and ZIP.

The raster schedule is specific to the supplied lillen2 export. Bitmap and
sprite bytes are copied verbatim into the two VIC banks.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SLOTS = (3, 0, 1, 2, 5, 6, 7, 4)
TOP_BAND_VIC_Y = (8, 29)
BOTTOM_BAND_VIC_Y = (250, 271)
SIDE_BANDS = 10
SIDE_VIC_Y = [50 + band * 21 for band in range(SIDE_BANDS - 1)] + [229]
SIDE_LEFT_SLOT = 3
SIDE_RIGHT_SLOT = 4
SIDE_SPARE_LEFT_SLOT = 5
SIDE_SPARE_RIGHT_SLOT = 6
PHASE_OFFSET = 1
HANDOFF_LAYOUT_SHA256 = "7200adf0adf16833302b22069cfc3c980fc79ecc2e308808dc25ad3133b49385"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_inputs(source, archive_path):
    image = source.read_bytes()
    if len(image) != 19434 or image[:2] != bytes((0, 0x9C)):
        raise ValueError("Expected an uncompressed 19,434-byte True Paint MCI.")
    if image[1002] != 0 or any(value > 15 for value in image[18434:19434]):
        raise ValueError("Lillen requires black background and valid shared Color RAM.")
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        sprites = archive.read("sprites.bin")
    expected_image = {"width": 368, "height": 272, "pixelAspectRatio": [1, 1],
                      "core": {"x": 24, "y": 35, "width": 320, "height": 200}}
    settings = manifest.get("settings", {})
    if (manifest.get("format") != "c64-border-sprites" or manifest.get("version") != 1
            or manifest.get("interlaced") is not True or manifest.get("image") != expected_image):
        raise ValueError("Expected the converter's two-field 368 by 272 PAL border export.")
    for name in ("vertical", "sides"):
        group = settings.get(name, {})
        if group.get("enabled") is not True or group.get("mode") != "multicolor":
            raise ValueError("Lillen requires both multicolor border groups.")
    if settings.get("vertical", {}).get("xExpanded") is not False:
        raise ValueError("Lillen requires the optimized normal-width vertical export.")
    shared = settings.get("multicolorIndices")
    if not isinstance(shared, list) or len(shared) != 2 or any(type(value) is not int or not 0 <= value < 16 for value in shared):
        raise ValueError("Expected two shared C64 sprite colors.")
    hardware = manifest.get("hardware", {})
    if hardware.get("backgroundColorRegister") != 0 or hardware.get("sharedMulticolorRegisters") != shared:
        raise ValueError("Border and bitmap register colors disagree.")
    fields = manifest.get("fields")
    records = manifest.get("sprites")
    if not isinstance(records, list) or len(records) != 104 or len(sprites) != 6656:
        raise ValueError("Expected exactly 104 native 64-byte sprite frames.")
    expected_fields = [{"phase": phase, "offsetX": phase, "spriteOffset": phase * 52,
                        "spriteCount": 52, "byteOffset": phase * 3328, "byteLength": 3328}
                       for phase in (0, 1)]
    if fields != expected_fields:
        raise ValueError("Invalid MCI sprite phase offsets or frame boundaries.")

    layout = []
    for group, vic_y in (("top", TOP_BAND_VIC_Y), ("bottom", BOTTOM_BAND_VIC_Y)):
        for band in (0, 1):
            for slot in SLOTS:
                layout.append((group, band, slot, vic_y[band]))
    for side in ("left", "right"):
        for band in range(SIDE_BANDS):
            slot = (SIDE_SPARE_LEFT_SLOT if side == "left" else SIDE_SPARE_RIGHT_SLOT) if band == SIDE_BANDS - 1 \
                else (SIDE_LEFT_SLOT if side == "left" else SIDE_RIGHT_SLOT)
            layout.append((side, band, slot, SIDE_VIC_Y[band]))

    for phase in (0, 1):
        for local, (group, band, slot, vic_y) in enumerate(layout):
            index = phase * 52 + local
            record = records[index]
            expected = {"index": index, "field": phase, "group": group, "band": band,
                        "hardwareSlot": slot, "vicY": vic_y, "multicolor": True,
                        "mode": "multicolor", "xExpanded": False, "yExpanded": False,
                        "displayWidth": 24, "displayHeight": 21,
                        "byteOffset": index * 64, "byteLength": 64}
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError(f"Invalid native placement or data metadata for sprite {index}.")
            if group in ("top", "bottom") and record.get("vicYRegister") != vic_y & 255:
                raise ValueError(f"Invalid wrapped Y register for sprite {index}.")
            color = record.get("colorIndex")
            if type(color) is not int or not 0 <= color < 16:
                raise ValueError(f"Invalid foreground color for sprite {index}.")
            if phase and record["x"] != records[local]["x"] + PHASE_OFFSET:
                raise ValueError("Sprite X must shift exactly one pixel between MCI fields.")
            if phase and color != records[local]["colorIndex"]:
                raise ValueError("Sprite foreground colors must match between MCI fields.")
            if group == "left" and record["x"] != phase:
                raise ValueError(f"Invalid left side X for sprite {index}.")
            if group == "right" and record["x"] != 344 + phase:
                raise ValueError(f"Invalid right side X for sprite {index}.")
            data = sprites[index * 64:(index + 1) * 64]
            if data[63] or (group in ("left", "right") and band == SIDE_BANDS - 1 and any(data[:30])):
                raise ValueError(f"Sprite {index} has invalid padding or overlapping spare rows.")
    # Handoff slots were timed against these X positions, color changes and
    # transparent rows. Repacking the ZIP does not change those constraints.
    layout_bytes = json.dumps([(record["x"], record["colorIndex"]) for record in records],
                              separators=(",", ":")).encode()
    if digest(sprites + layout_bytes) != HANDOFF_LAYOUT_SHA256:
        raise ValueError("This raster schedule requires the original lillen2 sprite bytes, positions and foregrounds.")
    return image, sprites, manifest


def bank_bytes(image, sprites, phase):
    bank = bytearray(0x4000)
    screen = image[2:1002] if phase == 0 else image[17410:18410]
    for address in (0, 0x400, 0x1800, 0x1c00):
        bank[address:address + 1000] = screen
    bank[0x800:0x1500] = sprites[phase * 3328:(phase + 1) * 3328]
    bank[0x2000:0x3f40] = image[1026:9026] if phase == 0 else image[9218:17218]
    def row_pointers(offset):
        pointers = bytearray(8)
        for column, slot in enumerate(SLOTS):
            pointers[slot] = 0x20 + offset + column
        return pointers
    bank[0x3f8:0x400] = row_pointers(0)
    bank[0x7f8:0x800] = bytes((0, 0x45, 0x4f, 0, 0, 0x49, 0x53, 0))
    bank[0x1bf8:0x1c00] = row_pointers(24)
    bank[0x1ff8:0x2000] = row_pointers(8)
    return bytes(bank)


def settings_asm(manifest):
    records = manifest["sprites"][:52]
    shared = manifest["settings"]["multicolorIndices"]
    lines = [
        f".const SPRITE_SHARED_1 = {shared[0]}",
        f".const SPRITE_SHARED_2 = {shared[1]}",
        f".var spriteColors = List().add({', '.join(str(record['colorIndex']) for record in records)})",
    ]
    for row, name in enumerate(("topFirstX", "topSecondX", "bottomFirstX", "bottomSecondX")):
        positions = [0] * 8
        for record in records[8 * row:8 * (row + 1)]:
            positions[record["hardwareSlot"]] = record["x"]
        lines.append(f".var {name} = List().add({', '.join(map(str, positions))})")
    return "\n".join(lines) + "\n"


def build(args):
    source, archive_path, output = args.mci.resolve(), args.sprites.resolve(), args.output.resolve()
    targets = (output, output.with_suffix(".sym"), output.with_suffix(".vs"), output.with_suffix(".build.json"))
    if len(set(targets)) != len(targets) or output.suffix != ".prg":
        raise ValueError("Use a .prg output path.")
    protected = {source, archive_path, source.with_suffix(".json")}
    for target in targets:
        if target in protected:
            raise ValueError("Build artifacts must not overwrite a supplied asset.")
        if target.exists() and not args.force:
            raise FileExistsError(f"Refusing to replace {target}; use --force for build artifacts.")
    image, sprites, manifest = read_inputs(source, archive_path)
    player = ROOT / "src/player.asm"
    with tempfile.TemporaryDirectory(prefix="c64-lillen-") as temporary:
        stage = Path(temporary)
        (stage / "image.mci").write_bytes(image)
        for phase, name in enumerate(("bank-a.bin", "bank-b.bin")):
            (stage / name).write_bytes(bank_bytes(image, sprites, phase))
        (stage / "settings.asm").write_text(settings_asm(manifest))
        shutil.copyfile(player, stage / "player.asm")
        output.parent.mkdir(parents=True, exist_ok=True)
        with (output.parent / "assembler.log").open("w") as log:
            subprocess.run([str(args.assembler.expanduser()), "player.asm", "-o", output.stem + ".prg",
                            "-odir", str(stage), "-symbolfile", "-vicesymbols"],
                           cwd=stage, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "ERROR IN ASSERTION" in (output.parent / "assembler.log").read_text().upper():
            raise ValueError("KickAssembler reported a failed assertion; inspect assembler.log.")
        program = (stage / (output.stem + ".prg")).read_bytes()
        if program[:2] != bytes((1, 8)) or len(program) != 0xC000 - 0x0801 + 2:
            raise ValueError("Unexpected Lillen load range; expected $0801 through $bfff.")
        receipt = {"format": "Lillen standalone PAL MCI with original border sprite bytes",
            "source": str(source), "source_sha256": digest(image),
            "border_archive": str(archive_path), "border_archive_sha256": digest(archive_path.read_bytes()),
            "sprite_bytes_sha256": digest(sprites), "player_sha256": digest(player.read_bytes()),
            "program_sha256": digest(program), "bytes": len(program),
            "display": {"width": 368, "height": 272, "phase_count": 2, "phase_b_offset_pixels": 1,
                        "sprites_per_field": 52, "vertical_sprite_height": 21,
                        "vertical_bands_per_border": 2, "vertical_x_expanded": False,
                        "side_bands_per_side": 10},
            "memory": {"screen_a": "$4000", "screen_b": "$c000", "second_top_a": "$5c00",
                       "second_top_b": "$dc00", "second_bottom_a": "$5800", "second_bottom_b": "$d800",
                       "sprites_a": "$4800", "sprites_b": "$c800", "bitmap_a": "$6000", "bitmap_b": "$e000",
                       "color_ram": "$d800", "phase_b_staging": "$8000",
                       "irq_trampolines": "$00c0/$00c3/$00c6", "side_hardware_slots": [1, 2],
                       "final_side_hardware_slots": [3, 4], "spare_hardware_slots": [5, 6]}}
        payloads = (program, (stage / "player.sym").read_bytes(), (stage / "player.vs").read_bytes(),
                    (json.dumps(receipt, indent=2) + "\n").encode())
        for target, payload in zip(targets, payloads):
            with target.open("wb" if args.force else "xb") as stream:
                stream.write(payload)
    print(f"Created {output} ({len(program):,} bytes; SHA256 {digest(program)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mci", type=Path, default=ROOT.parent / "images/borders/lillen2.mci")
    parser.add_argument("--sprites", type=Path, default=ROOT.parent / "images/borders/lillen2.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "build/lillen2/lillen2.prg")
    parser.add_argument("--assembler", type=Path, default=Path.home() / ".local/bin/kickass")
    parser.add_argument("--force", action="store_true")
    build(parser.parse_args())
