#!/usr/bin/env python3
"""Build Batman's native PAL MCI picture from its unchanged bitmap and ZIP."""

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


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_inputs(source, archive_path):
    image = source.read_bytes()
    if len(image) != 19434 or image[:2] != bytes((0, 0x9c)):
        raise ValueError("Expected an uncompressed 19,434-byte True Paint MCI.")
    if image[1002] != 0 or any(value > 15 for value in image[18434:19434]):
        raise ValueError("Batman requires black background and valid shared Color RAM.")
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        sprites = archive.read("sprites.bin")
    expected_image = {"width": 368, "height": 272, "pixelAspectRatio": [1, 1],
                      "core": {"x": 24, "y": 35, "width": 320, "height": 200}}
    settings = manifest.get("settings", {})
    if (manifest.get("format") != "c64-border-sprites" or manifest.get("version") != 1
            or manifest.get("interlaced") is not True or manifest.get("image") != expected_image):
        raise ValueError("Expected the converter's two-field 368 by 272 PAL border export.")
    if settings.get("vertical", {}).get("xExpanded") is False:
        raise ValueError("Batman requires X-expanded top/bottom sprites; optimized normal-width positions need a dedicated raster schedule.")
    for name in ("vertical", "sides"):
        group = settings.get(name, {})
        if group.get("enabled") is not True or group.get("mode") != "multicolor":
            raise ValueError("Batman requires both multicolor border groups.")
        if type(group.get("colorIndex")) is not int or not 0 <= group["colorIndex"] < 16:
            raise ValueError("Invalid individual sprite color.")
    optimized = settings.get("optimizeColors", False)
    if type(optimized) is not bool:
        raise ValueError("Invalid automatic sprite-color setting.")
    if not optimized and settings["vertical"]["colorIndex"] != settings["sides"]["colorIndex"]:
        raise ValueError("Batman currently uses one individual sprite color for both groups.")
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
    for phase in (0, 1):
        layout = []
        for group in ("top", "bottom"):
            for band in (0, 1):
                for column, slot in enumerate(SLOTS):
                    y = (-7 if group == "top" else 235) + band * 21
                    layout.append((group, band, slot, column * 48 + phase, y, True))
        for group in ("left", "right"):
            for band in range(10):
                last = band == 9
                layout.append((group, band, (3 if group == "left" else 4) + (2 if last else 0),
                               (0 if group == "left" else 344) + phase,
                               35 + (179 if last else band * 21), False))
        for local, (group, band, slot, x, y, expanded) in enumerate(layout):
            index = phase * 52 + local
            record = records[index]
            expected = {"index": index, "field": phase, "group": group, "band": band,
                        "hardwareSlot": slot, "x": x, "y": y, "vicX": x, "vicY": y + 15,
                        "multicolor": True, "mode": "multicolor",
                        "xExpanded": expanded, "yExpanded": False, "displayWidth": 48 if expanded else 24,
                        "displayHeight": 21, "rowHeights": [1] * 21, "byteOffset": index * 64, "byteLength": 64}
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError(f"Invalid native placement or data metadata for sprite {index}.")
            foreground = record.get("colorIndex")
            if type(foreground) is not int or not 0 <= foreground < 16:
                raise ValueError(f"Invalid foreground color for sprite {index}.")
            if not optimized and foreground != settings["vertical"]["colorIndex"]:
                raise ValueError(f"Unexpected manual foreground color for sprite {index}.")
            if phase and foreground != records[local]["colorIndex"]:
                raise ValueError("Sprite foreground colors must match between MCI fields.")
            if expanded and record.get("vicYRegister") != ((y + 15) & 255):
                raise ValueError(f"Invalid wrapped Y register for sprite {index}.")
            clip = {"x": phase if expanded else x,
                    "y": (0 if group == "top" else 235) if expanded else (224 if band == 9 else 35),
                    "width": 368 if expanded else 24,
                    "height": (35 if group == "top" else 37) if expanded else (11 if band == 9 else 200)}
            if record.get("clip") != clip:
                raise ValueError(f"Invalid visible clipping for sprite {index}.")
            data = sprites[index * 64:(index + 1) * 64]
            if data[63] or (not expanded and band == 9 and any(data[:30])):
                raise ValueError(f"Sprite {index} has invalid padding or overlapping spare rows.")
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
    with tempfile.TemporaryDirectory(prefix="c64-batman-") as temporary:
        stage = Path(temporary)
        (stage / "image.mci").write_bytes(image)
        for phase, name in enumerate(("bank-a.bin", "bank-b.bin")):
            (stage / name).write_bytes(bank_bytes(image, sprites, phase))
        settings = manifest["settings"]
        foregrounds = [record["colorIndex"] for record in manifest["sprites"][:52]]
        (stage / "settings.asm").write_text(
            f".const SPRITE_COLOR = {settings['vertical']['colorIndex']}\n"
            f".const SPRITE_SHARED_1 = {settings['multicolorIndices'][0]}\n"
            f".const SPRITE_SHARED_2 = {settings['multicolorIndices'][1]}\n"
            f".var spriteColors = List().add({', '.join(map(str, foregrounds))})\n")
        shutil.copyfile(player, stage / "player.asm")
        output.parent.mkdir(parents=True, exist_ok=True)
        with (output.parent / "assembler.log").open("w") as log:
            subprocess.run([str(args.assembler.expanduser()), "player.asm", "-o", "batman.prg",
                            "-odir", str(stage), "-symbolfile", "-vicesymbols"],
                           cwd=stage, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "ERROR IN ASSERTION" in (output.parent / "assembler.log").read_text().upper():
            raise ValueError("KickAssembler reported a failed assertion; inspect assembler.log.")
        program = (stage / "batman.prg").read_bytes()
        if program[:2] != bytes((1, 8)) or len(program) != 47105:
            raise ValueError("Unexpected Batman load range; expected $0801 through $bfff.")
        receipt = {"format": "Batman standalone PAL MCI with original border sprite bytes",
            "source": str(source), "source_sha256": digest(image),
            "border_archive": str(archive_path), "border_archive_sha256": digest(archive_path.read_bytes()),
            "sprite_bytes_sha256": digest(sprites), "player_sha256": digest(player.read_bytes()),
            "program_sha256": digest(program), "bytes": len(program),
            "display": {"width": 368, "height": 272, "phase_count": 2, "phase_b_offset_pixels": 1,
                        "sprites_per_field": 52, "vertical_sprite_height": 21, "vertical_bands_per_border": 2},
            "sprite_colors": {"shared": settings["multicolorIndices"], "foregrounds": foregrounds,
                              "tied_between_fields": True},
            "memory": {"screen_a": "$4000", "screen_b": "$c000", "tail_screen_a": "$4400", "tail_screen_b": "$c400",
                       "bottom_second_a": "$5800", "bottom_second_b": "$d800", "top_second_a": "$5c00", "top_second_b": "$dc00",
                       "sprites_a": "$4800", "sprites_b": "$c800", "bitmap_a": "$6000", "bitmap_b": "$e000",
                       "color_ram": "$d800", "phase_b_staging": "$8000", "irq_trampolines": "$00c0/$00c3/$00c6", "side_hardware_slots": [1, 2], "final_side_hardware_slots": [3, 4], "spare_hardware_slots": [5, 6]}}
        payloads = (program, (stage / "player.sym").read_bytes(), (stage / "player.vs").read_bytes(),
                    (json.dumps(receipt, indent=2) + "\n").encode())
        for target, payload in zip(targets, payloads):
            with target.open("wb" if args.force else "xb") as stream:
                stream.write(payload)
    print(f"Created {output} ({len(program):,} bytes; SHA256 {digest(program)})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mci", type=Path, default=ROOT / "assets/batman.mci")
    parser.add_argument("--sprites", type=Path, default=ROOT / "assets/batman-optimized-sprites.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "build/batman.prg")
    parser.add_argument("--assembler", type=Path, default=Path.home() / ".local/bin/kickass")
    parser.add_argument("--force", action="store_true")
    build(parser.parse_args())
