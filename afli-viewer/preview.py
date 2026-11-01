#!/usr/bin/env python3
"""Run one standalone PAL AFLI program in VICE and capture its display and RAM."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time


def preview(program, source, output):
    program = program.resolve()
    source = source.resolve()
    image = source.read_bytes()
    if len(image) != 16385 or image[:2] != b"\x00\x40":
        raise ValueError("Expected a converter AFLI export with load address $4000.")
    expected = bytearray(image[2:16194])
    for page in range(8):
        for tile_row in range(25):
            start = page * 1024 + tile_row * 40
            expected[start:start + 3] = bytes(3)
    for tile_row in range(25):
        start = 8192 + tile_row * 320
        expected[start:start + 24] = bytes(24)

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [
        "/opt/homebrew/bin/x64sc", "+saveres", "-minimized", "-pal", "-speed", "100",
        "+warp", "+autostart-warp", "-VICIIvsync", "+reu",
        "-sounddev", "dummy", "+confirmonexit", "+refreshonbreak",
        "+binarymonitor", "-autostartprgmode", "1", "-autostart", str(program),
        "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
    ]
    log = (output / "vice.log").open("w")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
    state = {"pid": process.pid, "port": port, "program": str(program),
             "source": str(source), "command": command}
    (output / "process.json").write_text(json.dumps(state, indent=2) + "\n")
    transcript = []
    try:
        # Allow direct-RAM autostart and relocation to finish before opening the
        # monitor. The RAM comparison below rejects an incomplete startup.
        time.sleep(25)
        if process.poll() is not None:
            raise RuntimeError("VICE exited before the AFLI display started; see vice.log.")
        with socket.create_connection(("127.0.0.1", port), timeout=5) as monitor:
            monitor.settimeout(0.25)

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
            run("r")
            for resource, expected_value in [
                ("InitialWarpMode", 0), ("Speed", 100),
                ("AutostartWarp", 0), ("VICIIVSync", 1),
            ]:
                response = run(f'resourceget "{resource}"')
                if f"{resource}={expected_value}" not in response:
                    raise RuntimeError(f"Unexpected {resource}: {response}")
            run("bank ram")
            for label, start, end in [("bank-a", "4000", "7f3f"),
                                      ("bank-b", "c000", "ff3f")]:
                target = output / f"{label}.bin"
                run(f'bsave "{target}" 0 {start} {end}')
                actual = target.read_bytes()
                if actual != expected:
                    mismatches = sum(a != b for a, b in zip(actual, expected))
                    raise ValueError(f"{label}: AFLI RAM mismatch ({len(actual)} bytes; {mismatches} different).")
            run("bank cpu")
            run("m d011 d018")
            run("io d000")
            screenshot = output / f"{program.stem}-vice.png"
            run(f'scrsh "{screenshot}" 2')
            if not screenshot.is_file():
                raise RuntimeError("VICE did not create its PNG capture.")
            monitor.sendall(b"x\n")
        verification = {
            "program": str(program), "source": str(source),
            "source_sha256": hashlib.sha256(image).hexdigest(),
            "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
            "pal": True, "speed_percent": 100, "warp": False, "vsync": True,
            "matching_active_bytes_per_bank": len(expected),
            "matching_display_banks": 2, "display_mask_left_hires_pixels": 24,
            "screenshot": str(screenshot), "pid": process.pid, "port": port,
        }
        (output / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
        print(json.dumps(verification), flush=True)
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        raise
    finally:
        (output / "monitor.log").write_text("\n".join(transcript))
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    preview(arguments.program, arguments.source, arguments.output)
