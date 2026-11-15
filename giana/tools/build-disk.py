#!/usr/bin/env python3
"""Build the Giana game and MCI chain as a real 1541 Spindle disk image."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess


PART = Path(__file__).resolve().parents[1]
BUILD = PART / "build"
RUNTIME = BUILD / "giana-unpacked.prg"
SOURCE_MCI = PART / "assets" / "giana-man.mci"
DISK = BUILD / "giana.d64"
SOURCE_MCI_SHA256 = "fdcd1028fdbbd71f7c2c86e70d6291d8c7c4828213cb24c8e9a0cc5a3e1a0b55"
RESIDENT, BUFFER, ZERO_PAGE = 0xce00, 0xcf00, 0x02


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_labels(path: Path) -> dict[str, int]:
    return {name: int(value, 16) for name, value in
            re.findall(r"\.label\s+([A-Za-z_][A-Za-z_0-9]*)\s*=\s*\$([0-9a-fA-F]+)", path.read_text())}


def runtime_ranges(labels: dict[str, int]) -> list[tuple[int, int]]:
    return [(0x0801, labels["setupEnd"]), (0x0c00, labels["spriteWorkEnd"]),
            (0x1000, 0x1a00), (0x1a00, 0x1c00), (0x1c00, labels["extraEnemyFramesEnd"]),
            (0x2000, 0x3f40), (0x3f40, labels["codeEnd"]),
            (0x3f90, labels["mciResidentEnd"]), (0x41c0, labels["musicOriginalEnd"]),
            (0x6000, labels["rendererEnd"]), (0x8600, 0x8c00),
            (0x8c00, labels["scene7LightingEnd"]), (0x9000, 0x9800),
            (0x9800, labels["levelControllerEnd"]), (0x9b40, labels["enemyDisplayEnd"]),
            (0xa000, 0xb100), (0xb200, 0xba00), (0xbb00, 0xbd00),
            (0xbd00, labels["roomControllerEnd"]), (0xc000, 0xc7d0),
            (0xc800, 0xce00), (0xe000, labels["endingPackedEnd"])]


def main() -> None:
    source = RUNTIME.read_bytes()
    load = int.from_bytes(source[:2], "little")
    payload = source[2:]
    limit = load + len(payload)
    labels = read_labels(BUILD / "main.sym")
    ranges = runtime_ranges(labels)
    covered = bytearray(len(payload))
    initial = []
    lines = []
    previous_end = load
    for start, end in ranges:
        if not load <= start < end <= limit or start < previous_end:
            raise ValueError(f"Invalid or overlapping runtime segment ${start:04x}..${end:04x}")
        if start < 0xe000 and end > RESIDENT:
            raise ValueError("Runtime segment overlaps Spindle resident/buffer or I/O shadow")
        offset = start - load
        data = payload[offset:offset + end - start]
        covered[offset:offset + len(data)] = bytes([1]) * len(data)
        file_offset = offset + 2
        lines.append(f'"{RUNTIME.name}" {start:04x} {file_offset:x} {len(data):x}')
        initial.append({"address": start, "end_exclusive": end, "bytes": len(data),
                        "source": RUNTIME.name, "file_offset": file_offset, "sha256": sha256(data)})
        previous_end = end
    omitted = [load + offset for offset, (value, present) in enumerate(zip(payload, covered))
               if value and not present]
    if omitted:
        raise ValueError(f"Runtime manifest omits meaningful data, first address ${omitted[0]:04x}")
    if load != 0x0801 or labels["start"] != 0x080e:
        raise ValueError("Unexpected game runtime load address or entry")
    mci = SOURCE_MCI.read_bytes()
    if len(mci) != 19434 or sha256(mci) != SOURCE_MCI_SHA256:
        raise ValueError("Expected the unchanged user-supplied giana-man MCI")

    def chunk(address: int, offset: int, size: int) -> dict:
        data = mci[offset:offset + size]
        if len(data) != size:
            raise ValueError("MCI component exceeds source file")
        lines.append(f'"../assets/{SOURCE_MCI.name}" {address:04x} {offset:x} {size:x}')
        return {"address": address, "end_exclusive": address + size, "bytes": size,
                "source": f"assets/{SOURCE_MCI.name}", "file_offset": offset, "sha256": sha256(data)}

    lines.append("")
    phase_b = [chunk(0xa000, 9218, 8000), chunk(0x8400, 17410, 1000), chunk(0xc000, 18434, 1000)]
    lines.append("")
    phase_a = [chunk(0x2000, 1026, 8000), chunk(0x0400, 2, 1000)]
    script = "\n".join(lines) + "\n"
    if any(len(line.encode()) >= 255 for line in lines):
        raise ValueError("Spin script line exceeds the upstream parser's limit")
    script_path = BUILD / "giana.spin"
    script_path.write_text(script)

    spec = importlib.util.spec_from_file_location("build_spindle", PART / "tools" / "build-spindle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    executable = module.build()
    command = [str(executable), "-v", "-r", "ce", "-b", "cf", "-z", "02", "-e", "080e",
               "-t", "GIANA DEMO", "-i", "g7", "-o", str(DISK), str(script_path)]
    run = subprocess.run(command, cwd=BUILD, capture_output=True, text=True)
    log = run.stdout + run.stderr
    (BUILD / "disk-build.log").write_text(log)
    if run.returncode:
        raise RuntimeError(f"Spin disk build failed:\n{log}")
    disk_data = DISK.read_bytes()
    if len(disk_data) != 174848:
        raise ValueError("Expected an ordinary 35-track D64")
    jobs = [{"index": 0, "purpose": "Initial game runtime", "chunks": initial},
            {"index": 1, "purpose": "Hidden MCI phase B and shared color staging", "chunks": phase_b},
            {"index": 2, "purpose": "MCI phase A", "chunks": phase_a}]
    manifest = {"format": "giana-spindle-disk-chain-v1", "disk": {"path": "build/giana.d64",
                "bytes": len(disk_data), "sha256": sha256(disk_data)},
                "runtime": {"path": "build/giana-unpacked.prg", "sha256": sha256(source),
                            "entry": labels["start"], "omitted_nonzero_bytes": 0},
                "mci": {"source": "assets/giana-man.mci", "sha256": sha256(mci)},
                "loader": {"name": "Spindle 3.1 / Spin", "resident_address": RESIDENT,
                           "buffer_address": BUFFER, "zero_page_start": ZERO_PAGE,
                           "zero_page_bytes": 5, "call_address": RESIDENT,
                           "tool_sha256": sha256(executable.read_bytes()),
                           "cia2_bank_selection": "$DD02; never alter $DD00"},
                "script": {"path": "build/giana.spin", "sha256": sha256(script.encode())},
                "jobs": jobs, "command": command}
    (BUILD / "disk-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Created {DISK} ({len(disk_data):,} bytes; 3 scripted loader jobs).")
    print(log.strip().splitlines()[-1])


if __name__ == "__main__":
    main()
