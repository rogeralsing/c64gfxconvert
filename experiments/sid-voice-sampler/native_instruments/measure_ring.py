"""Prove each SID2 ring read follows its matching native producer write.

Monitor tracepoints observe the unchanged program. Generation numbers detect
stale reads even when repeated silence would hide them in the SID register dump.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import native_support as support


def measure(build: dict, expected: bytes, out: Path, duration: float) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    labels = build["symbols"]
    ring_base = labels.get("sid2_high_buffer", 0x0600)
    ring_bytes = labels.get("C3_RING_BYTES", 256)
    writers = {int(value): name for name, value in labels.items()
               if name.startswith("c3_ring_store") or
               name in ("c3_neutral_store", "c3_muted_store")}
    readers = {int(labels[name]): name for name in ("sid2_read_high", "sid2_pending_read_high")}
    if not writers:
        raise ValueError("Export every actual producer ring-store instruction")
    points = writers | readers
    monitor, log = out / "ring.mon", out / "ring-monitor.log"
    log.unlink(missing_ok=True)
    commands = [f'logname "{log.resolve()}"', "log on",
                f'load "{build["program"]}" 0', f'break exec ${labels["done"]:04x}']
    for checkpoint, address in enumerate(points, 2):
        commands += [f"trace exec ${address:04x}", f'command {checkpoint} "stopwatch"']
    commands += [f'g ${labels["start"]:04x}', "log off", "quit"]
    monitor.write_text("\n".join(commands) + "\n")
    settings = support.profile()
    command = ["rtk", "proxy", *settings.vice_command(), "-console", "-seed", "1",
               "-initbreak", "ready", "-moncommands", str(monitor.resolve()),
               "-sounddev", "dump", "-soundarg", str((out / "registers.txt").resolve()),
               "-warp", "-limitcycles", str(round((duration + 15) * support.CLOCK))]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=duration + 120)
    (out / "vice.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not log.exists():
        raise RuntimeError(f"Ring tracing failed: {out}")
    instruction = re.compile(r"^\.C:([0-9a-fA-F]{4})\s+(?:[0-9a-fA-F]{2}\s+){3}"
                             r"(LDA|STA)\s+\$([0-9a-fA-F]{4})(,X)?\s+-\s+A:([0-9a-fA-F]{2})"
                             r" X:([0-9a-fA-F]{2}).*?\s(\d+)$")
    slots = [None] * ring_bytes
    written = read = 0
    min_depth = min_age = None
    max_depth = 0
    failures = []
    reached_done = False
    for line in log.read_text().splitlines():
        if line.startswith(f'.C:{labels["done"]:04x}'):
            reached_done = True
        match = instruction.match(line)
        if not match:
            continue
        pc, opcode, address, indexed, value, x, cycle = match.groups()
        pc, address, value, cycle = int(pc, 16), int(address, 16), int(value, 16), int(cycle)
        if indexed:
            address = (address + int(x, 16)) & 65535
        if pc not in points:
            continue
        if not ring_base <= address < ring_base + ring_bytes:
            failures.append({"kind": "outside_ring", "cycle": cycle, "address": address})
            continue
        slot = address - ring_base
        if pc in writers:
            wanted_address = (written + 1) % ring_bytes
            wanted_value = expected[written] if written < len(expected) else None
            if opcode != "STA" or slot != wanted_address or value != wanted_value:
                failures.append({"kind": "producer_sequence", "index": written,
                                 "address": address, "wanted_slot": wanted_address,
                                 "value": value, "wanted_value": wanted_value})
            slots[slot] = (written, cycle + (4 if indexed else 3))
            written += 1
            max_depth = max(max_depth, written - read)
            if written - read > ring_bytes:
                failures.append({"kind": "producer_overwrite", "written": written, "read": read})
        else:
            wanted_address = (read + 1) % ring_bytes
            generation = slots[slot]
            if opcode != "LDA" or slot != wanted_address or generation is None or generation[0] != read:
                failures.append({"kind": "stale_or_overwritten_read", "index": read,
                                 "slot": slot, "written_generation": generation})
            else:
                age = cycle + 3 - generation[1]
                min_age = age if min_age is None else min(min_age, age)
            depth = written - read
            min_depth = depth if min_depth is None else min(min_depth, depth)
            read += 1
    result = {"passed": reached_done and not failures and written == read == len(expected),
              "program_sha256": build["program_sha256"],
              "expected_values": len(expected), "produced_values": written, "consumed_values": read,
              "ring_base": ring_base, "ring_bytes": ring_bytes,
              "minimum_values_ready_before_read": min_depth, "maximum_queued_values": max_depth,
              "minimum_write_to_read_margin_cycles": min_age,
              "stale_reads_or_overwrites": len(failures), "first_failures": failures[:12],
              "monitor_sha256": support.digest(log),
              "scope": "Actual unmodified native execution. Every read has the correct sequential generation, including repeated neutral values. This proves causality beyond matching SID register values."}
    support.save(out / "ring-proof.json", result)
    if not result["passed"]:
        raise ValueError(json.dumps(result, indent=2))
    return result
