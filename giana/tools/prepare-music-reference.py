#!/usr/bin/env python3
"""Capture original Level1 SID calls in VSID, independently of the demo.

The pinned RSID wrapper calls $41C0 and returns to $CCF4. Capture each call
through the score-position $5D to $28 wrap and24 further PAL frames.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "giana/build/music-discovery"
SOURCE = ROOT / "giana/assets/music-source.sid"
SOURCE_SHA256 = "014764e6ee11df4b458c6b30e235ea639d702bd56766a87b5e90d4737558b1c8"
sys.path.insert(0, str(ROOT / "mydemo/discoball"))
from vice_support import Monitor, connect_monitor


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    trace = OUT / "original-subtune3-call-registers.txt"
    executable = os.environ.get("VSID") or shutil.which("vsid")
    assert executable, "Install VSID or set VSID to its executable path"
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    command = [executable, "-default", "+saveres", "-console", "-tune", "3", "-seed", "1",
               "-pal", "-sidmodel", "0", "-sidengine", "1", "-residsamp", "2",
               "-sounddev", "dump", "-soundarg", str(trace), "-warp", "-initbreak", "reset",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
               "-limitcycles", str(150 * 985248), str(SOURCE)]
    process = connection = monitor = None
    calls = []
    previous_position = wrapped = None
    started = time.monotonic()
    try:
        with (OUT / "original-call-reference-vsid.log").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            connection = connect_monitor(process, port)
            monitor = Monitor(connection)
            connection.settimeout(60)
            monitor.run("r")
            monitor.run("sidefx off")
            monitor.run("break 41c0")
            monitor.run("break ccf4")
            monitor.run("disable 2")
            for tick in range(6500):
                monitor.run("x")
                pc, _, entry = monitor.registers()
                assert pc == 0x41c0, (tick, hex(pc))
                monitor.run("disable 1")
                monitor.run("enable 2")
                monitor.run("x")
                pc, _, end = monitor.registers()
                assert pc == 0xccf4, (tick, hex(pc))
                monitor.run("disable 2")
                monitor.run("enable 1")
                monitor.run("bank ram")
                state = monitor.memory(OUT / "reference-state.bin", 0x41d0, 0x4288)
                bookmark = monitor.memory(OUT / "reference-bookmark.bin", 0x4ac2, 0x4aca)
                position = state[0x14]
                assert state[0x1c] == 0, "Original cue1 must leave the sampler disabled"
                if previous_position == 0x5d and position == 0x28 and wrapped is None:
                    wrapped = tick
                calls.append({"tick": tick, "entry_cycles": entry, "return_cycles": end,
                              "sequence_position": position, "state": state.hex(), "bookmark": bookmark.hex()})
                previous_position = position
                monitor.run("bank cpu")
                if tick % 512 == 0:
                    print(f"Original SID tick {tick}; position ${position:02x}; wrap={wrapped}", flush=True)
                if wrapped is not None and tick >= wrapped + 24:
                    break
    finally:
        if monitor:
            (OUT / "original-call-reference-monitor.log").write_text("\n".join(monitor.transcript))
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

    events = []
    clock = 0
    for line in trace.read_text().splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            delta, register, value = map(int, fields)
        except ValueError:
            continue
        clock += delta
        if 0 <= register <= 24:
            events.append((clock, register, value))
    event_index = 0
    for call in calls:
        while event_index < len(events) and events[event_index][0] < call["entry_cycles"]:
            event_index += 1
        values = []
        while event_index < len(events) and events[event_index][0] < call["return_cycles"]:
            values.append(list(events[event_index][1:]))
            event_index += 1
        call["events"] = values
    assert wrapped is not None, "No complete original score loop observed"
    assert sum(len(call["events"]) for call in calls) > 100
    result = {"source_sha256": SOURCE_SHA256, "subtune_one_based": 3,
              "profile": "original RSID PAL MOS6581", "command": command,
              "call_entry": 0x41c0, "call_return": 0xccf4, "calls": calls,
              "first_sequence_wrap_tick": wrapped,
              "sequence_positions": sorted({call["sequence_position"] for call in calls}),
              "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
              "elapsed_seconds": round(time.monotonic() - started, 3)}
    (OUT / "original-call-reference.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(f"Captured {len(calls)} original calls; score wraps at tick {wrapped}", flush=True)


if __name__ == "__main__":
    main()
