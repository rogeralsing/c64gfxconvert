#!/usr/bin/env python3
"""Pack a complete native C64 image for a safe, ordinary KERNAL LOAD.

The startup decoder runs from the future audio buffer at $0200. It restores
the image backwards with I/O banked out, then enters the original player.
There is no decompression during audio or video playback.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compress(data: bytes) -> bytes:
    """Encode reversed bytes with bounded literal and overlapping match runs."""
    source = data[::-1]
    chains: dict[bytes, deque[int]] = defaultdict(lambda: deque(maxlen=64))
    encoded, literals = bytearray(), bytearray()

    def flush() -> None:
        if literals:
            encoded.append(len(literals) - 1)
            encoded.extend(literals)
            literals.clear()

    index = 0
    while index < len(source):
        key = source[index:index + 3]
        length, distance = 0, 0
        limit = min(130, len(source) - index)
        if len(key) == 3:
            for previous in reversed(chains[key]):
                if index - previous > 65535:
                    break
                count = 3
                while count < limit and source[previous + count] == source[index + count]:
                    count += 1
                if count > length:
                    length, distance = count, index - previous
                if length == limit:
                    break
        if length >= 4:
            flush()
            encoded.append(0x80 | (length - 3))
            encoded.extend(distance.to_bytes(2, "little"))
            consumed = length
        else:
            literals.append(source[index])
            consumed = 1
            if len(literals) == 128:
                flush()
        for position in range(index, index + consumed):
            if position + 3 <= len(source):
                chains[source[position:position + 3]].append(position)
        index += consumed
    flush()
    return bytes(encoded[::-1])


def decode(packed: bytes, count: int) -> bytes:
    """Independent host interpretation of the backwards stored stream."""
    source, result, at = packed[::-1], bytearray(), 0
    while len(result) < count:
        command = source[at]
        at += 1
        if command < 128:
            size = command + 1
            result.extend(source[at:at + size])
            at += size
        else:
            size = (command & 127) + 3
            distance = int.from_bytes(source[at:at + 2], "little")
            at += 2
            if not 1 <= distance <= len(result):
                raise ValueError("Invalid backwards match distance")
            for _ in range(size):
                result.append(result[-distance])
    if len(result) != count or at != len(source):
        raise ValueError("Packed stream did not end at the image boundary")
    return bytes(result[::-1])


def package(native: Path, program: Path, *, entry: int) -> dict:
    native_bytes = native.read_bytes()
    load = int.from_bytes(native_bytes[:2], "little")
    original = native_bytes[2:]
    end = load + len(original)
    if load != 0x0801 or not load <= entry < end <= 65536:
        raise ValueError("Expected a BASIC-start native image loaded at $0801")
    packed = compress(original)
    if decode(packed, len(original)) != original:
        raise ValueError("Cold-start compressor failed its independent roundtrip")
    folder = program.parent
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cold-start.bin").write_bytes(packed)
    source = folder / "cold-start.asm"
    text = f'''// Restore the native image without loading through live I/O registers.
.label source_pointer = $20
.label output_pointer = $22
.label match_pointer = $24
.label run_length = $26
BasicUpstart2(unpack_start)
unpack_start:
    sei
    cld
    ldx #$ff
    txs
    lda #$7f
    sta $dc0d
    sta $dd0d
    lda $dc0d
    lda $dd0d
    lda #0
    sta $dc0e
    sta $dc0f
    sta $dd0e
    sta $dd0f
    sta $d011
    sta $d015
    sta $d01a
    lda #$34
    sta $01
    ldx #0
!copy:
    lda decoder_image,x
    sta $0200,x
    inx
    cpx #(decoder_end-decoder_start)
    bne !copy-
    jmp decoder_start
decoder_image:
.pseudopc $0200 {{
decoder_start:
    // Move the compressed input below the native load address. This keeps
    // literal-run overhead from overwriting unread input near the final page.
    lda #<packed_start
    sta source_pointer
    lda #>packed_start
    sta source_pointer+1
    lda #0
    sta output_pointer
    lda #4
    sta output_pointer+1
    .if ({len(packed) // 256} != 0) {{
    ldx #{len(packed) // 256}
!copy_page:
    ldy #0
!copy_byte:
    lda (source_pointer),y
    sta (output_pointer),y
    iny
    bne !copy_byte-
    inc source_pointer+1
    inc output_pointer+1
    dex
    bne !copy_page-
    }}
    .if ({len(packed) % 256} != 0) {{
    ldy #0
!copy_tail:
    lda (source_pointer),y
    sta (output_pointer),y
    iny
    cpy #{len(packed) % 256}
    bne !copy_tail-
    }}
    lda #<${0x0400 + len(packed) - 1:04x}
    sta source_pointer
    lda #>${0x0400 + len(packed) - 1:04x}
    sta source_pointer+1
    lda #<${end - 1:04x}
    sta output_pointer
    lda #>${end - 1:04x}
    sta output_pointer+1
next_command:
    jsr get_byte
    bmi match_run
    clc
    adc #1
    sta run_length
!literal:
    jsr get_byte
    jsr put_byte
    dec run_length
    bne !literal-
    jmp next_command
match_run:
    and #127
    clc
    adc #3
    sta run_length
    jsr get_byte
    clc
    adc output_pointer
    sta match_pointer
    jsr get_byte
    adc output_pointer+1
    sta match_pointer+1
!match:
    ldy #0
    lda (match_pointer),y
    jsr put_byte
    ldx match_pointer
    bne !match_low+
    dec match_pointer+1
!match_low:
    dec match_pointer
    dec run_length
    bne !match-
    jmp next_command
get_byte:
    ldy #0
    lda (source_pointer),y
    ldx source_pointer
    bne !source_low+
    dec source_pointer+1
!source_low:
    dec source_pointer
    ora #0
    rts
put_byte:
    ldy #0
    sta (output_pointer),y
    ldx output_pointer
    bne !output_low+
    dec output_pointer+1
!output_low:
    dec output_pointer
    lda output_pointer
    cmp #<${load - 1:04x}
    bne !more+
    lda output_pointer+1
    cmp #>${load - 1:04x}
    bne !more+
restore_done:
    lda #$35
    sta $01
    jmp ${entry:04x}
!more:
    rts
decoder_end:
}}
.assert "Decoder must fit its future audio buffer",decoder_end-decoder_start<256,true
packed_start:
.import binary "cold-start.bin"
packed_end:
.assert "Ordinary LOAD must end before I/O",*<=$d000,true
'''
    source.write_text(text)
    command = ["rtk", "proxy", str(Path.home() / ".local/bin/kickass"), str(source.resolve()),
               "-o", str(program.resolve()), "-symbolfile"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (folder / "cold-start-build.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    symbols = {key: int(value, 16) for key, value in re.findall(
        r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)", source.with_suffix(".sym").read_text())}
    packaged = program.read_bytes()
    # Execute the assembled decoder in a separate 6502 model. Trap any store
    # over unread compressed input, then compare every restored native byte.
    from py65.devices.mpu6502 import MPU
    memory = [0] * 65536
    memory[load:load + len(packaged) - 2] = packaged[2:]
    decoder_offset = symbols["decoder_image"] - load + 2
    decoder_length = symbols["decoder_end"] - symbols["decoder_start"]
    memory[0x0200:0x0200 + decoder_length] = packaged[decoder_offset:decoder_offset + decoder_length]
    cpu = MPU(memory=memory, pc=symbols["decoder_start"])
    for steps in range(8_000_000):
        if cpu.pc == entry:
            break
        if cpu.pc == symbols["put_byte"]:
            target = memory[0x22] + 256 * memory[0x23]
            source_cursor = memory[0x20] + 256 * memory[0x21]
            if 0x0400 <= target <= source_cursor:
                raise ValueError("Backwards restoration would overwrite unread input")
        cpu.step()
    else:
        raise ValueError("Cold-start decoder exceeded its bounded instruction budget")
    restored = bytes(memory[load:end])
    if restored != original:
        raise ValueError("Assembled cold-start decoder changed the native image")
    receipt = {"nativeProgram": str(native.resolve()), "nativeSha256": digest(native_bytes),
               "program": str(program.resolve()), "programSha256": digest(packaged),
               "nativeImageStart": load, "nativeImageEndExclusive": end,
               "nativeImageBytes": len(original), "compressedBytes": len(packed),
               "programBytes": len(packaged), "loadEndExclusive": load + len(packaged) - 2,
               "decoderBytes": decoder_length, "symbols": symbols,
               "hostDecoderCycles": cpu.processorCycles, "hostDecoderSteps": steps,
               "allRestoredBytesMatch": True, "noUnreadSourceOverlap": True,
               "scope": "Startup only; RAM under I/O is restored with I/O disabled. No decompression during playback."}
    (folder / "packaging.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entry", type=lambda value: int(value, 0), required=True)
    args = parser.parse_args()
    result = package(args.native.resolve(), args.output.resolve(), entry=args.entry)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
