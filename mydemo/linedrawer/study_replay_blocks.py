#!/usr/bin/env python3
"""Compare collision-aware literal motif replay with the cube's native line drawer."""

import argparse
from math import gcd
from random import Random
import re
import shutil
import socket
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from cube_model import ROTATION_FRAMES, frame_segments, normalized_cells, normalized_points
from linedrawer import build_font
from verify_linedrawer import BUFFERS, JCOUNT, load_monitor

HERE = Path(__file__).resolve().parent
KICKASS = Path.home() / ".local/bin/kickass"
TARGETS = (
    (0, 3, 156, 42),
    (159, 42, 3, 3),
    (3, 0, 27, 96),
)
CROSSINGS = (
    (24, 0, 24, 99), (48, 0, 48, 99), (80, 0, 80, 99),
    (112, 0, 112, 99), (0, 16, 159, 16), (0, 28, 159, 28),
    (0, 44, 159, 44), (0, 64, 159, 64),
)
SYMBOL = re.compile(r"^al C:([0-9a-fA-F]+) \.([^\s]+)$", re.M)


def assemble(source, program):
    arguments = [str(KICKASS), str(source), "-odir", str(program.parent),
                 "-o", str(program), "-vicesymbols"]
    result = subprocess.run(arguments, cwd=source.parent, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    symbols = program.with_name(source.stem + ".vs").read_text()
    return {name: int(address, 16) for address, name in SYMBOL.findall(symbols)}


def call_line(segment, screen, charset):
    values = (*segment, screen & 255, screen >> 8, charset >> 8)
    symbols = ("lx0", "ly0", "lx1", "ly1", "baseLo", "baseHi", "drawCharsetHi")
    setup = "\n".join(f"    lda #{value}\n    sta {name}" for name, value in zip(symbols, values))
    return setup + "\n    jsr drawCharLine"


def period_groups(major, minor):
    rate = (512 * minor + major) // (2 * major)
    return 256 // gcd(rate, 256)


def prepare_motif(segment, tile_to_code):
    x0, y0, x1, y1 = segment
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    axis = int(dy > dx)
    major, minor = (dy, dx) if axis else (dx, dy)
    period = period_groups(major, minor)
    start = segment[axis]
    forward = segment[axis + 2] > start
    if start % 4 != (0 if forward else 3):
        raise ValueError("Benchmark motifs start at a full group")
    points = normalized_points(*segment)
    repeats = major // (4 * period)
    if repeats < 2:
        raise ValueError("Benchmark requires at least two whole periods")
    tail = (*points[4 * period * repeats], x1, y1)
    assert normalized_points(*tail) == points[4 * period * repeats:]
    cells = dict(normalized_cells(*segment))
    glyphs = {cell: tile_to_code[mask] + 1 for cell, mask in cells.items()}
    first = {cell: code for cell, code in glyphs.items()
             if abs((cell // 40 if axis else cell % 40) - start // 4) < period}
    anchor = min(first)
    first_x, first_y = points[4 * period]
    step = (first_y // 4 - y0 // 4) * 40 + first_x // 4 - x0 // 4
    offsets = [cell - anchor for cell in first]
    if max(offsets) > 255:
        raise ValueError("A motif must fit one indirect-indexed range")
    for index in range(repeats):
        assert all(glyphs[cell + index * step] == code for cell, code in first.items())
    return anchor, step, repeats, offsets, list(first.values()), tail, glyphs


def secondary_stamp_seed(segment):
    points = normalized_points(*segment)
    for offset in range(0, len(points) - 3, 4):
        block = points[offset:offset + 4]
        first = block[0][0] // 4, block[0][1] // 4
        for x, y in block[1:]:
            cell = x // 4, y // 4
            if cell == first:
                continue
            left, top = cell[0] * 4, cell[1] * 4
            for px, py in ((left, top), (left + 3, top + 3)):
                if (px, py) not in block:
                    return px, py, px, py
    raise ValueError("Test line must contain a split block")


def fixture_source(segment, bank, pair, scratch, addresses):
    screen, charset, _ = pair
    anchor, step, repeats, offsets, codes, tail, glyphs = prepare_motif(segment, bank)
    shutil.copy2(HERE / "study_replay_block.asm", scratch)
    labels = "\n".join(f".label {name} = ${addresses[name]:04x}" for name in (
        "scrLo", "scrHi", "jcode", "jptrLo", "jptrHi", "stampJoint", "drawCharLine", "halt",
        "lx0", "ly0", "lx1", "ly1", "baseLo", "baseHi", "drawCharsetHi",
    ))
    offset_list, code_list = (",".join(map(str, items)) for items in (offsets, codes))
    source = f"""
{labels}
.import source "study_replay_block.asm"
.var studyOffsets = List().add({offset_list})
.var studyGlyphs = List().add({code_list})
*=$c100
baseline:
{call_line(segment, screen, charset)}
    jmp halt
.macro PlayMotif(body) {{
    lda #{(screen + anchor) & 255}
    sta scrLo
    lda #{(screen + anchor) >> 8}
    sta scrHi
    lda #{repeats}
    sta repeatCount
!repeat:
    jsr body
    dec repeatCount
    beq !tail+
    clc
    lda scrLo
    adc #{step & 255}
    sta scrLo
    lda scrHi
    adc #{(step >> 8) & 255}
    sta scrHi
    jmp !repeat-
!tail:
{call_line(tail, screen, charset)}
    jmp halt
}}
replay:
    PlayMotif(motif)
compact:
    PlayMotif(compactMotif)
repeatCount: .byte 0
motif:
    StudyReplayBlock(studyOffsets, studyGlyphs)
    rts
motifEnd:
compactMotif:
    StudyReplayCompactBlock(studyOffsets, studyGlyphs)
    rts
compactMotifEnd:
studyReplayCollision:
    sta jcode
studyReplayJoin:
    StudyReplayCollisionHandler()
studyReplayCompactStamp:
    StudyReplayCompactHandler()
settle:
    ldx #32
    ldy #0
!wait:
    dey
    bne !wait-
    dex
    bne !wait-
    jmp halt
"""
    x0, y0, x1, y1 = segment
    noise = Random(6510)
    stress = [(noise.randrange(160), noise.randrange(100),
               noise.randrange(160), noise.randrange(100)) for _ in range(24)]
    histories = {
        "blank": [],
        "duplicate": [segment],
        "crossings": CROSSINGS,
        "secondary": [secondary_stamp_seed(segment)],
        "prior joins": [*CROSSINGS, segment],
        "parallel": [(x0, y0 + 1, x1, y1 + 1)],
        "saturated": [*CROSSINGS, *stress],
    }
    for index, history in enumerate(histories.values()):
        source += f"setup{index}:\n"
        for prior in history:
            source += call_line(prior, screen, charset) + "\n"
        source += "    jmp halt\n"
    return source, histories, glyphs, repeats, len(codes)


def invoke(monitor, address, halt, measure=True):
    monitor.run(f"> c000 4c {address & 255:02x} {address >> 8:02x}")
    checkpoint = monitor.checkpoint(address) if measure else None
    monitor.run("r pc=c000")
    monitor.run("x")
    if checkpoint is None:
        assert monitor.registers()["pc"] == halt
        return 0
    start = monitor.registers()
    assert start["pc"] == address
    monitor.run("x")
    end = monitor.registers()
    assert end["pc"] == halt
    monitor.run(f"delete {checkpoint}")
    return end["clock"] - start["clock"]


def test_segment(monitor, target, pair, scratch, addresses, bank):
    screen, charset, _ = pair
    font = scratch / "stock-font.bin"
    dump = scratch / "dump.bin"
    halt = addresses["halt"]
    font.write_bytes(monitor.dump(dump, charset, charset + 2047))
    source, histories, glyphs, repeats, motif_size = fixture_source(target, bank, pair, scratch, addresses)
    fixture = scratch / "fixture.asm"
    fixture.write_text(source)
    program = scratch / "fixture.prg"
    labels = assemble(fixture, program)
    data = program.read_bytes()
    assert data[:2] == b"\x00\xc1" and len(data) <= 0x0f02
    binary = scratch / "fixture.bin"
    binary.write_bytes(data[2:])
    monitor.run(f'bload "{binary}" 0 c100')
    invoke(monitor, labels["settle"], halt, measure=False)
    inline_bytes = labels["motifEnd"] - labels["motif"]
    compact_bytes = labels["compactMotifEnd"] - labels["compactMotif"]
    print(f"{target}, {len(glyphs)} stamps, {repeats} × {motif_size} literal stamps, "
          f"{inline_bytes}/{compact_bytes} bytes per inline/compact motif", flush=True)
    for index, case in enumerate(histories):
        runs = []
        for mode in ("baseline", "replay", "compact"):
            monitor.run(f"fill {screen:04x} {screen + 999:04x} 00")
            monitor.run(f'bload "{font}" 0 {charset:04x}')
            monitor.run(f"> {JCOUNT:04x} 00")
            invoke(monitor, labels[f"setup{index}"], halt, measure=False)
            before = monitor.dump(dump, screen, screen + 999)
            count_before = monitor.dump(dump, JCOUNT, JCOUNT)[0]
            cycles = invoke(monitor, labels[mode], halt)
            after = monitor.dump(dump, screen, screen + 999)
            assert all(before[cell] == after[cell] for cell in range(1000) if cell not in glyphs)
            font_after = monitor.dump(dump, charset, charset + 2047)
            count_after = monitor.dump(dump, JCOUNT, JCOUNT)[0]
            runs.append((cycles, before, after, font_after, count_before, count_after))
        normal, replay, compact = runs
        assert normal[1:] == replay[1:] == compact[1:], (target, case, "different screen codes or glyphs")
        if case == "saturated":
            assert normal[4] == 55, "Stress setup did not fill the joint bank"
        occupied = sum(normal[1][cell] != 0 for cell in glyphs)
        different = sum(normal[1][cell] not in (0, glyph) for cell, glyph in glyphs.items())
        print(f"  {case:11s} {normal[0]:5d} -> {replay[0]:5d}/{compact[0]:5d} clocks "
              f"({normal[0] / replay[0]:.2f}x/{normal[0] / compact[0]:.2f}x), "
              f"occupied {occupied}, different {different}, "
              f"new join slots {normal[5] - normal[4]}", flush=True)
    monitor.run(f'bload "{font}" 0 {charset:04x}')


def cube_coverage():
    edges = repeated = occupied = stamps = 0
    for frame in range(ROTATION_FRAMES):
        drawn = set()
        for segment in frame_segments(frame):
            edges += 1
            for cell, _ in normalized_cells(*segment):
                stamps += 1
                occupied += cell in drawn
                drawn.add(cell)
            dx, dy = abs(segment[2] - segment[0]), abs(segment[3] - segment[1])
            axis = int(dy > dx)
            major, minor = (dy, dx) if axis else (dx, dy)
            if major:
                local = segment[axis] & 3
                if segment[axis + 2] < segment[axis]:
                    local = 3 - local
                prefix = (4 - local) & 3
                full_groups = (major + 1 - prefix) // 4
                repeated += full_groups >= 2 * period_groups(major, minor)
    print(f"Cube reference, {ROTATION_FRAMES} poses, {occupied}/{stamps} occupied stamps, "
          f"{repeated}/{edges} edges with at least two complete periods")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vice", default="/opt/homebrew/bin/x64sc")
    args = parser.parse_args()
    vm = load_monitor()
    bank = build_font()[0]
    with TemporaryDirectory(prefix="c64-line-replay-") as temporary:
        scratch = Path(temporary)
        program = scratch / "linedrawer.prg"
        addresses = assemble(HERE / "main.asm", program)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        command = [args.vice, "-default", "+saveres", "-minimized", "-pal", "-warp",
                   "+autostart-warp", "+confirmonexit", "-sounddev", "dummy",
                   "+refreshonbreak", "-initbreak", "reset", "-autostartprgmode", "1",
                   "-autostart", str(program), "-remotemonitor", "-remotemonitoraddress",
                   f"ip4://127.0.0.1:{port}"]
        with (scratch / "vice.log").open("w") as log:
            process = subprocess.Popen(command, cwd=scratch, stdout=log, stderr=log)
        try:
            with vm.connect(process, port) as connection:
                monitor = vm.Monitor(connection)
                connection.settimeout(15)
                monitor.checkpoint(addresses["cubeLoop"])
                monitor.run("x")
                assert monitor.registers()["pc"] == addresses["cubeLoop"]
                monitor.run("bank io")
                monitor.run("> d011 0b")  # Disable scanout DMA while timing the CPU.
                monitor.run("bank cpu")
                monitor.checkpoint(addresses["halt"])
                for index, target in enumerate(TARGETS):
                    test_segment(monitor, target, BUFFERS[index % len(BUFFERS)], scratch, addresses, bank)
        finally:
            process.terminate()
            process.wait(timeout=5)
    cube_coverage()


if __name__ == "__main__":
    main()
