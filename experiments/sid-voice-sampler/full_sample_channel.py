"""Prepare reusable gain banks and an independent full-song SID sample model.

The clock remains 126 PAL cycles. Extra per-instrument decimation and q16 gain
levels trade sampled bandwidth/dynamics for resident RAM; these choices do not
alter tracker timing. Silent and ended states keep distinct cursor semantics.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "instruments/hyperbased-full-samples"
CLOCK, PERIOD, PAULA = 985248, 126, 3546894.6
RATE = CLOCK / PERIOD
EXTRA_DECIMATION = {2: 1, 3: 1, 4: 1, 5: 1, 6: 1,
                    8: 3, 9: 3, 11: 3, 21: 3, 23: 3, 24: 3,
                    10: 2, 17: 2, 18: 2, 19: 2, 20: 2, 22: 2}


def _write(path: Path, content: str, *, library_dir: Path = LIBRARY) -> None:
    in_library = (path.absolute().is_relative_to(library_dir.absolute())
                  or path.resolve().is_relative_to(library_dir.resolve()))
    if in_library and path.exists():
        if path.read_text() != content:
            raise ValueError(f"Prepared instrument file changed; preserve and review it before regeneration: {path}")
        return
    path.write_text(content)


def _save(path: Path, value: dict, *, library_dir: Path = LIBRARY) -> None:
    _write(path, json.dumps(value, indent=2, allow_nan=False) + "\n", library_dir=library_dir)


def _quantized_gain(volume: int, quantum: int = 16) -> int:
    return min(64, ((2 * volume + quantum) // (2 * quantum)) * quantum)


def prepare_full_samples(mod: dict, ticks: list, out: Path, *, channel: int = 3,
                         source_receipt: dict | None = None, library_dir: Path = LIBRARY,
                         extra_decimation: dict[int, int] | None = None,
                         gain_quantum: int | dict[int, int] = 16,
                         allow_initial_silence: bool = False,
                         preferred_divisors: dict[int, int] | None = None) -> dict:
    """Compile a zero-based source channel into reusable banks and a model.

    Omitted keyword arguments preserve the accepted full Hyperbased format.
    ``gain_quantum`` may declare one integer step or an explicit step for every
    nonzero instrument. Initial sample-ID0 states are accepted only when
    enabled, before any real note, and must remain untriggered/period0/volume0.
    A preferred divisor is used only when every period in the complete
    triggered note fits the cursor. Held notes never change cursor scale.

    ``frames`` contains (fractional step, retrigger, variant ID). Variant bit 7
    means muted: the runtime still advances its logical cursor but reads a
    constant neutral value. ``real_end``/``loop_start`` are relative byte
    positions in the resampled source, not ends of physically trimmed banks.
    """
    if not ticks or any(abs(t["duration_s"] - .02) > 1e-9 for t in ticks):
        raise ValueError("The full sample model requires 20-ms source ticks")
    if abs(ticks[0]["time_s"]) > 1e-7 or any(
            abs(b["time_s"] - a["time_s"] - .02) > 1e-7 for a, b in zip(ticks, ticks[1:])):
        raise ValueError("The full sample model must cover a contiguous timeline from zero")
    if type(channel) is not int or channel < 0 or any(channel >= len(t["channels"]) for t in ticks):
        raise ValueError("channel must select a valid zero-based source channel")
    if type(allow_initial_silence) is not bool:
        raise ValueError("allow_initial_silence must be a boolean")
    default_receipt = json.loads((HERE.parent / "mod-hybrid/sources/hyperbased.source.json").read_text())
    source_receipt = default_receipt if source_receipt is None else source_receipt
    if source_receipt.get("sha256") != mod["sha256"]:
        raise ValueError("Full sample source differs from its receipt")
    library_dir, out = Path(library_dir).resolve(), Path(out)
    extra_decimation = dict(EXTRA_DECIMATION if extra_decimation is None else extra_decimation)
    states = [t["channels"][channel] for t in ticks]
    initial_silent_ticks, seen_instrument = 0, False
    for state in states:
        identifier = state["playing_sample"]
        if type(identifier) is not int or not 0 <= identifier <= len(mod["samples"]):
            raise ValueError("Invalid nonzero source instrument")
        if not 0 <= state["volume"] <= 64:
            raise ValueError("Source volume must be within0..64")
        if state.get("offset", 0) or "first_segment_bytes" in state or state.get("loop_sample", identifier) not in (0, identifier):
            raise ValueError("Offsets, short first DMA segments and independent sample-loop targets are unsupported")
        if not identifier:
            if not allow_initial_silence or seen_instrument:
                raise ValueError("Sample ID0 is allowed only as an explicitly enabled initial silent prefix")
            if state["trigger"] or state["period"] or state["volume"]:
                raise ValueError("Initial silence must have no trigger, period or source volume")
            initial_silent_ticks += 1
        elif not seen_instrument:
            if not state["trigger"]:
                raise ValueError("The sampled song must start its first real instrument with a trigger")
            seen_instrument = True
    identifiers = sorted({s["playing_sample"] for s in states} - {0})
    if not identifiers:
        raise ValueError("The full sample model requires a real instrument after any initial silence")
    if set(identifiers) != set(extra_decimation) or any(
            type(value) is not int or value < 1 for value in extra_decimation.values()):
        raise ValueError("extra_decimation must declare a positive integer factor for every source instrument")
    if type(gain_quantum) is int:
        quanta = {identifier: gain_quantum for identifier in identifiers}
    elif isinstance(gain_quantum, dict):
        quanta = dict(gain_quantum)
    else:
        raise ValueError("gain_quantum must be an integer or a per-instrument dictionary")
    if set(quanta) != set(identifiers) or any(type(value) is not int or not 1 <= value <= 64
                                           for value in quanta.values()):
        raise ValueError("gain_quantum must declare an integer1..64 for every source instrument")
    preferred_divisors = {} if preferred_divisors is None else dict(preferred_divisors)
    if not preferred_divisors.keys() <= set(identifiers) or any(
            type(value) is not int or value < 1 for value in preferred_divisors.values()):
        raise ValueError("preferred_divisors must select source instruments with positive integer divisors")
    legacy_configuration = (channel == 3 and source_receipt == default_receipt
                            and extra_decimation == EXTRA_DECIMATION
                            and all(value == 16 for value in quanta.values())
                            and not allow_initial_silence and not preferred_divisors)
    out.mkdir(parents=True, exist_ok=True)
    library_dir.mkdir(parents=True, exist_ok=True)
    canonical_divisors, base_divisors = {}, {}
    for identifier in identifiers:
        active = [s for s in states if s["playing_sample"] == identifier]
        if not mod["samples"][identifier - 1]["length"] or any(s["period"] <= 0 for s in active):
            raise ValueError(f"Invalid source sample/period for instrument {identifier}")
        canonical_divisors[identifier] = max(1, math.ceil(
            PAULA / min(s["period"] for s in active) / RATE * 256 / 255))
        base_divisors[identifier] = canonical_divisors[identifier] * extra_decimation[identifier]
    frame_divisors = [0] * len(states)
    divisor_note_counts = Counter()
    triggers = [index for index, state in enumerate(states) if state["trigger"]]
    for start, stop in zip(triggers, triggers[1:] + [len(states)]):
        identifier = states[start]["playing_sample"]
        note = states[start:stop]
        if any(state["playing_sample"] != identifier for state in note):
            raise ValueError("Source instrument changed without retrigger")
        divisor = base_divisors[identifier]
        preferred = preferred_divisors.get(identifier)
        if preferred is not None and all(1 <= round(PAULA / state["period"] / preferred / RATE * 256) <= 255
                                         for state in note):
            divisor = preferred
        frame_divisors[start:stop] = [divisor] * (stop - start)
        divisor_note_counts[identifier, divisor] += 1
    prepared, variants, variant_ids = {}, [], {}
    for identifier in identifiers:
        sample = mod["samples"][identifier - 1]
        for divisor in sorted({frame_divisors[index] for index, state in enumerate(states)
                               if state["playing_sample"] == identifier}):
            active = [state for index, state in enumerate(states)
                      if state["playing_sample"] == identifier and frame_divisors[index] == divisor]
            raw = np.frombuffer(sample["data"], np.int8).astype(np.float64) / 128
            filtered = resample_poly(raw, 1, divisor)
            source_end = (sample["loop_start"] + sample["loop_length"]
                          if sample["loop_start"] and sample["loop_length"] > 2 else sample["length"])
            real_end = math.ceil(source_end / divisor)
            loop_start = round(sample["loop_start"] / divisor) if sample["loop_length"] > 2 else None
            if real_end > len(filtered) or loop_start is not None and not 0 <= loop_start < real_end:
                raise ValueError(f"Invalid prepared loop for instrument {identifier}")
            if loop_start is None:
                # Page-rounded neutral tails make completion checks cheap.
                real_end = (real_end + 255) // 256 * 256
                filtered = np.pad(filtered, (0, real_end - len(filtered)))
            prepared[identifier, divisor] = {"divisor": divisor, "canonical_divisor": canonical_divisors[identifier],
                "real_end": real_end, "loop_start": loop_start, "original_bytes": sample["length"],
                "original_loop_start": sample["loop_start"], "original_loop_length": sample["loop_length"],
                "filtered": filtered}
            gains = sorted({64, *(_quantized_gain(s["volume"], quanta[identifier]) for s in active)} - {0})
            for gain in gains:
                index = len(variants)
                if index >= 128:
                    raise ValueError("Gain-bank IDs must fit below the mute bit")
                codes = np.clip(np.rint(128 + filtered * 127 * gain / 64), 0, 255).astype(np.uint8)
                variants.append({"id": index, "instrument": identifier, "gain": gain,
                                 "divisor": divisor, "real_end": real_end,
                                 "loop_start": loop_start, "codes": codes, "max_read_index": -1})
                variant_ids[identifier, gain, divisor] = index

    cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * CLOCK + PERIOD * 25) // (PERIOD * 50)
    counts = np.diff(cuts)
    if not set(map(int, counts)).issubset({156, 157}):
        raise ValueError("Unexpected tracker-to-sample clock rounding")
    frames, expected, position, current, ended = [], bytearray(), 0, 0, True
    current_divisor = 0
    pitch_errors, gain_errors, loop_wraps, muted_ticks, ended_ticks = [], [], 0, 0, 0
    gain_errors_by_instrument = {identifier: [] for identifier in identifiers}
    for frame, state in enumerate(states):
        identifier = state["playing_sample"]
        if not identifier:
            # Variant0 is remapped to a real retained bank below. The mute bit
            # selects neutral reads; step0 and trigger0 preserve inactivity.
            frames.append((0, 0, 128))
            expected.extend(bytes([128]) * int(counts[frame]))
            muted_ticks += 1
            ended_ticks += 1
            continue
        if state.get("offset", 0) or state.get("loop_sample", identifier) not in (0, identifier):
            raise ValueError("Offsets and independent sample-loop targets are unsupported")
        divisor = frame_divisors[frame]
        source = prepared[identifier, divisor]
        if state["trigger"]:
            current, position, ended = identifier, 0, False
            current_divisor = divisor
        if current != identifier or current_divisor != divisor:
            raise ValueError("Source instrument or cursor scale changed without retrigger")
        gain = _quantized_gain(state["volume"], quanta[identifier])
        gain_errors.append(gain - state["volume"])
        gain_errors_by_instrument[identifier].append(gain - state["volume"])
        variant = variants[variant_ids[identifier, gain or 64, divisor]]
        step = round(PAULA / state["period"] / source["divisor"] / RATE * 256)
        if not 1 <= step <= 255:
            raise ValueError("Prepared pitch step exceeds the eight-bit cursor")
        pitch_errors.append(1200 * math.log2(step * RATE * source["divisor"] * state["period"] / (256 * PAULA)))
        frames.append((step, int(state["trigger"]), variant["id"] | (0x80 if not gain else 0)))
        count = int(counts[frame])
        values = np.full(count, 128, np.uint8)
        if not gain:
            muted_ticks += 1
        if ended:
            ended_ticks += 1
        else:
            # Independent logical cursor: vector positions, no 6502 page or
            # self-modifying instruction representation is mirrored here.
            positions = position + np.arange(count, dtype=np.int64) * step
            indices = positions >> 8
            end = source["real_end"]
            loop = source["loop_start"]
            if loop is not None:
                wrapped = indices >= end
                if np.any(wrapped):
                    loop_wraps += 1
                    indices[wrapped] = loop + (indices[wrapped] - end) % (end - loop)
                valid = np.ones(count, dtype=bool)
            else:
                valid = indices < end
            if gain and np.any(valid):
                values[valid] = variant["codes"][indices[valid]]
                variant["max_read_index"] = max(variant["max_read_index"], int(indices[valid].max()))
            position += count * step
            if position >= end * 256:
                if loop is None:
                    position, ended = end * 256, True
                else:
                    position = loop * 256 + (position - end * 256) % ((end - loop) * 256)
        expected.extend(values.tobytes())

    # Muted frames and ended one-shots never read their selected gain bank.
    # Alias those unused variants to a real same-instrument bank rather than
    # reserving a neutral placeholder page for each unused gain value.
    retained = [variant for variant in variants if variant["max_read_index"] >= 0]
    for identifier, divisor in prepared:
        if not any((variant["instrument"], variant["divisor"]) == (identifier, divisor) for variant in retained):
            retained.append(next(variant for variant in variants
                                 if (variant["instrument"], variant["divisor"], variant["gain"])
                                 == (identifier, divisor, 64)))
    fallback = {(identifier, divisor): next(v for v in retained
                if (v["instrument"], v["divisor"]) == (identifier, divisor))
                for identifier, divisor in prepared}
    new_indices = {variant["id"]: index for index, variant in enumerate(retained)}
    remap = {}
    for variant in variants:
        target = variant if variant["max_read_index"] >= 0 else fallback[variant["instrument"], variant["divisor"]]
        remap[variant["id"]] = new_indices[target["id"]]
    frames = [(step, trigger, remap[variant & 127] | (variant & 128))
              for step, trigger, variant in frames]
    for index, variant in enumerate(retained):
        variant["id"] = index
    variants = retained
    banks, descriptors = [], []
    for variant in variants:
        size = max(256, ((variant["max_read_index"] + 256) // 256) * 256)
        data = np.full(size, 128, np.uint8)
        prefix = min(size, len(variant["codes"]))
        data[:prefix] = variant["codes"][:prefix]
        binary = data.tobytes()
        filename = f'{variant["instrument"]:02d}-gain-{variant["gain"]:02d}.asm'
        if variant["instrument"] in preferred_divisors:
            filename = f'{variant["instrument"]:02d}-divisor-{variant["divisor"]:02d}-gain-{variant["gain"]:02d}.asm'
        path = library_dir / filename
        _write(path, "// Reusable unsigned eight-bit gain bank; labels/alignment supplied by player.\n" +
                        "\n".join(".byte " + ",".join(f"${value:02x}" for value in binary[i:i + 16])
                                  for i in range(0, len(binary), 16)) + "\n", library_dir=library_dir)
        bank = {key: variant[key] for key in ("id", "instrument", "gain", "divisor", "real_end", "loop_start")}
        bank.update(data=binary, asm_path=path, max_read_index=variant["max_read_index"],
                    stored_bytes=size, sha256=hashlib.sha256(binary).hexdigest())
        banks.append(bank)
    for identifier in identifiers:
        sources = [source for (instrument, _), source in prepared.items() if instrument == identifier]
        source = next((source for source in sources if source["divisor"] == base_divisors[identifier]), sources[0])
        name = (f"Hyperbased instrument {identifier}" if legacy_configuration else
                f"{source_receipt.get('title_slug', 'MOD')} instrument {identifier}")
        descriptor = {"source_instrument": identifier, "name": name,
                      "kind": "sample_gain_variants", "volume_quantization_step": quanta[identifier],
                      **{key: source[key] for key in ("canonical_divisor", "divisor", "real_end", "loop_start",
                                                     "original_bytes", "original_loop_start", "original_loop_length")},
                      "variants": [{key: (str(bank[key].name) if key == "asm_path" else bank[key])
                                    for key in ("id", "gain", "stored_bytes", "max_read_index", "sha256", "asm_path")}
                                   for bank in banks if bank["instrument"] == identifier]}
        if identifier in preferred_divisors:
            descriptor["preferred_divisor"] = preferred_divisors[identifier]
            descriptor["preparations"] = [{key: source[key] for key in
                ("canonical_divisor", "divisor", "real_end", "loop_start")} for source in sources]
            for variant in descriptor["variants"]:
                bank = next(bank for bank in banks if bank["id"] == variant["id"])
                variant.update({key: bank[key] for key in ("divisor", "real_end", "loop_start")})
        filename = f"{identifier:02d}-sample.json"
        _save(library_dir / filename, descriptor, library_dir=library_dir)
        descriptors.append(filename)
    scope = ("Full channel-4 source instruments, q16 gain variants and explicitly reduced stored bandwidth. Bank prefixes contain every byte actually read while audible; virtual cursor ends can lie beyond their stored prefix."
             if legacy_configuration else
             f"Full channel-{channel + 1} source instruments with explicit gain quanta and decimation factors. Bank prefixes contain every audible read; virtual cursor ends can extend beyond stored prefixes.")
    _save(library_dir / "library.json", {"format_version": 1, "source": source_receipt,
                                    "instruments": descriptors,
                                    "scope": scope}, library_dir=library_dir)
    expected_data = bytes(expected)
    (out / "expected-input.bin").write_bytes(expected_data)
    duration = len(expected_data) / RATE
    metadata = {"source": source_receipt, "source_channel": channel + 1,
                "source_range_s": [0, ticks[-1]["time_s"] + ticks[-1]["duration_s"]],
                "frames": len(frames), "duration_s": duration,
                "source_duration_s": len(ticks) * .02,
                "duration_error_us": (duration - len(ticks) * .02) * 1e6,
                "input_codes": len(expected_data), "triggers": sum(s["trigger"] for s in states),
                "sample_rate_hz": RATE, "sample_period_cycles": PERIOD,
                "frame_sample_counts": dict(Counter(map(int, counts))),
                "bank_bytes": sum(bank["stored_bytes"] for bank in banks),
                "bank_variants": len(banks), "instruments": identifiers,
                "sample_preparation": [{"instrument": identifier,
                                        "canonical_divisor": source["canonical_divisor"],
                                        "divisor": source["divisor"],
                                        "real_end": source["real_end"],
                                        "loop_start": source["loop_start"],
                                        "loop_rounding_pitch_error_cents": (
                                            1200 * math.log2(source["original_loop_length"] /
                                                (source["divisor"] * (source["real_end"] - source["loop_start"])))
                                            if source["loop_start"] is not None else None)}
                                       for (identifier, _), source in prepared.items()],
                "muted_ticks": muted_ticks, "ended_ticks": ended_ticks,
                "loop_wrap_buffers": loop_wraps,
                "fractional_pitch_error_cents": [min(pitch_errors), max(pitch_errors)],
                "gain_quantization_error_units": [min(gain_errors), max(gain_errors)],
                "expected_input_sha256": hashlib.sha256(expected_data).hexdigest(),
                "quality": "Nearest q16 volume levels with half steps rounded upward. Additional per-instrument low-pass decimation preserves original clocks and note periods but lowers sampled bandwidth. Instruments 2–6 retain the accepted excerpt's decimation.",
                "loop_model": "Looped initial DMA end is ceil(source first-pass bytes/divisor); repeat begins at round(source loop start/divisor). One-shot ends are page-rounded with neutral padding only. Eight-bit fractional phase is retained across repeat; resampled endpoint rounding is disclosed pitch quantization.",
                "runtime_contract": "Mute bit requires constant neutral reads while cursor advances. Physical bank prefix ends are not logical sample ends. Ended one-shots stay silent through gain changes until a retrigger."}
    if not legacy_configuration:
        metadata.update(initial_silent_ticks=initial_silent_ticks, gain_quantum=quanta,
                        extra_decimation=extra_decimation,
                        gain_quantization_error_units_by_instrument={identifier: [min(errors), max(errors)]
                            for identifier, errors in gain_errors_by_instrument.items()},
                        maximum_absolute_gain_quantization_error_units=max(map(abs, gain_errors)),
                        quality="Explicit per-instrument nearest gain quanta, half steps rounded upward. Exact quantum1 retains source volume; extra decimation is separate and never implicit. Eight-bit sample values and original sample clock are retained.")
    if preferred_divisors:
        metadata.update(preferred_divisors=preferred_divisors,
            preferred_divisor_note_counts=[{"instrument": identifier, "divisor": divisor, "notes": count}
                for (identifier, divisor), count in sorted(divisor_note_counts.items())
                if identifier in preferred_divisors])
        metadata["runtime_contract"] += " Cursor scale is selected per complete triggered note and never changes while held."
    _save(out / "input.json", metadata, library_dir=library_dir)
    serial_banks = [{key: (str(bank[key]) if key == "asm_path" else bank[key])
                     for key in bank if key != "data"} for bank in banks]
    _save(out / "full-model.json", {"frames": frames, "banks": serial_banks, "metadata": metadata}, library_dir=library_dir)
    return {"frames": frames, "banks": banks, "metadata": metadata}
