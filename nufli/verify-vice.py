#!/usr/bin/env python3
"""Check a NUFLI PRG against converter color indices in normal-speed PAL VICE."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time

from PIL import Image


def verify(program, expected_file, palette_file, output, startup_seconds):
    expected = expected_file.read_bytes()
    if len(expected) != 64000 or max(expected) > 15:
        raise ValueError("Expected 320 × 200 C64 color indices.")
    palette = [tuple(int(v, 16) for v in line.split()[:3])
               for line in palette_file.read_text().splitlines() if line and not line.startswith("#")]
    if len(palette) != 16 or len(set(palette)) != 16:
        raise ValueError("Expected 16 distinct external palette colors.")
    output.mkdir(parents=True, exist_ok=False)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = ["/opt/homebrew/bin/x64sc", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "-VICIIvsync", "+reu", "-sounddev", "dummy",
               "+confirmonexit", "+refreshonbreak", "+binarymonitor", "-autostartprgmode", "1",
               "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette_file.resolve()),
               "-VICIIsaturation", "1000", "-VICIIcontrast", "1000", "-VICIIbrightness", "1000",
               "-VICIIgamma", "1000",
               "-autostart", str(program.resolve()), "-remotemonitor", "-remotemonitoraddress",
               f"ip4://127.0.0.1:{port}"]
    transcript = []
    samples = []
    log = (output / "vice.log").open("w")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        time.sleep(startup_seconds)
        if process.poll() is not None:
            raise RuntimeError("VICE exited before startup; see vice.log.")
        for sample in range(3):
            with socket.create_connection(("127.0.0.1", port), timeout=5) as monitor:
                monitor.settimeout(0.15)

                def receive():
                    chunks = []
                    while True:
                        try:
                            chunk = monitor.recv(65536)
                        except socket.timeout:
                            break
                        if not chunk:
                            break
                        chunks.append(chunk)
                    return b"".join(chunks).decode(errors="replace")

                def run(text):
                    monitor.sendall((text + "\n").encode())
                    response = receive()
                    transcript.append(text + "\n" + response)
                    if re.search(r"ERROR|Unknown resource|Unknown command", response):
                        raise RuntimeError(response)
                    return response

                receive()
                if sample == 0:
                    for resource, value in [("InitialWarpMode", 0), ("Speed", 100),
                                            ("AutostartWarp", 0), ("VICIIVSync", 1),
                                            ("VICIIColorSaturation", 1000), ("VICIIColorContrast", 1000),
                                            ("VICIIColorBrightness", 1000), ("VICIIColorGamma", 1000)]:
                        if f"{resource}={value}" not in run(f'resourceget "{resource}"'):
                            raise RuntimeError(f"Unexpected emulator resource: {resource}")
                    run("d 3100 31f4")
                response = run("break 310d")
                breakpoint = re.search(r"BREAK:\s*(\d+)", response)
                if not breakpoint:
                    raise RuntimeError("Could not set player foreground breakpoint.")
                run("x")
                registers = run("r")
                if not re.search(r"^\.;310d\s", registers, re.M | re.I):
                    raise RuntimeError("NUFLI player did not reach its foreground loop.")
                run(f"delete {breakpoint.group(1)}")
                run("io d000")
                screenshot = output / f"vice-{sample + 1}.png"
                run(f'scrsh "{screenshot.resolve()}" 2')
                if not screenshot.is_file():
                    raise RuntimeError("VICE did not write its screenshot.")
                if sample == 0:
                    run("bank ram")
                    run(f'bsave "{(output / "display-ram.bin").resolve()}" 0 2000 79ff')
                    run("bank cpu")
                image = Image.open(screenshot).convert("RGB")
                expected_rgb = [palette[index] for index in expected]
                candidates = []
                for origin_y in range(28, 41):
                    for origin_x in range(28, 37):
                        actual = list(image.crop((origin_x, origin_y, origin_x + 320, origin_y + 200)).get_flattened_data())
                        mismatch = sum(a != b for a, b in zip(actual, expected_rgb))
                        candidates.append((mismatch, origin_x, origin_y))
                mismatch, x, y = min(candidates)
                samples.append({"file": screenshot.name, "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                                "mismatches": mismatch, "origin": [x, y], "compared_pixels": 64000,
                                "registers": registers})
                monitor.sendall(b"x\n")
            if sample < 2:
                time.sleep(0.3)
        report = {"pass": all(sample["mismatches"] == 0 for sample in samples),
                  "program": str(program.resolve()), "sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
                  "expected_sha256": hashlib.sha256(expected).hexdigest(),
                  "pal": True, "speed_percent": 100, "warp": False,
                  "comparison": "exact RGB using the converter's external palette; all 320 columns and 200 rows",
                  "samples": samples}
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
        if not report["pass"]:
            raise RuntimeError("NUFLI player differs from the converter preview.")
    finally:
        (output / "monitor.log").write_text("\n".join(transcript))
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("--palette", type=Path, default=Path(__file__).resolve().parents[1] / "palettes/colodore.vpl")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-seconds", type=float, default=15)
    args = parser.parse_args()
    if not 0 <= args.startup_seconds <= 60:
        parser.error("Startup wait must be between 0 and 60 seconds.")
    verify(args.program, args.expected, args.palette, args.output, args.startup_seconds)
