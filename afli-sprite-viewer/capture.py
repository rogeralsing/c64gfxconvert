#!/usr/bin/env python3
"""Capture the experimental PAL AFLI/sprite player and its display RAM."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time


def capture(program, source, output):
    program = program.resolve()
    source = source.resolve()
    image = source.read_bytes()
    if len(image) != 16385 or image[:2] != b"\x00\x40":
        raise ValueError("Expected a 16,385-byte AFLI image loaded at $4000.")
    symbols = (program.parent / "boot-rendered.sym").read_text()
    match = re.search(r"\.label row100=\$([0-9a-fA-F]+)", symbols)
    if not match:
        raise ValueError("Missing active-image row100 symbol.")
    active_address = match.group(1).lower()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [
        "/opt/homebrew/bin/x64sc", "+saveres", "-minimized", "-pal", "-speed", "100",
        "+warp", "+autostart-warp", "-VICIIvsync", "+reu", "-sounddev", "dummy",
        "+confirmonexit", "+refreshonbreak", "+binarymonitor", "-autostartprgmode", "1",
        "-autostart", str(program), "-remotemonitor", "-remotemonitoraddress",
        f"ip4://127.0.0.1:{port}",
    ]
    log = (output / "vice.log").open("w")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
    state = {"pid": process.pid, "port": port, "program": str(program),
             "source": str(source), "command": command}
    (output / "process.json").write_text(json.dumps(state, indent=2) + "\n")
    transcript = []
    samples = []
    try:
        time.sleep(25)
        if process.poll() is not None:
            raise RuntimeError("VICE exited before startup completed; see vice.log.")
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

                def run(command_text):
                    monitor.sendall((command_text + "\n").encode())
                    response = receive()
                    transcript.append(command_text + "\n" + response)
                    if re.search(r"ERROR|Unknown resource|Unknown command", response):
                        raise RuntimeError(response)
                    return response

                receive()
                run("r")
                if sample == 0:
                    for resource, value in [("InitialWarpMode", 0), ("Speed", 100),
                                            ("AutostartWarp", 0), ("VICIIVSync", 1)]:
                        response = run(f'resourceget "{resource}"')
                        if f"{resource}={value}" not in response:
                            raise RuntimeError(f"Unexpected {resource}: {response}")
                # Observe sprite settings inside the image, after their per-frame
                # restoration. The bottom-cleanup path deliberately disables them.
                response = run(f"break {active_address}")
                checkpoint = re.search(r"BREAK:\s*(\d+)", response)
                if not checkpoint:
                    raise RuntimeError("VICE did not create the row100 breakpoint.")
                run("x")
                registers = run("r")
                if not re.search(r"^\.;" + active_address + r"\s", registers, re.M | re.I):
                    raise RuntimeError("The player did not reach its active-image row100.")
                run(f"delete {checkpoint.group(1)}")
                run("bank ram")
                if sample == 0:
                    for label, start, end in [("bank-a", "4000", "7fff"),
                                              ("bank-b", "c000", "ffff")]:
                        target = output / f"{label}.bin"
                        run(f'bsave "{target}" 0 {start} {end}')
                        if target.stat().st_size != 16384:
                            raise ValueError(f"Incomplete display bank: {target}")
                counter_file = output / f"frame-counter-{sample + 1}.bin"
                run(f'bsave "{counter_file}" 0 02f0 02f0')
                counter = counter_file.read_bytes()
                if len(counter) != 1:
                    raise ValueError("Incomplete frame-counter capture.")
                run("bank cpu")
                io = run("io d000")
                screenshot = output / f"{program.stem}-vice-{sample + 1}.png"
                run(f'scrsh "{screenshot}" 2')
                if not screenshot.is_file():
                    raise RuntimeError("VICE did not create the PNG capture.")
                samples.append({
                    "screenshot": str(screenshot),
                    "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                    "frame_counter": counter[0], "registers": registers, "vic": io,
                })
                monitor.sendall(b"x\n")
            if sample < 2:
                time.sleep(0.35)
        result = {
            "program": str(program), "source": str(source),
            "source_sha256": hashlib.sha256(image).hexdigest(),
            "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
            "pid": process.pid, "port": port, "pal": True, "speed_percent": 100,
            "warp": False, "vsync": True, "frame_counter_address": "$02f0",
            "register_observation": {
                "kernel_row_label": 100, "address": "$" + active_address,
                "timing": "exec breakpoint before the opcode fetch waits for DMA",
            },
            "samples": samples,
            "identical_capture_hashes": len({sample["sha256"] for sample in samples}) == 1,
            "frame_counter_advances": all(
                0 < (second["frame_counter"] - first["frame_counter"]) % 256 < 200
                for first, second in zip(samples, samples[1:])
            ),
        }
        (output / "capture.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key != "samples"}), flush=True)
        print("Frame counters:", [sample["frame_counter"] for sample in samples], flush=True)
    except Exception:
        if process.poll() is None:
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
    capture(arguments.program, arguments.source, arguments.output)
