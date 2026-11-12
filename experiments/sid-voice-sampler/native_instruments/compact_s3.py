"""Pack unchanged C4 instrument/pitch/gain windows for the native SID3 mixer.

The original sample cursor resets on C4 triggers. Repeated reads of the same
instrument, period, gain and source position share one byte. This is instrument
asset deduplication; no combined bass/drum waveform or song PCM is stored.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
SAMPLER = HERE.parent
sys.path.insert(0, str(SAMPLER))
import native_support as support

NEUTRAL = 113
SCALE = 90


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(out: Path, *, arena_start: int | None = None,
            placements: dict[int, int] | None = None,
            original: Path = SAMPLER / "work/hyperbased/linus-mix") -> dict:
    """Return exact reusable assets and frame-wise absolute ADC base pointers.

    Assets expose raw ``data`` bytes plus provenance and physical bounds.
    ``pointer_low``/``pointer_high`` are1000-byte arrays. The native loop starts
    Y at zero and reads ADC(base),Y through count−1. Pointer bases may precede a
    trimmed asset, but every actual indexed address is independently verified.
    Supply an arena origin, or a complete per-asset placement map for split RAM.
    """
    if (arena_start is None) == (placements is None):
        raise ValueError("Supply exactly one arena start or per-asset physical-placement map")
    out = Path(out).resolve()
    original = Path(original).resolve()
    out.mkdir(parents=True, exist_ok=True)
    receipt = json.loads((original / "input.json").read_text())
    counts = receipt["frame_sample_counts_exact"]
    if len(counts) != 1000 or sum(counts) != 156389:
        raise ValueError("This compact proof requires the unchanged first20seconds")
    expected = (original / "drum-input.bin").read_bytes()
    if len(expected) != sum(counts):
        raise ValueError("The canonical independent drum input is incomplete")
    mod = support.source_mod(receipt["source"], out)
    ticks = support.build_timeline(mod)["ticks"][:len(counts)]
    if len(ticks) != len(counts) or any(abs(t["duration_s"] - .02) > 1e-9 for t in ticks):
        raise ValueError("Original tracker timeline differs from the canonical20ms clock")

    groups, frame_info, current, period, source_position, cut = {}, [], None, None, 0, 0
    independently_replayed = bytearray()
    prepared = {}
    trigger_count = 0
    for tick_index, (tick, count) in enumerate(zip(ticks, counts)):
        state = tick["channels"][3]
        instrument, pitch, gain = (int(state[key]) for key in ("playing_sample", "period", "volume"))
        if state.get("offset", 0) or "first_segment_bytes" in state or state.get("loop_sample", instrument) not in (0, instrument):
            raise ValueError("Offsets, shortened DMA and independent repeat targets are outside this exact proof")
        if state["trigger"]:
            current, period, source_position = instrument, pitch, 0
            trigger_count += 1
        if current != instrument or period != pitch:
            raise ValueError("Original C4 changed held pitch/instrument without a trigger")
        key = instrument, pitch, gain
        sample = mod["samples"][instrument - 1]
        if sample["loop_length"] > 2:
            raise ValueError("This compact C4 proof requires the original one-shot samples")
        source_key = instrument, pitch
        if source_key not in prepared:
            ratio = Fraction(support.CLOCK / support.PERIOD * pitch / support.PAULA).limit_denominator(4096)
            raw = np.frombuffer(sample["data"], np.int8).astype(np.float64) / 128
            prepared[source_key] = (resample_poly(raw, ratio.numerator, ratio.denominator), ratio)
        wave, ratio = prepared[source_key]
        selected = wave[source_position:source_position + count]
        selected = np.pad(selected, (0, count - len(selected)))
        independent = np.rint(NEUTRAL + selected * SCALE * gain / 64).astype(int)
        if independent.min() < 0 or independent.max() > 225:
            raise ValueError("Original drum headroom changed")
        values = expected[cut:cut + count]
        if independent.astype(np.uint8).tobytes() != values:
            raise ValueError("Independent original-instrument replay differs from accepted C4 bytes")
        independently_replayed.extend(independent.astype(np.uint8).tobytes())
        group = groups.setdefault(key, {"values": {}, "first": None, "last": None,
                                       "frames": [], "source_sample_sha256": _sha(sample["data"]),
                                       "resampling_ratio": [ratio.numerator, ratio.denominator]})
        for offset, value in enumerate(values):
            location = source_position + offset
            prior = group["values"].setdefault(location, value)
            if prior != value:
                raise ValueError("Equal original instrument/pitch/gain/source positions disagree")
        constant = all(value == NEUTRAL for value in values)
        if not constant:
            group["first"] = source_position if group["first"] is None else min(group["first"], source_position)
            group["last"] = source_position + count - 1 if group["last"] is None else max(group["last"], source_position + count - 1)
            group["frames"].append(tick_index)
        frame_info.append({"tick": tick_index, "key": key, "source_position": source_position,
                           "constant": constant, "count": count, "trigger": bool(state["trigger"])})
        source_position += count
        cut += count
    if bytes(independently_replayed) != expected:
        raise ValueError("Original C4 phase/resampling model is not byte-identical")

    assets = [{"id": 0, "kind": "neutral", "data": bytes([NEUTRAL] * 256),
               "bytes": 256, "first_read_index": 0, "last_read_index": 255,
               "instrument": None, "source_period": None, "gain": None}]
    ids = {}
    for key, group in sorted(groups.items()):
        if group["first"] is None:
            continue
        first, last = group["first"], group["last"]
        data = bytes(group["values"].get(location, NEUTRAL) for location in range(first, last + 1))
        identifier = len(assets)
        ids[key] = identifier
        assets.append({"id": identifier, "kind": "original_C4_instrument_pitch_gain_window",
                       "instrument": key[0], "source_period": key[1], "gain": key[2],
                       "source_sample_sha256": group["source_sample_sha256"],
                       "resampling_ratio": group["resampling_ratio"],
                       "first_read_index": first, "last_read_index": last,
                       "read_frame_references": group["frames"],
                       "unread_internal_holes": sum(location not in group["values"] for location in range(first, last + 1)),
                       "data": data, "bytes": len(data)})
    if placements is None:
        placements, position = {}, arena_start
        for asset in assets:
            placements[asset["id"]] = position
            position += asset["bytes"]
    elif set(placements) != set(range(len(assets))):
        raise ValueError("Placement map must contain every compact asset exactly once")
    memory = {}
    for asset in assets:
        physical = placements[asset["id"]]
        size = asset["bytes"]
        if type(physical) is not int or not 0 <= physical <= physical + size - 1 <= 65535:
            raise ValueError("Compact C4 asset lies outside sixteen-bit RAM")
        if physical < 0xE000 and physical + size > 0xD000:
            raise ValueError("Compact C4 assets cannot occupy visible SID I/O")
        if physical + size > 0xFFFA:
            raise ValueError("Compact C4 assets cannot overwrite native interrupt vectors")
        asset.update(physical_min=physical, physical_max=physical + size - 1,
                     sha256=_sha(asset["data"]))
        for offset, value in enumerate(asset["data"]):
            address = physical + offset
            if address in memory:
                raise ValueError("Compact C4 physical assets overlap")
            memory[address] = value

    low, high, replay = bytearray(), bytearray(), bytearray()
    page_crosses, used_assets = [], Counter()
    for frame in frame_info:
        identifier = 0 if frame["constant"] else ids[frame["key"]]
        asset = assets[identifier]
        position = 0 if identifier == 0 else frame["source_position"]
        pointer = (asset["physical_min"] + position - asset["first_read_index"]) & 65535
        low.append(pointer & 255)
        high.append(pointer >> 8)
        crossing = 0
        for y in range(frame["count"]):
            address = (pointer + y) & 65535
            if not asset["physical_min"] <= address <= asset["physical_max"]:
                raise ValueError("Absolute ADC,Y reads outside a retained C4 window")
            replay.append(memory[address])
            crossing += int((pointer & 255) + y > 255)
        used_assets[identifier] += 1
        page_crosses.append(crossing)
        frame.update(asset_id=identifier, pointer=pointer,
                     pointer_low=pointer & 255, pointer_high=pointer >> 8,
                     indexed_page_cross_extra_cycles=crossing)
    if bytes(replay) != expected:
        raise ValueError("Relocated compact C4 windows differ from accepted drum input")

    for asset in assets:
        path = out / f'asset-{asset["id"]:02d}.bin'
        path.write_bytes(asset["data"])
        asset["file"] = str(path)
    (out / "pointer-low.bin").write_bytes(low)
    (out / "pointer-high.bin").write_bytes(high)
    (out / "counts.bin").write_bytes(bytes(counts))
    result = {"source": receipt["source"], "original": str(original),
              "sample_period_cycles": support.PERIOD,
              "sample_rate_hz": support.CLOCK / support.PERIOD,
              "frames": len(counts), "input_codes": len(expected),
              "frame_sample_counts_exact": counts, "source_triggers": trigger_count,
              "asset_count": len(assets), "asset_bytes": sum(asset["bytes"] for asset in assets),
              "pointer_bytes": len(low) + len(high), "counts_bytes": len(counts),
              "asset_frame_references": dict(used_assets), "assets": assets,
              "pointer_low": bytes(low), "pointer_high": bytes(high), "counts": counts,
              "frame_states": frame_info,
              "accepted_drum_sha256": _sha(expected), "compact_replay_sha256": _sha(replay),
              "independent_original_instrument_model_exact": True,
              "all_relocated_reads_within_physical_asset": True,
              "compact_roundtrip_passed": True,
              "page_cross_extra_cycles_total": sum(page_crosses),
              "page_cross_extra_cycles_per_frame": page_crosses,
              "page_cross_extra_cycles_maximum_frame": max(page_crosses),
              "maximum_extra_cycles_per_absolute_indexed_read": 1,
              "native_contract": "Reset logical source position at each original C4 trigger; advance by every156/157count including neutral frames. Frame pointer=physical window start+source position−first read index; Y starts0. Constant113frames use shared256-byte neutral asset. Native ADC absolute,Y needs both pointer bytes and must budget page crossings.",
              "scope": "Exact source-channel4 instrument/pitch/gain reuse only. No bass mixing, flattened song PCM, altered waveform, native CPU measurement or new listening acceptance."}
    serializable = {key: value for key, value in result.items() if key not in ("pointer_low", "pointer_high", "assets")}
    serializable["assets"] = [{key: value for key, value in asset.items() if key != "data"} for asset in assets]
    (out / "metadata.json").write_text(json.dumps(serializable, indent=2) + "\n")
    (out / ".gitignore").write_text("*\n!.gitignore\n!metadata.json\n")
    return result
