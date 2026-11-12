"""Measure automatic NMI buffer activation and native music foreground costs.

The PRG runs unchanged. Tracepoints measure instruction starts; hardware NMI
entry, RTI/RTS completion and the actual zero-page pointer instructions are
accounted separately. No foreground pointer-swap or wait-loop gate is assumed.
"""
from __future__ import annotations

import bisect
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import native_support as support

PERIOD = 126


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _range(values):
    return [min(values), max(values)] if values else []


def _background_costs(events, overlap, calls, fill_begins):
    """Attribute active caller guards/loop branches without charging idle waits."""
    markers = sorted(set(events.get("background_begin", []) + events.get("background_chunk", [])))
    prefixes = []
    for index, call in enumerate(calls):
        begin = call["begin_cycle"]
        fill = bisect.bisect_right(fill_begins, begin) - 1
        lower = max(fill_begins[fill] if fill >= 0 else -1,
                    calls[index - 1]["resume_cycle"] if index else -1)
        marker = bisect.bisect_left(markers, lower)
        prefix = markers[marker] if marker < len(markers) and markers[marker] <= begin else begin
        prefixes.append(prefix)
        call["background_entry_guard_foreground_cycles"] = begin - prefix - overlap(prefix, begin)
        call["background_loop_foreground_cycles_after_return"] = 0
    for index, call in enumerate(calls[:-1]):
        end, following = call["resume_cycle"], prefixes[index + 1]
        fill = bisect.bisect_left(fill_begins, end)
        # A new RLE fill separates production sessions; its surrounding idle
        # poll must not be counted as producer control overhead.
        if following >= end and (fill == len(fill_begins) or fill_begins[fill] > following):
            call["background_loop_foreground_cycles_after_return"] = following - end - overlap(end, following)
    before = sum(call["background_entry_guard_foreground_cycles"] for call in calls)
    after = sum(call["background_loop_foreground_cycles_after_return"] for call in calls)
    pump = sum(call["foreground_cycles_including_jsr_rts"] for call in calls)
    outputs = sum(call["outputs"] for call in calls)
    return {"c3_background_entry_guard_cpu_cycles": before,
            "c3_background_loop_cpu_cycles_between_calls": after,
            "c3_total_foreground_cycles_including_background_control": pump + before + after,
            "c3_total_foreground_cycles_per_output_including_background_control": (pump + before + after) / outputs if outputs else None,
            "c3_background_control_scope": "Includes active queue/boundary guards and branches between consecutive C3 calls. RLE fills and intervening idle waits excluded; final exit into each idle wait is not charged."}


def measure(program: Path, labels: dict, counts: list[int], out: Path) -> dict:
    """Profile all buffers and automatic activations, including C3 call costs."""
    program, out = Path(program).resolve(), Path(out).resolve()
    counts = list(counts)
    if len(counts) < 2 or any(type(n) is not int or n not in (156, 157) for n in counts):
        raise ValueError("Supply complete original156/157sample buffer counts")
    out.mkdir(parents=True, exist_ok=True)
    required = ("nmi_entry", "nmi_rti", "frame_boundary", "fill_begin", "fill_end",
                "pointer_swap_begin", "pointer_low_store", "buffer_read", "start", "done")
    missing = [name for name in required if name not in labels]
    if missing:
        raise ValueError(f"Missing automatic-activation profiling labels: {','.join(missing)}")
    points = {name: int(labels[name]) for name in required if name not in ("buffer_read", "start", "done")}
    # Older auto candidates have no explicit label on this two-byte LDA zp.
    # Validate the executed opcode/operand below; never index PRG bytes at ZP.
    points["pointer_ready_read"] = int(labels.get("pointer_ready_read", labels["pointer_low_store"] - 2))
    for name in ("background_begin", "background_chunk", "c3_pump"):
        if name in labels:
            points[name] = int(labels[name])
    kernels = {}
    for kind, begin, end in (("slow", "c3_produce_block", "c3_produce_block_rts"),
                             ("fast", "c3_produce_fast_block", "c3_fast_block_rts"),
                             ("ended", "c3_emit_ended_block", "c3_ended_block_rts")):
        if begin in labels and end in labels:
            points[begin], points[end] = int(labels[begin]), int(labels[end])
            kernels[kind] = begin, end
    writer_addresses = sorted({int(value) for name, value in labels.items()
                               if name.startswith("c3_ring_store") or name in ("c3_neutral_store", "c3_muted_store")})
    for index, address in enumerate(writer_addresses):
        points[f"c3_store_{index}"] = address
    raw = program.read_bytes()
    load = int.from_bytes(raw[:2], "little")
    if "c3_pump" in labels:
        target = int(labels["c3_pump"])
        instruction = bytes((0x20, target & 255, target >> 8))
        for offset in range(2, len(raw) - 2):
            if raw[offset:offset + 3] == instruction:
                site = load + offset - 2
                points[f"c3_call_{site:04x}"] = site
                points[f"c3_resume_{site:04x}"] = site + 3
    by_address = {}
    for name, address in points.items():
        by_address.setdefault(address, []).append(name)
    monitor, log, dump, stats_path = (out / name for name in
                                      ("cpu.mon", "cpu-monitor.log", "registers.txt", "stats.bin"))
    for path in (log, dump, stats_path):
        path.unlink(missing_ok=True)
    commands = [f'logname "{log}"', "log on", f'load "{program}" 0',
                f'break exec ${labels["done"]:04x}']
    for checkpoint, address in enumerate(by_address, 2):
        commands.extend((f"trace exec ${address:04x}", f'command {checkpoint} "stopwatch"'))
    commands.extend((f'g ${labels["start"]:04x}',
                     f'bsave "{stats_path}" 0 $0002 $000d', "log off", "quit"))
    monitor.write_text("\n".join(commands) + "\n")
    settings = support.profile()
    duration = sum(counts) * PERIOD / support.CLOCK
    source_sha = _sha(program)
    command = ["rtk", "proxy", *settings.vice_command(), "-console", "-seed", "1",
               "-initbreak", "ready", "-moncommands", str(monitor), "-sounddev", "dump",
               "-soundarg", str(dump), "-warp", "-limitcycles", str(round((duration + 15) * support.CLOCK))]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=duration + 120)
    (out / "vice.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not all(path.exists() for path in (log, dump, stats_path)):
        raise RuntimeError(f"Automatic music CPU trace failed; inspect {out / 'vice.log'}")
    if _sha(program) != source_sha:
        raise ValueError("Program changed during the unmodified CPU measurement")
    events = {name: [] for name in points}
    snapshots, bodies = {}, {}
    trace = re.compile(r"^\.C:([0-9a-fA-F]{4})\s+(.*?)\s+- A:([0-9a-fA-F]{2}) X:([0-9a-fA-F]{2}) Y:([0-9a-fA-F]{2}).*\s(\d+)$")
    reached_done = False
    with log.open() as stream:
        for line in stream:
            match = trace.match(line)
            if not match:
                continue
            pc, body, a, x, y, clock = match.groups()
            pc, clock = int(pc, 16), int(clock)
            reached_done |= pc == int(labels["done"])
            for name in by_address.get(pc, ()):
                events[name].append(clock)
                bodies.setdefault(name, body)
                if name in ("pointer_ready_read", "pointer_low_store"):
                    snapshots.setdefault(name, []).append((clock, int(a, 16), int(x, 16), int(y, 16)))
    failures = []
    def require(condition, message):
        if not condition and len(failures) < 12:
            failures.append(message)
    entries, returns = events["nmi_entry"], events["nmi_rti"]
    boundaries = events["frame_boundary"]
    require(reached_done, "native done breakpoint not reached")
    require(len(entries) == sum(counts), f"NMI entries{len(entries)} expected{sum(counts)}")
    require(len(returns) in (len(entries) - 1, len(entries)), "NMI returns do not cover every completed interrupt")
    require(len(boundaries) == len(counts), f"boundaries{len(boundaries)} expected{len(counts)}")
    if not entries or not boundaries:
        raise ValueError(f"Missing native CPU events; inspect {log}")
    observed_counts, previous = [], 0
    for boundary in boundaries:
        consumed = bisect.bisect_right(entries, boundary)
        observed_counts.append(consumed - previous)
        previous = consumed
    require(observed_counts == counts, "actual boundary sample counts differ from source")
    starts, ends, costs = [], [], []
    regular, boundary_costs, pending_costs = Counter(), Counter(), Counter()
    boundary_indices = {bisect.bisect_right(entries, boundary) - 1 for boundary in boundaries}
    pending_indices = {index + 1 for index in boundary_indices if index + 1 < len(entries)}
    for index, (entry, ret) in enumerate(zip(entries, returns)):
        require(entry < ret, f"NMI{index} return precedes entry")
        if index + 1 < len(entries):
            require(ret + 6 <= entries[index + 1] - 7, f"NMI{index} overlaps next hardware entry")
        starts.append(entry - 7)
        ends.append(ret + 6)
        cost = ret - entry + 13
        costs.append(cost)
        (boundary_costs if index in boundary_indices else pending_costs if index in pending_indices else regular)[cost] += 1
    cumulative = [0]
    for cost in costs:
        cumulative.append(cumulative[-1] + cost)
    def overlap(begin, end):
        if end <= begin:
            return 0
        left, right = bisect.bisect_right(ends, begin), bisect.bisect_left(starts, end)
        if left >= right:
            return 0
        return (cumulative[right] - cumulative[left] - max(0, begin - starts[left])
                - max(0, ends[right - 1] - end))
    begins, finishes = events["fill_begin"], events["fill_end"]
    require(len(begins) == len(finishes) == len(counts), "not exactly one completed RLE fill per source frame")
    activations, reads, stores = (events[name] for name in
                                  ("pointer_swap_begin", "pointer_ready_read", "pointer_low_store"))
    require(len(activations) == len(reads) == len(stores), "activation/read/store counts differ")
    require(len(activations) in (len(counts) - 1, len(counts)), "unexpected automatic activation count")
    low_body = bodies.get("pointer_low_store", "")
    ready_body = bodies.get("pointer_ready_read", "")
    require(low_body.split()[:1] == ["85"], "activation low store is not the measured three-cycle STA zero-page")
    require(ready_body.split()[:1] == ["A5"], "ready shadow read is not three-cycle LDA zero-page")
    low_operand = re.search(r"\bSTA\s+\$([0-9a-fA-F]+)\b", low_body)
    require(low_operand is not None and int(low_operand[1], 16) == int(labels["buffer_read"]) + 1,
            "activation low store does not target the sample read operand")
    rows, activation_rows = [], []
    active_count = min(len(counts) - 1, len(activations))
    for index, (begin, end) in enumerate(zip(begins, finishes)):
        require(begin < end, f"RLE fill{index} markers reversed")
        stolen = overlap(begin, end)
        row = {"frame": index, "samples_generated": counts[index],
               "fill_begin_cycle": begin, "fill_rts_cycle": end,
               "fill_wall_cycles_before_rts": end - begin,
               "nmi_cycles_during_fill": stolen,
               "fill_foreground_cycles_before_rts": end - begin - stolen}
        if index and index - 1 < active_count:
            ready, deadline = end + 6, reads[index - 1] + 2
            boundary = boundaries[index - 1]
            nmi_index = bisect.bisect_right(entries, boundary) - 1
            hardware = entries[nmi_index] - 7
            row.update(deadline_cycle=deadline, boundary_nmi_hardware_entry=hardware,
                       fill_return_complete_cycle=ready,
                       deadline_slack_wall_cycles=deadline - ready,
                       deadline_slack_foreground_cycles=deadline - ready - overlap(ready, deadline),
                       fill_return_margin_before_boundary_hardware_entry=hardware - ready)
            require(ready <= hardware, f"RLE fill{index} returns after its activation NMI began")
            require(ready < deadline, f"RLE fill{index} misses actual ready-shadow read")
        if index >= 2 and index - 2 < active_count:
            activation_complete = stores[index - 2] + 3
            row["restart_wall_cycles_after_previous_activation"] = begin - activation_complete
            row["restart_foreground_cycles_after_previous_activation"] = begin - activation_complete - overlap(activation_complete, begin)
        rows.append(row)
    for index in range(active_count):
        begin, read, store = activations[index], reads[index], stores[index]
        boundary = boundaries[index]
        nmi_index = bisect.bisect_right(entries, boundary) - 1
        require(boundary <= begin < read < store, f"activation{index} instruction order invalid")
        require(nmi_index + 1 < len(entries) and store + 3 <= entries[nmi_index + 1] - 7,
                f"activation{index} pointer not complete before next hardware entry")
        got_low = snapshots["pointer_low_store"][index][1]
        wanted_low = 256 - counts[index + 1]
        require(got_low == wanted_low, f"activation{index} low value{got_low} expected{wanted_low}")
        got_high = snapshots["pointer_ready_read"][index][1]
        wanted_high = int(labels["buffer_b"] if index % 2 == 0 else labels["buffer_a"]) >> 8
        require(got_high == wanted_high, f"activation{index} wrong alternating buffer page")
        activation_rows.append({"activated_frame": index + 1, "boundary_cycle": boundary,
                                "shadow_read_bus_cycle": read + 2,
                                "low_pointer_store_bus_cycle": store + 2,
                                "pointer_complete_cycle": store + 3,
                                "activation_instruction_cycles": store + 3 - begin,
                                "margin_before_next_nmi_hardware_entry": entries[nmi_index + 1] - 7 - store - 3})

    writes = sorted(clock for name in events if name.startswith("c3_store_") for clock in events[name])
    call_starts = sorted(clock for name in events if name.startswith("c3_call_") for clock in events[name])
    call_ends = sorted(clock for name in events if name.startswith("c3_resume_") for clock in events[name])
    require(len(call_starts) - len(call_ends) in (0, 1), "C3 JSR/resume events are not paired")
    call_rows = []
    for index, (begin, end) in enumerate(zip(call_starts, call_ends)):
        require(begin < end and (index + 1 == len(call_starts) or end < call_starts[index + 1]),
                f"C3 call{index} is not ordered")
        values = bisect.bisect_left(writes, end) - bisect.bisect_left(writes, begin)
        call_rows.append({"call": index, "begin_cycle": begin, "resume_cycle": end,
                          "outputs": values, "wall_cycles_including_jsr_rts": end - begin,
                          "foreground_cycles_including_jsr_rts": end - begin - overlap(begin, end)})
    kernel_rows = []
    for kind, (begin_name, end_name) in kernels.items():
        require(len(events[begin_name]) - len(events[end_name]) in (0, 1), f"{kind} kernel entry/RTS mismatch")
        for begin, end in zip(events[begin_name], events[end_name]):
            require(begin < end, f"{kind} kernel reversed markers")
            kernel_rows.append({"kind": kind, "begin_cycle": begin,
                                "outputs": bisect.bisect_left(writes, end) - bisect.bisect_left(writes, begin),
                                "foreground_cycles_including_jsr_rts": end + 6 - begin - overlap(begin, end + 6) + 6})
    clock, latch_count, last_latch = 0, 0, None
    gaps = Counter()
    first_latch = None
    with dump.open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) != 3:
                continue
            delta, register, value = map(int, fields)
            clock += delta
            if register & 31 == 18 and value == 17:
                latch_count += 1
                if latch_count > 1:
                    if first_latch is None:
                        first_latch = clock
                    else:
                        gaps[clock - last_latch] += 1
                    last_latch = clock
    require(latch_count - 1 == sum(counts) and set(gaps) == {126}, "profiler run lost the fixed126cycle sample clock")
    stats = stats_path.read_bytes()
    generated, underruns = int.from_bytes(stats[8:10], "little"), stats[6]
    require(generated == len(counts) and underruns == 0, "native frame/underrun counters failed")
    active = [row for row in rows if "deadline_cycle" in row]
    pump_outputs = sum(row["outputs"] for row in call_rows)
    pump_cpu = sum(row["foreground_cycles_including_jsr_rts"] for row in call_rows)
    kernel_cpu = sum(row["foreground_cycles_including_jsr_rts"] for row in kernel_rows)
    background_costs = _background_costs(events, overlap, call_rows, begins)
    details = {"frames": rows, "activations": activation_rows, "c3_calls": call_rows,
               "c3_kernels": kernel_rows, "instruction_markers": points,
               "expected_frame_counts": counts, "observed_frame_counts": observed_counts,
               "failures": failures}
    (out / "cpu-frames.json").write_text(json.dumps(details, indent=2) + "\n")
    result = {"passed": not failures, "program_sha256": source_sha, "profile": settings.PROFILE,
              "frames": len(counts), "samples": sum(counts), "generated_frames": generated,
              "underruns": underruns, "sample_period_cycles": PERIOD,
              "duration_s": duration, "sample_gap_counts": dict(gaps),
              "first_latch_cycle": first_latch,
              "nmi_full_cycles_regular": dict(sorted(regular.items())),
              "nmi_full_cycles_boundary": dict(sorted(boundary_costs.items())),
              "nmi_full_cycles_sid1_pending": dict(sorted(pending_costs.items())),
              "nmi_cpu_fraction": sum(costs) / (len(costs) * PERIOD),
              "maximum_nmi_cycles": max(costs),
              "automatic_activation_events": len(activations),
              "active_activations_checked": active_count,
              "unused_terminal_activations_ignored": len(activations) - active_count,
              "pointer_low_store_cycles": 3, "pointer_shadow_read_bus_offset_cycles": 2,
              "fill_wall_cycles_range_before_rts": _range([row["fill_wall_cycles_before_rts"] for row in active]),
              "fill_foreground_cycles_range_before_rts": _range([row["fill_foreground_cycles_before_rts"] for row in active]),
              "minimum_deadline_slack_wall_cycles": min((row["deadline_slack_wall_cycles"] for row in active), default=None),
              "minimum_deadline_slack_foreground_cycles": min((row["deadline_slack_foreground_cycles"] for row in active), default=None),
              "minimum_fill_return_margin_before_boundary_hardware_entry": min((row["fill_return_margin_before_boundary_hardware_entry"] for row in active), default=None),
              "fill_restart_foreground_cycles_after_previous_activation_range": _range([row["restart_foreground_cycles_after_previous_activation"] for row in rows if "restart_foreground_cycles_after_previous_activation" in row]),
              "minimum_pointer_commit_margin_before_next_nmi": min((row["margin_before_next_nmi_hardware_entry"] for row in activation_rows), default=None),
              "c3_completed_pump_calls": len(call_rows), "c3_terminal_interrupted_calls": len(call_starts) - len(call_ends),
              "c3_pump_outputs": pump_outputs,
              "c3_required_ring_values": (sum(counts) + 1) // 4,
              "c3_production_count_complete": pump_outputs == (sum(counts) + 1) // 4,
              "c3_pump_cpu_cycles_including_manager_jsr_rts": pump_cpu,
              "c3_pump_cycles_per_output_including_manager": pump_cpu / pump_outputs if pump_outputs else None,
              "c3_pump_call_foreground_cycles_range": _range([row["foreground_cycles_including_jsr_rts"] for row in call_rows]),
              "c3_kernel_cpu_cycles_including_jsr_rts": kernel_cpu,
              "c3_kernel_cycles_per_output": kernel_cpu / pump_outputs if pump_outputs else None,
              "c3_manager_cycles_above_kernel_calls": pump_cpu - kernel_cpu,
              "c3_pump_calls_by_output_count": {str(count): {"calls": len(values), "foreground_cycles_range": _range(values)}
                                                  for count, values in sorted({n: [row["foreground_cycles_including_jsr_rts"] for row in call_rows if row["outputs"] == n]
                                                                             for n in {row["outputs"] for row in call_rows}}.items())},
              "monitor_log_sha256": _sha(log), "register_dump_sha256": _sha(dump),
              "failures": failures,
              "scope": "Unmodified automatic-activation PRG. Every NMI/boundary, exact buffer length and126cycle latch clock checked. RLE fills meet the actual NMI shadow-read deadline; no foreground wait/pointer-swap gate. Costs include hardware entry/RTI and JSR/RTS as stated; final nonreturning NMI is excluded from averages. Ring generations and audio quality require separate proofs."}
    result.update(background_costs)
    (out / "cpu-budget.json").write_text(json.dumps(result, indent=2) + "\n")
    if failures:
        raise ValueError(f"Automatic music CPU verification failed: {'; '.join(failures[:3])}; see {out / 'cpu-budget.json'}")
    return result
