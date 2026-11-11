#!/usr/bin/env python3
"""Execute the fixed Huffman decoder in py65 and normal PAL VICE."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess
import sys


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build/huffman-native"
ASSETS = HERE / "build/huffman-study/current"
sys.path.insert(0, "/tmp/disco-sid-analysis-py65")
from py65.devices.mpu6502 import MPU

SPEC = importlib.util.spec_from_file_location("huffman_native_monitor", HERE.parent / "verify-c64.py")
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stats(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)}


def verify(args):
    manifest = json.loads((BUILD / "build.json").read_text())
    program = (BUILD / "decoder.prg").read_bytes()
    labels = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (BUILD / "huffman-decoder.sym").read_text())}
    compressed = (ASSETS / "compressed.bin").read_bytes()
    decoded = (ASSETS / "decoded.bin").read_bytes()
    index = json.loads((ASSETS / "frames-index.json").read_text())
    report = {"pass": False, "manifest": manifest, "programSha256": sha(program),
              "compressedSha256": sha(compressed), "decodedSha256": sha(decoded),
              "scope": "Huffman decoding into hidden RAM only; no delta application or disk-loader CPU included."}
    cpu = MPU()
    load = int.from_bytes(program[:2], "little")
    cpu.memory[load:load + len(program) - 2] = program[2:]
    host_cycles = []
    per_frame = []
    for record in index:
        packed = compressed[record["offset"]:record["offset"] + record["bytes"]]
        wanted = decoded[record["sourceOffset"]:record["sourceOffset"] + record["decodedBytes"]]
        cpu.memory[0x7000:0x7000 + len(packed) + 2] = packed + b"\0\0"
        cpu.memory[labels["decoded_length"]:labels["decoded_length"] + 2] = record["decodedBytes"].to_bytes(2, "little")
        cpu.memory[0x3000:0x3400] = [0xa5] * 1024
        cpu.memory[0x1fe:0x200] = [0xff, 0x0f]
        cpu.pc = labels["huffman_decode"]
        cpu.sp = 0xfd
        before = cpu.processorCycles
        steps = 0
        while cpu.pc != 0x1000:
            cpu.step()
            steps += 1
            if steps > 100000:
                raise AssertionError(f"Decoder did not return at frame{record['frame']}")
        actual = bytes(cpu.memory[0x3000:0x3000 + len(wanted)])
        if actual != wanted:
            mismatches = [(i, a, b) for i, (a, b) in enumerate(zip(actual, wanted)) if a != b]
            raise AssertionError(f"Huffman output differs at frame{record['frame']}: {mismatches[:8]}")
        if cpu.memory[0x3000 + len(wanted)] != 0xa5:
            raise AssertionError("Decoder wrote past its declared output length")
        elapsed = cpu.processorCycles - before
        host_cycles.append(elapsed)
        per_frame.append({"frame": record["frame"], "decodedBytes": len(wanted), "cycles": elapsed,
                          "cyclesPerByte": elapsed / len(wanted)})
    report["py65"] = {"pass": True, "frames": len(index), "decodedBytes": len(decoded),
                      "instructionCycles": stats(host_cycles),
                      "cyclesPerByteWeighted": sum(host_cycles) / len(decoded), "perFrame": per_frame}
    print(json.dumps({"py65Pass": True, "frames": len(index), "cycles": stats(host_cycles)}), flush=True)
    if args.py65_only:
        report["pass"] = True
        (BUILD / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        return report

    selected = sorted(set(list(range(0, len(index), 32)) + [
        min(range(len(index)), key=lambda i: host_cycles[i]),
        max(range(len(index)), key=lambda i: host_cycles[i])]))
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [str(args.vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100",
               "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
               "+refreshonbreak", "+binarymonitor", "-initbreak", "reset",
               "-autostartprgmode", "1", "-autostart", str(BUILD / "decoder.prg"),
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    output = BUILD / "pal-proof"
    output.mkdir(exist_ok=True)
    connection = monitor = process = None
    samples = []
    with (output / "vice.log").open("w") as log:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            connection = native.connect(process, port)
            monitor = native.Monitor(connection)
            monitor.run("sidefx off")
            for resource, value in (("MachineVideoStandard", 1), ("Speed", 100),
                                    ("InitialWarpMode", 0), ("AutostartWarp", 0)):
                if f"{resource}={value}" not in monitor.run(f'resourceget "{resource}"'):
                    raise AssertionError("Unexpected VICE resource " + resource)
            for name in ("benchmark_start", "decode_start", "decode_end", "frame_done"):
                monitor.checkpoint(labels[name])

            def arrive(name):
                monitor.run("x")
                registers = monitor.registers()
                if registers["pc"] != labels[name]:
                    raise AssertionError(f"Expected{name}, got${registers['pc']:04x}")
                return registers

            for pose in selected:
                arrive("benchmark_start")
                record = index[pose]
                packed = compressed[record["offset"]:record["offset"] + record["bytes"]]
                wanted = decoded[record["sourceOffset"]:record["sourceOffset"] + record["decodedBytes"]]
                frame_file = output / "input.prg"
                frame_file.write_bytes(b"\x00\x70" + packed + b"\0\0")
                monitor.run(f'load "{frame_file}" 0')
                length_file = output / "length.prg"
                length_file.write_bytes(labels["decoded_length"].to_bytes(2, "little") + record["decodedBytes"].to_bytes(2, "little"))
                monitor.run(f'load "{length_file}" 0')
                started = arrive("decode_start")
                ended = arrive("decode_end")
                arrive("frame_done")
                actual = monitor.dump(output / "output.bin", 0x3000, 0x3000 + len(wanted) - 1)
                if actual != wanted:
                    raise AssertionError(f"PAL Huffman output differs at frame{pose}")
                monitor.run("bank io")
                vic = monitor.dump(output / "vic.bin", 0xd000, 0xd03f)
                monitor.run("bank cpu")
                if vic[0x11] & 0x7f != 0x1b or vic[0x16] & 0x1f != 8:
                    raise AssertionError("PAL display mode was not active during decoding")
                elapsed = ended["clock"] - started["clock"]
                samples.append({"frame": pose, "decodedBytes": len(wanted), "compressedBytes": len(packed),
                                "palCycles": elapsed, "cyclesPerByte": elapsed / len(wanted),
                                "start": started, "end": ended, "outputMatches": True})
                print(json.dumps({"frame": pose, "palCycles": elapsed, "decodedBytes": len(wanted)}), flush=True)
            report["pal"] = {"pass": True, "samples": samples, "frames": len(samples),
                             "cycles": stats([sample["palCycles"] for sample in samples]),
                             "cyclesPerByteWeighted": sum(sample["palCycles"] for sample in samples) / sum(sample["decodedBytes"] for sample in samples),
                             "palClockHz": native.PAL_CLOCK, "palFieldCycles": native.PAL_FRAME_CYCLES,
                             "twoFieldFrameBudget": 2 * native.PAL_FRAME_CYCLES,
                             "displayEnabled": True, "includesVicStalls": True,
                             "speedPercent": 100, "warp": False}
            report["pass"] = True
        finally:
            if monitor:
                (output / "monitor.log").write_text("\n".join(monitor.transcript))
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
            (BUILD / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"pass": report["pass"], "py65Cycles": report["py65"]["instructionCycles"],
                      "palCycles": report["pal"]["cycles"], "tables": manifest["lookupTableBytes"],
                      "decoderCodeAndState": manifest["codeAndStateBytes"]}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--py65-only", action="store_true")
    parser.add_argument("--vice", type=Path, default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"))
    verify(parser.parse_args())
