#!/usr/bin/env python3
"""Verify both PAFLI phases, bank data, scroll compensation, and frame cadence in PAL VICE."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time

from PIL import Image


def verify(program, expected_files, output):
    player = json.loads((Path(__file__).parent / 'prg/player.json').read_text())
    frame_end = player['frame_end'].removeprefix('$')
    expected = [path.read_bytes() for path in expected_files]
    if any(len(data) != 64000 or max(data) > 15 for data in expected):
        raise ValueError("Expected two 320 × 200 preview files of C64 palette indices.")
    original = program.read_bytes()
    if len(original) != 48013 or original[:2] != b"\x01\x08":
        raise ValueError("Expected a standalone converter PAFLI PRG.")
    palette_file = Path(__file__).resolve().parents[1] / "palettes/colodore.vpl"
    palette = [tuple(int(v, 16) for v in line.split()[:3])
               for line in palette_file.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    expected_rgb = [[palette[index] for index in frame] for frame in expected]
    output.mkdir(parents=True, exist_ok=False)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = ["/opt/homebrew/bin/x64sc", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "-VICIIvsync", "+reu", "-sounddev", "dummy",
               "+confirmonexit", "+refreshonbreak", "+binarymonitor", "-autostartprgmode", "1",
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette_file.resolve()),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000", "-VICIIbrightness", "1000",
               "-VICIIgamma", "1000", "-autostart", str(program.resolve()), "-remotemonitor",
               "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    transcript, samples, checked_banks = [], [], set()
    with (output / "vice.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            time.sleep(15)
            if process.poll() is not None:
                raise RuntimeError("VICE exited during startup.")
            with socket.create_connection(("127.0.0.1", port), timeout=5) as monitor:
                # Some VICE connections send an initial prompt before the
                # first request; drain it so responses stay with their command.
                monitor.settimeout(0.2)
                try:
                    while monitor.recv(65536):
                        pass
                except socket.timeout:
                    pass
                monitor.settimeout(5)

                def receive():
                    data = b""
                    while not re.search(rb"\(C:\$[0-9a-fA-F]{4}\) $", data):
                        part = monitor.recv(65536)
                        if not part:
                            raise RuntimeError("VICE monitor closed unexpectedly.")
                        data += part
                    return data.decode(errors="replace")

                def run(text):
                    monitor.sendall((text + "\n").encode())
                    response = receive()
                    transcript.append(text + "\n" + response)
                    if re.search(r"ERROR|Unknown command|Unknown resource", response):
                        raise RuntimeError(response)
                    return response

                run("r")
                for name, value in [("Speed", 100), ("InitialWarpMode", 0), ("AutostartWarp", 0),
                                    ("VICIIVSync", 1), ("VICIIColorSaturation", 1000),
                                    ("VICIIColorContrast", 1000), ("VICIIColorBrightness", 1000),
                                    ("VICIIColorGamma", 1000)]:
                    response = run(f'resourceget "{name}"')
                    while f"{name}=" not in response:
                        response += receive()
                    if f"{name}={value}" not in response:
                        raise RuntimeError(f"Unexpected emulator resource: {name}")
                # Stop after the active image, before either phase/bank toggle.
                run(f"break {frame_end}")
                for sample in range(6):
                    run("x")
                    registers = run("r")
                    if not re.search(r"^\.;" + frame_end + r"\s", registers, re.M | re.I):
                        raise RuntimeError("Player did not finish an active image.")
                    bank_file = output / f"vic-bank-{sample}.bin"
                    scroll_file = output / f"vic-scroll-{sample}.bin"
                    counter_file = output / f"counter-{sample}.bin"
                    run(f'bsave "{bank_file.resolve()}" 0 dd00 dd00')
                    run(f'bsave "{scroll_file.resolve()}" 0 d016 d016')
                    bank = bank_file.read_bytes()[0] & 3
                    phase = {2: 0, 0: 1}.get(bank)
                    if phase is None:
                        raise RuntimeError(f"Unexpected VIC bank: {bank}")
                    scroll = scroll_file.read_bytes()[0] & 7
                    if scroll != phase * 4:
                        raise RuntimeError("Bitmap bank and X-scroll phase disagree.")
                    run("bank ram")
                    run(f'bsave "{counter_file.resolve()}" 0 02f0 02f0')
                    if phase not in checked_banks:
                        start = 0x4000 if phase == 0 else 0xc000
                        dump = output / f"phase-{phase}-ram.bin"
                        run(f'bsave "{dump.resolve()}" 0 {start:04x} {start + 16191:04x}')
                        staged = 2 + (0x4000 if phase == 0 else 0x83e8) - 0x0801
                        if dump.read_bytes() != original[staged:staged + 16192]:
                            raise RuntimeError("Active screen/bitmap bank differs from the exported PRG.")
                        checked_banks.add(phase)
                    run("bank cpu")
                    screenshot = output / f"frame-{sample + 1}-phase-{phase}.png"
                    run(f'scrsh "{screenshot.resolve()}" 2')
                    image = Image.open(screenshot).convert("RGB")
                    # The PAL engine's artifact and phase margin occupy x=0..27.
                    reference = [expected_rgb[phase][y * 320 + x] for y in range(200) for x in range(28, 320)]
                    candidates = []
                    for y in range(28, 41):
                        for x in range(28, 37):
                            actual = list(image.crop((x + 28, y, x + 320, y + 200)).get_flattened_data())
                            candidates.append((sum(a != b for a, b in zip(actual, reference)), x, y))
                    mismatch, x, y = min(candidates)
                    lower_border = image.crop((0, y + 200, image.width, image.height))
                    lower_border_nonblack = sum(pixel != palette[0] for pixel in lower_border.get_flattened_data())
                    # The existing x=0..27 AFLI artifact remains outside the
                    # image. Validate the cleared data and overscan under the
                    # usable image, including the eight deliberately erased rows.
                    image_tail = image.crop((x + 28, y + 192, x + 320, image.height))
                    image_tail_nonblack = sum(pixel != palette[0] for pixel in image_tail.get_flattened_data())
                    samples.append({"phase": phase, "xscroll": scroll, "counter": counter_file.read_bytes()[0],
                                    "mismatches": mismatch, "compared_pixels": 58400, "origin": [x, y],
                                    "lower_border_nonblack_pixels": lower_border_nonblack,
                                    "image_tail_nonblack_pixels": image_tail_nonblack,
                                    "screenshot": screenshot.name,
                                    "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest()})
            counter_advances = all((b["counter"] - a["counter"]) % 256 == 1 for a, b in zip(samples, samples[1:]))
            alternating = all(a["phase"] != b["phase"] for a, b in zip(samples, samples[1:]))
            stable = all(len({s["sha256"] for s in samples if s["phase"] == phase}) == 1 for phase in [0, 1])
            report = {"pass": checked_banks == {0, 1} and counter_advances and alternating and stable and
                      all(sample["mismatches"] == 0 and sample["image_tail_nonblack_pixels"] == 0
                          for sample in samples),
                      "program_sha256": hashlib.sha256(original).hexdigest(),
                      "pal": True, "speed_percent": 100, "warp": False, "visible_area": [28, 0, 320, 192],
                      "cleared_image_rows": [192, 199],
                      "frame_end": '$' + frame_end,
                      "bank_bytes_matched_per_phase": 16192, "alternating": alternating,
                      "one_counter_increment_per_frame": counter_advances, "stable_phases": stable, "samples": samples}
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2), flush=True)
            if not report["pass"]:
                raise RuntimeError("PAFLI playback differs from its aligned converter previews.")
        finally:
            (output / "monitor.log").write_text("\n".join(transcript))
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.program, [args.first, args.second], args.output)
