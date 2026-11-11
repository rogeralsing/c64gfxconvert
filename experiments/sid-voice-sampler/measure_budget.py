"""Measure oscillator-player CPU deadlines without instrumenting its code.

VICE tracepoints record instruction-start cycle counters. The sampler program
is loaded unchanged, and a simultaneous SID dump checks that profiling leaves
every amplitude latch at the expected 126-cycle interval.
"""
from __future__ import annotations

import bisect
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
PERIOD = 126


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile():
    path = HERE.parent / "mod-hybrid/vice_profile.py"
    spec = importlib.util.spec_from_file_location("voice_budget_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _label(labels: dict, *names: str) -> int:
    for name in names:
        if name in labels:
            return int(labels[name])
    raise ValueError(f"Missing CPU profiling label: {' / '.join(names)}")


def measure(program: Path, labels: dict, expected_frame_counts: int | list[int], out: Path) -> dict:
    """Profile one complete native run, including variable buffer lengths.

    A list gives the expected NMI count for each buffer. An integer specifies
    that many 50-Hz source ticks, cumulatively rounded to the fixed sample
    clock with midpoint rounding. No audio is generated or modified here.
    Detailed measurements/logs remain in ``out``; the return value is compact.
    """
    program, out = Path(program).resolve(), Path(out).resolve()
    settings = _profile()
    if type(expected_frame_counts) is int:
        cuts = [(index * settings.PAL_CLOCK + PERIOD * 25) // (PERIOD * 50)
                for index in range(expected_frame_counts + 1)]
        counts = [b - a for a, b in zip(cuts, cuts[1:])]
    else:
        counts = [int(count) for count in expected_frame_counts]
    if len(counts) < 2 or any(count not in (156, 157) for count in counts):
        raise ValueError("The measured player requires 156/157-sample buffers")
    out.mkdir(parents=True, exist_ok=True)
    source_sha = _sha(program)
    points = {
        "nmi_entry": _label(labels, "nmi_entry"),
        "nmi_rti": _label(labels, "nmi_rti") if "nmi_rti" in labels else _label(labels, "nmi_end") - 1,
        "frame_boundary": _label(labels, "frame_boundary"),
        "fill_begin": _label(labels, "fill_begin", "fill_frame"),
        "fill_end": _label(labels, "fill_end", "fill_frame_rts"),
        "wait_start": _label(labels, "wait_start"),
        "pointer_swap_begin": _label(labels, "pointer_swap_begin"),
        "pointer_commit": _label(labels, "pointer_commit"),
    }
    low_store = int(labels.get("pointer_low_store", points["pointer_commit"] - 3))
    raw = program.read_bytes()
    load = int.from_bytes(raw[:2], "little")
    store_offset = low_store - load + 2
    if raw[store_offset] not in (0x8C, 0x8D, 0x8E):
        raise ValueError("Pointer completion needs an absolute STA/STX/STY instruction")
    operand = int.from_bytes(raw[store_offset + 1:store_offset + 3], "little")
    if operand != _label(labels, "buffer_read") + 1:
        raise ValueError("Pointer completion does not target buffer_read's low byte")
    points["pointer_low_store"] = low_store
    if len(set(points.values())) != len(points):
        raise ValueError("CPU profiling markers must identify distinct instructions")
    monitor, monitor_log = out / "cpu.mon", out / "cpu-monitor.log"
    register_dump = out / "registers.txt"
    for path in (monitor_log, register_dump):
        path.unlink(missing_ok=True)
    commands = [f'logname "{monitor_log}"', "log on",
                f'load "{program}" 0', f'break exec ${_label(labels, "done"):04x}']
    for checkpoint, address in enumerate(points.values(), 2):
        commands += [f"trace exec ${address:04x}", f'command {checkpoint} "stopwatch"']
    commands += [f'g ${_label(labels, "start"):04x}', "log off", "quit"]
    monitor.write_text("\n".join(commands) + "\n")
    duration = sum(counts) * PERIOD / settings.PAL_CLOCK
    command = settings.vice_command() + [
        "-console", "-seed", "1", "-initbreak", "ready", "-moncommands", str(monitor),
        "-sounddev", "dump", "-soundarg", str(register_dump), "-warp",
        "-limitcycles", str(round((duration + 15) * settings.PAL_CLOCK)),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=duration + 120)
    (out / "vice.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not monitor_log.is_file() or not register_dump.is_file():
        raise RuntimeError(f"VICE CPU profiling failed; inspect {out}")
    if _sha(program) != source_sha:
        raise ValueError("Program changed during CPU profiling")
    events = {name: [] for name in points}
    by_address = {address: name for name, address in points.items()}
    instruction = re.compile(r"^\.C:([0-9a-fA-F]{4})\b.*\s(\d+)$")
    reached_done = False
    with monitor_log.open() as stream:
        for line in stream:
            match = instruction.match(line)
            if match:
                address, cycle = int(match[1], 16), int(match[2])
                if address in by_address:
                    events[by_address[address]].append(cycle)
                if address == labels["done"]:
                    reached_done = True
    entries, returns = events["nmi_entry"], events["nmi_rti"]
    boundaries = events["frame_boundary"]
    if not reached_done or len(entries) != sum(counts) or len(returns) != len(entries) - 1:
        raise ValueError("CPU trace did not cover every NMI and terminal completion")
    if len(boundaries) != len(counts):
        raise ValueError("CPU trace did not cover every buffer boundary")
    observed_counts, previous = [], 0
    for boundary in boundaries:
        consumed = bisect.bisect_right(entries, boundary)
        observed_counts.append(consumed - previous)
        previous = consumed
    if observed_counts != counts:
        raise ValueError("Native buffer lengths differ from the requested source timing")
    starts, ends, costs = [], [], []
    regular, frame_nmis = Counter(), Counter()
    for index, (entry, ret) in enumerate(zip(entries, returns)):
        if not entry < ret < entries[index + 1]:
            raise ValueError("NMI entry/return trace is not properly ordered")
        # Tracepoints observe instruction starts: seven hardware-entry cycles
        # precede entry and six RTI cycles follow its tracepoint.
        starts.append(entry - 7)
        ends.append(ret + 6)
        cost = ret - entry + 13
        costs.append(cost)
        boundary_index = bisect.bisect_right(boundaries, entry)
        is_boundary = boundary_index < len(boundaries) and boundaries[boundary_index] < ret
        (frame_nmis if is_boundary else regular)[cost] += 1
    prefix = [0]
    for cost in costs:
        prefix.append(prefix[-1] + cost)

    def nmi_overlap(start: int, end: int) -> int:
        left = bisect.bisect_right(ends, start)
        right = bisect.bisect_left(starts, end)
        if left >= right:
            return 0
        total = prefix[right] - prefix[left]
        total -= max(0, start - starts[left])
        total -= max(0, ends[right - 1] - end)
        return total

    begins, finishes = events["fill_begin"], events["fill_end"]
    if len(begins) != len(counts) or len(finishes) != len(counts):
        raise ValueError("CPU trace did not cover every foreground buffer fill")
    frames = []
    for index, (start, end) in enumerate(zip(begins, finishes)):
        if end <= start:
            raise ValueError("Foreground fill markers are not ordered")
        stolen = nmi_overlap(start, end)
        row = {"frame": index, "samples_generated": counts[index],
               "fill_begin_cycle": start, "fill_rts_cycle": end,
               "fill_wall_cycles_before_rts": end - start,
               "nmi_cycles_during_fill": stolen,
               "fill_foreground_cycles_before_rts": end - start - stolen}
        if index:
            # Frame i is prepared while frame i-1 plays. Choosing the next
            # boundary after completion would hide a missed deadline.
            deadline, ready = boundaries[index - 1], end + 6
            slack = deadline - ready
            row.update(deadline_cycle=deadline, deadline_slack_wall_cycles=slack,
                       deadline_slack_foreground_cycles=slack - nmi_overlap(ready, deadline))
            wait = bisect.bisect_left(events["wait_start"], end)
            if wait < len(events["wait_start"]):
                row["first_wait_cycle"] = events["wait_start"][wait]
        frames.append(row)
    swap_starts, swap_stores = events["pointer_swap_begin"], events["pointer_low_store"]
    if len(swap_starts) != len(counts) - 1 or len(swap_stores) != len(swap_starts):
        raise ValueError("CPU trace did not cover every active buffer-pointer replacement")
    swaps = []
    for index, (start, store) in enumerate(zip(swap_starts, swap_stores)):
        commit = store + 4
        next_entry = bisect.bisect_left(entries, commit)
        next_nmi = entries[next_entry] - 7 if next_entry < len(entries) else None
        swaps.append({"activated_frame": index + 1, "swap_begin_cycle": start,
                      "low_pointer_committed_cycle": commit,
                      "wall_cycles_through_store": commit - start,
                      "nmi_cycles_inside_swap": nmi_overlap(start, commit),
                      "cycles_before_next_nmi_hardware_entry": next_nmi - commit if next_nmi else None})
    latch_cycles, clock = [], 0
    with register_dump.open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) == 3:
                delta, register, value = map(int, fields)
                clock += delta
                if register & 31 == 18 and value == 0x11:
                    latch_cycles.append(clock)
    # The existing sampler initialization establishes one neutral held level.
    latch_cycles = latch_cycles[1:]
    gaps = Counter(b - a for a, b in zip(latch_cycles, latch_cycles[1:]))
    if len(latch_cycles) != sum(counts) or set(gaps) != {PERIOD}:
        raise ValueError("Monitor profiling disturbed or missed the sample clock")
    active = frames[1:]
    if any(frame["deadline_slack_wall_cycles"] <= 0 for frame in active):
        raise ValueError("A generated buffer missed its actual consumption deadline")
    details = {"frames": frames, "swaps": swaps, "instruction_markers": points,
               "expected_frame_counts": counts, "observed_frame_counts": observed_counts}
    (out / "cpu-frames.json").write_text(json.dumps(details, indent=2) + "\n")
    average_cost = sum(costs) / len(costs)
    result = {
        "passed": True, "program_sha256": source_sha, "profile": dict(settings.PROFILE),
        "command": command, "frames": len(counts), "samples": sum(counts),
        "sample_period_cycles": PERIOD, "duration_s": duration,
        "buffer_sample_counts": dict(sorted(Counter(counts).items())),
        "nmi_full_cycles_regular": dict(sorted(regular.items())),
        "nmi_full_cycles_boundary": dict(sorted(frame_nmis.items())),
        "nmi_cpu_fraction": average_cost / PERIOD,
        "available_foreground_cycles_per_buffer": {
            count: count * (PERIOD - average_cost) for count in sorted(set(counts))},
        "fill_wall_cycles_range_before_rts": [min(f["fill_wall_cycles_before_rts"] for f in active),
                                              max(f["fill_wall_cycles_before_rts"] for f in active)],
        "fill_foreground_cycles_range_before_rts": [min(f["fill_foreground_cycles_before_rts"] for f in active),
                                                    max(f["fill_foreground_cycles_before_rts"] for f in active)],
        "minimum_deadline_slack_wall_cycles": min(f["deadline_slack_wall_cycles"] for f in active),
        "minimum_deadline_slack_foreground_cycles": min(f["deadline_slack_foreground_cycles"] for f in active),
        "pointer_swap_cycles_range": [min(s["wall_cycles_through_store"] for s in swaps),
                                      max(s["wall_cycles_through_store"] for s in swaps)],
        "pointer_swaps_interrupted": sum(s["nmi_cycles_inside_swap"] > 0 for s in swaps),
        "minimum_pointer_commit_margin_cycles": min(s["cycles_before_next_nmi_hardware_entry"] for s in swaps
                                                     if s["cycles_before_next_nmi_hardware_entry"] is not None),
        "sample_gap_counts": dict(sorted(gaps.items())),
        "monitor_log_sha256": _sha(monitor_log), "register_dump_sha256": _sha(register_dump),
        "scope": "Unmodified native program; monitor instruction tracepoints only. Hardware-entry/RTI costs included, final non-returning NMI excluded from average. Fill timing ends at the RTS instruction; six cycles are included in deadline readiness. Variable-frame deadlines come from actual boundary NMIs. Every profiler-run latch still has a 126-cycle interval. No audio or physical SID quality claim.",
    }
    (out / "cpu-budget.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
