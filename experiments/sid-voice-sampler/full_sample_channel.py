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


def _write(path: Path, content: str) -> None:
    if path.is_relative_to(LIBRARY) and path.exists() and path.read_text() != content:
        raise ValueError(f"Prepared instrument file changed; preserve and review it before regeneration: {path}")
    path.write_text(content)


def _save(path: Path, value: dict) -> None:
    _write(path, json.dumps(value, indent=2, allow_nan=False) + "\n")


def _quantized_gain(volume: int) -> int:
    return min(64, ((volume + 8) // 16) * 16)


def prepare_full_samples(mod: dict, ticks: list, out: Path) -> dict:
    """Compile channel 4 and write its reusable sample library plus model.

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
    states = [t["channels"][3] for t in ticks]
    if not states[0]["trigger"]:
        raise ValueError("The sampled song must start with a real trigger")
    identifiers = sorted({s["playing_sample"] for s in states})
    if set(identifiers) != set(EXTRA_DECIMATION):
        raise ValueError("Unexpected instrument set in the full Hyperbased sample channel")
    out.mkdir(parents=True, exist_ok=True)
    LIBRARY.mkdir(parents=True, exist_ok=True)
    prepared, variants, variant_ids = {}, [], {}
    for identifier in identifiers:
        sample = mod["samples"][identifier - 1]
        active = [s for s in states if s["playing_sample"] == identifier]
        if not sample["length"] or any(s["period"] <= 0 for s in active):
            raise ValueError(f"Invalid source sample/period for instrument {identifier}")
        canonical = max(1, math.ceil(PAULA / min(s["period"] for s in active) / RATE * 256 / 255))
        divisor = canonical * EXTRA_DECIMATION[identifier]
        raw = np.frombuffer(sample["data"], np.int8).astype(np.float64) / 128
        filtered = resample_poly(raw, 1, divisor)
        source_end = (sample["loop_start"] + sample["loop_length"]
                      if sample["loop_start"] and sample["loop_length"] > 2 else sample["length"])
        real_end = math.ceil(source_end / divisor)
        loop_start = round(sample["loop_start"] / divisor) if sample["loop_length"] > 2 else None
        if real_end > len(filtered) or loop_start is not None and not 0 <= loop_start < real_end:
            raise ValueError(f"Invalid prepared loop for instrument {identifier}")
        if loop_start is None:
            # Neutral padding extends only the inaudible tail. Page-aligned
            # one-shot ends let the native cursor test completion on page
            # crossings instead of spending cycles on every source byte.
            real_end = (real_end + 255) // 256 * 256
            filtered = np.pad(filtered, (0, real_end - len(filtered)))
        prepared[identifier] = {"divisor": divisor, "canonical_divisor": canonical,
                                "real_end": real_end, "loop_start": loop_start,
                                "original_bytes": sample["length"],
                                "original_loop_start": sample["loop_start"],
                                "original_loop_length": sample["loop_length"],
                                "filtered": filtered}
        gains = sorted({64, *(_quantized_gain(s["volume"]) for s in active)} - {0})
        for gain in gains:
            index = len(variants)
            if index >= 128:
                raise ValueError("Gain-bank IDs must fit below the mute bit")
            codes = np.clip(np.rint(128 + filtered * 127 * gain / 64), 0, 255).astype(np.uint8)
            variants.append({"id": index, "instrument": identifier, "gain": gain,
                             "divisor": divisor, "real_end": real_end,
                             "loop_start": loop_start, "codes": codes, "max_read_index": -1})
            variant_ids[identifier, gain] = index

    cuts = (np.arange(len(ticks) + 1, dtype=np.int64) * CLOCK + PERIOD * 25) // (PERIOD * 50)
    counts = np.diff(cuts)
    if not set(map(int, counts)).issubset({156, 157}):
        raise ValueError("Unexpected tracker-to-sample clock rounding")
    frames, expected, position, current, ended = [], bytearray(), 0, 0, True
    pitch_errors, gain_errors, loop_wraps, muted_ticks, ended_ticks = [], [], 0, 0, 0
    for frame, state in enumerate(states):
        identifier = state["playing_sample"]
        if state.get("offset", 0) or state.get("loop_sample", identifier) not in (0, identifier):
            raise ValueError("Offsets and independent sample-loop targets are unsupported")
        source = prepared[identifier]
        if state["trigger"]:
            current, position, ended = identifier, 0, False
        if current != identifier:
            raise ValueError("Source instrument changed without retrigger")
        gain = _quantized_gain(state["volume"])
        gain_errors.append(gain - state["volume"])
        variant = variants[variant_ids[identifier, gain or 64]]
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
    fallback = {identifier: next(v for v in retained if v["instrument"] == identifier)
                for identifier in identifiers}
    new_indices = {variant["id"]: index for index, variant in enumerate(retained)}
    remap = {}
    for variant in variants:
        target = variant if variant["max_read_index"] >= 0 else fallback[variant["instrument"]]
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
        path = LIBRARY / filename
        _write(path, "// Reusable unsigned eight-bit gain bank; labels/alignment supplied by player.\n" +
                        "\n".join(".byte " + ",".join(f"${value:02x}" for value in binary[i:i + 16])
                                  for i in range(0, len(binary), 16)) + "\n")
        bank = {key: variant[key] for key in ("id", "instrument", "gain", "divisor", "real_end", "loop_start")}
        bank.update(data=binary, asm_path=path, max_read_index=variant["max_read_index"],
                    stored_bytes=size, sha256=hashlib.sha256(binary).hexdigest())
        banks.append(bank)
    for identifier in identifiers:
        source = prepared[identifier]
        descriptor = {"source_instrument": identifier, "name": f"Hyperbased instrument {identifier}",
                      "kind": "sample_gain_variants", "volume_quantization_step": 16,
                      **{key: source[key] for key in ("canonical_divisor", "divisor", "real_end", "loop_start",
                                                     "original_bytes", "original_loop_start", "original_loop_length")},
                      "variants": [{key: (str(bank[key].name) if key == "asm_path" else bank[key])
                                    for key in ("id", "gain", "stored_bytes", "max_read_index", "sha256", "asm_path")}
                                   for bank in banks if bank["instrument"] == identifier]}
        filename = f"{identifier:02d}-sample.json"
        _save(LIBRARY / filename, descriptor)
        descriptors.append(filename)
    source_receipt = json.loads((HERE.parent / "mod-hybrid/sources/hyperbased.source.json").read_text())
    if source_receipt["sha256"] != mod["sha256"]:
        raise ValueError("Full Hyperbased source differs from its receipt")
    _save(LIBRARY / "library.json", {"format_version": 1, "source": source_receipt,
                                    "instruments": descriptors,
                                    "scope": "Full channel-4 source instruments, q16 gain variants and explicitly reduced stored bandwidth. Bank prefixes contain every byte actually read while audible; virtual cursor ends can lie beyond their stored prefix."})
    expected_data = bytes(expected)
    (out / "expected-input.bin").write_bytes(expected_data)
    duration = len(expected_data) / RATE
    metadata = {"source": source_receipt, "source_channel": 4,
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
                                        "canonical_divisor": prepared[identifier]["canonical_divisor"],
                                        "divisor": prepared[identifier]["divisor"],
                                        "real_end": prepared[identifier]["real_end"],
                                        "loop_start": prepared[identifier]["loop_start"],
                                        "loop_rounding_pitch_error_cents": (
                                            1200 * math.log2(prepared[identifier]["original_loop_length"] /
                                                (prepared[identifier]["divisor"] *
                                                 (prepared[identifier]["real_end"] - prepared[identifier]["loop_start"])))
                                            if prepared[identifier]["loop_start"] is not None else None)}
                                       for identifier in identifiers],
                "muted_ticks": muted_ticks, "ended_ticks": ended_ticks,
                "loop_wrap_buffers": loop_wraps,
                "fractional_pitch_error_cents": [min(pitch_errors), max(pitch_errors)],
                "gain_quantization_error_units": [min(gain_errors), max(gain_errors)],
                "expected_input_sha256": hashlib.sha256(expected_data).hexdigest(),
                "quality": "Nearest q16 volume levels with half steps rounded upward. Additional per-instrument low-pass decimation preserves original clocks and note periods but lowers sampled bandwidth. Instruments 2–6 retain the accepted excerpt's decimation.",
                "loop_model": "Looped initial DMA end is ceil(source first-pass bytes/divisor); repeat begins at round(source loop start/divisor). One-shot ends are page-rounded with neutral padding only. Eight-bit fractional phase is retained across repeat; resampled endpoint rounding is disclosed pitch quantization.",
                "runtime_contract": "Mute bit requires constant neutral reads while cursor advances. Physical bank prefix ends are not logical sample ends. Ended one-shots stay silent through gain changes until a retrigger."}
    _save(out / "input.json", metadata)
    serial_banks = [{key: (str(bank[key]) if key == "asm_path" else bank[key])
                     for key in bank if key != "data"} for bank in banks]
    _save(out / "full-model.json", {"frames": frames, "banks": serial_banks, "metadata": metadata})
    return {"frames": frames, "banks": banks, "metadata": metadata}
