"""Pack independent PCM/SID state streams into shared twelve-tick chunks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CLOCK, PERIOD, CHUNK = 985248, 126, 12


def _dictionary(rows: list[tuple]) -> tuple[list[tuple], list[int]]:
    entries, indices, seen = [], [], {}
    for row in rows:
        if row not in seen:
            if len(entries) == 256:
                raise ValueError("A full-song state dictionary exceeds 256 entries")
            seen[row] = len(entries); entries.append(row)
        indices.append(seen[row])
    return entries, indices


def _chunks(indices: list[int]) -> tuple[list[tuple], list[int]]:
    unique, playlist, seen = [], [], {}
    for start in range(0, len(indices), CHUNK):
        block = tuple((indices[start:start + CHUNK] + [0] * CHUNK)[:CHUNK])
        if block not in seen:
            seen[block] = len(unique); unique.append(block)
        playlist.append(seen[block])
    return unique, playlist


def _bytes(values) -> str:
    return "    .byte " + ",".join(map(str, values))


def pack_score(pcm_frames: list, sid_rows: list, banks: list,
               out: Path, frame_count: int, sid_settings: list | None = None) -> dict:
    """Write banks, SoA state tables, chunks, playlist and exact frame clock.

    Bank IDs are contiguous; each bank is page-aligned and contains a used
    prefix. Logical end/loop offsets can extend beyond that stored prefix,
    but the independent sample compiler must prove every audible read exists.
    Muted reads use the runtime's constant-value instruction instead of RAM.
    """
    if frame_count != len(pcm_frames) or frame_count != len(sid_rows) or not 1 <= frame_count <= 65535:
        raise ValueError("Full-song frame counts disagree or exceed 16-bit range")
    banks = sorted(banks, key=lambda bank: bank["id"])
    if [bank["id"] for bank in banks] != list(range(len(banks))) or not 1 <= len(banks) <= 128:
        raise ValueError("Sample variants require contiguous IDs below 128")
    for row in pcm_frames:
        step, trigger, variant = row
        if not 0 <= step <= 255 or trigger not in (0, 1) or not 0 <= variant <= 255 or (variant & 127) >= len(banks):
            raise ValueError("Invalid sampled state")
    if any(len(row) != 6 or any(not 0 <= x <= 255 for x in row) for row in sid_rows):
        raise ValueError("Invalid SID register row")
    streams = [[tuple(row) for row in pcm_frames],
               [tuple(row[:3]) for row in sid_rows], [tuple(row[3:]) for row in sid_rows]]
    dictionaries, ids, blocks, playlists = [], [], [], []
    for rows in streams:
        dictionary, indices = _dictionary(rows)
        chunks, playlist = _chunks(indices)
        decoded = [dictionary[value] for block in playlist for value in chunks[block]][:frame_count]
        if decoded != rows:
            raise ValueError("Full-song compressed score failed its complete roundtrip")
        dictionaries.append(dictionary); ids.append(indices); blocks.append(chunks); playlists.append(playlist)
    # Check the absolute resident span on the host. An oversized collection
    # can wrap a 16-bit assembler program counter and otherwise make a final
    # address assertion appear to pass while overwriting the runtime.
    bank_bytes = sum(len(bytes(bank["data"])) for bank in banks)
    dictionary_start = (0x1000 + bank_bytes + len(banks) * 5 + 255) & ~255
    resident_end = (dictionary_start + 9 * 256 + sum(len(stream) for stream in blocks) * CHUNK
                    + len(playlists[0]) * 6 + 175)
    if resident_end > 0xD000:
        raise ValueError(f"Resident gain banks and score exceed C64 RAM: end${resident_end:05x}, limit$0d000")
    settings = ([{"sustain": 2, "pulse_width": 1966}, {"sustain": 1, "pulse_width": 2048}]
                if sid_settings is None else sid_settings)
    if len(settings) != 2 or any(
            type(s["sustain"]) is not int or not 0 <= s["sustain"] <= 15
            or type(s["pulse_width"]) is not int or not 0 <= s["pulse_width"] <= 4095
            for s in settings):
        raise ValueError("Declare exactly two valid SID sustain/pulse-width settings")
    lines = [f".label FRAME_COUNT = {frame_count}"]
    for index, setting in enumerate(settings, 1):
        lines += [f'.label SID{index}_SUSTAIN = {setting["sustain"]}',
                  f'.label SID{index}_PULSE = {setting["pulse_width"]}']
    lines += ['.assert "Full runtime must fit before banks", runtime_end <= $1000, true',
              '.pc = $1000 "Reusable full-song instrument variants"']
    for bank in banks:
        data = bytes(bank["data"])
        if len(data) % 256 or not data:
            raise ValueError("Sample variants must contain nonempty complete pages")
        end, loop = int(bank["real_end"]), bank["loop_start"]
        if not 0 < end < 0xFF00 or (loop is not None and not 0 <= loop < end):
            raise ValueError("Invalid logical sample bounds")
        if loop is None and end & 255:
            raise ValueError("One-shot logical end must include neutral page padding")
        path = Path(bank["asm_path"]).resolve()
        lines += [".align $100", f'variant_bank_{bank["id"]}:', f'    .import source "{path}"']
    lines += ["sample_banks_end:", "bank_base_hi:",
              _bytes(f'>variant_bank_{bank["id"]}' for bank in banks),
              "bank_end_lo:", _bytes(bank["real_end"] & 255 for bank in banks),
              "bank_end_hi:", _bytes(bank["real_end"] >> 8 for bank in banks),
              "bank_loop_lo:", _bytes(0 if bank["loop_start"] is None else bank["loop_start"] & 255 for bank in banks),
              "bank_loop_hi:", _bytes(255 if bank["loop_start"] is None else bank["loop_start"] >> 8 for bank in banks)]
    names = [("pcm", ["step", "trigger", "variant"]),
             ("lead", ["low", "high", "control"]), ("bass", ["low", "high", "control"])]
    for dictionary, (name, fields) in zip(dictionaries, names):
        for column, field in enumerate(fields):
            values = [row[column] for row in dictionary] + [0] * (256 - len(dictionary))
            lines += [".align $100", f"{name}_{field}:", _bytes(values)]
    for chunks, (name, _) in zip(blocks, names):
        for index, block in enumerate(chunks):
            lines += [f"{name}_chunk_{index}:", _bytes(block)]
    lines += ["score:", "playlist:"]
    for pcm, lead, bass in zip(*playlists):
        lines.append(f"    .word pcm_chunk_{pcm},lead_chunk_{lead},bass_chunk_{bass}")
    cuts = [(i * CLOCK + PERIOD * 25) // (PERIOD * 50) for i in range(176)]
    starts = [256 - (b - a) for a, b in zip(cuts, cuts[1:])]
    full_cuts = [(i * CLOCK + PERIOD * 25) // (PERIOD * 50) for i in range(frame_count + 1)]
    if any(256 - starts[i % 175] != b - a for i, (a, b) in enumerate(zip(full_cuts, full_cuts[1:]))):
        raise ValueError("Cyclic frame table differs from cumulative PAL timing")
    lines += ["frame_start_low:", _bytes(starts), "program_end:",
              '.assert "Resident full song below I/O", program_end <= $d000, true']
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.asm").write_text("\n".join(lines) + "\n")
    raw = bytes(value for rows in streams for row in rows for value in row)
    result = {"format": "Three page-aligned state dictionaries, independent 12-tick chunks and direct 16-bit chunk-pointer playlist",
              "frames": frame_count, "chunk_ticks": CHUNK,
              "dictionary_entries": [len(x) for x in dictionaries],
              "unique_chunks": [len(x) for x in blocks], "playlist_entries": len(playlists[0]),
              "dictionary_bytes": 9 * 256, "chunk_bytes": sum(len(x) for x in blocks) * CHUNK,
              "playlist_bytes": len(playlists[0]) * 6, "clock_bytes": 175,
              "bank_metadata_bytes": len(banks) * 5,
              "bank_bytes": sum(len(bytes(bank["data"])) for bank in banks),
              "decoded_score_sha256": hashlib.sha256(raw).hexdigest(),
              "roundtrip_passed": True,
              "scope": "All source sample retriggers, gain/mute selections and SID register states survive compression exactly. Sample preparation and SID approximation remain separate quality choices."}
    result["score_bytes_before_alignment"] = sum(result[k] for k in
                                                 ("dictionary_bytes", "chunk_bytes", "playlist_bytes", "clock_bytes", "bank_metadata_bytes"))
    (out / "score-compression.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
