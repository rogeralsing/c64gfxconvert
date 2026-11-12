"""Strict streaming verification of the integrated native dual-sampler music.

Every musical SID2/SID3 write is checked in order, including the last SID2
phase after the final SID3 prefix. Only explicit zero-control shutdown writes
after that phase are excluded. Failure reports retain a few examples, not the
complete multi-megabyte trace.
"""
from __future__ import annotations

from collections import Counter, deque
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLER = HERE.parent
PERIOD = 126


class _Ordered:
    def __init__(self, wanted):
        self.iterator = iter(wanted)
        self.expected = next(self.iterator, None)
        self.observed = self.mismatches = 0
        self.first = []

    def consume(self, event):
        if event != self.expected:
            self.mismatches += 1
            if len(self.first) < 8:
                self.first.append({"index": self.observed,
                                   "observed": event, "expected": self.expected})
        self.observed += 1
        self.expected = next(self.iterator, None)

    def finish(self):
        missing = 0
        while self.expected is not None:
            if not missing and len(self.first) < 8:
                self.first.append({"index": self.observed,
                                   "observed": None, "expected": self.expected})
            missing += 1
            self.expected = next(self.iterator, None)
        self.mismatches += missing
        return self.mismatches == 0


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source(c3expectedpath, directmeta, out):
    metadata = None
    if isinstance(directmeta, dict):
        metadata = directmeta
    elif directmeta is not None:
        path = Path(directmeta)
        path = path / "metadata.json" if path.is_dir() else path
        metadata = json.loads(path.read_text())
        if c3expectedpath is None:
            c3expectedpath = path.parent / "expected-high.bin"
    if c3expectedpath is None and metadata is not None:
        c3expectedpath = metadata.get("expected_high_file") or out / "c3/expected-high.bin"
    if c3expectedpath is None:
        raise ValueError("Supply the bound expected-high path or direct metadata")
    path = Path(c3expectedpath).resolve()
    expected = path.read_bytes()
    if metadata and metadata.get("expected_high_sha256") not in (None, _sha(expected)):
        raise ValueError("Bound C3 expected-high bytes differ from their metadata")
    return expected, metadata, path


def verify(build: dict, receipt: dict, pcm: dict, rows: list[list[int]],
           out: Path, c3expectedpath: Path | None = None, *,
           directmeta: dict | Path | None = None,
           ring_counters: dict | None = None,
           sid2_muted: bool = False,
           baseline_first_latch_cycle: int | None = 2191487) -> dict:
    """Verify actual SID dump against the two independent input models.

    Rows may have three SID1 fields or the original six ordinary-voice fields;
    only their first three fields are the preserved ordinary SID1 part.
    ``ring_counters`` can supply named runtime underrun/overrun/error counts once
    the producer exports them. They are also accepted in the capture receipt.
    """
    out = Path(out).resolve()
    expected3 = (out / "expected-input.bin").read_bytes()
    expected2, meta2, source2 = _source(c3expectedpath, directmeta, out)
    counts = pcm["frame_sample_counts_exact"]
    if len(counts) != pcm["frames"] or len(rows) != len(counts):
        raise ValueError("Frame counts and SID1 rows must cover the prepared phrase")
    if any(type(count) is not int or not 1 <= count <= 256 for count in counts):
        raise ValueError("Every SID3 buffer needs an explicit positive byte-sized count")
    if sum(counts) != len(expected3) or pcm["input_codes"] != len(expected3):
        raise ValueError("SID3 expected input length differs from the frame clock")
    if any(len(row) < 3 for row in rows):
        raise ValueError("Every original frame must include all three SID1 fields")
    total = len(expected3)
    if total % 4 != 1 or len(expected2) != (total + 1) // 4:
        raise ValueError("Bound phrase must finish on SID2 phase0 and cover every phase2 ring read")
    neutral2 = meta2.get("neutral_frequency_high", 54) if meta2 else 54
    enable2, release2 = (25, 9) if sid2_muted else (17, 1)
    if meta2 and (meta2.get("hold_cycles") != 249 or meta2.get("reference_hold_cycles") != 105):
        raise ValueError("This measured ISR requires direct data translated with249/105cycles")
    if meta2 and meta2.get("startup_neutral_values", 1) != 1:
        raise ValueError("The native first SID2 latch must consume exactly one startup neutral")
    cuts = [0]
    for count in counts:
        cuts.append(cuts[-1] + count)

    def wanted3(first):
        for index, value in enumerate(expected3):
            time = first + index * PERIOD
            yield time, 18, 17
            yield time + 6, 18, 1
            yield time + 12, 18, 9
            yield time + 20, 15, value
            yield time + 26, 18, 1

    def wanted2(first):
        index2 = 0
        for index in range(total):
            time = first + index * PERIOD
            if index % 4 == 0:
                yield time + 35, 11, enable2
                yield time + 41, 11, 9
            elif index % 4 == 2:
                yield time + 37, 8, expected2[index2]
                yield time + 43, 11, release2
                index2 += 1

    def wanted1(first):
        for frame in range(1, len(counts)):
            time = first + cuts[frame] * PERIOD
            for field, (register, offset) in enumerate(((0, 53), (1, 60), (4, 67))):
                yield time + offset, register, rows[frame][field]

    clock = event_count = startup_latches = 0
    first = last = active_end = None
    previous_latch3 = previous_latch2 = None
    latch3_count = latch2_count = high2_count = input3_count = 0
    gaps3, gaps2 = Counter(), Counter()
    pre1, pre2, pre_master = deque(maxlen=3), {}, None
    startup1, startup2 = [], {}
    check1 = check2 = check3 = None
    shutdown, unexpected_shutdown = Counter(), []
    master_events = []
    unplanned_filter_writes = []
    parse_errors = []
    startup_master = None
    with Path(receipt["media"]).open() as stream:
        for line_number, line in enumerate(stream, 1):
            fields = line.split()
            if len(fields) != 3:
                continue
            try:
                delta, address, value = map(int, fields)
            except ValueError:
                continue
            if delta < 0 or not 0 <= value <= 255:
                if len(parse_errors) < 8:
                    parse_errors.append({"line": line_number, "delta": delta, "value": value})
            clock += delta
            register = address & 31
            event = clock, register, value
            event_count += 1
            if first is None:
                if register in (0, 1, 4):
                    pre1.append(event)
                elif register in (7, 8, 11):
                    pre2[register] = event
                elif register == 24:
                    pre_master = event
                if register == 18 and value == 17:
                    startup_latches += 1
                    if startup_latches == 2:
                        first = clock
                        last = first + (total - 1) * PERIOD
                        # Last index is phase0: include its SID2 TEST write.
                        active_end = last + 41
                        startup1 = list(pre1)
                        startup2 = dict(pre2)
                        startup_master = pre_master
                        check1, check2, check3 = (_Ordered(wanted1(first)),
                                                 _Ordered(wanted2(first)),
                                                 _Ordered(wanted3(first)))
                if first is None:
                    continue

            if register == 18 and value == 17:
                latch3_count += 1
                if previous_latch3 is not None:
                    gaps3[clock - previous_latch3] += 1
                previous_latch3 = clock
            if register == 15:
                input3_count += 1
            if register == 11 and value == enable2:
                latch2_count += 1
                if previous_latch2 is not None:
                    gaps2[clock - previous_latch2] += 1
                previous_latch2 = clock
            if register == 8:
                high2_count += 1

            if 14 <= register <= 20:
                if clock > active_end and register == 18 and value == 0 and check3.expected is None:
                    shutdown["sid3"] += 1
                else:
                    check3.consume(event)
            elif 7 <= register <= 13:
                if clock > active_end and register == 11 and value == 0 and check2.expected is None:
                    shutdown["sid2"] += 1
                else:
                    check2.consume(event)
            elif 0 <= register <= 6:
                if clock > active_end and register == 4 and value == 0 and check1.expected is None:
                    shutdown["sid1"] += 1
                else:
                    check1.consume(event)
            elif register == 24:
                if clock > active_end and value == 0:
                    shutdown["master"] += 1
                elif len(master_events) < 8:
                    master_events.append(event)
            elif 21 <= register <= 23 and len(unplanned_filter_writes) < 8:
                unplanned_filter_writes.append(event)
            if any(value > 1 for value in shutdown.values()) and len(unexpected_shutdown) < 8:
                unexpected_shutdown.append(event)

    checks = [check1, check2, check3]
    exact1 = exact2 = exact3 = False
    if first is not None:
        exact1, exact2, exact3 = [check.finish() for check in checks]
    expected_startup1 = [(register, rows[0][field])
                         for field, register in enumerate((0, 1, 4))]
    startup1_exact = [(register, value) for _, register, value in startup1] == expected_startup1
    startup1_timing = (len(startup1) == 3 and startup1[1][0] - startup1[0][0] == 7
                       and startup1[2][0] - startup1[1][0] == 7
                       and first is not None and startup1[-1][0] < first)
    startup2_exact = all(register in startup2 and startup2[register][2] == value
                         for register, value in ((7, 0), (8, neutral2), (11, release2)))
    startup_master_exact = startup_master is not None and startup_master[2] & 15 == 15
    stats = bytes.fromhex(receipt["stats_hex"])
    if len(stats) < 10:
        raise ValueError("Capture statistics omit generated frame/underrun counters")
    generated, underruns = int.from_bytes(stats[8:10], "little"), stats[6]
    ring = dict(receipt.get("ring_counters", {}))
    if ring_counters is not None:
        ring.update(ring_counters)
    ring_errors = {name: value for name, value in ring.items()
                   if any(token in name.lower() for token in ("underrun", "overrun", "underflow", "overflow", "empty", "error", "hazard"))
                   and value != 0}
    baseline_first = baseline_first_latch_cycle
    report = {"profile": receipt["profile"], "program_sha256": build["program_sha256"],
              "trace_sha256": receipt["media_sha256"], "native_events_read": event_count,
              "expected_samples": total, "observed_latches": latch3_count,
              "input_codes_written": input3_count,
              "sid3_register_events": 0 if check3 is None else check3.observed,
              "sid3_complete_ordered_prefix_and_inputs_exact": exact3,
              "sample_gap_counts": dict(gaps3), "first_latch_cycle": first,
              "last_latch_cycle": previous_latch3, "music_end_cycle_including_sid2_phase": active_end,
              "sid2_expected_source": str(source2), "sid2_expected_high_sha256": _sha(expected2),
              "sid2_register_events": 0 if check2 is None else check2.observed,
              "sid2_all_ordered_phase_events_exact": exact2,
              "sid2_frequency_high_writes": high2_count,
              "sid2_latches_including_startup_neutral": latch2_count,
              "sid2_latch_gap_counts": dict(gaps2),
              "sid2_startup_values_exact": startup2_exact,
              "sid2_startup_registers": {str(register): event for register, event in startup2.items()},
              "sid2_startup_release_offset_from_first_sid3_latch":
                  startup2[11][0] - first if first is not None and 11 in startup2 else None,
              "sid2_frequency_low_unchanged_zero": startup2_exact and exact2,
              "sid2_clock": f"Global phases0/2 at SID3 indices0mod4/2mod4; never reset at50Hz. Phase0 CTRL{enable2}@+35,CTRL9@+41; phase2 high@+37,CTRL{release2}@+43. Lastphase0 fullychecked.",
              "sid2_muted": sid2_muted,
              "sid2_enable_control": enable2,
              "sid2_release_control": release2,
              "ordinary_sid1_writes_checked": (0 if check1 is None else check1.observed) + len(startup1),
              "ordinary_sid1_values_and_exact_timing": exact1 and startup1_exact and startup1_timing,
              "ordinary_sid1_startup_values_exact": startup1_exact,
              "ordinary_sid1_startup_offsets_from_first_latch": [time - first for time, _, _ in startup1] if first is not None else [],
              "ordinary_sid1_frame_offsets_after_first_nmi": [53, 60, 67],
              "baseline_first_latch_cycle": baseline_first,
              "first_latch_matches_approved_absolute_phase": first == baseline_first,
              "first_latch_shift_from_approved_cycles": first - baseline_first if first is not None and baseline_first is not None else None,
              "absolute_startup_phase_is_a_gate": False,
              "generated_frames": generated, "underruns": underruns,
              "ring_counters": ring, "ring_error_counters": ring_errors,
              "ring_counter_coverage": bool(ring),
              "master_volume_start_exact": startup_master_exact,
              "d418_writes_during_music": master_events,
              "unplanned_filter_writes": unplanned_filter_writes,
              "explicit_shutdown_zero_writes": dict(shutdown),
              "unexpected_duplicate_shutdown_events": unexpected_shutdown,
              "parse_errors": parse_errors,
              "scope": "Every native SID3 input/prefix and SID2 phase write, global126/504cycle clocks, startup neutral state, every SID1 score value and poststartup exact slot, complete frame counter and available runtime error counters. Digital correctness does not establish timbre, balance or physical SID fidelity. Absolute startup phase is reported pending calibration."}
    report["passed"] = (first is not None and latch3_count == total and input3_count == total
                        and exact3 and set(gaps3) == {126}
                        and exact2 and high2_count == len(expected2)
                        and latch2_count == len(expected2) + 1 and set(gaps2) == {504}
                        and startup2_exact and exact1 and startup1_exact and startup1_timing
                        and generated == pcm["frames"] and not underruns
                        and not ring_errors and startup_master_exact and not master_events
                        and not unplanned_filter_writes and not unexpected_shutdown and not parse_errors)
    for name, check in (("sid1", check1), ("sid2", check2), ("sid3", check3)):
        report[f"{name}_event_mismatches"] = None if check is None else check.mismatches
        report[f"first_{name}_mismatches"] = [] if check is None else check.first
    output = out / "player-check.json"
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if not report["passed"]:
        failures = [name for name, passed in (("SID3", exact3), ("SID2", exact2 and startup2_exact),
                                              ("SID1", exact1 and startup1_exact and startup1_timing),
                                              ("runtime", generated == pcm["frames"] and not underruns and not ring_errors),
                                              ("master", startup_master_exact and not master_events)) if not passed]
        raise ValueError(f"Integrated native verification failed ({','.join(failures) or 'counts/clock/shutdown'}); see {output}")
    return report
