"""Exact physical-row score transport for the native full-length player.

Rows are 24 physical bytes, never audio. Sparse byte changes and waits are
compressed with bounded 4 KiB LZSS. Native decoding is in full-length-score.asm.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
WIDTH = 24
HEADER = 11
MAGIC = b"FSC1"
HISTORY_BYTES = 4096


def _rows(rows) -> list[bytes]:
    if isinstance(rows, (bytes, bytearray)):
        if len(rows) % WIDTH:
            raise ValueError("Physical rows must contain exactly24 bytes each")
        rows = [bytes(rows[i:i + WIDTH]) for i in range(0, len(rows), WIDTH)]
    else:
        rows = [bytes(row) for row in rows]
    if not rows or len(rows) > 65535 or any(len(row) != WIDTH for row in rows):
        raise ValueError("Expected1..65535 physical24-byte rows")
    return rows


def _clear_transients(state: bytearray) -> None:
    state[15] = state[22] = 0
    state[23] &= 0xFC  # Ordinary retriggers clear; PCM gain bits persist.


def encode_events(rows) -> bytes:
    rows = _rows(rows)
    previous = bytearray(WIDTH)
    output = bytearray()
    waits = 0

    def flush():
        nonlocal waits
        while waits:
            count = min(255, waits)
            output.extend((0, count))
            waits -= count

    for row in rows:
        _clear_transients(previous)
        groups, payload = 0, bytearray()
        for group in range(3):
            mask, values = 0, bytearray()
            for bit in range(8):
                index = group * 8 + bit
                if row[index] != previous[index]:
                    mask |= 1 << bit
                    values.append(row[index])
            if mask:
                groups |= 1 << group
                payload.append(mask)
                payload.extend(values)
        if groups:
            flush()
            output.append(groups)
            output.extend(payload)
        else:
            waits += 1
        previous[:] = row
    flush()
    return bytes(output)


def decode_events(data: bytes, count: int) -> list[bytes]:
    state = bytearray(WIDTH)
    rows, position, waits = [], 0, 0
    while len(rows) < count:
        _clear_transients(state)
        if waits:
            waits -= 1
        else:
            groups = data[position]
            position += 1
            if not groups:
                waits = data[position] - 1
                position += 1
                if waits < 0:
                    raise ValueError("Zero-length score wait")
            else:
                if groups > 7:
                    raise ValueError("Invalid physical score group mask")
                for group in range(3):
                    if groups & (1 << group):
                        mask = data[position]
                        position += 1
                        for bit in range(8):
                            if mask & (1 << bit):
                                state[group * 8 + bit] = data[position]
                                position += 1
        rows.append(bytes(state))
    if position != len(data) or waits:
        raise ValueError("Unused physical score event data")
    return rows


def _lz_encode(data: bytes, long_matches: bool = False) -> bytes:
    output, position = bytearray(), 0
    while position < len(data):
        flag_at = len(output)
        output.append(0)
        for bit in range(8):
            if position == len(data):
                break
            maximum = 255 if long_matches else 18
            for length in range(min(maximum, len(data) - position), 2, -1):
                found = data.rfind(data[position:position + length],
                                   max(0, position - HISTORY_BYTES), position + length - 1)
                if found >= 0:
                    word = (position - found - 1) | (min(15, length - 3) << 12)
                    output.extend(word.to_bytes(2, "little"))
                    if long_matches and length >= 18:
                        output.append(length - 18)
                    position += length
                    break
            else:
                output[flag_at] |= 1 << bit
                output.append(data[position])
                position += 1
    return bytes(output)


def _lz_decode(data: bytes, size: int, long_matches: bool = False) -> bytes:
    output, cursor = bytearray(), 0
    while len(output) < size:
        flags = data[cursor]
        cursor += 1
        for bit in range(8):
            if len(output) == size:
                break
            if flags & (1 << bit):
                output.append(data[cursor])
                cursor += 1
            else:
                word = int.from_bytes(data[cursor:cursor + 2], "little")
                cursor += 2
                distance, length = (word & 4095) + 1, (word >> 12) + 3
                if long_matches and length == 18:
                    length += data[cursor]
                    cursor += 1
                if distance > len(output) or len(output) + length > size:
                    raise ValueError("Invalid physical-score LZSS reference")
                for _ in range(length):
                    output.append(output[-distance])
    if cursor != len(data):
        raise ValueError("Unused physical-score LZSS bytes")
    return bytes(output)


def encode_rows(rows) -> bytes:
    rows = _rows(rows)
    descriptors = sorted({row[16:22] for row in rows})
    if len(descriptors) > 255:
        raise ValueError("PCM descriptor dictionary exceeds255 entries")
    identifiers = {descriptor: index for index, descriptor in enumerate(descriptors)}
    logical = [row[:16] + bytes((identifiers[row[16:22]], 0, 0, 0, 0, 0)) + row[22:]
               for row in rows]
    events = encode_events(logical)
    packed = _lz_encode(events, long_matches=True)
    table = b"".join(bytes(descriptor[field] for descriptor in descriptors) for field in range(6))
    blob = (MAGIC + bytes((WIDTH, 7)) + len(rows).to_bytes(2, "little")
            + len(events).to_bytes(3, "little") + bytes((len(descriptors),)) + table + packed)
    if decode_rows(blob, len(rows)) != rows:
        raise ValueError("Full physical score roundtrip changed row bytes")
    return blob


def decode_rows(blob: bytes, count: int) -> list[bytes]:
    if blob[:4] != MAGIC or blob[4] != WIDTH or blob[5] not in (1, 7):
        raise ValueError("Unknown full physical score format")
    if int.from_bytes(blob[6:8], "little") != count:
        raise ValueError("Physical score frame count differs")
    size = int.from_bytes(blob[8:11], "little")
    if blob[5] == 1:
        return decode_events(_lz_decode(blob[HEADER:], size), count)
    descriptors = blob[11]
    start = 12 + descriptors * 6
    logical = decode_events(_lz_decode(blob[start:], size, long_matches=True), count)
    result = []
    for row in logical:
        identifier = row[16]
        if identifier >= descriptors:
            raise ValueError("PCM descriptor ID outside table")
        descriptor = bytes(blob[12 + field * descriptors + identifier] for field in range(6))
        result.append(row[:16] + descriptor + row[22:])
    return result


def prepare(rows, out: Path, stream_address: int = 0x8000) -> dict:
    rows = _rows(rows)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    blob = encode_rows(rows)
    (out / "score-stream.bin").write_bytes(blob)
    (out / "physical-rows.bin").write_bytes(b"".join(rows))
    data = out / "score-data.asm"
    data.write_text(f'.pc = ${stream_address:04x} "Compressed physical score"\n'
                    'score_data:\n'
                    f'    .import binary "{(out / "score-stream.bin").resolve()}"\n'
                    'score_data_end:\n'
                    + "".join(f'.label score_pcm_table_{16 + field} = score_data+{12 + field * blob[11]}\n'
                              for field in range(6)))
    assembly = out / "score.asm"
    assembly.write_text(f'.label FRAME_COUNT = {len(rows)}\n'
                        f'.const SCORE_HEADER_BYTES = {12 + blob[11] * 6}\n'
                        '.const SCORE_PCM_DESCRIPTORS = 1\n'
                        '.const SCORE_LONG_MATCHES = 1\n'
                        '.label tick_record = $0600\n'
                        '.pc = $f000 "Full physical score decoder"\n'
                        f'.import source "{(HERE / "full-length-score.asm").resolve()}"\n'
                        f'.import source "{data}"\n')
    receipt = {"codec": "physical24-pcm-descriptors-delta-wait-long-lzss4k", "frames": len(rows),
               "score_bytes": len(blob), "history_bytes": HISTORY_BYTES,
               "stream_address": stream_address, "stream_end": stream_address + len(blob),
               "score_asm": str(assembly), "score_data_asm": str(data),
               "stream_file": str(out / "score-stream.bin"),
               "rows_file": str(out / "physical-rows.bin"),
               "sha256": hashlib.sha256(blob).hexdigest(),
               "row_sha256": hashlib.sha256(b"".join(rows)).hexdigest(),
               "event_bytes": int.from_bytes(blob[8:11], "little"),
               "pcm_descriptors": blob[11], "pcm_descriptor_bytes": blob[11] * 6,
               "host_roundtrip_exact": True,
               "native_code_source": str(HERE / "full-length-score.asm"),
               "native_code_address": 0xF000, "tick_record_address": 0x0600,
               "decoder_zp": [0x40, 0x51], "history_range": [0xE000, 0xF000],
               "transients": "Offsets15/22 zero each tick; only bits0/1 of23 zero each tick; gain bits persist."}
    (out / "score.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


build_score = prepare


def verify_native(rows, out: Path) -> dict:
    """Decode every row in VICE and export physical bytes plus timer bounds."""
    rows = _rows(rows)
    out = Path(out).resolve()
    prepared = prepare(rows, out, stream_address=0x1000)
    if prepared["stream_end"] > 0xD000:
        raise ValueError("Standalone score stream does not fit below I/O")
    harness = out / "harness.asm"
    harness.write_text('''BasicUpstart2(start)
start:
    sei
    cld
    lda #$35
    sta $01
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    ldx #$0f
!clear:
    sta $02,x
    dex
    bpl !clear-
    jsr score_init
    lda #$ff
    sta $dc04
    sta $dc05
    lda #$11
    sta $dc0e
resume:
    lda score_exhausted
    bne done
    lda #0
    sta $02
    sta $04
    lda #2
    sta $03
row_loop:
    jsr read_timer
    sta $07
    lda $0b
    sta $08
    jsr score_next_tick
    jsr read_timer
    sta $09
    lda $0b
    sta $0a
    lda $07
    sec
    sbc $09
    sta $0c
    lda $08
    sbc $0a
    sta $0d
    ldy #23
!copy:
    lda tick_record,y
    sta ($02),y
    dey
    bpl !copy-
    ldy #24
    lda $0c
    sta ($02),y
    iny
    lda $0d
    sta ($02),y
    clc
    lda $02
    adc #26
    sta $02
    bcc !position+
    inc $03
!position:
    inc $04
    lda score_exhausted
    bne dump_ready
    lda $04
    cmp #39
    bne row_loop
dump_ready:
    jmp dump_ready
read_timer:
    lda $dc05
    sta $0b
    lda $dc04
    tax
    lda $dc05
    cmp $0b
    bne read_timer
    txa
    rts
done:
    jmp done
.assert "Score harness below stream", * <= $1000, true
.import source "score.asm"
''')
    command = [str(Path.home() / ".local/bin/kickass"), str(harness),
               "-o", str(out / "harness.prg"), "-symbolfile"]
    assembled = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out / "harness-build.log").write_text(assembled.stdout + assembled.stderr)
    if assembled.returncode:
        raise RuntimeError(assembled.stdout + assembled.stderr)
    symbols = {name: int(value, 16) for name, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", (out / "harness.sym").read_text())}
    chunks = []
    monitor = [f'load "{out / "harness.prg"}" 0',
               f'break exec ${symbols["dump_ready"]:04x}',
               f'break exec ${symbols["done"]:04x}', f'g ${symbols["start"]:04x}']
    for start in range(0, len(rows), 39):
        count = min(39, len(rows) - start)
        path = out / f"chunk-{start:05d}.bin"
        chunks.append(path)
        monitor.extend((f'bsave "{path}" 0 $0200 ${0x200 + count * 26 - 1:04x}',
                        f'g ${symbols["resume"]:04x}'))
    monitor.append('quit')
    (out / "harness.mon").write_text("\n".join(monitor) + "\n")
    import native_support as support
    command = support.profile().vice_command() + ["-console", "-seed", "1", "-warp",
        "-initbreak", "ready", "-moncommands", str(out / "harness.mon"),
        "-limitcycles", "150000000", "-sounddev", "dump",
        "-soundarg", str(out / "registers.txt")]
    captured = subprocess.run(command, text=True, capture_output=True, timeout=180)
    (out / "harness-vice.log").write_text(captured.stdout + captured.stderr)
    if captured.returncode or not all(path.exists() for path in chunks):
        raise RuntimeError("Native score harness did not produce every output chunk")
    actual, cycles = [], []
    for path in chunks:
        raw = path.read_bytes()
        if len(raw) % 26:
            raise ValueError("Incomplete native score output record")
        for offset in range(0, len(raw), 26):
            actual.append(raw[offset:offset + 24])
            cycles.append(int.from_bytes(raw[offset + 24:offset + 26], "little"))
    mismatches = [i for i, (a, b) in enumerate(zip(actual, rows)) if a != b]
    passed = len(actual) == len(rows) and not mismatches
    result = {"passed": passed, "rows_compared": len(actual), "row_mismatches": len(mismatches),
              "mismatch_examples": mismatches[:20], "physical_bytes_compared": len(actual) * WIDTH,
              "score": prepared, "decoder_code_bytes": symbols["decoder_end"] - 0xF000,
              "native_row_sha256": hashlib.sha256(b"".join(actual)).hexdigest(),
              "maximum_timer_interval_cycles": max(cycles),
              "maximum_after_first_row_cycles": max(cycles[1:], default=0),
              "mean_timer_interval_cycles": sum(cycles) / len(cycles),
              "cycle_scope": "Standalone foreground only, no music NMI. Timer interval includes call and coherent timer-reading overhead, so it is an upper bound rather than exact inner-routine cycles.",
              "worst_rows": sorted(range(len(cycles)), key=cycles.__getitem__, reverse=True)[:20]}
    (out / "native-proof.json").write_text(json.dumps(result, indent=2) + "\n")
    if not passed:
        raise ValueError("Native physical score differs from source rows")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rows", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stream-address", type=lambda value: int(value, 0), default=0x8000)
    parser.add_argument("--verify-native", action="store_true")
    args = parser.parse_args()
    result = (verify_native(args.rows.read_bytes(), args.out) if args.verify_native else
              prepare(args.rows.read_bytes(), args.out, args.stream_address))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
