#!/usr/bin/env python3
"""Native line conformance against a direct integer half-plane equation."""
import hashlib
import json
import pathlib
import re
import statistics
from py65.devices.mpu6502 import MPU

HERE = pathlib.Path(__file__).resolve().parent
ASSETS = HERE.parent / "build"
PROBES = [(1, 1), (4, 1), (6, 1), (1, 4), (6, 4), (1, 6), (4, 6), (6, 6)]


def mask(line, x, y):
    major, minor = (y, x) if line["axis"] else (x, y)
    result = 0
    for bit, (px, py) in enumerate(PROBES):
        a, b = (py, px) if line["axis"] else (px, py)
        distance = (
            8 * (8 * (minor - line["v"]) + b)
            - line["n"] * (8 * (major - line["u"]) + a)
            - line["phase"] * 8
        )
        filled = distance > 0 if line["positive"] else distance < 0
        if filled or (distance == 0 and line["include"]):
            result |= 1 << bit
    return result


def synthetic():
    for n in range(-8, 9):
        for phase in range(8):
            for axis in range(2):
                major_limit, minor_limit = ((25, 40) if axis else (40, 25))
                for positive in range(2):
                    for include in range(2):
                        line = dict(
                            n=n, phase=phase, axis=axis, positive=positive,
                            include=include, u=major_limit // 2,
                            v=(n * 7 + phase * 3) % minor_limit,
                            major_start=0, length=major_limit,
                        )
                        yield "synthetic-full", line
                        start = (phase * 5 + n * 3) % major_limit
                        yield "synthetic-finite", dict(
                            line, major_start=start,
                            length=(phase + positive * 3 + include) % (major_limit - start + 1),
                        )


def checker():
    source = (ASSETS / "q8-descriptors.bin").read_bytes()
    counts = (ASSETS / "white-face-counts.bin").read_bytes()
    read = 0
    for frame in range(64):
        size = int.from_bytes(source[read:read + 2], "little")
        read += 2
        packet = source[read:read + size]
        read += size
        cursor = 5
        for face, count in enumerate(counts):
            if not ((packet[face >> 3] >> (face & 7)) & 1):
                continue
            for edge in range(count):
                code = int.from_bytes(packet[cursor:cursor + 3], "little")
                cursor += 3
                anchor, axis = code & 1023, (code >> 20) & 1
                x, y = anchor % 40, anchor // 40
                yield "checker", dict(
                    n=((code >> 14) & 63) - 8,
                    phase=(code >> 10) & 15, axis=axis,
                    positive=(code >> 21) & 1, include=(code >> 22) & 1,
                    u=y if axis else x, v=x if axis else y,
                    major_start=0, length=25 if axis else 40,
                )
        assert cursor == len(packet), (frame, cursor, len(packet))
    assert read == len(source)


def main():
    labels = dict(
        (name, int(value, 16))
        for name, value in re.findall(
            r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)",
            (HERE / "build/main.sym").read_text(),
        )
    )
    prg = (HERE / "build/line.prg").read_bytes()
    glyphs = (ASSETS / "glyph-lut.bin").read_bytes()
    memory = [0] * 65536
    address = int.from_bytes(prg[:2], "little")
    memory[address:address + len(prg) - 2] = prg[2:]
    machine_code = bytes(memory[labels["draw_line"]:labels["line_n"]])
    ge = bytes(memory[labels["ge_table"]:labels["ge_end"]])
    eq = bytes(memory[labels["eq_table"]:labels["eq_end"]])
    assert len(ge) == len(eq) == 816
    # Validate every loaded mathematical mask without createTables/maskAt.
    for n in range(-8, 9):
        for phase in range(8):
            for axis in range(2):
                for relative in range(-1, 2):
                    index = (((n + 8) * 8 + phase) * 2 + axis) * 3 + relative + 1
                    expect_ge = expect_eq = 0
                    for bit, (px, py) in enumerate(PROBES):
                        major, minor = (py, px) if axis else (px, py)
                        distance = 8 * (minor + relative * 8) - n * major - phase * 8
                        if distance >= 0:
                            expect_ge |= 1 << bit
                        if distance == 0:
                            expect_eq |= 1 << bit
                    assert ge[index] == expect_ge and eq[index] == expect_eq
    cpu = MPU(memory=memory)
    groups = {}
    checked = writes = 0
    for case, (kind, line) in enumerate([*synthetic(), *checker()]):
        # Exercise page-aligned and unaligned caller-selected buffers.
        screen = 0x0400 if case & 1 else 0x0CA5
        before = bytes((case * 13 + cell * 37) & 255 for cell in range(1000))
        memory[screen:screen + 1000] = before
        memory[screen - 1] = 0xA5
        memory[screen + 1000] = 0x5A
        expected = bytearray(before)
        start, end = line["major_start"], line["major_start"] + line["length"]
        partial = 0
        for major in range(start, end):
            minor_limit = 40 if line["axis"] else 25
            for minor in range(minor_limit):
                x, y = (minor, major) if line["axis"] else (major, minor)
                value = mask(line, x, y)
                if value not in (0, 255):
                    expected[y * 40 + x] = glyphs[value]
                    partial += 1
        for name, value in line.items():
            memory[labels["line_" + name]] = value & 255
        memory[2], memory[3] = screen & 255, screen >> 8
        cpu.pc, cpu.sp = labels["draw_line"], 0xFD
        memory[0x1FE], memory[0x1FF] = 0xFF, 1
        begin = cpu.processorCycles
        for instruction in range(100000):
            if cpu.pc == 0x0200:
                break
            cpu.step()
        else:
            raise AssertionError(("Line did not return", kind, line))
        actual = bytes(memory[screen:screen + 1000])
        if actual != expected:
            wrong = [i for i in range(1000) if actual[i] != expected[i]]
            raise AssertionError((kind, line, wrong[:10], [(i, actual[i], expected[i]) for i in wrong[:3]]))
        assert memory[screen - 1] == 0xA5 and memory[screen + 1000] == 0x5A
        assert bytes(memory[labels["draw_line"]:labels["line_n"]]) == machine_code
        assert bytes(memory[labels["ge_table"]:labels["ge_end"]]) == ge
        assert bytes(memory[labels["eq_table"]:labels["eq_end"]]) == eq
        assert bytes(memory[labels["glyph_lut"]:labels["glyph_lut_end"]]) == glyphs
        groups.setdefault(kind, []).append(cpu.processorCycles - begin)
        checked += 1000
        writes += partial
    report = dict(
        pass_=True, comparedScreenBytes=checked, partialGlyphWrites=writes,
        codeAndInputBytes=labels["line_code_end"] - labels["draw_line"],
        addressConstantBytes=labels["address_tables_end"] - labels["line_code_end"],
        mathematicalLookupBytes=1888, zeroPageBytes=22,
        prgBytes=len(prg), prgSha256=hashlib.sha256(prg).hexdigest(),
        measurement="py65 instruction cycles per callable line, including anchor seek and clipping; no VIC stalls or full-movie FPS.",
        groups={kind: dict(cases=len(values), min=min(values), mean=statistics.mean(values), max=max(values))
                for kind, values in groups.items()},
    )
    report["pass"] = report.pop("pass_")
    (HERE / "build/verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
