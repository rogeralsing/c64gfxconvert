#!/usr/bin/env python3
"""Check actual PAL VIC-II ECM pixels and loaded data in an owned VICE process."""

import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time

from PIL import Image, ImageChops


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build"
PROMPT = re.compile(rb"\((?:C|8|9|10|11):\$[0-9a-fA-F]{4}\) $")
BACKGROUNDS = (0, 1, 6, 14)


class Monitor:
    def __init__(self, connection):
        self.connection = connection
        self.transcript = []
        connection.settimeout(30)
        self.run("r")

    def run(self, command):
        self.connection.sendall((command + "\n").encode())
        response = bytearray()
        while not PROMPT.search(response) or (
            command == "r" and not re.search(rb"^\.;", response, re.M)
        ):
            chunk = self.connection.recv(65536)
            if not chunk:
                raise ConnectionError("Owned VICE monitor closed unexpectedly.")
            response.extend(chunk)
        result = response.decode(errors="replace")
        self.transcript.append(command + "\n" + result)
        if re.search(r"ERROR|Unknown command|Unknown resource|Syntax error", result):
            raise RuntimeError(f"VICE rejected {command!r}: {result}")
        return result

    def dump(self, name, first, last):
        path = OUTPUT / name
        self.run(f'bsave "{path}" 0 {first:04x} {last:04x}')
        data = path.read_bytes()
        if len(data) != last - first + 1:
            raise AssertionError(f"Incomplete VICE memory dump: {path}")
        return data


def connect_monitor(process, port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Owned VICE exited; inspect build/vice.log.")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("Owned VICE monitor did not start within 15 seconds.")


def decode_ecm(screen, colors, font, palette):
    image = Image.new("RGB", (320, 200))
    pixels = image.load()
    for cell, code in enumerate(screen):
        glyph = code & 63
        background = palette[BACKGROUNDS[code >> 6]]
        foreground = palette[colors[cell] & 15]
        x, y = cell % 40 * 8, cell // 40 * 8
        for row in range(8):
            bits = font[glyph * 8 + row]
            for column in range(8):
                pixels[x + column, y + row] = (
                    foreground if bits & (128 >> column) else background
                )
    return image


def compare_screenshot(path, expected):
    screenshot = Image.open(path).convert("RGB")
    for top in range(28, 49):
        for left in range(28, 41):
            crop = screenshot.crop((left, top, left + 320, top + 200))
            if ImageChops.difference(crop, expected).getbbox() is None:
                return {"origin": [left, top], "compared_pixels": 64000,
                        "mismatched_pixels": 0}
    raise AssertionError("Native VIC-II screenshot differs from independent ECM decoding.")


def verify():
    subprocess.run([str(HERE / "build.sh")], cwd=HERE, check=True)
    expected_font = (OUTPUT / "font.bin").read_bytes()
    expected_screen = (OUTPUT / "screen.bin").read_bytes()
    expected_colors = (OUTPUT / "color.bin").read_bytes()
    if tuple(map(len, (expected_font, expected_screen, expected_colors))) != (512, 1000, 1000):
        raise AssertionError("Invalid generated asset lengths.")
    glyphs = [expected_font[index * 8:(index + 1) * 8] for index in range(64)]
    if glyphs[0] != bytes(8):
        raise AssertionError("Glyph zero must be empty.")
    for index in range(33):
        if sum(row.bit_count() for row in glyphs[index]) != index:
            raise AssertionError(f"Glyph {index} must contain exactly {index} set pixels.")
        if index and any(previous & current != previous for previous, current
                         in zip(glyphs[index - 1], glyphs[index])):
            raise AssertionError("Successive glyphs must preserve every previously set pixel.")
    if glyphs[32] != bytes([0xaa, 0x55] * 4):
        raise AssertionError("Glyph 32 must be a 50% checkerboard.")
    if any(any(glyph) for glyph in glyphs[33:]):
        raise AssertionError("Unused ECM glyphs must remain empty.")
    symbols = (OUTPUT / "demo.sym").read_text()
    match = re.search(r"\.label\s+ready\s*=\s*\$([0-9a-fA-F]+)", symbols)
    if not match:
        raise AssertionError("Missing native ready label.")
    ready = int(match[1], 16)
    palette_path = HERE.parents[1] / "palettes/colodore.vpl"
    palette = [tuple(int(channel, 16) for channel in line.split()[:3])
               for line in palette_path.read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    if len(palette) != 16:
        raise AssertionError("Expected a sixteen-color VICE palette.")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    program = OUTPUT / "ecm-dither.prg"
    command = [
        "/opt/homebrew/bin/x64sc", "-default", "+saveres", "-minimized", "-pal",
        "-speed", "100", "+warp", "+autostart-warp", "+confirmonexit",
        "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor",
        "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program),
        "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette_path),
        "-VICIIsaturation", "1000", "-VICIIcontrast", "1000",
        "-VICIIbrightness", "1000", "-VICIIgamma", "1000",
        "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
    ]
    report = {"pass": False, "program": program.name, "pal": True,
              "speed_percent": 100, "warp": False,
              "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
              "command": command}
    process, connection, monitor = None, None, None
    with (OUTPUT / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report["owned_pid"] = process.pid
            connection = connect_monitor(process, port)
            monitor = Monitor(connection)
            monitor.run("sidefx off")
            response = monitor.run(f"break {ready:04x}")
            checkpoint = re.search(r"BREAK:\s*(\d+)", response)
            if not checkpoint:
                raise AssertionError("VICE did not set ready breakpoint.")
            monitor.run("x")
            response = monitor.run("r")
            if not re.search(rf"^\.;{ready:04x}\s", response, re.M | re.I):
                raise AssertionError(f"Program did not reach ready: {response}")
            monitor.run(f"delete {checkpoint[1]}")
            # The static loop takes three clocks per instruction. More than two
            # PAL frames lets VIC scan every cell before screenshot capture.
            monitor.run("step 15000")
            monitor.run("bank ram")
            screen = monitor.dump("native-screen.bin", 0x0400, 0x07e7)
            font = monitor.dump("native-font.bin", 0x2000, 0x21ff)
            monitor.run("bank io")
            colors = monitor.dump("native-color.bin", 0xd800, 0xdbe7)
            vic = monitor.dump("native-vic.bin", 0xd000, 0xd03f)
            cia2 = monitor.dump("native-cia2.bin", 0xdd00, 0xdd02)
            monitor.run("bank cpu")
            if screen != expected_screen:
                raise AssertionError("Native screen differs from generated screen codes.")
            if font != expected_font:
                raise AssertionError("Native font differs from generated glyphs.")
            if bytes(color & 15 for color in colors) != expected_colors:
                raise AssertionError("Native foreground colors differ from generated colors.")
            if vic[0x11] & 0x7f != 0x5b or vic[0x16] & 0x1f != 8 or vic[0x18] & 0xfe != 0x18:
                raise AssertionError("VIC is not using 40x25 ECM at screen $0400/font $2000.")
            if tuple(color & 15 for color in vic[0x21:0x25]) != BACKGROUNDS:
                raise AssertionError("Unexpected global ECM background palette.")
            if cia2[0] & 3 != 3 or cia2[2] & 3 != 3 or vic[0x15] != 0:
                raise AssertionError("VIC bank zero or sprite disable is incorrect.")
            screenshot = OUTPUT / "vice.png"
            monitor.run(f'scrsh "{screenshot}" 2')
            expected = decode_ecm(screen, colors, font, palette)
            report["screenshot"] = compare_screenshot(screenshot, expected)
            expected.resize((960, 600), Image.Resampling.NEAREST).save(OUTPUT / "native-preview.png")
            report.update({"font_bytes_compared": 512, "screen_bytes_compared": 1000,
                           "color_bytes_compared": 1000, "global_backgrounds": BACKGROUNDS,
                           "font_contract": {"active_glyphs": 33, "nested_pixels": True,
                                             "set_pixels": list(range(33)),
                                             "checkerboard_50_percent": True,
                                             "empty_unused_slots": 31},
                           "vic_registers": {"d011": vic[0x11], "d016": vic[0x16],
                                             "d018": vic[0x18]}, "pass": True})
        except Exception as error:
            report["error"] = repr(error)
            raise
        finally:
            if monitor:
                (OUTPUT / "monitor.log").write_text("\n".join(monitor.transcript))
            if connection:
                try:
                    connection.sendall(b"quit\n")
                except OSError:
                    pass
                connection.close()
            if process and process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            report["owned_process_exit_code"] = process.returncode if process else None
            (OUTPUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "screenshot": report["screenshot"],
                      "verification": str(OUTPUT / "verification.json")}))


if __name__ == "__main__":
    verify()
