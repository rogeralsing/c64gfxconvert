#!/usr/bin/env python3
"""Capture a standalone layered FLI or AFLI/sprite PRG in normal-speed PAL VICE."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import time
import zipfile


def capture(program, source, output, symbols, active_symbol, frame_counter, startup_seconds):
    program = program.resolve()
    source = source.resolve()
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:
            raise ValueError("Layer archive failed its ZIP CRC check.")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") not in {"c64-afli-sprite-layers", "c64-fli-sprite-layers"} or manifest.get("version") != 1:
            raise ValueError("Expected a version 1 converter FLI or AFLI/sprite layer archive.")
        multicolor = manifest["format"] == "c64-fli-sprite-layers"
    symbol_text = (symbols or program.parent / "boot-rendered.sym").read_text()
    match = re.search(r"\.label\s+" + re.escape(active_symbol) + r"=\$([0-9a-fA-F]+)", symbol_text)
    if not match:
        raise ValueError(f"Missing active-image symbol {active_symbol}.")
    active_address = match.group(1).lower().zfill(4)
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
    transcript, samples = [], []
    log = (output / "vice.log").open("w")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    state = {"pid": process.pid, "port": port, "program": str(program),
             "source": str(source), "command": command}
    (output / "process.json").write_text(json.dumps(state, indent=2) + "\n")
    try:
        time.sleep(startup_seconds)
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

                def run(text):
                    monitor.sendall((text + "\n").encode())
                    response = receive()
                    transcript.append(text + "\n" + response)
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
                response = run(f"break {active_address}")
                checkpoint = re.search(r"BREAK:\s*(\d+)", response)
                if not checkpoint:
                    raise RuntimeError(f"VICE did not create the {active_symbol} breakpoint.")
                run("x")
                registers = run("r")
                if not re.search(r"^\.;" + active_address + r"\s", registers, re.M | re.I):
                    raise RuntimeError(f"The player did not reach {active_symbol} at ${active_address}.")
                run(f"delete {checkpoint.group(1)}")
                run("bank ram")
                if sample == 0:
                    for label, start, end in [("bank-a", "4000", "7fff"), ("bank-b", "c000", "ffff")]:
                        target = output / f"{label}.bin"
                        run(f'bsave "{target}" 0 {start} {end}')
                        if target.stat().st_size != 16384:
                            raise ValueError(f"Incomplete display bank: {target}")
                counter_file = output / f"frame-counter-{sample + 1}.bin"
                run(f'bsave "{counter_file}" 0 {frame_counter:04x} {frame_counter:04x}')
                counter = counter_file.read_bytes()
                if len(counter) != 1:
                    raise ValueError("Incomplete frame-counter capture.")
                run("bank cpu")
                if sample == 0 and multicolor:
                    color_target = output / "color-ram.bin"
                    run(f'bsave "{color_target}" 0 d800 dbe7')
                    if color_target.stat().st_size != 1000:
                        raise ValueError("Incomplete Color RAM capture.")
                vic = run("io d000")
                screenshot = output / f"{program.stem}-vice-{sample + 1}.png"
                run(f'scrsh "{screenshot}" 2')
                if not screenshot.is_file():
                    raise RuntimeError("VICE did not create the PNG capture.")
                samples.append({"screenshot": str(screenshot),
                                "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                                "frame_counter": counter[0], "registers": registers, "vic": vic})
                monitor.sendall(b"x\n")
            if sample < 2:
                time.sleep(0.35)
        result = {
            "program": str(program), "source": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "program_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
            "pid": process.pid, "port": port, "pal": True, "speed_percent": 100,
            "warp": False, "vsync": True, "frame_counter_address": f"${frame_counter:04x}",
            "register_observation": {"symbol": active_symbol, "address": "$" + active_address,
                                     "timing": "execution breakpoint inside the active image"},
            "samples": samples,
            "identical_capture_hashes": len({sample["sha256"] for sample in samples}) == 1,
            "frame_counter_advances": all(
                0 < (second["frame_counter"] - first["frame_counter"]) % 256 < 128
                for first, second in zip(samples, samples[1:])),
        }
        (output / "capture.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key != "samples"}), flush=True)
        print("Frame counters:", [sample["frame_counter"] for sample in samples], flush=True)
    finally:
        (output / "monitor.log").write_text("\n".join(transcript))
        terminated_by_capture = process.poll() is None
        if terminated_by_capture:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()
        state["terminated_by_capture"] = terminated_by_capture
        state["exit_code"] = process.returncode
        (output / "process.json").write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path)
    parser.add_argument("source", type=Path, help="Exact exported layer ZIP")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", type=Path)
    parser.add_argument("--active-symbol", default="row100")
    parser.add_argument("--frame-counter", type=lambda value: int(value.removeprefix("$"), 16), default=0x02f0)
    parser.add_argument("--startup-seconds", type=float, default=25)
    arguments = parser.parse_args()
    if not 0 <= arguments.frame_counter <= 65535 or not 0 <= arguments.startup_seconds <= 60:
        parser.error("Frame counter must be a C64 address and startup delay must be 0..60 seconds.")
    capture(arguments.program, arguments.source, arguments.output, arguments.symbols,
            arguments.active_symbol, arguments.frame_counter, arguments.startup_seconds)
