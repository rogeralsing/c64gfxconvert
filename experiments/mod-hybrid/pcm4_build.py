"""Pack a full four-channel MOD arrangement into a resident PAL C64 player."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
CLOCK = 985248
RATE = CLOCK / 256


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(tick: dict, offsets: bool = False, loop_targets: bool = False) -> tuple:
    result = []
    if len(tick["pcm"]) != 4:
        raise ValueError("Four PCM channels are required")
    for voice in tick["pcm"]:
        sample, step, volume = (int(voice[k]) for k in ("sample", "step", "volume"))
        if not 0 <= sample < 256 or not 0 <= step < 256 or not 0 <= volume <= 64:
            raise ValueError("PCM ID, fractional step or volume outside hardware bounds")
        state = (sample, step, min(15, (volume * 15 + 32) // 64), bool(voice["trigger"]))
        offset = int(voice.get("offset", 0)) if state[3] else 0
        fraction = int(voice.get("offset_fraction", 0)) if state[3] else 0
        if not 0 <= offset <= 65535 or not 0 <= fraction <= 255:
            raise ValueError("Sample start offset exceeds the 16.8-bit cursor")
        if not offsets and (offset or fraction):
            raise ValueError("Sample offsets require the extended score format")
        state = state + (offset, fraction) if offsets else state
        if loop_targets:
            loop_id = int(voice.get("loop_sample", sample))
            if not 0 <= loop_id <= 255:
                raise ValueError("Loop sample ID exceeds the PCM descriptor range")
            state += (loop_id,)
        result.append(state)
    return tuple(result)


def encode(ticks: list, offsets: bool = False, variable_ticks: bool = False,
           loop_targets: bool = False) -> bytes:
    result = bytearray()
    previous = None
    held = 0
    previous_samples = None

    def flush():
        nonlocal held
        while held:
            count = min(127, held)
            result.append(count)
            held -= count

    for tick in ticks:
        current = normalize(tick, offsets, loop_targets)
        mask, payload = 0, bytearray()
        if variable_ticks and tick["sample_count"] != previous_samples:
            mask |= 16
            payload.append(tick["sample_count"])
        for index, state in enumerate(current):
            old = previous[index] if previous else None
            flags = sum(bit for bit, field in ((1, 0), (2, 1), (4, 2))
                        if old is None or state[field] != old[field])
            flags |= 8 if state[3] else 0
            flags |= 16 if offsets and state[3] and (state[4] or state[5]) else 0
            flags |= 32 if loop_targets and (old is None or state[-1] != old[-1]) else 0
            if flags:
                mask |= 1 << index
                payload.append(flags)
                for bit, field in ((1, 0), (2, 1), (4, 2)):
                    if flags & bit:
                        payload.append(state[field])
                if flags & 16:
                    payload.extend((state[4] & 255, state[4] >> 8, state[5]))
                if flags & 32:
                    payload.append(state[-1])
        if mask:
            flush()
            result.append(128 | mask)
            result.extend(payload)
        else:
            held += 1
        previous = current
        if variable_ticks:
            previous_samples = tick["sample_count"]
    flush()
    result.append(0)
    return bytes(result)


def pack(ticks: list, grouping: str, offsets: bool = False, variable_ticks: bool = False,
         loop_targets: bool = False) -> dict:
    groups = []
    for index, tick in enumerate(ticks):
        key = ((tick["order"], tick["row"]) if grouping == "row" else tick["order"]
               if grouping == "order" else index // int(grouping))
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(tick)
    blocks, lookup, playlist = [], {}, []
    for _, group in groups:
        data = encode(group, offsets, variable_ticks, loop_targets)
        if data not in lookup:
            lookup[data] = len(blocks)
            blocks.append(data)
        playlist.append(lookup[data])
    result = {"grouping": grouping, "blocks": blocks, "playlist": playlist,
              "bytes": sum(map(len, blocks)) + 2 * (len(playlist) + 1)}
    if offsets:
        result["sample_offsets"] = True
    if variable_ticks:
        result["variable_ticks"] = True
    if loop_targets:
        result["loop_targets"] = True
    return result


def decode(packed: dict, with_timing: bool = False) -> list:
    offsets, variable_ticks = packed.get("sample_offsets", False), packed.get("variable_ticks", False)
    loop_targets = packed.get("loop_targets", False)
    initial = (0, 0, 0, False, 0, 0) if offsets else (0, 0, 0, False)
    states = [initial + (0,) if loop_targets else initial] * 4
    sample_count = None
    result = []
    for index in packed["playlist"]:
        block, position = packed["blocks"][index], 0
        while True:
            command = block[position]
            position += 1
            if not command:
                break
            states = [state[:3] + ((False, 0, 0) if offsets else (False,))
                      + ((state[-1],) if loop_targets else ()) for state in states]
            if command < 128:
                result.extend((tuple(states), sample_count) if with_timing else tuple(states)
                              for _ in range(command))
                continue
            if variable_ticks and command & 16:
                sample_count = block[position]
                position += 1
            for voice in range(4):
                if command & (1 << voice):
                    flags = block[position]
                    position += 1
                    state = list(states[voice])
                    for bit, field in ((1, 0), (2, 1), (4, 2)):
                        if flags & bit:
                            state[field] = block[position]
                            position += 1
                    if offsets and flags & 16:
                        state[4] = block[position] | block[position + 1] << 8
                        state[5] = block[position + 2]
                        position += 3
                    if loop_targets and flags & 32:
                        state[-1] = block[position]
                        position += 1
                    state[3] = bool(flags & 8)
                    states[voice] = tuple(state)
            result.append((tuple(states), sample_count) if with_timing else tuple(states))
        if position != len(block):
            raise ValueError("Unexpected trailing packed bytes")
    return result


def render_ticks(ticks: list) -> tuple[list, bool]:
    """Quantize variable tracker ticks to the fixed DAC clock, without tempo drift.

    Existing 50 Hz scores keep their original stream and C64 Bresenham clock.
    Slower ticks may exceed the byte-sized countdown; held subdivisions retain
    the same cursors and only the first subdivision carries a note trigger.
    """
    if not ticks:
        raise ValueError("A PCM score must contain ticks")
    if all(abs(tick["duration_s"] - 0.02) <= 1e-8 for tick in ticks):
        return ticks, False
    result, cumulative, previous_cut = [], Fraction(0), 0
    for tick in ticks:
        duration = Fraction(5, 2 * int(tick["bpm"])) if "bpm" in tick else Fraction(str(tick["duration_s"]))
        if duration <= 0 or abs(float(duration) - tick["duration_s"]) > 1e-8:
            raise ValueError("Tracker tick duration and BPM disagree")
        cumulative += duration * Fraction(CLOCK, 256)
        cut = (cumulative.numerator * 2 + cumulative.denominator) // (2 * cumulative.denominator)
        count = cut - previous_cut
        previous_cut = cut
        if count < 5:
            raise ValueError("Tracker tick is too short for four staged voice commits")
        pieces = math.ceil(count / 255)
        for index in range(pieces):
            part = count * (index + 1) // pieces - count * index // pieces
            record = dict(tick, sample_count=part)
            if index:
                record["pcm"] = [dict(voice, trigger=False, offset=0, offset_fraction=0) for voice in tick["pcm"]]
            result.append(record)
    if len(result) > 65535:
        raise ValueError("Expanded score exceeds the 16-bit runtime tick counter")
    return result, True


def bytes_asm(data: bytes) -> str:
    return "\n".join("    .byte " + ",".join(f"${value:02x}" for value in data[i:i + 24])
                     for i in range(0, len(data), 24))


def build(input_path: Path, out: Path, score_codec: str = "legacy") -> dict:
    if score_codec not in ("legacy", "dictionary", "dictionary8"):
        raise ValueError("score_codec must be legacy, dictionary or dictionary8")
    arrangement = json.loads(input_path.read_text())
    mode = arrangement.get("mixing", {}).get("mode", "feedback")
    if mode not in ("feedback", "nearest"):
        raise ValueError(f"Unknown PCM4 quantizer mode:{mode}")
    try:
        output_gain = float(arrangement.get("mixing", {}).get("output_gain", 1.0))
    except (TypeError, ValueError) as error:
        raise ValueError("PCM4 output_gain must be finite and positive") from error
    if not math.isfinite(output_gain) or output_gain <= 0:
        raise ValueError("PCM4 output_gain must be finite and positive")
    if mode == "feedback" and output_gain != 1.0:
        raise ValueError("PCM4 output_gain other than1 requires nearest quantization")
    if abs(arrangement["pcm_rate_hz"] - RATE) > 1e-6:
        raise ValueError("Four-PCM backend requires the 3848.625Hz DAC clock")
    source_ticks = arrangement["ticks"]
    ticks, variable_ticks = render_ticks(source_ticks)
    offsets = any(voice.get("offset", 0) or voice.get("offset_fraction", 0)
                  for tick in ticks for voice in tick["pcm"] if voice["trigger"])
    loop_targets = any("loop_sample" in voice for tick in ticks for voice in tick["pcm"])
    if loop_targets and variable_ticks and any(tick["sample_count"] < 8 for tick in ticks):
        raise ValueError("Extended loop-pointer ticks require at least eight DAC sample slots")
    choices = [pack(ticks, grouping, offsets, variable_ticks, loop_targets)
               for grouping in ("row", "order", "16", "32", "48", "64", "96", "128")]
    packed = min(choices, key=lambda item: item["bytes"])
    baseline_score_bytes = packed["bytes"]
    dictionary = None
    dictionary_choices = []
    if score_codec != "legacy":
        from score_dictionary import decode_blocks, encode_blocks
        groupings = tuple(dict.fromkeys((packed["grouping"], "row", "order", "128")))
        for grouping in groupings:
            raw = next(item for item in choices if item["grouping"] == grouping)
            candidate = encode_blocks(raw["blocks"], one_byte=score_codec == "dictionary8")
            if decode_blocks(candidate) != raw["blocks"]:
                raise ValueError("Dictionary codec changed score bytes")
            total = candidate["bytes"] + 2 * (len(raw["playlist"]) + 1)
            dictionary_choices.append((total, raw, candidate))
        _, packed, dictionary = min(dictionary_choices, key=lambda item: item[0])
    if decode(packed) != [normalize(tick, offsets, loop_targets) for tick in ticks]:
        raise ValueError("Packed stream differs from the entire quantized source timeline")
    if variable_ticks and [length for _, length in decode(packed, with_timing=True)] != [tick["sample_count"] for tick in ticks]:
        raise ValueError("Packed stream changed tracker tick sample counts")
    out.mkdir(parents=True, exist_ok=True)
    entries = {int(item["id"]): dict(item) for item in arrangement["pcm_bank"]}
    if not entries or 0 in entries:
        raise ValueError("Sample IDs must be positive;0 is reserved for silence")
    used_ids = {v["sample"] for tick in ticks for v in tick["pcm"]} - {0}
    used_ids |= {v["loop_sample"] for tick in ticks for v in tick["pcm"] if v.get("loop_sample")}
    if not used_ids <= entries.keys():
        raise ValueError("Timeline references a missing sample")
    lines = [".align $100", "volume_table:"]
    table = bytes(32 + round((sample - 8) * level / 4) for level in range(16) for sample in range(16))
    lines.append(bytes_asm(table))
    if mode == "nearest":
        # Gain changes the final DAC lookup only. Clamp before rounding also
        # handles finite gains whose intermediate scaled value overflows.
        quantize = bytes(round(min(15, max(0, 8 + (value - 128) * output_gain / 16)))
                         for value in range(256))
        lines.extend(("quantize_table:", bytes_asm(quantize)))
    else:
        # KickAssembler resolves symbols in both conditional branches.
        lines.append(".label quantize_table = volume_table")
    bank, bank_receipt = {}, []
    for index, entry in entries.items():
        original = Path(entry["data_file"]).read_bytes()
        if not original or max(original) > 15:
            raise ValueError("Sample bank must store unsigned4bit values in full bytes")
        start, length = int(entry["loop_start"]), int(entry["loop_length"])
        data = original
        if length:
            if start < 0 or start + length > len(data):
                raise ValueError("Loop lies outside the sample")
            copies = max(1, math.ceil(256 / length))
            data = data[:start] + data[start:start + length] * copies
        else:
            start, copies = 0, 1
        bank[index] = data
        entry["stored_loop_start"] = start
        bank_receipt.append({"id": index, "source_bytes": len(original), "stored_bytes": len(data),
                             "loop_start": start, "loop_length": length * copies,
                             "loop_copies": copies, "marker": 128 if length or entry.get("loop_target_id") else 129,
                             "source_sha256": sha(Path(entry["data_file"]))})
        if entry.get("loop_target_id"):
            bank_receipt[-1]["loop_target_id"] = int(entry["loop_target_id"])
    if offsets:
        for tick in ticks:
            for voice in tick["pcm"]:
                if voice["trigger"] and voice["sample"]:
                    offset = int(voice.get("offset", 0))
                    if offset > len(bank[int(voice["sample"])]):
                        raise ValueError("Sample start offset exceeds its stored bank")
    def loop_address(index: int) -> str:
        target = int(entries[index].get("loop_target_id", index))
        if target not in entries:
            raise ValueError("Initial segment refers to a missing loop bank")
        if entries[target]["loop_length"]:
            return f"sample_{target}+{entries[target]['stored_loop_start']}"
        return "silence_sample"

    for name, expr in (("bank_start_lo", lambda i: f"<sample_{i}"),
                       ("bank_start_hi", lambda i: f">sample_{i}"),
                       ("bank_loop_lo", lambda i: f"<({loop_address(i)})" if loop_address(i) != "silence_sample" else "<silence_sample"),
                       ("bank_loop_hi", lambda i: f">({loop_address(i)})" if loop_address(i) != "silence_sample" else ">silence_sample")):
        lines.append(name + ":")
        fallback = "<silence_sample" if name.endswith("lo") else ">silence_sample"
        lines.append("    .byte " + ",".join(expr(i) if i in entries else fallback for i in range(max(entries) + 1)))
    lines.append("song_playlist:")
    for offset in range(0, len(packed["playlist"]), 12):
        lines.append("    .word " + ",".join(f"song_block_{i}" for i in packed["playlist"][offset:offset + 12]))
    lines.append("    .word 0")
    emitted_blocks = dictionary["blocks"] if dictionary else packed["blocks"]
    for index, block in enumerate(emitted_blocks):
        lines.extend((f"song_block_{index}:", bytes_asm(block)))
    if dictionary:
        count = len(dictionary["phrases"])
        lines.append("phrase_start_lo:")
        lines.append("    .byte 0" + "".join(f",<phrase_{i}" for i in range(1, count + 1)))
        lines.append("phrase_start_hi:")
        lines.append("    .byte 0" + "".join(f",>phrase_{i}" for i in range(1, count + 1)))
        lines.append("phrase_lengths:")
        lines.append(bytes_asm(bytes([0] + [len(phrase) for phrase in dictionary["phrases"]])))
        for index, phrase in enumerate(dictionary["phrases"], 1):
            lines.extend((f"phrase_{index}:", bytes_asm(phrase)))
    lines.append("pcm_bank_begin:")
    for index, data in sorted(bank.items()):
        path = out / f"sample-{index:02d}.bin"
        path.write_bytes(data)
        lines.extend((f"sample_{index}:", f'    .import binary "{path.resolve()}"'))
        if entries[index]["loop_length"] or entries[index].get("loop_target_id"):
            lines.append(f"    .byte $80\n    .word {loop_address(index)}")
        else:
            lines.append("    .byte $81")
    lines.extend(("pcm_bank_end:", "program_end:", '.assert "Resident PCM4 program below I/O", program_end <= $d000, true'))
    (out / "data.asm").write_text("\n".join(lines) + "\n")
    wrapper = out / "pcm4.asm"
    wrapper.write_text(('#define SCORE_DICTIONARY\n' if dictionary else '')
                       + ('#define SCORE_DICTIONARY_8\n' if score_codec == "dictionary8" else '')
                       + ('#define SAMPLE_OFFSETS\n' if offsets else '')
                       + ('#define VARIABLE_TICKS\n' if variable_ticks else '')
                       + ('#define LOOP_TARGETS\n' if loop_targets else '')
                       + f'.const QUANTIZER_NEAREST = {int(mode == "nearest")}\n'
                       f'#import "{(HERE / "pcm4_player.asm").resolve()}"\n#import "{(out / "data.asm").resolve()}"\n')
    prg = out / "stardust.prg"
    command = [str(Path.home() / ".local/bin/kickass"), str(wrapper.resolve()), "-o", str(prg.resolve()), "-symbolfile"]
    compiled = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out / "build.log").write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise RuntimeError(f"Assembler failed; inspect{out / 'build.log'}")
    sym = out / "pcm4.sym"
    labels = {name: int(value, 16) for name, value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", sym.read_text())}
    if labels["program_end"] > 0xd000:
        raise ValueError(f"Packed data exceeds RAM budget; end${labels['program_end']:04x}")
    receipt = {"input": str(input_path.resolve()), "arrangement_sha256": sha(input_path),
               "program": str(prg.resolve()), "program_sha256": sha(prg), "symbols": str(sym.resolve()),
               "program_bytes": prg.stat().st_size, "program_end": labels["program_end"], "labels": labels,
               "ticks": len(ticks), "duration_s": arrangement["duration_s"], "pcm_rate_hz": RATE,
               "pcm_channels": 4, "sid_voices": 0, "sample_timer_cycles": 256,
               "mixing": {"mode": mode, "output_gain": output_gain,
                          "fine_contributions": "32+round((nibble-8)*level/4)",
                          "quantizer": "clamp(round(8+(sum-128)*output_gain/16),0,15), ties-to-even" if mode == "nearest" else "floor((sum+residual)/16); retain low4 residual bits",
                          "residual_feedback": mode == "feedback"},
               "quantized_timeline_roundtrip_verified": True,
               "compression": {"grouping": packed["grouping"], "stream_bytes": packed["bytes"],
                               "unique_blocks": len(packed["blocks"]), "playlist_entries": len(packed["playlist"]),
                               "alternatives": {item["grouping"]: item["bytes"] for item in choices}},
               "pcm_bank": {"stored_sample_bytes": sum(map(len, bank.values())), "samples": bank_receipt,
                            "marker_bytes": sum(3 if e["loop_length"] or e.get("loop_target_id") else 1 for e in entries.values())},
               "clock": {"cut_formula": "(30789*n+200)//400", "initial_next_dac": 8,
                         "initial_residual": 0,
                         "stagger_samples_before_boundary": [7, 5, 3, 1] if loop_targets else [3, 2, 1, 0],
                         "semantics": ("Write previous DAC; commit staged voice at tick_samples8/6/4/2 with recovery IRQs between commits; resolve marker, mix current cursors, advance8bit fractional steps. EOF skips stagger and stops at final boundary."
                                       if loop_targets else "Write previous DAC; commit staged voice at tick_samples4/3/2/1; resolve marker, mix current cursors, advance8bit fractional steps. EOF skips stagger and stops at final boundary.")},
               "source_sha256": {name: sha(HERE / name) for name in ("pcm4_build.py", "pcm4_player.asm")}}
    receipt["compression"]["codec"] = score_codec
    if offsets or variable_ticks or loop_targets:
        receipt["extended_score"] = {"sample_offsets": bool(offsets), "variable_ticks": variable_ticks,
                                     "loop_targets": loop_targets,
                                     "source_ticks": len(source_ticks), "runtime_ticks": len(ticks)}
        receipt["sample_count"] = (sum(tick["sample_count"] for tick in ticks) if variable_ticks
                                   else (len(ticks) * 30789 + 200) // 400)
        receipt["clock"]["cut_formula"] = "nearest cumulative tracker duration * 985248/256; ties upward" if variable_ticks else receipt["clock"]["cut_formula"]
    if dictionary:
        receipt["compression"].update({
            "stream_bytes": min(item[0] for item in dictionary_choices),
            "legacy_best_stream_bytes": baseline_score_bytes,
            "saved_data_bytes_before_decoder": baseline_score_bytes - min(item[0] for item in dictionary_choices),
            "dictionary_entries": len(dictionary["phrases"]),
            "dictionary_bytes": dictionary["dictionary_bytes"],
            "dictionary_metadata_bytes": dictionary["metadata_bytes"],
            "encoded_block_bytes": dictionary["encoded_block_bytes"],
            "dictionary_alternatives": {item[1]["grouping"]: item[0] for item in dictionary_choices},
            "dictionary_byte_roundtrip_verified": True,
        })
        receipt["source_sha256"]["score_dictionary.py"] = sha(HERE / "score_dictionary.py")
    (out / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "results/pcm4-clean/arrangement.json")
    parser.add_argument("--out", type=Path, default=HERE / "results/pcm4-clean/c64")
    parser.add_argument("--score-codec", choices=("legacy", "dictionary", "dictionary8"), default="legacy")
    args = parser.parse_args()
    result = build(args.input, args.out, args.score_codec)
    print(json.dumps({key: result[key] for key in ("program", "symbols", "program_bytes", "program_end", "compression")}))


if __name__ == "__main__":
    main()
