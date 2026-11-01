#!/usr/bin/env python3
"""Compare layered FLI or AFLI/sprite PAL captures with exact exported ZIP pixels."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import zipfile

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sha = lambda data: hashlib.sha256(data).hexdigest()


def verify(run, source, split_y):
    run, source = run.resolve(), source.resolve()
    capture = json.loads((run / "capture.json").read_text())
    with zipfile.ZipFile(source) as archive:
        assert archive.testzip() is None, "ZIP CRC mismatch"
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] in {"c64-afli-sprite-layers", "c64-fli-sprite-layers"} and manifest["version"] == 1
        multicolor = manifest["format"] == "c64-fli-sprite-layers"
        if multicolor:
            screens = archive.read(manifest["files"]["screen"])
            bitmap = archive.read(manifest["files"]["bitmap"])
            color_ram = archive.read(manifest["files"]["colorRam"])
            assert len(screens) == 8192 and len(bitmap) == 8000 and len(color_ram) == 1000
            assert all(value < 16 for value in color_ram)
            image = bytes([0, 64]) + screens + bitmap + bytes(191)
            background = manifest["backgroundColor"]["index"]
            assert type(background) is int and 0 <= background < 16
            assert manifest["image"] == {"width": 160, "height": 200, "pixelAspectRatio": [2, 1]}
            assert manifest["canvas"]["width"] == 320 and manifest["canvas"]["height"] == 200
        else:
            image = archive.read(manifest["files"]["afli"])
        mask = archive.read(manifest["files"]["spriteMask"])
    assert len(image) == 16385 and image[:2] == bytes([0, 64]), "Invalid AFLI payload"
    assert len(mask) == 4800 and manifest["mask"]["bitOrder"] == "msb-first", "Invalid sprite raster mask"
    valid_rect = manifest["layout"].get("fliValidRect", manifest["layout"].get("afliValidRect"))
    assert valid_rect == {"x": 112, "y": 0, "width": 208, "height": 200}
    assert manifest["layout"]["spriteRect"] == {"x": 112, "y": 0, "width": 192, "height": 200}
    sprite_color = manifest["spriteColor"]["index"]
    assert isinstance(sprite_color, int) and 0 <= sprite_color < 16
    palette_text = (ROOT / "index.html").read_text().split("const C64_PALETTE = [", 1)[1].split("];", 1)[0]
    colors = re.findall(r"index:\s*(\d+).*?rgb:\s*\[(\d+),\s*(\d+),\s*(\d+)\]", palette_text)
    palette = {int(index): tuple(map(int, (r, g, b))) for index, r, g, b in colors}
    assert len(palette) == 16 and tuple(manifest["spriteColor"]["rgb"]) == palette[sprite_color]
    underlay = bytearray(64000)
    for y in range(200):
        row = y & 7
        for column in range(40):
            tile = (y >> 3) * 40 + column
            screen = image[2 + row * 1024 + tile]
            bits = image[0x2002 + tile * 8 + row]
            if multicolor:
                choices = [background, screen >> 4, screen & 15, color_ram[tile]]
                for pixel in range(4):
                    color = choices[(bits >> (6 - pixel * 2)) & 3]
                    offset = y * 320 + column * 8 + pixel * 2
                    underlay[offset:offset + 2] = bytes([color, color])
            else:
                for bit in range(8):
                    underlay[y * 320 + column * 8 + bit] = screen >> 4 if bits & (128 >> bit) else screen & 15
    composite = bytearray(underlay)
    opaque = bytearray(64000)
    for y in range(200):
        for x in range(192):
            if mask[y * 24 + (x >> 3)] & (128 >> (x & 7)):
                pixel = y * 320 + 112 + x
                composite[pixel] = sprite_color
                opaque[pixel] = 1
    expected = bytes(composite[y * 320 + x] for y in range(200) for x in range(112, 320))
    expected_opaque = bytes(opaque[y * 320 + x] for y in range(200) for x in range(112, 320))
    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(capture["source_sha256"] == sha(source.read_bytes()), "Capture source ZIP differs")
    check(capture["program_sha256"] == sha(Path(capture["program"]).read_bytes()), "Program changed after capture")
    check(capture["pal"] and capture["speed_percent"] == 100 and not capture["warp"] and capture["vsync"],
          "Capture settings are not PAL100%, warp off, vsync on")
    calibrated = json.loads((ROOT / "afli-viewer/validation/vice-palette-reference.json").read_text())["mapping"]
    vice_palette = {tuple(map(int, rgb.split(","))): index for rgb, index in calibrated.items()}
    known_capture_rgb = {index: rgb for rgb, index in vice_palette.items()}
    rows, counters, hashes = [], [], []
    samples = capture["samples"]
    check(len(samples) >= 3, "Fewer than three captures")
    for number, sample in enumerate(samples, 1):
        screenshot = Path(sample["screenshot"])
        actual_image = Image.open(screenshot).convert("RGB")
        check(actual_image.size == (384, 272), f"Capture {number} dimensions differ")
        hashes.append(sha(screenshot.read_bytes()))
        check(hashes[-1] == sample["sha256"], f"Capture {number} PNG changed")
        counter = (run / f"frame-counter-{number}.bin").read_bytes()
        check(len(counter) == 1 and counter[0] == sample["frame_counter"], f"Capture {number} frame counter differs")
        counters.append(sample["frame_counter"])
        actual = [vice_palette.get(actual_image.getpixel((32 + x, 32 + y)), -1)
                  for y in range(200) for x in range(112, 320)]
        wrong = [pixel for pixel, (a, e) in enumerate(zip(actual, expected)) if a != e]
        check(not wrong, f"Capture {number}: {len(wrong)} image pixel mismatches")
        bottom = [(x, y) for y in range(232, 272) for x in range(384)
                  if actual_image.getpixel((x, y)) != (0, 0, 0)]
        check(not bottom, f"Capture {number}: {len(bottom)} nonblack bottom pixels")
        registers = {}
        for line in sample["vic"].splitlines():
            match = re.match(r">C:([0-9a-fA-F]{4})\s+(.*)", line)
            if match:
                values = match[2].split()[:16]
                if len(values) == 16 and all(re.fullmatch(r"[0-9a-fA-F]{2}", value) for value in values):
                    registers.update({int(match[1], 16) + offset: int(value, 16) for offset, value in enumerate(values)})
        check(registers.get(0xd015) == 255 and registers.get(0xd010) == 224,
              f"Capture {number}: sprite enable or X-MSB mismatch")
        check(all(registers.get(address) == 0 for address in [0xd017, 0xd01b, 0xd01c, 0xd01d]),
              f"Capture {number}: sprite expansion, priority, or hires mode mismatch")
        check(all(registers.get(0xd027 + sprite, -1) & 15 == sprite_color for sprite in range(8)),
              f"Capture {number}: selected sprite color mismatch")
        check(registers.get(0xd016, -1) & 0x1f == (0x18 if multicolor else 0x08),
              f"Capture {number}: bitmap multicolor or X-scroll mismatch")
        if multicolor:
            check(registers.get(0xd021, -1) & 15 == background,
                  f"Capture {number}: selected background color mismatch")
        rows.append({
            "screenshot": str(screenshot), "sha256": hashes[-1], "frame_counter": counters[-1],
            "pixels_compared": 41600, "sprite_pixels": sum(expected_opaque),
            "underlay_pixels": 41600 - sum(expected_opaque), "mismatches": len(wrong),
            "sprite_mismatches": sum(expected_opaque[pixel] for pixel in wrong),
            "row_mismatches": dict(Counter(pixel // 208 for pixel in wrong)),
            "first_mismatches": [{"x": 112 + pixel % 208, "y": pixel // 208,
                                  "expected": expected[pixel], "actual": actual[pixel]} for pixel in wrong[:32]],
            "bottom_pixels_compared": 15360, "bottom_nonblack_pixels": len(bottom),
            "bottom_nonblack_by_row": dict(Counter(y for x, y in bottom)),
        })
    advances = [(second - first) % 256 for first, second in zip(counters, counters[1:])]
    check(all(0 < advance < 128 for advance in advances), "Frame counter did not advance unambiguously")
    check(len(set(hashes)) == 1, "Raw capture PNG hashes differ")
    # Preserve only the bank's declared visible half. The opposite bitmap half,
    # fourteen reserved character columns, and matrix tails may store sprites.
    ram = []
    for name, base in [("bank-a.bin", 0x4000), ("bank-b.bin", 0xc000)]:
        bank_path = run / name
        if not bank_path.exists():
            continue
        bank = bank_path.read_bytes()
        check(len(bank) == 16384, f"{name}: incomplete RAM dump")
        bank_rows = range(split_y) if base == 0x4000 else range(split_y, 200)
        visible_offsets = []
        for y in bank_rows:
            for column in range(14, 40):
                tile = (y >> 3) * 40 + column
                visible_offsets.append((y & 7) * 1024 + tile)
                visible_offsets.append(8192 + tile * 8 + (y & 7))
        # A bitmap byte encodes eight pixels; each visible source column above
        # contributes one byte, just as each screen byte defines its color pair.
        wrong = [offset for offset in visible_offsets if bank[offset] != image[2 + offset]]
        check(not wrong, f"{name}: {len(wrong)} visible {'FLI' if multicolor else 'AFLI'} RAM bytes differ")
        ram.append({"file": str(bank_path), "visible_source_y": [0, split_y] if base == 0x4000 else [split_y, 200],
                    "bytes_compared": len(visible_offsets), "mismatches": len(wrong),
                    "first_mismatches": [f"${base + offset:04x}" for offset in wrong[:32]]})
    color_report = None
    if multicolor:
        color_path = run / "color-ram.bin"
        check(color_path.is_file(), "Missing Color RAM capture")
        if color_path.is_file():
            actual_color = color_path.read_bytes()
            check(len(actual_color) == 1000, "Incomplete Color RAM capture")
            wrong = [index for index, value in enumerate(actual_color) if value & 15 != color_ram[index]]
            check(not wrong, f"{len(wrong)} Color RAM bytes differ")
            color_report = {"file": str(color_path), "bytes_compared": len(actual_color),
                            "mismatches": len(wrong), "first_mismatches": wrong[:32]}
    report = {
        "pass": not failures, "failures": failures, "source": str(source), "source_sha256": sha(source.read_bytes()),
        "program": capture["program"], "program_sha256": capture["program_sha256"],
        "sprite_color": manifest["spriteColor"], "sprite_pixels": sum(opaque),
        "source_mode": "fli" if multicolor else "afli",
        "background_color": manifest.get("backgroundColor") if multicolor else None,
        "color_ram": color_report,
        "contract": {"source_rect": [112, 0, 320, 200], "image_origin": [32, 32],
                     "sprite_rect": [112, 0, 304, 200], "black_bottom_rect": [0, 232, 384, 272],
                     "vic_bank_split_y": split_y},
        "expected_composite_indices_sha256": sha(composite), "ram": ram, "samples": rows,
        "counter_advances": advances, "identical_raw_capture_hashes": len(set(hashes)) == 1,
        "evidence_limit": "Three advancing normal-speed PAL captures; not a claim of indefinite stability",
    }
    target = run / "layer-verification.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    # Keep actual emulator pixels, including VICE's palette, for the deliverable.
    actual_image = Image.open(samples[0]["screenshot"]).convert("RGB")
    actual_image.crop((144, 32, 352, 232)).resize((624, 600), Image.Resampling.NEAREST).save(run / "actual-composite.png")
    expected_rgb = bytes(channel for index in expected for channel in known_capture_rgb[index])
    Image.frombytes("RGB", (208, 200), expected_rgb).save(run / "expected-vice-composite.png")
    print(json.dumps({"pass": report["pass"], "report": str(target), "failures": failures,
                      "pixel_mismatches": [row["mismatches"] for row in rows],
                      "bottom_nonblack_pixels": [row["bottom_nonblack_pixels"] for row in rows],
                      "ram_mismatches": [bank["mismatches"] for bank in ram],
                      "counter_advances": advances, "actual_composite": str(run / "actual-composite.png")}, indent=2))
    return report["pass"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("source", type=Path, help="Exact exported layer ZIP")
    parser.add_argument("--split-y", type=int, default=87,
                        help="Source row where display switches from bank $4000 to $C000 (default: 87)")
    arguments = parser.parse_args()
    if not 0 <= arguments.split_y <= 200:
        parser.error("Bank split row must be 0..200.")
    raise SystemExit(0 if verify(arguments.run, arguments.source, arguments.split_y) else 1)
