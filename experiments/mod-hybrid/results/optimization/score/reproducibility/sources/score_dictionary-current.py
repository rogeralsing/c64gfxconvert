"""Lossless, non-recursive byte-phrase compression for the packed PCM score.

The first variant uses FE 00 for literal FE and FE 01..FF for a raw phrase.
The smaller dictionary8 variant leaves 00..BF literal, uses C0 followed by a
raw literal byte, and C1..FF for one of 63 raw phrases. Neither variant nests
dictionary references, keeping the 6502 decoder bounded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import heapq
import json
import lzma
from pathlib import Path
import zlib


ESCAPE = 0xFE
TOKEN_ESCAPE = 0xC0
LENGTHS = tuple(range(2, 25)) + (28, 32, 40, 48, 64, 96, 128, 192, 255)


def encode_blocks(blocks: list[bytes], maximum: int = 255, candidate_limit: int = 8192,
                  one_byte: bool = False) -> dict:
    """Find profitable phrases without matching across block or token boundaries."""
    maximum = min(maximum, 255 - TOKEN_ESCAPE if one_byte else 255)
    token_bytes = 1 if one_byte else 2

    def escapes(phrase):
        return sum(value >= TOKEN_ESCAPE for value in phrase) if one_byte else phrase.count(ESCAPE)

    candidates = Counter()
    for data in blocks:
        for length in LENGTHS:
            if len(data) >= length:
                candidates.update(data[i:i + length] for i in range(len(data) - length + 1))
    # A phrase costs its raw bytes and three bytes of pointer/length metadata.
    ranked = [(count * (len(phrase) + escapes(phrase) - token_bytes) - len(phrase) - 3, phrase)
              for phrase, count in candidates.items() if count > 1]
    ranked = heapq.nlargest(candidate_limit, (item for item in ranked if item[0] > 0))
    del candidates
    chunks: list[list[bytes | int]] = [[data] for data in blocks]
    heap = [(-profit, phrase, -1) for profit, phrase in ranked]
    heapq.heapify(heap)
    phrases = []
    revision = 0
    while heap and len(phrases) < maximum:
        negative, phrase, measured_revision = heapq.heappop(heap)
        if measured_revision != revision:
            count = sum(chunk.count(phrase) for group in chunks for chunk in group if isinstance(chunk, bytes))
            profit = count * (len(phrase) + escapes(phrase) - token_bytes) - len(phrase) - 3
            if profit > 0:
                heapq.heappush(heap, (-profit, phrase, revision))
            continue
        if negative >= 0:
            break
        phrases.append(phrase)
        phrase_id = len(phrases)
        replaced = []
        for group in chunks:
            result = []
            for chunk in group:
                if not isinstance(chunk, bytes) or phrase not in chunk:
                    result.append(chunk)
                    continue
                parts = chunk.split(phrase)
                for index, part in enumerate(parts):
                    if part:
                        result.append(part)
                    if index != len(parts) - 1:
                        result.append(phrase_id)
            replaced.append(result)
        chunks = replaced
        revision += 1
    encoded = []
    for group in chunks:
        output = bytearray()
        for chunk in group:
            if isinstance(chunk, int):
                if one_byte:
                    output.append(TOKEN_ESCAPE + chunk)
                else:
                    output.extend((ESCAPE, chunk))
            else:
                for value in chunk:
                    if one_byte:
                        if value >= TOKEN_ESCAPE:
                            output.append(TOKEN_ESCAPE)
                        output.append(value)
                    else:
                        output.append(value)
                        if value == ESCAPE:
                            output.append(0)
        encoded.append(bytes(output))
    dictionary_bytes = sum(map(len, phrases))
    metadata_bytes = 3 * (len(phrases) + 1)
    result = {"blocks": encoded, "phrases": phrases, "one_byte": one_byte,
              "token_escape": TOKEN_ESCAPE if one_byte else ESCAPE,
              "encoded_block_bytes": sum(map(len, encoded)),
              "dictionary_bytes": dictionary_bytes, "metadata_bytes": metadata_bytes}
    result["bytes"] = result["encoded_block_bytes"] + dictionary_bytes + metadata_bytes
    if decode_blocks(result) != blocks:
        raise ValueError("Dictionary codec changed packed score bytes")
    return result


def decode_blocks(packed: dict) -> list[bytes]:
    output = []
    one_byte = packed.get("one_byte", False)
    token_escape = packed.get("token_escape", TOKEN_ESCAPE)
    for block in packed["blocks"]:
        result = bytearray()
        position = 0
        while position < len(block):
            value = block[position]
            position += 1
            if one_byte:
                if value < token_escape:
                    result.append(value)
                elif value == token_escape:
                    if position == len(block):
                        raise ValueError("Truncated single-byte dictionary escape")
                    result.append(block[position])
                    position += 1
                else:
                    phrase_id = value - token_escape
                    if phrase_id > len(packed["phrases"]):
                        raise ValueError("Single-byte dictionary phrase ID outside table")
                    result.extend(packed["phrases"][phrase_id - 1])
                continue
            if value != ESCAPE:
                result.append(value)
                continue
            if position == len(block):
                raise ValueError("Truncated dictionary escape")
            phrase_id = block[position]
            position += 1
            if phrase_id:
                if phrase_id > len(packed["phrases"]):
                    raise ValueError("Dictionary phrase ID outside table")
                result.extend(packed["phrases"][phrase_id - 1])
            else:
                result.append(ESCAPE)
        output.append(bytes(result))
    return output


def rle_blocks(blocks: list[bytes]) -> dict:
    """Evaluate FE/count/value byte runs; count zero escapes a literal FE."""
    encoded = []
    for data in blocks:
        result = bytearray()
        position = 0
        while position < len(data):
            value = data[position]
            end = position + 1
            while end < len(data) and data[end] == value and end - position < 255:
                end += 1
            count = end - position
            if count >= 4:
                result.extend((ESCAPE, count, value))
            else:
                for _ in range(count):
                    result.append(value)
                    if value == ESCAPE:
                        result.append(0)
            position = end
        encoded.append(bytes(result))
    restored = []
    for data in encoded:
        result = bytearray()
        position = 0
        while position < len(data):
            value = data[position]
            position += 1
            if value != ESCAPE:
                result.append(value)
            else:
                count = data[position]
                position += 1
                if count:
                    result.extend([data[position]] * count)
                    position += 1
                else:
                    result.append(ESCAPE)
        restored.append(bytes(result))
    if restored != blocks:
        raise ValueError("RLE changed packed score bytes")
    return {"blocks": encoded, "bytes": sum(map(len, encoded)), "roundtrip_verified": True}


def evaluate(source: Path, out: Path, one_byte: bool = False) -> dict:
    from pcm4_build import decode, normalize, pack

    arrangement = json.loads(source.read_bytes())
    ticks = arrangement["ticks"]
    choices = [pack(ticks, grouping) for grouping in ("row", "order", "16", "32", "48", "64", "96", "128")]
    baseline = min(choices, key=lambda item: item["bytes"])
    expected = [normalize(tick) for tick in ticks]
    reports = []
    best = None
    # Raw block de-duplication has different interactions with phrase sharing.
    groupings = list(dict.fromkeys((baseline["grouping"], "row", "order", "128")))
    for grouping in groupings:
        raw = next(item for item in choices if item["grouping"] == grouping)
        compressed = encode_blocks(raw["blocks"], one_byte=one_byte)
        restored = dict(raw, blocks=decode_blocks(compressed))
        if decode(restored) != expected:
            raise ValueError("Dictionary score differs from normalized source ticks")
        playlist_bytes = 2 * (len(raw["playlist"]) + 1)
        total = compressed["bytes"] + playlist_bytes
        report = {"grouping": grouping, "raw_score_bytes": raw["bytes"],
                  "dictionary_score_bytes": total, "playlist_bytes": playlist_bytes,
                  "encoded_block_bytes": compressed["encoded_block_bytes"],
                  "dictionary_bytes": compressed["dictionary_bytes"],
                  "metadata_bytes": compressed["metadata_bytes"],
                  "phrases": len(compressed["phrases"]), "roundtrip_verified": True}
        run_length = rle_blocks(raw["blocks"])
        report["rle_score_bytes_before_decoder"] = run_length["bytes"] + playlist_bytes
        reports.append(report)
        if best is None or total < best[0]:
            best = (total, raw, compressed)
    total, raw, compressed = best
    joined = b"".join(baseline["blocks"])
    # These are offline compression bounds, not implemented 6502 codecs.
    bounds = {"zlib_block_payload_bytes": len(zlib.compress(joined, 9)),
              "lzma_block_payload_bytes": len(lzma.compress(joined)),
              "scope": "Payload-only offline comparison; excludes resident decoder, workspace and random-block access overhead."}
    receipt = {"source": str(source.resolve()), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "duration_s": arrangement["duration_s"], "ticks": len(ticks),
               "baseline_score_bytes": baseline["bytes"], "baseline_grouping": baseline["grouping"],
               "dictionary_score_bytes": total, "saved_score_bytes_before_decoder": baseline["bytes"] - total,
               "best_grouping": raw["grouping"], "alternatives": reports, "offline_bounds": bounds,
               "one_byte_dictionary_tokens": one_byte,
               "token_escape": TOKEN_ESCAPE if one_byte else ESCAPE,
               "phrase_lengths_considered": LENGTHS,
               "roundtrip_all_ticks_verified": True}
    out.mkdir(parents=True, exist_ok=True)
    (out / "compression.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--one-byte", action="store_true")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.input, args.out, args.one_byte), indent=2))


if __name__ == "__main__":
    main()
