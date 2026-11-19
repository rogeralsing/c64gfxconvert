#!/usr/bin/env python3
"""Verify the standalone Lillen player against the supplied MCI and sprite ZIP.

The reference decodes the original file formats independently of the builder.
VICE provides completed PAL fields (screenshotted at the frameComplete
breakpoint) and RAM through read-only monitor commands.
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
import time
import zipfile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT.parent / "images/borders"
PROMPT = re.compile(rb"\(C:\$[0-9a-fA-F]{4}\) $")
PAL_CYCLES = 19656
FULL_BOX = (0, 0, 384, 272)
CORE_BOX = (32, 35, 352, 235)
BORDER_BOXES = {"top": (0, 0, 384, 35), "bottom": (0, 235, 384, 272),
                "left": (0, 35, 32, 235), "right": (352, 35, 384, 235)}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_labels(path):
    labels = {}
    for name, address in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", path.read_text()):
        labels[name] = int(address, 16)
    return labels


class Monitor:
    """Text monitor transport; all issued commands are retained for inspection."""

    def __init__(self, connection):
        self.connection = connection
        self.transcript = []
        connection.settimeout(0.1)
        try:
            while connection.recv(65536):
                pass
        except socket.timeout:
            pass
        connection.settimeout(15)

    def run(self, command):
        self.connection.sendall((command + "\n").encode())
        response = b""
        while not PROMPT.search(response) or (command == "r" and not re.search(rb"^\.;", response, re.M)):
            part = self.connection.recv(65536)
            if not part:
                raise RuntimeError("VICE closed its monitor connection")
            response += part
        text = response.decode(errors="replace")
        self.transcript.append(command + "\n" + text)
        if re.search(r"ERROR|Unknown command|Unknown resource|Syntax error", text):
            raise RuntimeError(f"VICE rejected {command!r}:\n{text}")
        return text

    def memory(self, path, first, last):
        self.run(f'bsave "{path.resolve()}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        assert len(data) == last - first + 1, "VICE memory dump is incomplete"
        return data

    def registers(self):
        response = self.run("r")
        match = re.search(r"^\.;([0-9a-fA-F]{4})\s+(.*)$", response, re.M)
        assert match, response
        fields = match[2].split()
        return int(match[1], 16), int(fields[-3]), int(fields[-2]), int(fields[-1])


def connect_monitor(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("VICE exited during startup; inspect vice.log")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("VICE did not open its remote monitor")


def breakpoint(monitor, address):
    response = monitor.run(f"break ${address:04x}")
    match = re.search(r"BREAK:\s*(\d+)", response)
    assert match, response
    return int(match[1])


class Reference:
    """Independent True Paint bitmap and VIC sprite bit decoder."""

    def __init__(self, source, archive, palette):
        self.source_path, self.archive_path = source.resolve(), archive.resolve()
        self.source = source.read_bytes()
        assert len(self.source) == 19434 and self.source[:2] == b"\x00\x9c", "Expected True Paint MCI"
        self.screens = (self.source[2:1002], self.source[17410:18410])
        self.bitmaps = (self.source[1026:9026], self.source[9218:17218])
        self.colors, self.background = self.source[18434:19434], self.source[1002]
        assert 0 <= self.background < 16 and all(0 <= value < 16 for value in self.colors)
        with zipfile.ZipFile(archive) as package:
            self.manifest = json.loads(package.read("manifest.json"))
            self.sprite_bytes = package.read("sprites.bin")
        manifest = self.manifest
        assert (manifest["format"], manifest["version"], manifest["interlaced"]) == ("c64-border-sprites", 1, True)
        assert manifest["image"] == {"width": 368, "height": 272, "pixelAspectRatio": [1, 1],
                                     "core": {"x": 24, "y": 35, "width": 320, "height": 200}}
        self.settings = manifest["settings"]
        assert self.settings["vertical"]["xExpanded"] is False
        assert manifest["hardware"]["backgroundColorRegister"] == self.background
        self.shared = self.settings["multicolorIndices"]
        assert len(self.shared) == 2 and all(type(value) is int and 0 <= value < 16 for value in self.shared)
        assert manifest["hardware"]["sharedMulticolorRegisters"] == self.shared
        self.palette = [tuple(int(value, 16) for value in line.split()[:3])
                        for line in palette.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        assert len(self.palette) == 16
        assert len(manifest["sprites"]) == 104 and len(self.sprite_bytes) == 6656
        assert manifest["fields"] == [
            {"phase": phase, "offsetX": phase, "spriteOffset": phase * 52,
             "spriteCount": 52, "byteOffset": phase * 3328, "byteLength": 3328}
            for phase in (0, 1)]
        self.sprites = []
        for phase in (0, 1):
            sprites = [entry for entry in manifest["sprites"] if entry["field"] == phase]
            assert len(sprites) == 52
            for local, sprite in enumerate(sprites):
                index = phase * 52 + local
                assert sprite["index"] == index and sprite["byteOffset"] == index * 64
                assert sprite["mode"] == "multicolor" and sprite["multicolor"] is True
                assert sprite["displayWidth"] == 24 and sprite["displayHeight"] == 21
                assert sprite["xExpanded"] is False and sprite["yExpanded"] is False
                assert 0 <= sprite["colorIndex"] < 16
                if phase:
                    first = self.sprites[0][local]
                    assert sprite["vicX"] == first["vicX"] + 1
                    assert sprite["vicY"] == first["vicY"]
                    assert sprite["colorIndex"] == first["colorIndex"]
            self.sprites.append(sprites)
        self.images = [self.decode(phase) for phase in (0, 1)]

    def decode(self, phase):
        indices = [[self.background] * 384 for _ in range(272)]
        for y in range(200):
            for x in range(160):
                cell = y // 8 * 40 + x // 4
                value = self.bitmaps[phase][cell * 8 + y % 8]
                code = value >> (6 - 2 * (x % 4)) & 3
                screen = self.screens[phase][cell]
                color = (self.background, screen >> 4, screen & 15, self.colors[cell])[code]
                left = 32 + phase + x * 2
                indices[y + 35][left:left + 2] = [color, color]
        for sprite in sorted(self.sprites[phase], key=lambda entry: entry["hardwareSlot"], reverse=True):
            native = self.sprite_bytes[sprite["byteOffset"]:sprite["byteOffset"] + 64]
            colors = (self.background, self.shared[0], sprite["colorIndex"], self.shared[1])
            left, top = sprite["vicX"] + 8, sprite["vicY"] + 1 - 16
            for row in range(21):
                y = top + row
                if not 0 <= y < 272:
                    continue
                for column in range(12):
                    code = native[row * 3 + column // 4] >> (6 - 2 * (column % 4)) & 3
                    if code:
                        for x in range(left + column * 2, left + (column + 1) * 2):
                            if 0 <= x < 384:
                                indices[y][x] = colors[code]
        result = Image.new("RGB", (384, 272))
        result.putdata([self.palette[color] for row in indices for color in row])
        return result


def differences(actual, expected, box):
    a, e = actual.load(), expected.load()
    return [(x, y, a[x, y], e[x, y]) for y in range(box[1], box[3]) for x in range(box[0], box[2]) if a[x, y] != e[x, y]]


def verify(args):
    program, output = args.program.resolve(), args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    reference = Reference(args.source, args.border_sprites, args.palette)
    labels = read_labels(program.with_suffix(".sym"))
    assert all(name in labels for name in ("start", "frameComplete", "phase", "fieldCounter",
                                           "screenA", "screenB", "spriteDataA", "spriteDataB",
                                           "bitmapA", "bitmapB"))
    for phase, image in enumerate(reference.images):
        image.save(output / f"expected-phase-{phase}.png")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [args.vice, "-default", "+saveres", "-minimized", "-pal", "-speed", "100", "+warp",
               "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor",
               "-autostartprgmode", "1", "-autostart", str(program), "-VICIIfilter", "0", "-VICIIextpal",
               "-VICIIpalette", str(args.palette.resolve()), "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
               "-VICIIbrightness", "1000", "-VICIIgamma", "1000", "-remotemonitor", "-remotemonitoraddress",
               f"ip4://127.0.0.1:{port}", "-initbreak", "reset", "-warp", "-VICIIborders", "0", "-seed", "1"]
    result = {"passed": False, "program": str(program), "program_sha256": sha256(program.read_bytes()),
              "source_mci": str(reference.source_path), "source_mci_sha256": sha256(reference.source),
              "border_archive": str(reference.archive_path), "border_archive_sha256": sha256(reference.archive_path.read_bytes()),
              "sprite_bytes_sha256": sha256(reference.sprite_bytes), "requested_fields": args.frames,
              "warmup_fields": args.warmup, "pal_cycles_per_field": PAL_CYCLES,
              "native_pal_fps": "13684/273", "command": command,
              "vertical_sprite_positions": [sprite["vicX"] for sprite in reference.sprites[0][:32]],
              "shared_sprite_colors": reference.shared}
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
                pc, raster, cycle, elapsed = monitor.registers()
                assert pc == labels["frameComplete"], ("Unexpected execution checkpoint", pc)
                monitor.run("bank ram")
                ram = monitor.memory(output / "ram.bin", 0, 0xffff)
                monitor.run("bank io")
                vic = monitor.memory(output / "vic.bin", 0xd000, 0xd03f)
                colors = bytes(value & 15 for value in monitor.memory(output / "colors.bin", 0xd800, 0xdbe7))
                cia = monitor.memory(output / "cia.bin", 0xdd00, 0xdd03)
                monitor.run("bank cpu")
                if index < args.warmup:
                    continue
                phase, counter = ram[labels["phase"]], ram[labels["fieldCounter"]]
                assert phase in (0, 1)
                boundary_error = None if (raster, cycle) == (302, 3) else [raster, cycle]
                memory_error = None
                try:
                    layout = check_memory(phase, ram, vic, colors, cia, reference, labels)
                except AssertionError as error:
                    layout = {"phase": phase}
                    memory_error = str(error)
                if previous:
                    assert phase == previous["phase"] ^ 1, "An MCI field was skipped or repeated"
                    assert counter == (previous["counter"] + 1) & 255
                    assert elapsed - previous["cycles"] == PAL_CYCLES, ("PAL cadence", elapsed - previous["cycles"])
                screenshot = output / f"field-{len(fields):03d}.png"
                monitor.run(f'screenshot "{screenshot}" 2')
                with Image.open(screenshot) as image:
                    actual = image.convert("RGB")
                assert actual.size == (384, 272)
                expected = reference.images[phase]
                full, core = differences(actual, expected, FULL_BOX), differences(actual, expected, CORE_BOX)
                borders = {name: len(differences(actual, expected, box)) for name, box in BORDER_BOXES.items()}
                row = {"field": len(fields), "counter": counter, "raster": raster, "line_cycle": cycle,
                       "cycles": elapsed, **layout, "pixel_differences": len(full), "core_pixel_differences": len(core),
                       "border_pixel_differences": borders, "boundary_error": boundary_error,
                       "memory_error": memory_error, "first_pixel_differences": full[:24],
                       "actual_rgb_sha256": sha256(actual.tobytes())}
                fields.append(row)
                images.append(screenshot)
                previous = row
            assert len(fields) == args.frames and {row["phase"] for row in fields} == {0, 1}
            worst = max(row["pixel_differences"] for row in fields)
            result["fields"] = fields
            result["screenshots"] = [str(path) for path in images]
            result["worst_pixel_differences"] = worst
            result["passed"] = (worst == 0 and all(row["memory_error"] is None for row in fields)
                                and all(row["boundary_error"] is None for row in fields))
            result["elapsed_host_seconds"] = time.monotonic() - began
    except Exception as error:
        result["failure"] = {"message": str(error), "type": type(error).__name__}
    finally:
        result.setdefault("fields", fields)
        if monitor:
            (output / "monitor.log").write_text("\n".join(monitor.transcript))
        with (output / "verification.json").open("w") as stream:
            stream.write(json.dumps(result, indent=2) + "\n")
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
    summary = {key: result[key] for key in ("passed", "failure", "worst_pixel_differences") if key in result}
    print(json.dumps({**summary, "captured_fields": len(fields), "report": str(output / "verification.json")}))
    if not result["passed"]:
        raise SystemExit(1)


def check_memory(phase, ram, vic, colors, cia, reference, labels):
    """Assert the registers and memory at the frameComplete breakpoint."""
    bank = (~(cia[0] | (~cia[2] & 255))) & 3
    assert bank == (1, 3)[phase], ("MCI VIC bank", phase, bank)
    assert vic[0x16] & 0x3f == 0x18 + phase, ("MCI fine scroll", phase, hex(vic[0x16]))
    assert vic[0x11] & 0x37 == 0x33, ("Bitmap mode/display/Y scroll", hex(vic[0x11]))
    assert vic[0x15] == 255 and vic[0x1c] == 255 and vic[0x1b] == 0
    assert vic[0x17] == 0 and vic[0x1d] == 0, "No sprite may use expansion"
    assert vic[0x20] & 15 == 0 and vic[0x21] & 15 == reference.background
    assert [vic[0x25] & 15, vic[0x26] & 15] == reference.shared
    assert colors == reference.colors, "Color RAM differs from original MCI"
    for index, suffix in enumerate(("A", "B")):
        for name, expected in (("screen", reference.screens[index]), ("bitmap", reference.bitmaps[index]),
                               ("spriteData", reference.sprite_bytes[index * 3328:(index + 1) * 3328])):
            address = labels[name + suffix]
            assert ram[address:address + len(expected)] == expected, (index, name, hex(address), "Source bytes changed")
        base = labels["screen" + suffix]
        atlas = (labels["spriteData" + suffix] - base) // 64
        assert ram[base + 0x400:base + 0x400 + 1000] == reference.screens[index], (index, "Tail matrix changed")
        for group, band, matrix in (("top", 1, 0x1c00), ("bottom", 0, 0), ("bottom", 1, 0x1800)):
            records = [sprite for sprite in reference.sprites[index]
                       if sprite["group"] == group and sprite["band"] == band]
            assert len(records) == 8
            for sprite in records:
                slot = sprite["hardwareSlot"]
                pointer = atlas + sprite["index"] % 52
                assert ram[base + matrix + 0x3f8 + slot] == pointer, (
                    index, group, band, "Prepared sprite pointer", slot)
        left_slot, right_slot = labels["sideLeftSlot"], labels["sideRightSlot"]
        final_left, final_right = labels["finalSideLeftSlot"], labels["finalSideRightSlot"]
        assert (left_slot, right_slot, final_left, final_right) == (1, 2, 3, 4)
        for group, band, slot in (("left", 7, left_slot), ("right", 7, right_slot),
                                  ("left", 8, final_left), ("right", 8, final_right),
                                  ("left", 9, 5), ("right", 9, 6)):
            sprite = next(sprite for sprite in reference.sprites[index]
                          if sprite["group"] == group and sprite["band"] == band)
            pointer = atlas + sprite["index"] % 52
            assert ram[base + 0x7f8 + slot] == pointer, (index, "Last side pointer", group, band)
    assert vic[0x18] & 0xfe == 8, ("Restored primary screen", hex(vic[0x18]))
    for sprite in reference.sprites[phase][24:32]:
        slot = sprite["hardwareSlot"]
        x = vic[slot * 2] | (((vic[0x10] >> slot) & 1) << 8)
        assert x == sprite["vicX"], ("Completed lower-band X", phase, slot, x, sprite["vicX"])
        actual_color = vic[0x27 + slot] & 15
        assert actual_color == sprite["colorIndex"], (
            "Completed lower-band color", phase, slot, actual_color, sprite["colorIndex"])
    assert ram[0x7fff] == ram[0xffff] == 0, "Idle graphics bytes must be zero"
    assert ram[0xc0] == ram[0xc3] == 0x4c and ram[0xc6] == 0x40
    assert ram[0xc1] | ram[0xc2] << 8 == labels["irqFirst"]
    assert ram[0xc4] | ram[0xc5] << 8 == labels["irqStable"]
    return {"phase": phase, "vic_bank": bank}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", type=Path, default=ROOT / "build/lillen2/lillen2.prg")
    parser.add_argument("--source", type=Path, default=SOURCE_DIR / "lillen2.mci")
    parser.add_argument("--border-sprites", type=Path, default=SOURCE_DIR / "lillen2.zip")
    parser.add_argument("--palette", type=Path, default=ROOT / "assets/peptoette-a.vpl")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/lillen2/proof")
    parser.add_argument("--vice", default=os.environ.get("VICE") or shutil.which("x64sc"))
    parser.add_argument("--frames", type=int, default=16)
    parser.add_argument("--warmup", type=int, default=8)
    args = parser.parse_args()
    if not args.vice:
        parser.error("x64sc was not found; set VICE or use --vice")
    if args.frames < 2 or args.warmup < 2:
        parser.error("At least two captured fields and two warmup fields are required")
    verify(args)
