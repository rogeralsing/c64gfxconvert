"""Verify complete oscillator-sampled performances without retaining SID dumps.

Sample values and clock intervals are checked while reading the trace. Only
ordinary SID voice writes are retained, so long songs do not allocate millions
of Python event tuples.
"""
from __future__ import annotations

from array import array
from collections import Counter
import json
from pathlib import Path

CLOCK, PERIOD = 985248, 126
REGISTERS = (0, 1, 4, 7, 8, 11)


def verify(compiled: dict, receipt: dict, pcm: dict, rows: list[list[int]],
           out: Path) -> dict:
    """Check every input, latch and ordered synth write over the whole trace."""
    expected = (out / "expected-input.bin").read_bytes()
    if len(rows) != pcm["frames"] or any(len(row) != len(REGISTERS) for row in rows):
        raise ValueError("Expected six SID fields for every prepared frame")
    synth_cycles, synth_registers, synth_values = array("q"), bytearray(), bytearray()
    clock = event_count = latch_pulses = latches = input_count = mismatches = 0
    first_latch = last_latch = master_on = None
    first_input_mismatches, master_events = [], []
    gaps = Counter()
    with Path(receipt["media"]).open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) != 3:
                continue
            delta, address, value = map(int, fields)
            clock += delta
            register = address & 31
            event_count += 1
            if register == 18 and value == 0x11:
                latch_pulses += 1
                # The first pulse establishes the initial neutral held level.
                if latch_pulses > 1:
                    if first_latch is None:
                        first_latch = clock
                    else:
                        gaps[clock - last_latch] += 1
                    last_latch = clock
                    latches += 1
            if register == 15 and first_latch is not None and clock > first_latch:
                wanted = expected[input_count] if input_count < len(expected) else None
                if value != wanted:
                    mismatches += 1
                    if len(first_input_mismatches) < 16:
                        first_input_mismatches.append({"index": input_count,
                                                       "expected": wanted, "observed": value})
                input_count += 1
            if register == 24:
                if value == 15 and master_on is None:
                    master_on = clock
                if first_latch is not None:
                    master_events.append((clock, value))
            if master_on is not None and clock > master_on and register in REGISTERS:
                synth_cycles.append(clock)
                synth_registers.append(register)
                synth_values.append(value)
    if input_count < len(expected):
        missing = len(expected) - input_count
        mismatches += missing
        if len(first_input_mismatches) < 16:
            first_input_mismatches.append({"index": input_count, "missing_values": missing})
    sample_match = input_count == len(expected) and mismatches == 0

    # Finish disables the synth voices after the final latch; those writes
    # belong to shutdown rather than the prepared musical score.
    synth_count = 0
    if last_latch is not None:
        for cycle in synth_cycles:
            if cycle > last_latch:
                break
            synth_count += 1
    expected_synth_count = len(rows) * len(REGISTERS)
    synth_mismatches, first_synth_mismatches = 0, []
    for index in range(synth_count):
        if index < expected_synth_count:
            frame, field = divmod(index, len(REGISTERS))
            wanted = (REGISTERS[field], rows[frame][field])
        else:
            wanted = None
        observed = (synth_registers[index], synth_values[index])
        if observed != wanted:
            synth_mismatches += 1
            if len(first_synth_mismatches) < 16:
                first_synth_mismatches.append({"index": index, "expected": wanted,
                                               "observed": observed})
    synth_mismatches += max(0, expected_synth_count - synth_count)
    same_synth = synth_count == expected_synth_count and not synth_mismatches
    timing_errors, minimum_offset, maximum_offset = 0, None, None
    if same_synth and first_latch is not None:
        for index in range(synth_count):
            frame = index // len(REGISTERS)
            cycle = synth_cycles[index]
            if frame == 0:
                timing_errors += cycle >= first_latch
            else:
                cut = (frame * CLOCK + PERIOD * 25) // (PERIOD * 50)
                boundary = first_latch + (cut - 1) * PERIOD
                offset = cycle - boundary
                minimum_offset = offset if minimum_offset is None else min(minimum_offset, offset)
                maximum_offset = offset if maximum_offset is None else max(maximum_offset, offset)
                timing_errors += not 0 <= offset <= 4 * PERIOD
    stats = bytes.fromhex(receipt["stats_hex"])
    generated, underruns = int.from_bytes(stats[8:10], "little"), stats[6]
    master_writes = [(cycle, value) for cycle, value in master_events
                     if first_latch is not None and first_latch <= cycle <= last_latch]
    result = {"profile": receipt["profile"], "program_sha256": compiled["program_sha256"],
              "trace_sha256": receipt["media_sha256"], "expected_samples": len(expected),
              "observed_latches": latches, "input_codes_written": input_count,
              "all_sample_inputs_match_independent_model": sample_match,
              "input_mismatches": mismatches, "first_input_mismatches": first_input_mismatches,
              "sample_gap_counts": dict(gaps), "first_latch_cycle": first_latch,
              "last_latch_cycle": last_latch, "generated_frames": generated,
              "underruns": underruns, "ordinary_sid_writes_checked": synth_count,
              "ordinary_sid_sequence_matches": same_synth,
              "ordinary_sid_write_mismatches": synth_mismatches,
              "first_synth_mismatches": first_synth_mismatches,
              "synth_frame_timing_errors": timing_errors,
              "synth_commit_offset_cycles_after_boundary_latch":
                  [minimum_offset, maximum_offset] if minimum_offset is not None else [],
              "d418_writes_during_music": master_writes,
              "native_events_read": event_count,
              "retained_synth_event_bytes": len(synth_cycles) * synth_cycles.itemsize
                  + len(synth_registers) + len(synth_values),
              "scope": "Streaming verification of every sampled input and latch, every ordered ordinary-voice frequency/control write and its frame, completed buffers and constant master volume. Does not establish original timbre, physical SID fidelity or perceived balance."}
    result["passed"] = (sample_match and latches == len(expected) and set(gaps) == {PERIOD}
                        and generated == pcm["frames"] and not underruns and same_synth
                        and not timing_errors and not master_writes)
    (out / "player-check.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if not result["passed"]:
        raise ValueError(f"Native streaming verification failed: {result}")
    return result
