"""Build and verify the complete, explicitly arranged Hyperbased performance.

This is called by build_linus_mix.py. The bounded listening reference remains
separate; a full performance must pass native checks before being published.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
import soundfile as sf

import native_support as support

HERE = Path(__file__).resolve().parent
CLOCK, PERIOD = support.CLOCK, support.PERIOD
REFERENCE = HERE / "work/hyperbased/linus-mix"
LISTENING_GAIN = 3.6308204724132565


def reference_hashes() -> dict[str, str]:
    return {p.name: support.digest(p) for p in REFERENCE.iterdir()
            if p.suffix in (".prg", ".wav")}


def write_coverage(out: Path) -> dict:
    """Keep every omitted passage reviewable without publishing raw traces."""
    routing_path = out / "instruments/routing.json"
    routing = json.loads(routing_path.read_text())
    omitted = {}
    for row in routing["omissions"]:
        for channel, instrument in zip(row["channels"], row["instruments"]):
            omitted.setdefault((channel, instrument), []).append(row["tick"])
    spans, totals = [], {}
    for (channel, instrument), ticks in sorted(omitted.items()):
        totals[str(channel)] = totals.get(str(channel), 0) + len(ticks) / 50
        start = previous = ticks[0]
        for tick in ticks[1:] + [None]:
            if tick is not None and tick == previous + 1:
                previous = tick
                continue
            spans.append({"source_channel": channel, "instrument": instrument,
                          "start_s": start / 50, "end_s": (previous + 1) / 50,
                          "ticks": previous - start + 1})
            start = previous = tick
    report = {"source_channels": 4, "omitted_channel_seconds": totals,
              "omitted_passages": spans, "routing_sha256": support.digest(routing_path),
              "scope": "Every omitted active source tick, grouped into exact contiguous passages. Channel seconds can overlap; they are not silent seconds in the complete mix."}
    support.save(out / "coverage.json", report)
    return report


def verify_trace(build: dict, receipt: dict, prepared: dict, rows: list,
                 expected: bytes, out: Path, enabled=(True, True, True)) -> dict:
    """Check every sample prefix and every ordinary-voice value in VICE's dump.

    Ordinary-voice writes outside the NMI may vary in phase, but must occur in
    their assigned tick. No host audio comparison substitutes for this proof.
    """
    counts = prepared["frame_sample_counts_exact"]
    cuts = np.r_[0, np.cumsum(counts)].astype(np.int64)
    tick_cycles = cuts * PERIOD
    sid1_gates = {int(time) - 67: tick for tick, time in enumerate(tick_cycles[1:-1], 1)}
    assert len(rows) == len(counts) and len(expected) == int(cuts[-1])
    prefix = ((0, 18, 17), (6, 18, 1), (12, 18, 9),
              (20, 15, None), (26, 18, 1))
    first, clock, enables, position = None, 0, 0, 0
    mismatches, examples = 0, []
    startup = deque(maxlen=64)
    voices = [0, 0]
    fields = {0: (0, 0), 1: (0, 1), 4: (0, 2), 2: (0, 3),
              3: (0, 4), 6: (0, 5), 7: (1, 0), 8: (1, 1),
              11: (1, 2), 9: (1, 3), 10: (1, 4), 13: (1, 5)}
    ordinary_counts = np.zeros((len(rows), 12), dtype=np.int32)
    shutdown, master, sid1_offsets = [], [], []
    gate_writes = 0

    def mismatch(observed, wanted):
        nonlocal mismatches
        mismatches += 1
        if len(examples) < 8:
            examples.append({"observed": observed, "expected": wanted})

    with Path(receipt["media"]).open() as stream:
        for line in stream:
            values = line.split()
            if len(values) != 3:
                continue
            delta, register, value = map(int, values)
            clock += delta
            register &= 31
            if register == 18 and value == 17:
                enables += 1
                if enables == 2:
                    first = clock
            if first is None:
                startup.append((clock, register, value))
                continue
            relative = clock - first
            if register in (15, 18):
                if position < len(expected) * 5:
                    sample, field = divmod(position, 5)
                    offset, wanted_register, wanted_value = prefix[field]
                    if wanted_value is None:
                        wanted_value = expected[sample]
                    wanted = (sample * PERIOD + offset, wanted_register, wanted_value)
                    observed = (relative, register, value)
                    if observed != wanted:
                        mismatch(observed, wanted)
                    position += 1
                else:
                    shutdown.append((relative, register, value))
            elif register == 24:
                master.append((relative, value))
            elif register in fields:
                if relative > (len(expected) - 1) * PERIOD + 26:
                    shutdown.append((relative, register, value))
                    continue
                voice, field = fields[register]
                if register == 4 and relative in sid1_gates:
                    tick = sid1_gates[relative]
                    descriptors = prepared.get("score_rows")
                    continuous = descriptors is not None and descriptors[tick][1] & 1
                    wanted = rows[tick - 1 if continuous else tick][2] if enabled[0] else 24
                    if not continuous and rows[tick][23] & 1:
                        wanted &= 254
                    if value != wanted:
                        mismatch((tick, "gate", value), (tick, "gate", wanted))
                    gate_writes += 1
                    continue
                tick = int(np.searchsorted(tick_cycles, relative, side="right") - 1)
                if not 0 <= tick < len(rows):
                    mismatch((relative, register, value), "ordinary write inside a source tick")
                    continue
                wanted = rows[tick][voice * 6 + field]
                if not enabled[voice]:
                    wanted = 24 if field == 2 else 0 if field in (0, 1, 5) else wanted
                if register == 11 and ordinary_counts[tick, 8] == 0 and rows[tick][23] & 2:
                    wanted &= 254
                if value != wanted:
                    mismatch((tick, register, value), (tick, register, wanted))
                ordinary_counts[tick, voice * 6 + field] += 1
                voices[voice] += 1
                if voice == 0 and field < 3 and tick:
                    offset = relative - int(cuts[tick]) * PERIOD
                    sid1_offsets.append(offset)
                    if offset != (53, 60, 67)[field]:
                        mismatch((tick, register, offset), (tick, register, (53, 60, 67)[field]))

    stats = bytes.fromhex(receipt["stats_hex"])
    underruns = int.from_bytes(stats[6:8], "little")
    generated = int.from_bytes(stats[8:10], "little")
    if position != len(expected) * 5:
        mismatch(position, len(expected) * 5)
    if generated != len(rows) or underruns:
        mismatch({"generated": generated, "underruns": underruns},
                 {"generated": len(rows), "underruns": 0})
    last = (len(expected) - 1) * PERIOD
    if any(time <= last + 26 for time, _ in master) or len(master) != 1 or master[0][1] != 0:
        mismatch(master, "one zero master write after the final sample prefix")
    wanted_shutdown = [(last + 76, 4, 0), (last + 80, 11, 0), (last + 84, 18, 0)]
    if shutdown != wanted_shutdown or master != [(last + 88, 0)]:
        mismatch({"voices": shutdown, "master": master},
                 {"voices": wanted_shutdown, "master": [(last + 88, 0)]})
    # Frame zero is committed before sampling; every later frame must have all
    # twelve ordinary-voice writes. Startup values are checked separately below.
    wanted_counts = np.ones_like(ordinary_counts[1:])
    wanted_counts[:, 8] = 2
    if not np.all(ordinary_counts[1:] == wanted_counts):
        bad = np.argwhere(ordinary_counts[1:] != wanted_counts)[:8]
        mismatch(bad.tolist(), "one write per ordinary register per tick")
    if gate_writes != len(rows) - 1:
        mismatch(gate_writes, len(rows) - 1)
    if first is None:
        mismatch(None, "first native sample latch")
    else:
        startup_master = next((value for _, register, value in reversed(startup) if register == 24), None)
        wanted_master = 15 if enabled[2] else 143
        if startup_master != wanted_master:
            mismatch(("startup", 24, startup_master), ("startup", 24, wanted_master))
        for register, (voice, field) in fields.items():
            initial = next((value for _, reg, value in reversed(startup) if reg == register), None)
            wanted = rows[0][voice * 6 + field]
            if not enabled[voice]:
                wanted = 24 if field == 2 else 0 if field in (0, 1, 5) else wanted
            if initial != wanted:
                mismatch(("startup", register, initial), ("startup", register, wanted))
    result = {"passed": mismatches == 0, "first_latch_cycle": first,
              "frames": generated, "underruns": underruns,
              "sample_values": len(expected), "sample_period_cycles": PERIOD,
              "every_sample_value_and_prefix_checked": True,
              "ordinary_voice_writes": voices,
              "sid1_boundary_gate_prewrites": gate_writes,
              "SID1_fixed_offsets": sorted(set(sid1_offsets)),
              "master_volume_constant_during_stream": not any(t <= last + 26 for t, _ in master),
              "expected_input_sha256": hashlib.sha256(expected).hexdigest(),
              "trace_sha256": receipt["media_sha256"], "mismatches": mismatches,
              "first_mismatches": examples, "shutdown": shutdown,
              "enabled_physical_outputs": list(enabled)}
    support.save(out / "player-check.json", result)
    if mismatches:
        raise ValueError(f"Full-length native proof failed: {examples}")
    return result


def capture_audio(build: dict, folder: Path, duration: float, first_latch: int, frames: int) -> tuple:
    receipt = support.capture(build, folder, duration, audio=True)
    support.save(folder / "receipt.json", receipt)
    return read_audio_capture(receipt, duration, first_latch, frames)


def read_audio_capture(receipt: dict, duration: float, first_latch: int, frames: int) -> tuple:
    stats = bytes.fromhex(receipt["stats_hex"])
    if int.from_bytes(stats[6:8], "little"):
        raise ValueError("Audio run missed a native buffer")
    if int.from_bytes(stats[8:10], "little") != frames:
        raise ValueError("Audio run did not complete every source tick")
    raw, rate = sf.read(receipt["media"], dtype="float64", always_2d=True)
    assert rate == 22050 and raw.shape[1] == 1
    start = round(first_latch * rate / CLOCK)
    count = round(duration * rate)
    signal = raw[start:start + count, 0].copy()
    if len(signal) != count:
        raise ValueError("Incomplete full-length VICE WAV")
    signal -= signal.mean()
    return signal, rate, receipt


def link_instruments(prepared: dict, out: Path) -> tuple[list, Path, dict]:
    """Link reusable banks in stock RAM, leaving one contiguous score arena."""
    out.mkdir(parents=True, exist_ok=True)
    pages = prepared["triangle_pages"]
    triangle_end = 0x1000 + len(pages) * 256
    if triangle_end > 0x7000:
        raise ValueError("Triangle volume tables exceed the low asset arena")
    free = [[triangle_end, 0x7000], [0x8000, 0xd000]]
    assets, addresses = prepared["assets"], {}
    for asset in sorted(assets, key=lambda item: -len(item["data"])):
        size = len(asset["data"])
        arena = next((pair for pair in free if pair[1] - pair[0] >= size), None)
        if arena is None:
            raise ValueError(f"Reusable PCM bank {asset['id']} does not fit stock RAM")
        addresses[asset["id"]] = arena[0]
        arena[0] += size
    score_arena = max(free, key=lambda pair: pair[1] - pair[0])
    rows, physical_rows = [], []
    for index, semantic in enumerate(prepared.get("score_rows", prepared["rows"])):
        row = list(semantic)
        if "score_rows" not in prepared:
            row[5] <<= 4
            row[11] <<= 4
        row[14] += 0x10
        asset = assets[row[16]]
        base = addresses[asset["id"]]
        end = base + asset["logical_bytes"]
        loop = base + asset["loop_offset"] if asset["loop_offset"] else 0
        if loop and end - loop < 157:
            raise ValueError("A native PCM loop must span at least 157 values")
        row[16:22] = [base & 255, base >> 8, end & 255, end >> 8, loop & 255, loop >> 8]
        rows.append(row)
        physical = list(prepared["rows"][index])
        physical[5] <<= 4
        physical[11] <<= 4
        physical[14:23] = row[14:23]
        physical_rows.append(physical)
    lines = ['.assert "Main code must leave instrument tables free", runtime_end <= $1000, true']
    for index, data in enumerate(pages):
        filename = out / f"triangle-{index:02d}.bin"
        filename.write_bytes(data)
        lines += [f'.pc = ${0x1000 + index * 256:04x} "Triangle volume table"',
                  f'.import binary "{filename.resolve()}"']
    for asset in assets:
        filename = out / f"pcm-{asset['id']:03d}.bin"
        filename.write_bytes(asset["data"])
        lines += [f'.pc = ${addresses[asset["id"]]:04x} "Reusable PCM instrument"',
                  f'.import binary "{filename.resolve()}"']
    data_asm = out / "data.asm"
    data_asm.write_text("\n".join(lines) + "\n")
    (out / "score-rows.bin").write_bytes(bytes(value for row in rows for value in row))
    (out / "physical-rows.bin").write_bytes(bytes(value for row in physical_rows for value in row))
    ledger = {"triangle_bytes": len(pages) * 256,
              "pcm_bytes_including_guards": sum(len(a["data"]) for a in assets),
              "asset_addresses": addresses, "remaining_arenas": free,
              "score_address": score_arena[0], "score_capacity": score_arena[1] - score_arena[0],
              "runtime_reserved": [[0x0801, 0x1000], [0x7000, 0x8000]],
              "decoder_code_reserved": [0xf000, 0xff00],
              "decoder_history_reserved": [0xe000, 0xf000],
              "external_memory": False}
    support.save(out / "memory-layout.json", ledger)
    return rows, data_asm, ledger


def measure_deadlines(build: dict, counts: list, out: Path) -> dict:
    """Trace every completed fill and its actual consuming pointer swap."""
    out.mkdir(parents=True, exist_ok=True)
    labels = build["symbols"]
    points = {name: labels[name] for name in ("fill_begin", "fill_end", "pointer_swap_begin")}
    log, stats, monitor = (out / name for name in ("deadlines.log", "stats.bin", "deadlines.mon"))
    for p in (log, stats):
        p.unlink(missing_ok=True)
    commands = [f'logname "{log.resolve()}"', "log on",
                f'load "{build["program"]}" 0', f'break exec ${labels["done"]:04x}']
    for checkpoint, address in enumerate(points.values(), 2):
        commands += [f'trace exec ${address:04x}', f'command {checkpoint} "stopwatch"']
    commands += [f'g ${labels["start"]:04x}',
                 f'bsave "{stats.resolve()}" 0 $0002 $000d', "log off", "quit"]
    monitor.write_text("\n".join(commands) + "\n")
    duration = sum(counts) * PERIOD / CLOCK
    command = ["rtk", "proxy", *support.profile().vice_command(), "-console", "-seed", "1",
               "-initbreak", "ready", "-moncommands", str(monitor.resolve()),
               "-sounddev", "dump", "-soundarg", "/dev/null", "-warp",
               "-limitcycles", str(round((duration + 15) * CLOCK))]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=duration + 120)
    (out / "vice.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not stats.exists():
        raise RuntimeError(f"Full-song deadline capture failed; inspect {out}")
    by_pc = {address: name for name, address in points.items()}
    events = {name: [] for name in points}
    pattern = re.compile(r"^\.C:([0-9a-fA-F]{4})\s+.*\s(\d+)$")
    for line in log.read_text().splitlines():
        match = pattern.match(line)
        if match:
            pc, cycle = int(match[1], 16), int(match[2])
            if pc in by_pc:
                events[by_pc[pc]].append(cycle)
    begins, finishes, swaps = (events[name] for name in points)
    if len(begins) != len(counts) or len(finishes) != len(counts) or len(swaps) != len(counts) - 1:
        raise ValueError({"begin": len(begins), "finish": len(finishes), "swaps": len(swaps),
                          "expected_frames": len(counts)})
    margins = [swap - (finish + 6) for swap, finish in zip(swaps, finishes[1:])]
    if min(margins) <= 0:
        raise ValueError(f"A full-song buffer was prepared too late: {min(margins)} cycles")
    counters = stats.read_bytes()
    if int.from_bytes(counters[6:8], "little") or int.from_bytes(counters[8:10], "little") != len(counts):
        raise ValueError("Native counters disagree with full-song deadline trace")
    result = {"passed": True, "frames": len(counts), "causal_buffer_activations": len(swaps),
              "minimum_wall_cycle_margin": min(margins),
              "maximum_fill_wall_cycles": max(end + 6 - start for start, end in zip(begins[1:], finishes[1:])),
              "underruns": 0, "program_sha256": build["program_sha256"],
              "scope": "Every full-song fill completes before its matching hardware pointer activation. Wall time includes NMI work; this is not a foreground CPU percentage.",
              "log_sha256": support.digest(log)}
    support.save(out / "deadline-check.json", result)
    return result


def capture_autostart(build: dict, out: Path, duration: float) -> dict:
    """Exercise true-drive disk LOAD, without injection or virtual-FS traps."""
    out.mkdir(parents=True, exist_ok=True)
    monitor, stats, media = (out / name for name in ("autostart.mon", "stats.bin", "registers.txt"))
    for path in (stats, media):
        path.unlink(missing_ok=True)
    monitor.write_text(f'break exec ${build["symbols"]["done"]:04x}\ng\n'
                       f'bsave "{stats.resolve()}" 0 $0002 $000d\nquit\n')
    command = ["rtk", "proxy", *support.profile().vice_command(), "-console", "-seed", "1",
               "-initbreak", "reset", "-moncommands", str(monitor.resolve()),
               "-drive8truedrive", "-autostartprgmode", "2",
               "-autostartprgdiskimage", str((out / "autostart.d64").resolve()),
               "-autostart", build["program"],
               "-sounddev", "dump", "-soundarg", str(media.resolve()), "-warp",
               "-limitcycles", str(round((duration + 600) * CLOCK))]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=duration + 180)
    (out / "vice.log").write_text(completed.stdout + completed.stderr)
    if completed.returncode or not stats.exists():
        raise RuntimeError(f"Normal autostart did not complete; inspect {out}")
    return {"program_sha256": build["program_sha256"], "stats_hex": stats.read_bytes().hex(),
            "media": str(media.resolve()), "media_sha256": support.digest(media),
            "profile": support.profile().PROFILE, "command": command,
            "autostartprgmode": 2,
            "manual_load_or_SYS_or_addressed_g": False}


def static_control(build: dict, out: Path, frames: int) -> dict:
    """Keep identical muted SID startup, then hold an independently static SID."""
    out.mkdir(parents=True, exist_ok=True)
    labels = build["symbols"]
    raw = bytearray(Path(build["program"]).read_bytes())
    load = int.from_bytes(raw[:2], "little")
    offset = labels["song_started"] - load + 2
    if raw[offset:offset + 6] != bytes((0x8d, 0x0e, 0xdd, 0x8d, 0x0f, 0xdc)):
        raise ValueError("Unexpected native timer-start sequence")
    raw[offset:offset + 6] = bytes((0xa9, 0, 0x8d, 0x0e, 0xdd, 0xea))
    # The normal handler's copied page is unused when timers stay stopped.
    # Each X/Y pass lasts at least 326,656 cycles. Hold beyond the selected
    # performance without forcing shorter recordings to wait 340 seconds.
    passes = math.ceil((frames / 50 + 2) * CLOCK / 326656)
    if not 1 <= passes <= 65535:
        raise ValueError("Static-control duration exceeds its native counter")
    code = bytearray((0xa9, passes & 255, 0x85, 0xfc, 0xa9, passes >> 8, 0x85, 0xfd,
                      0xa0, 255, 0xa2, 255, 0xca, 0xd0, 0xfd,
                      0x88, 0xd0, 0xf8, 0xa5, 0xfc, 0xd0, 2, 0xc6, 0xfd,
                      0xc6, 0xfc, 0xa5, 0xfc, 0x05, 0xfd, 0xd0, 0xe8,
                      0xa9, frames & 255, 0x85, 0x0a,
                      0xa9, frames >> 8, 0x85, 0x0b,
                      0x4c, labels["done"] & 255, labels["done"] >> 8))
    template = labels["normal_image"] - load + 2
    raw[template:template + len(code)] = code
    wait = labels["wait_start"] - load + 2
    raw[wait:wait + 3] = bytes((0x4c, 0, 4))
    path = out / "static.prg"
    path.write_bytes(raw)
    return dict(build, program=str(path.resolve()), program_sha256=support.digest(path))


def run(out: Path, *, assemble_only=False) -> dict:
    """Complete the same native arrangement in PRG, register proof and stems."""
    import full_length_instruments as instruments
    import full_length_score as score
    import full_length_runtime as runtime

    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    protected = reference_hashes()
    prepared = instruments.prepare(out / "instruments")
    coverage = write_coverage(out)
    expected = instruments.expected_input(prepared)
    (out / "expected-input.bin").write_bytes(expected)
    rows, data_asm, ledger = link_instruments(prepared, out / "linked")
    physical_raw = (out / "linked/physical-rows.bin").read_bytes()
    physical_rows = [list(physical_raw[i:i + 24]) for i in range(0, len(physical_raw), 24)]
    packed = score.prepare(rows, out / "score", ledger["score_address"])
    if packed["score_bytes"] > ledger["score_capacity"]:
        raise ValueError(f"Compact note score needs {packed['score_bytes']} bytes; actual free arena is {ledger['score_capacity']}")
    ledger.update(score_bytes=packed["score_bytes"], score_history_bytes=packed["history_bytes"])
    modes = {"all": (True, True, True), "sid-1": (True, False, False),
             "sid-2": (False, True, False), "sid-3": (False, False, True),
             "muted": (False, False, False)}
    builds = {name: runtime.build(out / "programs" / name, data_asm, Path(packed["score_asm"]),
                                 enabled, loader_arena=tuple(ledger["remaining_arenas"][0]),
                                 sid_programs_asm=Path(prepared["sid_programs_asm"]))
              for name, enabled in modes.items()}
    for build in builds.values():
        labels = build["symbols"]
        if labels.get("decoder_end", 0xf800) > 0xf800:
            raise ValueError("Score decoder overlaps native SID instrument programs")
    duration = len(expected) * PERIOD / CLOCK
    result = {"scope": "Hyperbased arrangement through the user-selected musical ending; listening approval remains separate.",
              "source": prepared["source"], "frames": len(rows), "duration_s": duration,
              "nominal_duration_s": len(rows) / 50,
              "program": {k: v for k, v in builds["all"].items() if k != "symbols"},
              "memory": ledger, "score": packed, "arrangement": prepared["report"],
              "coverage": coverage,
              "canonical_reference_hashes": protected}
    (out / ".gitignore").write_text("*\n!.gitignore\n!player.prg\n!all.wav\n!sid-1.wav\n!sid-2.wav\n!sid-3.wav\n!verification.json\n!coverage.json\n!sid1-reference-check.json\n!README.md\n")
    support.save(out / "verification.json", result)
    if assemble_only:
        shutil.copyfile(builds["all"]["program"], out / "player.prg")
        return result

    def verify_variant(item):
        name, build = item
        folder = out / "programs" / name
        receipt = support.capture(build, folder / "registers", duration)
        support.save(folder / "register-receipt.json", receipt)
        proof = verify_trace(build, receipt, prepared, physical_rows, expected, folder, modes[name])
        return name, proof

    proofs = dict([verify_variant(("all", builds["all"]))])
    result["deadlines"] = measure_deadlines(builds["all"], prepared["frame_sample_counts_exact"], out / "deadlines")
    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs.update(pool.map(verify_variant, ((name, build) for name, build in builds.items() if name != "all")))
    epochs = {proof["first_latch_cycle"] for proof in proofs.values()}
    if len(epochs) != 1:
        raise ValueError("Stem programs changed their native startup epoch")
    result["native"] = proofs
    support.save(out / "verification.json", result)
    autostart = capture_autostart(builds["all"], out / "autostart", duration)
    result["autostart"] = verify_trace(builds["all"], autostart, prepared, physical_rows,
                                       expected, out / "autostart", modes["all"])
    result["autostart"].update(autostartprgmode=2,
                               program_sha256=builds["all"]["program_sha256"],
                               manual_load_or_SYS_or_addressed_g=False)
    support.save(out / "autostart/receipt.json", autostart)
    support.save(out / "verification.json", result)

    from native_instruments.measure_music_budget import measure
    budget = measure(Path(builds["all"]["program"]), builds["all"]["symbols"],
                     prepared["frame_sample_counts_exact"], out / "cpu")
    result["cpu"] = normalize_budget(budget)
    support.save(out / "verification.json", result)
    if not budget["passed"]:
        raise ValueError(f"Full-song CPU timing proof failed: {budget.get('failures')}")

    result.update(record_outputs(builds, proofs, out, duration, len(rows)))
    result["canonical_reference_unchanged"] = reference_hashes() == protected
    if not result["canonical_reference_unchanged"]:
        raise ValueError("Protected twenty-second reference changed")
    # Keep the previous listening player until the real audio reference passes.
    shutil.copyfile(builds["all"]["program"], out / "player.prg")
    support.save(out / "verification.json", result)
    return result


def normalize_budget(budget: dict) -> dict:
    budget = {key: value for key, value in budget.items() if not key.startswith("c3_")}
    partition = budget["attribution"]["cpu_partition"]
    partition["tick_synthesis_and_mix"] = partition.pop("bass_drum_fill")
    partition.pop("c3_producer", None)
    budget["scope"] = "Complete native performance. Every NMI and buffer activation measured. Foreground fill includes SID programs, native phase/cursors and PCM mixing; prefetched note decoding is counted separately. Main-control residual includes busy waits. No separate C3 sampler exists."
    return budget


def record_outputs(builds: dict, proofs: dict, out: Path, duration: float, frames: int) -> dict:
    """Capture the verified programs through one shared audio delivery path."""
    def record_variant(item):
        name, build = item
        folder = out / "programs" / name / "audio"
        epoch = proofs["all" if name == "static-control" else name]["first_latch_cycle"]
        cached = folder / "receipt.json"
        if cached.exists():
            receipt = json.loads(cached.read_text())
            media = Path(receipt["media"])
            if (receipt["program_sha256"] == build["program_sha256"]
                    and receipt["profile"] == support.profile().PROFILE
                    and media.exists() and support.digest(media) == receipt["media_sha256"]):
                return name, read_audio_capture(receipt, duration, epoch, frames)
        return name, capture_audio(build, folder, duration, epoch, frames)

    audio_builds = dict(builds)
    audio_builds["static-control"] = static_control(builds["muted"], out / "static-control", frames)
    with ThreadPoolExecutor(max_workers=6) as pool:
        captured = dict(pool.map(record_variant, audio_builds.items()))
    peak = max(float(np.max(np.abs(signal))) for name, (signal, _, _) in captured.items()
               if name not in ("muted", "static-control"))
    # Preserve the previous listening level when shortening the arrangement.
    gain = LISTENING_GAIN
    if peak * gain >= 1:
        raise ValueError("The shared listening gain would clip a native capture")
    muted_difference = captured["muted"][0] - captured["static-control"][0]
    muted_peak_lsb = float(np.max(np.abs(muted_difference)) * gain * 32768)
    mute_control = {"passed": muted_peak_lsb <= 1,
                              "maximum_pcm16_lsb_difference": muted_peak_lsb,
                              "scope": "Independent full-length static-SID control versus muted producer run, common native clock and gain."}
    if muted_peak_lsb > 1:
        support.save(out / "mute-control-check.json", mute_control)
        raise ValueError(f"All-muted native playback differs from static SID: {muted_peak_lsb} PCM16 LSB")
    from sid1_reference import compare
    sid1_reference = compare(captured["sid-1"][0], captured["sid-1"][1])
    support.save(out / "sid1-reference-check.json", sid1_reference)
    if not sid1_reference["passed"]:
        raise ValueError("SID1 audio changed from the accepted reference; inspect sid1-reference-check.json")
    audio = {}
    for name, (signal, rate, receipt) in captured.items():
        if name in ("muted", "static-control"):
            continue
        filename = f"{name}.wav"
        sf.write(out / filename, signal * gain, rate, subtype="PCM_16")
        audio[name] = {"file": filename, "sha256": support.digest(out / filename),
                       "frames": len(signal), "rate": rate, "duration_s": len(signal) / rate,
                       "listening_gain": gain, "raw_peak": float(np.max(np.abs(signal))),
                       "raw_capture_sha256": receipt["media_sha256"],
                       "profile": receipt["profile"],
                       "processing": "Actual independent VICE capture, native-clock crop, DC removal and one shared constant gain. No EQ, host mixing, alignment or dynamics."}
    return {"audio": audio, "mute_control": mute_control, "sid1_reference": sid1_reference}


def record_verified(out: Path) -> dict:
    """Resume WAV recording only when the existing native proofs still match."""
    out = Path(out).resolve()
    result = json.loads((out / "verification.json").read_text())
    proofs = result["native"]
    builds = {name: json.loads((out / "programs" / name / "build.json").read_text()) for name in proofs}
    expected_sha = support.digest(out / "expected-input.bin")
    for name, build in builds.items():
        receipt = json.loads((out / "programs" / name / "register-receipt.json").read_text())
        if (not proofs[name]["passed"] or support.digest(Path(build["program"])) != build["program_sha256"]
                or receipt["program_sha256"] != build["program_sha256"]
                or proofs[name]["expected_input_sha256"] != expected_sha):
            raise ValueError(f"Cannot resume recording: {name} native proof no longer matches")
    budget = json.loads((out / "cpu/cpu-budget.json").read_text())
    if (not budget["passed"] or budget["program_sha256"] != builds["all"]["program_sha256"]
            or not result["autostart"]["passed"] or not result["deadlines"]["passed"]):
        raise ValueError("Cannot resume recording without matching full CPU/autostart/deadline proofs")
    result["cpu"] = normalize_budget(budget)
    support.save(out / "verification.json", result)
    result.update(record_outputs(builds, proofs, out, result["duration_s"], result["frames"]))
    result["canonical_reference_unchanged"] = reference_hashes() == result["canonical_reference_hashes"]
    if not result["canonical_reference_unchanged"]:
        raise ValueError("Protected twenty-second reference changed")
    shutil.copyfile(builds["all"]["program"], out / "player.prg")
    support.save(out / "verification.json", result)
    return result
