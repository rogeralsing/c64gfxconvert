"""Prepare compact reusable C3 waves for a future native second SID sampler.

Data study only: this does not change the accepted mixer or produce a listening
WAV. Each original instrument/divisor has one base wave. The C64 contract uses
an eight-bit fractional step, a bank/retrigger field and an exact gain-table ID.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.signal import resample_poly, stft

HERE = Path(__file__).resolve().parent
SAMPLER = HERE.parent
sys.path.insert(0, str(SAMPLER))
import native_support as support

HEADROOM = 1.5
AMPLITUDE = 90
TICKS = 1000


def _save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frequency_table(hold_cycles: int) -> dict:
    """Translate target codes into 16-bit pitches for a measured hold window.

    The accepted voice-3 transfer uses ``code << 8`` for exactly 100 cycles.
    This translation preserves that accumulator displacement for another
    oscillator. It does not prove that a proposed ISR has that hold window.
    """
    if type(hold_cycles) is not int or hold_cycles < 100:
        raise ValueError("Declare a measured preparation window of at least 100 cycles")
    words = [round(code * 256 * 100 / hold_cycles) for code in range(256)]
    errors = [word * hold_cycles / (256 * 100) - code for code, word in enumerate(words)]
    return {"hold_cycles": hold_cycles, "words": words,
            "low": bytes(word & 255 for word in words),
            "high": bytes(word >> 8 for word in words),
            "maximum_equivalent_input_code_error": max(map(abs, errors)),
            "requires": "Write both SID frequency bytes; a high-byte-only implementation has a different quantization contract."}


def _filter_source(sample: dict, divisor: int) -> np.ndarray:
    raw = np.frombuffer(sample["data"], np.int8).astype(np.float64) / 128
    if sample["loop_length"] > 2:
        end = sample["loop_start"] + sample["loop_length"]
        loop = raw[sample["loop_start"]:end]
        # The finite first-pass bank needs the following loop samples as FIR
        # context; zero padding here would corrupt the repeat join.
        raw = np.r_[raw[:end], np.tile(loop, math.ceil(32 * divisor / len(loop)))]
    return resample_poly(raw, 1, divisor)


def _build_model(mod: dict, ticks: list, period: int,
                 frame_counts: list[int] | None = None) -> dict:
    rate = support.CLOCK / period
    if frame_counts is None:
        counts = np.diff([(i * support.CLOCK + period * 25) // (period * 50)
                          for i in range(len(ticks) + 1)]).astype(int).tolist()
    else:
        counts = list(frame_counts)
        if len(counts) != len(ticks) or any(type(count) is not int or count < 0 for count in counts):
            raise ValueError("Caller sample counts must be one nonnegative integer per original tracker tick")
        if not sum(counts):
            raise ValueError("Caller sample clock produces no values")
    states = [tick["channels"][2] for tick in ticks]
    gains = sorted({int(state["volume"]) for state in states})
    gain_ids = {gain: index for index, gain in enumerate(gains)}
    tables = {gain: np.clip(np.rint(128 + (np.arange(256) - 128) * HEADROOM
                                    * AMPLITUDE / 127 * gain / 64), 0, 255).astype(np.uint8)
              for gain in gains}
    banks, by_key, frames, notes = [], {}, [], []
    current_bank = current_instrument = None
    current_period = None
    step = 0
    for index, state in enumerate(states):
        identifier = int(state["playing_sample"])
        if not identifier:
            if current_bank is not None or state["trigger"] or state["period"] or state["volume"]:
                raise ValueError("Sample ID0 must be an untriggered silent prefix")
            frames.append((0, 0, gain_ids[0]))
            continue
        if state.get("offset", 0) or "first_segment_bytes" in state or state.get("loop_sample", identifier) not in (0, identifier):
            raise ValueError("This data contract does not erase offsets or independent DMA targets")
        if state["trigger"]:
            current_instrument, current_period = identifier, int(state["period"])
            divisor = max(1, math.ceil(support.PAULA / current_period / rate * 256 / 255))
            step = round(support.PAULA / current_period / divisor / rate * 256)
            if not 1 <= step <= 255:
                raise ValueError("Chosen divisor does not fit the native eight-bit fractional step")
            key = identifier, divisor
            if key not in by_key:
                sample = mod["samples"][identifier - 1]
                filtered = _filter_source(sample, divisor)
                codes = np.rint(128 + filtered * 127 / HEADROOM).astype(int)
                if codes.min() < 0 or codes.max() > 255:
                    raise ValueError("Base wave would clip before gain lookup")
                end_source = (sample["loop_start"] + sample["loop_length"]
                              if sample["loop_length"] > 2 else sample["length"])
                bank = {"id": len(banks), "source_instrument": identifier, "divisor": divisor,
                        "logical_end_q8": round(end_source / divisor * 256),
                        "loop_start_q8": (round(sample["loop_start"] / divisor * 256)
                                          if sample["loop_length"] > 2 else None),
                        "source_end": end_source, "source_loop_start": sample["loop_start"],
                        "source_loop_length": sample["loop_length"],
                        "source_sample_sha256": _sha(sample["data"]),
                        "filtered": filtered, "codes": codes.astype(np.uint8),
                        "max_read_index": -1}
                by_key[key] = bank; banks.append(bank)
            current_bank = by_key[key]
            notes.append({"start_tick": index, "instrument": identifier,
                          "source_period": current_period, "bank": current_bank["id"],
                          "step": step, "divisor": divisor,
                          "pitch_error_cents": 1200 * math.log2(step * rate * divisor
                                                                * current_period / (256 * support.PAULA))})
        if current_bank is None or current_instrument != identifier or current_period != state["period"]:
            raise ValueError("Held source pitch/instrument changed without a retrigger")
        frames.append((step, current_bank["id"] | (128 if state["trigger"] else 0), gain_ids[state["volume"]]))

    # Logical fractional cursor; this identifies every address the target must
    # read, including zero-volume frames. No muted-read loophole trims a bank.
    phase, ended, active = 0, True, None
    output, wraps = bytearray(), 0
    for (step, selector, gain_id), count in zip(frames, counts):
        if selector & 128:
            active, phase, ended = banks[selector & 127], 0, False
        gain = gains[gain_id]
        for _ in range(count):
            value = 128
            if not ended:
                location = phase >> 8
                active["max_read_index"] = max(active["max_read_index"], location)
                value = int(tables[gain][active["codes"][location]])
                phase += step
                if phase >= active["logical_end_q8"]:
                    repeat = active["loop_start_q8"]
                    if repeat is None:
                        ended = True
                    else:
                        phase = repeat + (phase - active["logical_end_q8"]) % (active["logical_end_q8"] - repeat)
                        wraps += 1
            output.append(value)

    # Independent closed-form note model. It derives each address from elapsed
    # output index, rather than emulating the scalar phase/carry state above.
    # Its volume target is evaluated in floating point directly, bypassing the
    # base-code and gain-table pipeline.
    reference = np.full(sum(counts), 128, np.uint8)
    cuts = np.r_[0, np.cumsum(counts)]
    stop_ticks = [note["start_tick"] for note in notes[1:]] + [len(ticks)]
    for note, stop_tick in zip(notes, stop_ticks):
        bank = banks[note["bank"]]
        start_sample = int(cuts[note["start_tick"]])
        end_sample = int(cuts[stop_tick])
        raw_phases = np.arange(end_sample - start_sample, dtype=np.int64) * note["step"]
        repeat = bank["loop_start_q8"]
        valid = raw_phases < bank["logical_end_q8"]
        if repeat is not None:
            after = ~valid
            raw_phases[after] = repeat + (raw_phases[after] - bank["logical_end_q8"]) % (bank["logical_end_q8"] - repeat)
            valid[:] = True
        locations = raw_phases >> 8
        exact_gains = np.concatenate([np.full(counts[index], states[index]["volume"], np.float64)
                                      for index in range(note["start_tick"], stop_tick)])
        target = np.full(len(raw_phases), 128, np.uint8)
        target[valid] = np.clip(np.rint(128 + bank["filtered"][locations[valid]]
                                               * AMPLITUDE * exact_gains[valid] / 64), 0, 255).astype(np.uint8)
        reference[start_sample:end_sample] = target
    actual = np.frombuffer(output, np.uint8)
    difference = actual.astype(np.int16) - reference.astype(np.int16)
    if int(np.abs(difference).max()) > 1:
        raise ValueError("Native lookup target differs from the independent gain model by more than one code")
    return {"banks": banks, "frames": frames, "counts": counts, "gains": gains,
            "tables": tables, "notes": notes, "expected": bytes(output),
            "reference": reference.tobytes(), "loop_wraps": wraps,
            "maximum_lookup_error_codes": int(np.abs(difference).max()),
            "changed_lookup_codes": int(np.count_nonzero(difference))}


def _decode_bank_files(out: Path, metadata: dict) -> bytes:
    """Roundtrip the emitted compact contract, including actual bank padding."""
    banks = metadata["banks"]
    waves = {b["id"]: (out / b["file"]).read_bytes() for b in banks}
    table_bytes = (out / "gain-tables.bin").read_bytes()
    tables = [table_bytes[index:index + 256] for index in range(0, len(table_bytes), 256)]
    score = (out / "frames.bin").read_bytes()
    phase = 0
    ended = True
    bank = None
    values = bytearray()
    for index, count in enumerate(metadata["frame_sample_counts_exact"]):
        step, selector, gain_id = score[index * 3:index * 3 + 3]
        if selector & 128:
            bank = banks[selector & 127]; phase = 0; ended = False
        for _ in range(count):
            value = 128
            if not ended:
                location = phase // 256
                if not 0 <= location < len(waves[bank["id"]]):
                    raise ValueError("Emitted native cursor reads outside its retained bank")
                value = tables[gain_id][waves[bank["id"]][location]]
                phase += step
                if phase >= bank["logical_end_q8"]:
                    if bank["loop_start_q8"] is None:
                        ended = True
                    else:
                        phase = bank["loop_start_q8"] + (phase - bank["logical_end_q8"]) % (bank["logical_end_q8"] - bank["loop_start_q8"])
            values.append(value)
    return bytes(values)


def _quality(mod: dict, ticks: list, model: dict, period: int) -> dict:
    rate = support.CLOCK / period
    spectra = []
    for identifier in (8, 9, 10, 11):
        sample = mod["samples"][identifier - 1]
        raw = np.frombuffer(sample["data"], np.int8).astype(float)
        if sample["loop_length"] > 2:
            raw = raw[sample["loop_start"]:sample["loop_start"] + sample["loop_length"]]
        power = np.abs(np.fft.rfft((raw - raw.mean()) * np.hanning(len(raw)))) ** 2
        frequencies = np.fft.rfftfreq(len(raw))
        for source_period in sorted({note["source_period"] for note in model["notes"] if note["instrument"] == identifier}):
            source_rate = support.PAULA / source_period
            spectra.append({"instrument": identifier, "source_period": source_period,
                            "raw_spectral_power_above_output_nyquist_fraction": float(power[frequencies > rate / 2 / source_rate].sum() / power.sum())})
    # The approved short native reference's input model is already in its
    # receipt. Analyze on the original shared clock; never edit its audio.
    recovery = SAMPLER / "work/hyperbased/recovery/sampled-c3"
    receipt = json.loads((recovery / "verification.json").read_text())
    previous = Path(receipt["build"]["program"]).parent / "expected-input.bin"
    if not previous.exists():
        raise ValueError("Approved recovery input model is needed for the bandwidth comparison")
    high = np.frombuffer(previous.read_bytes(), np.uint8).astype(float) - 128
    length_ticks = receipt["input"]["frames"]
    factor = period // support.PERIOD
    comparison = resample_poly(high, 1, factor)
    length = sum(model["counts"][:length_ticks])
    low = np.frombuffer(model["expected"], np.uint8).astype(float)[:length] - 128
    comparison = comparison[:length]
    samples = min(len(low), len(comparison))
    a, b = low[:samples], comparison[:samples]
    nperseg = min(256, samples)
    frequencies, _, ax = stft(a, rate, nperseg=nperseg, noverlap=nperseg // 2, boundary=None)
    _, _, bx = stft(b, rate, nperseg=nperseg, noverlap=nperseg // 2, boundary=None)
    body = (frequencies >= 50) & (frequencies <= min(900, rate * .45))
    x, y = np.abs(ax[body]).ravel(), np.abs(bx[body]).ravel()
    return {"raw_bandwidth_analysis": spectra,
            "approved_7819hz_reference_input_sha256": support.digest(previous),
            "reference_source_range_s": [0, length_ticks * .02],
            "analysis_only_reference_lowpass_factor": factor,
            "low_band_spectral_cosine": float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y))),
            "unshifted_waveform_correlation_after_reference_lowpass": float(np.corrcoef(a, b)[0, 1]),
            "processing_scope": "Analysis only: approved high-rate input is low-pass resampled to the proposed lower clock for comparison. No WAV is generated, changed, aligned or mixed.",
            "limitation": "Both proposed clocks discard upper orchestral partials present in the approved 7.82-kHz recovery. Original low body and source envelope are retained as sampled data, but lower-rate listening acceptance is still open."}


def prepare(out: Path, sample_period_cycles: int = 504, *,
            frame_counts: list[int] | None = None,
            clock_binding: str | dict | None = None,
            startup_neutral_values: int = 0,
            analyze_quality: bool = True) -> dict:
    if sample_period_cycles not in (252, 504):
        raise ValueError("This bounded study evaluates only 252- and 504-cycle sampler clocks")
    if type(startup_neutral_values) is not int or startup_neutral_values < 0:
        raise ValueError("Startup neutral count must be a nonnegative integer")
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    source = json.loads((SAMPLER.parent / "mod-hybrid/sources/hyperbased.source.json").read_text())
    source = dict(source, title_slug="hyperbased")
    mod = support.source_mod(source, out)
    ticks = support.build_timeline(mod)["ticks"][:TICKS]
    if len(ticks) != TICKS or any(abs(tick["duration_s"] - .02) > 1e-9 for tick in ticks):
        raise ValueError("Expected the unchanged first 1,000 tracker ticks")
    if frame_counts is not None and clock_binding is None:
        raise ValueError("Caller frame counts require an explicit native clock/phase/pipeline binding description")
    model = _build_model(mod, ticks, sample_period_cycles, frame_counts)
    descriptors = []
    for bank in model["banks"]:
        size = max(256, (bank["max_read_index"] + 256) // 256 * 256)
        codes = np.full(size, 128, np.uint8)
        count = min(size, len(bank["codes"]))
        codes[:count] = bank["codes"][:count]
        path = out / f'bank-{bank["id"]:02d}-source-{bank["source_instrument"]:02d}-d{bank["divisor"]:02d}.bin'
        path.write_bytes(codes.tobytes())
        descriptors.append({key: bank[key] for key in ("id", "source_instrument", "divisor", "logical_end_q8", "loop_start_q8", "source_end", "source_loop_start", "source_loop_length", "source_sample_sha256", "max_read_index")}
                           | {"file": path.name, "bytes": size, "sha256": support.digest(path)})
    (out / "gain-tables.bin").write_bytes(b"".join(model["tables"][gain].tobytes() for gain in model["gains"]))
    frame_bytes = bytes(value for row in model["frames"] for value in row)
    (out / "frames.bin").write_bytes(frame_bytes)
    dictionary = list(dict.fromkeys(model["frames"]))
    if len(dictionary) > 256:
        raise ValueError("Source state dictionary no longer fits its one-byte index")
    dictionary_ids = {row: index for index, row in enumerate(dictionary)}
    indices = bytes(dictionary_ids[row] for row in model["frames"])
    fields = bytearray(3 * 256)
    for index, row in enumerate(dictionary):
        for field, value in enumerate(row):
            fields[field * 256 + index] = value
    (out / "frame-indices.bin").write_bytes(indices)
    (out / "frame-fields.bin").write_bytes(fields)
    restored = bytes(fields[field * 256 + index] for index in indices for field in range(3))
    if restored != frame_bytes:
        raise ValueError("Native page-indexed state dictionary changes the score")
    (out / "expected-input.bin").write_bytes(model["expected"])
    latches = bytes([128] * startup_neutral_values) + model["expected"]
    (out / "expected-latches.bin").write_bytes(latches)
    (out / "independent-gain-target.bin").write_bytes(model["reference"])
    banks_bytes = sum(bank["bytes"] for bank in descriptors)
    gain_bytes, score_bytes = len(model["gains"]) * 256, len(model["frames"]) * 3
    indexed_score_bytes = len(indices) + len(fields)
    metadata = {"source": source, "source_range_s": [0, 20],
                "sample_period_cycles": sample_period_cycles,
                "sample_rate_hz": support.CLOCK / sample_period_cycles,
                "clock_binding": clock_binding if frame_counts is not None else "Ideal zero-origin lower-rate clock, tracker cuts rounded directly at that rate. Before native integration, bind per-frame counts to the measured SID2 event phase relative to the existing156/157-sample SID3 buffers; nested rounding may assign one sample differently at some tick edges.",
                "caller_frame_counts": frame_counts is not None,
                "startup_neutral_values": startup_neutral_values,
                "startup_neutral_code": 128,
                "expected_latch_values": len(latches),
                "expected_latches_sha256": _sha(latches),
                "output_values": len(model["expected"]), "tracker_frames": len(ticks),
                "frame_sample_counts_exact": model["counts"],
                "source_triggers": len(model["notes"]),
                "source_trigger_counts": dict(Counter(note["instrument"] for note in model["notes"])),
                "gain_levels": model["gains"], "gain_quantum": 1,
                "gain_tables_bytes": gain_bytes, "base_bank_bytes": banks_bytes,
                "score_bytes": score_bytes, "frame_record_bytes": 3,
                "frame_contract": ["fractional step Q0.8", "bank ID in bits0..6, retrigger in bit7", "gain-table ID"],
                "indexed_score": {"unique_states": len(dictionary), "indices_file": "frame-indices.bin",
                                  "field_pages_file": "frame-fields.bin", "bytes": indexed_score_bytes,
                                  "contract": "One state index per tracker tick. Three256-byte pages provide step, bank/retrigger and gain ID at that index. Zero-filled dictionary padding is not an extra state.",
                                  "roundtrip_passed": True},
                "bank_metadata_bytes_estimate": 7 * len(descriptors),
                "total_native_data_bytes_estimate": banks_bytes + gain_bytes + score_bytes + 7 * len(descriptors),
                "total_indexed_native_data_bytes_estimate": banks_bytes + gain_bytes + indexed_score_bytes + 7 * len(descriptors),
                "native_contract": "Integer byte cursor plus eight-bit fractional phase. On trigger reset phase0 and select bank. Read current byte, apply shared gain table, then add step. Ended one-shots output128. Loop wraps preserve fractional endpoints from logical_end_q8 and loop_start_q8. Gain0 still advances and its reads are included in retained prefixes. Initial silent prefix must not read an uninitialized bank.",
                "loop_wraps_in_this_phrase": model["loop_wraps"],
                "loop_scope": "Original instrument8 loop is preserved in metadata and independent models, but no note reaches it in these first20s; native repeat handling is not exercised by this phrase.",
                "headroom_scale": HEADROOM, "output_amplitude_codes": AMPLITUDE,
                "maximum_gain_lookup_error_codes": model["maximum_lookup_error_codes"],
                "gain_lookup_changed_codes": model["changed_lookup_codes"],
                "pitch_error_cents_range": [min(note["pitch_error_cents"] for note in model["notes"]), max(note["pitch_error_cents"] for note in model["notes"])],
                "banks": descriptors, "notes": model["notes"],
                "expected_input_sha256": support.digest(out / "expected-input.bin"),
                "expected_input_code_range": [min(model["expected"]), max(model["expected"])],
                "script_sha256": support.digest(Path(__file__)),
                "scope": "Data preparation only for a future second native SID sample voice. No native dual-voice playback or listening acceptance is claimed."}
    decoded = _decode_bank_files(out, metadata)
    if decoded != model["expected"]:
        raise ValueError("Packed frames and trimmed banks do not reproduce the expected sampled stream")
    metadata["packed_roundtrip_passed"] = True
    metadata["quality"] = (_quality(mod, ticks, model, sample_period_cycles)
                           if analyze_quality else
                           {"performed": False,
                            "reason": "Optional host quality comparison skipped; no generated recovery reference is required.",
                            "scope": "Independent cursor/gain checks and emitted-bank/score roundtrips remain mandatory."})
    _save(out / "metadata.json", metadata)
    (out / ".gitignore").write_text("*\n!.gitignore\n!metadata.json\n")
    return metadata
