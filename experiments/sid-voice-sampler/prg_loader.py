"""Package an unchanged native image for an ordinary C64 KERNAL LOAD.

The assembled player has code under KERNAL ROM. Loading its flat image through
$D000 would write to VIC, SID and CIA registers before the player can bank ROM
out. Stage that high code in a declared unused low-RAM arena instead. A short
bootstrap restores it before entering the original, byte-identical player.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess


def package(native: Path, program: Path, *, entry: int,
            arena: tuple[int, int]) -> dict:
    raw = native.read_bytes()
    load = int.from_bytes(raw[:2], "little")
    end = load + len(raw) - 2
    start, limit = arena
    if not (load <= entry < start < limit <= 0xd000 < 0xf000 < end <= 0xff00):
        raise ValueError("Invalid native image or low-RAM loader arena")
    offset = lambda address: address - load + 2
    if any(raw[offset(start):offset(limit)]):
        raise ValueError("Loader arena overlaps nonzero native data")
    if any(raw[offset(0xd000):offset(0xf000)]):
        raise ValueError("Packaging requires unused I/O RAM and zeroed score history")
    original = raw[offset(entry):offset(entry) + 3]
    if original != bytes((0x78, 0xd8, 0xa2)):
        raise ValueError("Unexpected native SEI/CLD/LDX entry")

    length = end - 0xf000
    pages, remainder = divmod(length, 256)
    lines = [f'.pc = ${start:04x} "Safe disk-load bootstrap"', 'loader_enter:',
             'sei', 'cld', 'lda #$7f', 'sta $dc0d', 'sta $dd0d',
             'lda $dc0d', 'lda $dd0d', 'lda #$35', 'sta $01',
             'lda #0', 'ldx #0', '!clear:']
    # Reproduce the flat image's zeroed history without loading across I/O.
    lines += [f'sta ${address:04x},x' for address in range(0xe000, 0xf000, 256)]
    lines += ['inx', 'bne !clear-', 'ldx #0', '!copy:']
    for page in range(pages):
        lines += [f'lda loader_payload+{page * 256},x',
                  f'sta ${0xf000 + page * 256:04x},x']
    if pages:
        lines += ['inx', 'bne !copy-']
    if remainder:
        lines += ['ldx #0', '!tail:', f'lda loader_payload+{pages * 256},x',
                  f'sta ${0xf000 + pages * 256:04x},x', 'inx',
                  f'cpx #{remainder}', 'bne !tail-']
    for index, value in enumerate(original):
        lines += [f'lda #{value}', f'sta ${entry + index:04x}']
    lines += ['loader_done:', f'jmp ${entry:04x}', 'loader_payload:',
              f'.import binary "{native.resolve()}", {offset(0xf000)}, {length}',
              'loader_end:',
              f'.assert "Bootstrap exceeds its unused arena", * <= ${limit:04x}, true']
    source = program.parent / 'loader.asm'
    source.write_text('\n'.join(lines) + '\n')
    loader = program.parent / 'loader.prg'
    command = ['rtk', 'proxy', str(Path.home() / '.local/bin/kickass'),
               str(source.resolve()), '-o', str(loader.resolve()), '-symbolfile']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (program.parent / 'loader-build.log').write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    labels = {key: int(value, 16) for key, value in re.findall(
        r'\.label\s+(\w+)\s*=\s*\$([\da-fA-F]+)', source.with_suffix('.sym').read_text())}
    staged = loader.read_bytes()[2:]
    packed = bytearray(raw[:offset(0xd000)])
    packed[offset(start):offset(start) + len(staged)] = staged
    packed[offset(entry):offset(entry) + 3] = bytes((0x4c, start & 255, start >> 8))
    program.write_bytes(packed)
    return {'native_program': str(native.resolve()),
            'native_sha256': hashlib.sha256(raw).hexdigest(),
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'native_bytes': len(raw), 'native_end_exclusive': end,
            'load_end_exclusive': 0xd000, 'arena': [start, limit],
            'loader_bytes': labels['loader_payload'] - start,
            'staged_bytes': length, 'symbols': labels,
            'scope': 'Startup only. Original entry and high code restored before playback; score, instruments and playback addresses unchanged.'}
