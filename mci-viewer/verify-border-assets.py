#!/usr/bin/env python3
"""Compare native PAL fields against the original MCI and exported sprite bytes.

The reference decodes both file formats independently. VICE supplies complete
VIC-II screenshots and RAM; the monitor never writes to the running C64.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import zipfile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mydemo/discoball"))
from vice_support import Monitor, connect_monitor, read_labels, vice_command

PAL_CYCLES = 19656
BITMAP_BOX = (32, 35, 352, 235)
SIDE_VIEWPORT = (8, 35, 376, 235)
FULL_BOX = (0, 0, 384, 272)
SIDE_SLOTS = (3, 4, 5, 6)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def breakpoint(monitor, address):
    response = monitor.run(f"break ${address:04x}")
    match = re.search(r"BREAK:\s*(\d+)", response)
    assert match, response
    return int(match[1])


def registers(monitor):
    response = monitor.run("r")
    match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
    assert match, response
    values = match[2].split()
    return int(match[1], 16), int(values[-3]), int(values[-2]), int(values[-1])


class Reference:
    """True Paint bitmap planes plus the VIC's native sprite bit encoding."""

    def __init__(self, source, border_sprites, palette):
        self.source_path = source.resolve()
        self.archive_path = border_sprites.resolve()
        self.source = self.source_path.read_bytes()
        assert len(self.source) == 19434 and self.source[:2] == b"\x00\x9c", "Expected a True Paint MCI file"
        self.screens = (self.source[2:1002], self.source[17410:18410])
        self.bitmaps = (self.source[1026:9026], self.source[9218:17218])
        self.colors = self.source[18434:19434]
        self.background = self.source[1002]
        assert self.background < 16 and all(color < 16 for color in self.colors)
        with zipfile.ZipFile(self.archive_path) as archive:
            self.manifest = json.loads(archive.read("manifest.json"))
            self.sprite_bytes = archive.read("sprites.bin")
        manifest = self.manifest
        assert manifest["format"] == "c64-border-sprites" and manifest["version"] == 1
        assert manifest["interlaced"] is True
        assert manifest["image"] == {
            "width": 368, "height": 200, "pixelAspectRatio": [1, 1],
            "core": {"x": 24, "y": 0, "width": 320, "height": 200}
        }, "This verifier covers the normal-height side-border layout"
        settings = manifest["settings"]
        assert not settings["vertical"]["enabled"] and settings["sides"]["enabled"]
        assert settings["sides"]["mode"] == "multicolor"
        self.foreground = settings["sides"]["colorIndex"]
        self.multicolors = settings["multicolorIndices"]
        assert len(self.multicolors) == 2
        assert all(isinstance(color, int) and 0 <= color < 16 for color in [self.foreground, *self.multicolors])
        assert manifest["hardware"]["backgroundColorRegister"] == self.background
        self.palette = [tuple(int(value, 16) for value in line.split()[:3])
                        for line in palette.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        assert len(self.palette) == 16
        assert len(self.sprite_bytes) == 2 * 20 * 64
        assert len(manifest["sprites"]) == 40
        assert [(field["phase"], field["offsetX"], field["spriteCount"], field["byteOffset"], field["byteLength"])
                for field in manifest["fields"]] == [(0, 0, 20, 0, 1280), (1, 1, 20, 1280, 1280)]
        self.sprites = []
        for phase in (0, 1):
            sprites = [sprite for sprite in manifest["sprites"] if sprite["field"] == phase]
            assert len(sprites) == 20
            assert {(sprite["group"], sprite["band"]) for sprite in sprites} == {
                (group, band) for group in ("left", "right") for band in range(10)
            }
            for sprite in sprites:
                group, band = sprite["group"], sprite["band"]
                last = band == 9
                x = (0 if group == "left" else 344) + phase
                y = 179 if last else band * 21
                expected_slot = (3 if group == "left" else 4) + (2 if last else 0)
                assert (sprite["x"], sprite["y"], sprite["vicX"], sprite["vicY"], sprite["hardwareSlot"]) == (
                    x, y, x, y + 50, expected_slot)
                assert sprite["mode"] == "multicolor" and sprite["multicolor"] is True
                assert sprite["colorIndex"] == self.foreground
                assert sprite["xExpanded"] is False and sprite["yExpanded"] is False
                assert sprite["displayWidth"] == 24 and sprite["displayHeight"] == 21
                assert sprite["rowHeights"] == [1] * 21
                assert sprite["clip"] == {
                    "x": x, "y": 189 if last else 0, "width": 24, "height": 11 if last else 200
                }
                local = (0 if group == "left" else 10) + band
                assert sprite["index"] == phase * 20 + local
                assert sprite["byteOffset"] == (phase * 20 + local) * 64 and sprite["byteLength"] == 64
                data = self.sprite_bytes[sprite["byteOffset"]:sprite["byteOffset"] + 64]
                assert len(data) == 64 and data[63] == 0
                if last:
                    assert data[:30] == bytes(30), "The spare pair's ten overlapping rows must be transparent"
            self.sprites.append(sprites)
        self.images = [self.decode(phase) for phase in (0, 1)]

    def decode(self, phase):
        # The crop includes the normal top/bottom borders. They remain black;
        # horizontal overscan shows D021 during the picture's 200 raster rows.
        indices = [[0] * 384 for _ in range(272)]
        for y in range(35, 235):
            indices[y] = [self.background] * 384
        for y in range(200):
            for x in range(160):
                cell = y // 8 * 40 + x // 4
                value = self.bitmaps[phase][cell * 8 + y % 8]
                code = value >> (6 - 2 * (x % 4)) & 3
                screen = self.screens[phase][cell]
                color = (self.background, screen >> 4, screen & 15, self.colors[cell])[code]
                left = 32 + phase + x * 2
                indices[y + 35][left:left + 2] = [color, color]
        # Sprite zero has highest priority. Code zero reveals the underlying
        # bitmap, including the first/rightmost pixel of the shifted MCI field.
        for sprite in sorted(self.sprites[phase], key=lambda entry: entry["hardwareSlot"], reverse=True):
            offset = sprite["byteOffset"]
            data = self.sprite_bytes[offset:offset + 64]
            colors = (self.background, self.multicolors[0], sprite["colorIndex"], self.multicolors[1])
            left = sprite["vicX"] + 8
            top = sprite["vicY"] + 1 - 16
            for row in range(21):
                y = top + row
                if not 35 <= y < 235:
                    continue
                for column in range(12):
                    code = data[row * 3 + column // 4] >> (6 - 2 * (column % 4)) & 3
                    if code:
                        for x in (left + column * 2, left + column * 2 + 1):
                            if 0 <= x < 384:
                                indices[y][x] = colors[code]
        image = Image.new("RGB", (384, 272))
        image.putdata([self.palette[color] for row in indices for color in row])
        return image

    def check_memory(self, phase, ram, vic, colors, cia):
        pins = (cia[0] | (~cia[2] & 0xff)) & 3
        bank = (~pins) & 3
        assert bank == (1, 2)[phase], ("MCI bank", phase, bank)
        assert vic[0x18] & 0xfe == 0x38, ("Tail screen matrix", vic[0x18])
        assert vic[0x16] & 0x3f == 0x18 + phase, ("MCI fine scroll", phase, vic[0x16])
        assert vic[0x11] & 0x37 == 0x33, ("Bitmap mode/display/scroll", vic[0x11])
        assert vic[0x15] & ~0x78 == 0, ("Only the four side hardware slots may be enabled", vic[0x15])
        assert vic[0x1c] & 0x78 == 0x78 and vic[0x1b] & 0x78 == 0
        assert vic[0x17] & 0x78 == 0 and vic[0x1d] & 0x78 == 0
        assert vic[0x20] & 15 == 0 and vic[0x21] & 15 == self.background
        assert [vic[0x25] & 15, vic[0x26] & 15] == self.multicolors
        assert all(vic[0x27 + slot] & 15 == self.foreground for slot in SIDE_SLOTS)
        assert colors == self.colors, "Color RAM differs from the original MCI export"
        for index, (screen, tail_screen, bitmap, sprites) in enumerate(
                ((0x4000, 0x4c00, 0x6000, 0x4400), (0x8000, 0x8c00, 0xa000, 0x8400))):
            assert ram[screen:screen + 1000] == self.screens[index], (index, "MCI screen changed")
            assert ram[tail_screen:tail_screen + 1000] == self.screens[index], (index, "Tail screen changed")
            assert ram[bitmap:bitmap + 8000] == self.bitmaps[index], (index, "MCI bitmap changed")
            assert ram[sprites:sprites + 1280] == self.sprite_bytes[index * 1280:(index + 1) * 1280], (
                index, "Exported native sprite bytes changed")
            # Changing matrix on badline 155 selects the next pair atomically.
            # Both copies retain their last primary and spare sprite pointers.
            for matrix, pointers in ((screen, ((3, 0x14), (4, 0x1e), (5, 0x19), (6, 0x23))),
                                     (tail_screen, ((3, 0x18), (4, 0x22), (5, 0x19), (6, 0x23)))):
                for slot, pointer in pointers:
                    actual = ram[matrix + 0x3f8 + slot]
                    assert actual == pointer, (index, hex(matrix), slot, "Last sprite pointer", actual)
        assert ram[0x7fff] == ram[0xbfff] == 0
        for slot in SIDE_SLOTS:
            last = next(sprite for sprite in reversed(self.sprites[phase]) if sprite["hardwareSlot"] == slot)
            x = vic[slot * 2] | (((vic[0x10] >> slot) & 1) << 8)
            assert x == last["vicX"], ("Sprite X phase", phase, slot, x, last["vicX"])
            assert vic[slot * 2 + 1] == last["vicY"], ("Sprite Y", slot, vic[slot * 2 + 1], last["vicY"])
        return {"phase": phase, "vic_bank": bank, "screen": (0x4c00, 0x8c00)[phase],
                "bitmap": (0x6000, 0xa000)[phase]}


def differences(actual, expected, box):
    a, e = actual.load(), expected.load()
    return [(x, y, a[x, y], e[x, y])
            for y in range(box[1], box[3]) for x in range(box[0], box[2]) if a[x, y] != e[x, y]]


def verify(args):
    program = args.program.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    reference = Reference(args.source, args.border_sprites, args.palette)
    for phase, image in enumerate(reference.images):
        image.save(output / f"expected-phase-{phase}.png")
    labels = read_labels(program.with_suffix(".sym"))
    assert all(name in labels for name in ("start", "phase", "fieldCounter", "frameComplete"))
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = vice_command(args.vice, program, port, args.palette.resolve())
    command += ["-initbreak", "reset", "-warp", "-VICIIborders", "0", "-seed", "1"]
    result = {"passed": False, "program": str(program), "program_sha256": sha256(program.read_bytes()),
              "source_mci": str(reference.source_path), "source_mci_sha256": sha256(reference.source),
              "border_archive": str(reference.archive_path),
              "border_archive_sha256": sha256(reference.archive_path.read_bytes()),
              "sprite_bytes_sha256": sha256(reference.sprite_bytes), "requested_fields": args.frames,
              "warmup_fields": args.warmup, "native_pal_fps": "13684/273", "side_viewport": SIDE_VIEWPORT,
              "command": command}
    process = connection = monitor = None
    fields, images = [], []
    began = time.monotonic()
    try:
        with (output / "vice.log").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            connection = connect_monitor(process, port)
            monitor = Monitor(connection)
            monitor.run("r")
            monitor.run("sidefx off")
            startup = breakpoint(monitor, labels["start"])
            monitor.run("x")
            assert monitor.registers()[0] == labels["start"]
            monitor.run(f"disable {startup}")
            complete = breakpoint(monitor, labels["frameComplete"])
            previous = None
            for index in range(args.warmup + args.frames):
                monitor.run("x")
                pc, raster, line_cycle, cycles = registers(monitor)
                assert pc == labels["frameComplete"], ("Execution checkpoint", pc)
                monitor.run("bank ram")
                ram = monitor.memory(output / "ram.bin", 0, 0xffff)
                phase, count = ram[labels["phase"]], ram[labels["fieldCounter"]]
                monitor.run("bank io")
                vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                colors = bytes(value & 15 for value in monitor.memory(output / "colors.bin", 0xd800, 0xdbe7))
                cia = monitor.memory(output / "cia.bin", 0xdd00, 0xdd03)
                monitor.run("bank cpu")
                if index < args.warmup:
                    continue
                assert raster == 302 and line_cycle == 3, ("Stable field boundary", index, raster, line_cycle)
                assert phase in (0, 1)
                layout = reference.check_memory(phase, ram, vic, colors, cia)
                if previous:
                    assert phase == previous["phase"] ^ 1, ("MCI field skipped/repeated", index)
                    assert count == (previous["counter"] + 1) & 255
                    assert abs(cycles - previous["cycles"] - PAL_CYCLES) <= 1, ("PAL cadence", cycles - previous["cycles"])
                screenshot = output / f"field-{len(fields):03d}.png"
                monitor.run(f'screenshot "{screenshot}" 2')
                with Image.open(screenshot) as image:
                    actual = image.convert("RGB")
                assert actual.size == (384, 272)
                expected = reference.images[phase]
                full = differences(actual, expected, FULL_BOX)
                extended = differences(actual, expected, SIDE_VIEWPORT)
                bitmap = differences(actual, expected, BITMAP_BOX)
                actual_pixels = actual.load()
                vertical_pixels = [(x, y) for y in (*range(35), *range(235, 272)) for x in range(384)
                                   if actual_pixels[x, y] != reference.palette[0]]
                row = {"field": len(fields), "counter": count, "raster": raster, "line_cycle": line_cycle,
                       "cycles": cycles, **layout, "pixel_differences": len(full),
                       "side_viewport_pixel_differences": len(extended), "bitmap_pixel_differences": len(bitmap),
                       "nonblack_vertical_border_pixels": len(vertical_pixels),
                       "first_pixel_differences": full[:16], "actual_rgb_sha256": sha256(actual.tobytes())}
                if len(fields) < 2:
                    actual.save(output / f"actual-phase-{phase}.png")
                fields.append(row)
                images.append(actual)
                previous = row
                if len(fields) % 8 == 0:
                    print(f"Native exported side-border MCI: {len(fields)}/{args.frames} PAL fields", flush=True)
            monitor.run(f"disable {complete}")
        assert len(fields) == args.frames and {field["phase"] for field in fields} == {0, 1}
        result.update(fields=fields, pixel_differences=sum(field["pixel_differences"] for field in fields),
                      side_viewport_pixel_differences=sum(field["side_viewport_pixel_differences"] for field in fields),
                      bitmap_pixel_differences=sum(field["bitmap_pixel_differences"] for field in fields),
                      nonblack_vertical_border_pixels=sum(field["nonblack_vertical_border_pixels"] for field in fields))
        assert result["nonblack_vertical_border_pixels"] == 0, "Vertical borders must remain visually black"
        assert result["pixel_differences"] == 0, ("Native fields differ from source MCI and sprite bytes", result["pixel_differences"])
        images[0].save(output / "native.gif", save_all=True, append_images=images[1:],
                       duration=20, loop=0, disposal=1, optimize=False)
        result["passed"] = True
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if monitor:
            (output / "monitor.log").write_text("\n".join(monitor.transcript))
        if connection:
            try:
                connection.sendall(b"quit\n")
            except OSError:
                pass
            connection.close()
        if process:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        result["elapsed_host_seconds"] = round(time.monotonic() - began, 3)
        result.setdefault("fields", fields)
        (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in ("command", "fields")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--border-sprites", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "giana/build/cyberpunk-border-check")
    parser.add_argument("--palette", type=Path, default=ROOT / "palettes/peptoette-a.vpl")
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--vice", default=os.environ.get("VICE") or shutil.which("x64sc"))
    args = parser.parse_args()
    if not args.vice:
        parser.error("x64sc was not found; set VICE or use --vice")
    if args.frames < 2 or args.warmup < 6:
        parser.error("At least two captured fields and six warmup fields are required")
    verify(args)


if __name__ == "__main__":
    main()
