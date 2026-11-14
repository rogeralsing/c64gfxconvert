"""Data-only budget for complete source-control events, never waveform data.

This measures a possible score representation. It does not implement a C64
decoder, assign SID voices, synthesize instruments or claim a native budget.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import lzma
from pathlib import Path
import sys
import zlib

SID = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SID))
import native_support as support

FIELDS = ((1, "playing_sample"), (2, "period"), (1, "volume"), (1, "loop_target"))


def normalize(state: dict) -> tuple:
    return (int(state["playing_sample"]), int(state["period"]), int(state["volume"]),
            int(state.get("loop_sample", state["playing_sample"])), bool(state["trigger"]),
            int(state.get("offset", 0)), state.get("first_segment_bytes"))


def encode(frames: list, *, volume_ramps: bool = False) -> tuple[bytes, dict]:
    previous = [[0, 0, 0, 0] for _ in range(4)]
    ramps = [[0, 0] for _ in range(4)]
    output, waits, changes = bytearray(), 0, Counter()
    payload_sizes, waiting_runs = [], []

    def flush_wait():
        nonlocal waits
        while waits:
            count = min(255, waits)
            output.extend((0, count)); waiting_runs.append(count); waits -= count

    for index, frame in enumerate(frames):
        channel_mask, payload = 0, bytearray()
        for channel, state in enumerate(frame):
            if ramps[channel][1]:
                previous[channel][2] += ramps[channel][0]
                ramps[channel][1] -= 1
            command, body = int(state[4]), bytearray()
            changes["trigger"] += bool(state[4])
            for field, (width, name) in enumerate(FIELDS):
                if state[field] != previous[channel][field]:
                    command |= 2 << field
                    body.extend(int(state[field]).to_bytes(width, "little"))
                    changes[name] += 1
            if state[5]:
                command |= 32; body.extend(state[5].to_bytes(2, "little")); changes["offset"] += 1
            if state[6] is not None:
                command |= 64; body.extend(int(state[6]).to_bytes(2, "little")); changes["short_DMA"] += 1
            if volume_ramps and not ramps[channel][1] and index + 3 < len(frames):
                delta = frames[index + 1][channel][2] - state[2]
                count = 0
                if delta:
                    while index + count + 1 < len(frames) and frames[index + count + 1][channel][2] == state[2] + (count + 1) * delta:
                        count += 1
                if count >= 3:
                    command |= 128; body.extend((delta & 255, count))
                    ramps[channel] = [delta, count]
                    changes["volume_ramp_program"] += 1
                    changes["volume_ticks_automated"] += count
            if command:
                channel_mask |= 1 << channel
                payload.extend((command,)); payload.extend(body)
            previous[channel] = list(state[:4])
        if channel_mask:
            flush_wait(); output.extend((channel_mask,)); output.extend(payload)
            payload_sizes.append(1 + len(payload))
        else:
            waits += 1
    flush_wait()
    return bytes(output), {"field_events": dict(changes), "event_frames": len(payload_sizes),
        "unchanged_frames": sum(waiting_runs), "wait_commands": len(waiting_runs),
        "maximum_wait_ticks": max(waiting_runs, default=0),
        "maximum_event_frame_bytes": max(payload_sizes, default=0)}


def decode(data: bytes, frame_count: int) -> list:
    """Decode through persistent state and ephemeral trigger/offset fields."""
    position, result = 0, []
    state = [[0, 0, 0, 0] for _ in range(4)]
    ramps = [[0, 0] for _ in range(4)]

    def advance():
        for values, ramp in zip(state, ramps):
            if ramp[1]:
                values[2] += ramp[0]
                ramp[1] -= 1

    while len(result) < frame_count:
        marker = data[position]; position += 1
        if marker == 0:
            count = data[position]; position += 1
            if not count or len(result) + count > frame_count:
                raise ValueError("Invalid event-score wait")
            for _ in range(count):
                advance()
                result.append([tuple(values) + (False, 0, None) for values in state])
            continue
        if marker & 240:
            raise ValueError("Unknown event-score frame marker")
        advance()
        frame = []
        for channel in range(4):
            trigger, offset, segment = False, 0, None
            if marker & (1 << channel):
                command = data[position]; position += 1
                if not command:
                    raise ValueError("Invalid channel update mask")
                trigger = bool(command & 1)
                for field, (width, _) in enumerate(FIELDS):
                    if command & (2 << field):
                        state[channel][field] = int.from_bytes(data[position:position + width], "little")
                        position += width
                if command & 32:
                    offset = int.from_bytes(data[position:position + 2], "little"); position += 2
                if command & 64:
                    segment = int.from_bytes(data[position:position + 2], "little"); position += 2
                if command & 128:
                    delta = int.from_bytes(data[position:position + 1], "little", signed=True)
                    remaining = data[position + 1]; position += 2
                    if not delta or remaining < 3 or not 0 <= state[channel][2] + delta * remaining <= 64:
                        raise ValueError("Invalid exact volume-ramp program")
                    ramps[channel] = [delta, remaining]
            frame.append(tuple(state[channel]) + (trigger, offset, segment))
        result.append(frame)
    if position != len(data):
        raise ValueError("Unused or truncated score data")
    return result


def lzss_encode(data: bytes) -> bytes:
    """Bounded4KiB history,3..18-byte matches and eight flag bits per group."""
    output, position = bytearray(len(data).to_bytes(4, "little")), 0
    while position < len(data):
        flag_at = len(output); output.append(0)
        for bit in range(8):
            if position == len(data):
                break
            for length in range(min(18, len(data) - position), 2, -1):
                found = data.rfind(data[position:position + length], max(0, position - 4096), position + length - 1)
                if found >= 0:
                    word = (position - found - 1) | ((length - 3) << 12)
                    output.extend(word.to_bytes(2, "little")); position += length
                    break
            else:
                output[flag_at] |= 1 << bit
                output.append(data[position]); position += 1
    return bytes(output)


def lzss_decode(data: bytes) -> bytes:
    size, cursor, output = int.from_bytes(data[:4], "little"), 4, bytearray()
    while len(output) < size:
        flags = data[cursor]; cursor += 1
        for bit in range(8):
            if len(output) == size:
                break
            if flags & (1 << bit):
                output.append(data[cursor]); cursor += 1
            else:
                word = int.from_bytes(data[cursor:cursor + 2], "little"); cursor += 2
                distance, length = (word & 4095) + 1, (word >> 12) + 3
                if distance > len(output) or len(output) + length > size:
                    raise ValueError("Invalid LZSS reference")
                for _ in range(length):
                    output.append(output[-distance])
    if cursor != len(data):
        raise ValueError("Unused LZSS bytes")
    return bytes(output)


def measure(out: Path) -> dict:
    out = out.resolve(); out.mkdir(parents=True, exist_ok=True)
    source = json.loads((SID.parent / "mod-hybrid/sources/hyperbased.source.json").read_text())
    mod = support.source_mod(source, out)
    timeline = support.build_timeline(mod)
    ticks = timeline["ticks"]
    if len(ticks) != 16692 or any(abs(tick["duration_s"] - .02) > 1e-10 for tick in ticks):
        raise ValueError("Expected the pinned complete50Hz Hyperbased traversal")
    frames = [[normalize(state) for state in tick["channels"]] for tick in ticks]
    events, stats = encode(frames)
    restored = decode(events, len(frames))
    if restored != frames:
        raise ValueError("Event-score roundtrip changed source control")
    packed = lzss_encode(events)
    if lzss_decode(packed) != events:
        raise ValueError("Bounded LZSS roundtrip changed event data")
    ramp_events, ramp_stats = encode(frames, volume_ramps=True)
    if decode(ramp_events, len(frames)) != frames:
        raise ValueError("Exact volume automation changed source control")
    packed_ramps = lzss_encode(ramp_events)
    if lzss_decode(packed_ramps) != ramp_events:
        raise ValueError("Bounded LZSS changed volume-automation data")
    digest = lambda data: hashlib.sha256(data).hexdigest()
    flat = json.dumps(frames, separators=(",", ":")).encode()
    report = {"passed": True, "source_sha256": mod["sha256"], "ticks": len(ticks),
        "duration_s": len(ticks) / 50, "source_channels": 4, "normalized_channel_states": len(ticks) * 4,
        "event_score_bytes": len(events), "event_bytes_per_second": len(events) / (len(ticks) / 50),
        "bounded_LZSS_bytes_including4byte_header": len(packed), "bounded_LZSS_history_bytes": 4096,
        "offline_zlib_bytes": len(zlib.compress(events, 9)), "offline_LZMA_bytes": len(lzma.compress(events)),
        "all_normalized_states_exact": True, "LZSS_roundtrip_exact": True, **stats,
        "normalized_states_sha256": digest(flat), "event_score_sha256": digest(events),
        "bounded_LZSS_sha256": digest(packed), "measurement_source_sha256": support.digest(Path(__file__)),
        "exact_volume_ramp_variant": {"event_score_bytes": len(ramp_events),
            "bounded_LZSS_bytes_including4byte_header": len(packed_ramps),
            "offline_zlib_bytes": len(zlib.compress(ramp_events, 9)),
            "offline_LZMA_bytes": len(lzma.compress(ramp_events)),
            "all_normalized_states_exact": True, "LZSS_roundtrip_exact": True, **ramp_stats,
            "event_score_sha256": digest(ramp_events), "bounded_LZSS_sha256": digest(packed_ramps),
            "automation": "Per-channel signed volume delta plus exact tick count; only runs of3or more equal nonzero steps. Advance on every50Hz tick, including wait commands. No waveform or audio data is involved."},
        "format": "Frame channel-mask1..15, then per-channel trigger/field masks with only changed instrument,16-bit period,volume and loop target; optional offset/shortDMA. Marker0 plus1..255ticks represents unchanged control, not stopped music. All per-tick pitch/volume effects remain resolved exactly.",
        "scope": "All four source channels before voice routing. No audio, waveform bank or SID-register expansion. This measures encoded data only: no C64 decoder, total RAM fit, sample-mixer CPU or listening fidelity is proved. LZSS needs a native streaming decoder and4KiB history; zlib/LZMA are offline size comparisons only."}
    (out / "score-events.bin").write_bytes(events)
    (out / "score-events.lzss.bin").write_bytes(packed)
    (out / "score-ramp-events.bin").write_bytes(ramp_events)
    (out / "score-ramp-events.lzss.bin").write_bytes(packed_ramps)
    support.save(out / "score-budget.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=SID / "work/hyperbased/full-length-budget")
    print(json.dumps(measure(parser.parse_args().out), indent=2))
