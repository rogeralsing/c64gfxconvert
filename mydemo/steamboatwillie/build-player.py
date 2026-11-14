#!/usr/bin/env python3
"""Build a cyclic, precomputed screen-only delta movie with a fixed black foreground."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'build'
PAL_CLOCK = 985248
FIELD_CYCLES = 19656
MOVIE_START = 0x2800


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def decode_pixels(screen, font):
    bits = np.unpackbits(np.frombuffer(font, dtype=np.uint8)).reshape(256, 8, 8)
    masks = bits[np.asarray(screen)]
    return np.where(masks, 0, 255).astype(np.uint8).reshape(25, 40, 8, 8).transpose(0, 2, 1, 3).reshape(200, 320)


def rgba_hash(pixels):
    image = np.empty((200, 320, 4), dtype=np.uint8)
    image[..., :3] = pixels[..., None]
    image[..., 3] = 255
    return sha(image.tobytes())


def encode_screen(before_screen, after_screen):
    # Byte-optimal cursor commands: 0=end, 1..127=skip, 128..255=copy
    # 1..128 literals. A literal may bridge unchanged cells when that costs
    # less than emitting another skip and literal command.
    cost, choice = [0] * 1001, [None] * 1000
    cost[1000] = 1
    last_change = max(np.flatnonzero(before_screen != after_screen), default=-1)
    for first in range(999, -1, -1):
        if first > last_change:
            cost[first], choice[first] = 1, ('end', 0)
            continue
        options = [(1 + count + cost[first + count], 'copy', count)
                   for count in range(1, min(128, 1000 - first) + 1)]
        for count in range(1, min(127, 1000 - first) + 1):
            if before_screen[first + count - 1] != after_screen[first + count - 1]:
                break
            options.append((1 + cost[first + count], 'skip', count))
        best, operation, count = min(options)
        cost[first], choice[first] = best, (operation, count)
    cursor, first = bytearray(), 0
    while first < 1000:
        operation, count = choice[first]
        if operation == 'end':
            break
        if operation == 'skip':
            cursor.append(count)
        else:
            cursor.append(127 + count)
            cursor.extend(after_screen[first:first + count])
        first += count
    cursor.append(0)
    assert len(cursor) == cost[0]

    grouped = bytearray()
    for page in range(4):
        first, end = page * 256, min((page + 1) * 256, 1000)
        groups = defaultdict(list)
        for position in range(first, end):
            if before_screen[position] != after_screen[position]:
                groups[int(after_screen[position])].append(position - first)
        grouped.extend(len(groups).to_bytes(2, 'little'))
        for value, positions in sorted(groups.items()):
            assert 1 <= len(positions) <= 256
            grouped.extend((value, len(positions) - 1))
            grouped.extend(positions)
    mode = int(len(cursor) <= len(grouped))
    result = bytearray((mode,))
    result.extend(cursor if mode else grouped)
    changed_characters = int(np.count_nonzero(before_screen != after_screen))
    return bytes(result), dict(characterChanges=changed_characters, bytes=len(result), screenMode=('groups','cursor')[mode],
                              cursorBytes=len(cursor), groupedBytes=len(grouped))


def decode_screen(raw, screen):
    """Interpret the stored binary format independently of group selection."""
    screen = screen.copy()
    mode, at = raw[0], 1
    assert mode in (0, 1)
    if mode == 1:
        cursor = 0
        while True:
            command = raw[at]
            at += 1
            if command == 0:
                break
            if command < 128:
                cursor += command
            else:
                count = command - 127
                assert cursor + count <= 1000
                screen[cursor:cursor + count] = list(raw[at:at + count])
                at += count
                cursor += count
    else:
        for page in range(4):
            groups = int.from_bytes(raw[at:at + 2], 'little')
            at += 2
            for _ in range(groups):
                value, minus_one = raw[at:at + 2]
                at += 2
                for position in raw[at:at + minus_one + 1]:
                    target = page * 256 + position
                    assert target < 1000
                    screen[target] = value
                at += minus_one + 1
    assert at == len(raw), 'A mono packet must end at its screen-delta terminator'
    return screen


def host_verify(output, labels, manifest, screens):
    from py65.devices.mpu6502 import MPU

    class Memory(list):
        color_writes = 0

        def __setitem__(self, address, value):
            if isinstance(address, int) and 0xd800 <= address < 0xdc00:
                self.color_writes += 1
            super().__setitem__(address, value)

    program = (output / 'player.prg').read_bytes()
    first = int.from_bytes(program[:2], 'little')
    memory = Memory([0xa5] * 65536)
    memory[first:first + len(program) - 2] = program[2:]
    for address in (0x0400, 0x0800):
        memory[address:address + 1024] = screens[0].tobytes().ljust(1024, b'\0')
    memory[0xd800:0xdc00] = bytes(1024)
    cpu = MPU(memory=memory)

    def run(target):
        start = cpu.processorCycles
        for _ in range(500000):
            if cpu.pc == labels[target]:
                return cpu.processorCycles - start
            cpu.step()
        raise AssertionError(('CPU limit', target, hex(cpu.pc)))

    front, back, records = 0x0400, 0x0800, []
    for serial in range(1, len(screens) * 2 + 1):
        current, upcoming = (serial - 1) % len(screens), serial % len(screens)
        memory[labels['film_frame']] = current
        memory[labels['front_screen_hi']] = front >> 8
        memory[labels['back_screen_hi']] = back >> 8
        previous_front = bytes(memory[front:front + 1024])
        cpu.pc = labels['prepare_start']
        preparation = run('prepared')
        assert memory[labels['next_frame']] == upcoming
        assert bytes(memory[front:front + 1024]) == previous_front
        assert bytes(memory[back:back + 1000]) == screens[upcoming].tobytes()
        assert memory[2] + 256 * memory[3] == manifest['packetEnds'][upcoming]
        cpu.pc = labels['commit_start']
        commit = run('presented')
        front, back = back, front
        assert bytes(memory[front:front + 1000]) == screens[upcoming].tobytes()
        assert bytes(memory[front + 1000:front + 1024]) == bytes(24)
        assert bytes(memory[0xd800:0xdc00]) == bytes(1024)
        assert memory.color_writes == 0, 'No ColorRAM store may execute during a frame'
        assert preparation + commit < manifest['holdFields'] * 18456
        records.append(dict(serial=serial, frame=upcoming, preparationCpuCycles=preparation,
                            commitCpuCycles=commit, totalCpuCycles=preparation + commit))
    assert bytes(memory[0x2000:0x2800]) == (output / 'font.bin').read_bytes()
    assert bytes(memory[manifest['movieStart']:manifest['movieEnd']]) == (output / 'movie.bin').read_bytes()
    result = dict(passed=True, programSha256=manifest['programSha256'], cases=len(records),
                  scope='Assembled screen-only 6502 preparation and presentation; every ColorRAM store is audited. No VIC stalls or native FPS.',
                  perFrameColorWrites=memory.color_writes, records=records,
                  maximumCpuCycles=max(record['totalCpuCycles'] for record in records))
    write_json(output / 'host-proof.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=HERE / 'generated')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--playback-fps', type=float, help='Separate-output throughput benchmark; source frames remain unchanged')
    args = parser.parse_args()
    data, output = args.data.resolve(), args.output.resolve()
    if output == OUTPUT.resolve():
        write_json(HERE / 'native.json', {'ready': False})
    source = json.loads((data / 'manifest.json').read_text())
    count, source_fps = int(source['frameCount']), float(source['fps'])
    fps = source_fps if args.playback_fps is None else args.playback_fps
    assert output != OUTPUT.resolve() or fps == source_fps, 'Use a separate output for a speed benchmark'
    assert 1 <= count <= 255 and 0 < fps <= 25
    assert source['hardwareMode'] == 'hires' and source['monochrome']
    assert source['globalBackgroundC64Index'] == 1 and source['fixedForegroundC64'] == 0
    hold_fields = round(PAL_CLOCK / FIELD_CYCLES / fps)
    font = (data / 'font.bin').read_bytes()
    font_sha = sha(font)
    assert len(font) == 2048 and font_sha == source['fontSha256']
    assert font[:8] == bytes(8) and font[8:16] == bytes([255]) * 8
    screen_raw = (data / 'screen.frames').read_bytes()
    assert len(screen_raw) == count * 1000
    screens = np.frombuffer(screen_raw, dtype=np.uint8).reshape(count, 1000)
    if (data / 'color.frames').exists():
        colors = (data / 'color.frames').read_bytes()
        assert len(colors) == count * 1000 and not any(colors), 'Web-only compatibility colors must be black'
    expected_hashes = [rgba_hash(decode_pixels(screen, font)) for screen in screens]
    assert expected_hashes == source['expectedDecodedRGBAHashes']

    packets, records = [], []
    for frame in range(count):
        packet, record = encode_screen(screens[(frame - 1) % count], screens[frame])
        assert np.array_equal(decode_screen(packet, screens[(frame - 1) % count]), screens[frame])
        packets.append(packet)
        records.append(dict(frame=frame, **record))
    payload = b''.join(packets)
    output.mkdir(parents=True, exist_ok=True)
    offsets, at = [], 0
    for packet in packets:
        offsets.append(at)
        at += len(packet)
    sizing = dict(frameCount=count, fps=fps, sourceFPS=source_fps, playbackBenchmark=fps != source_fps,
                  holdFields=hold_fields, movieBytes=len(payload),
                  screenDeltaBytes=len(payload), colorBytesInMovie=0,
                  maximumLowMovieBytes=0xd000 - MOVIE_START, packetMeanBytes=statistics.mean(map(len, packets)),
                  packetMaxBytes=max(map(len, packets)), bootstrapBytes=1024, fontBytes=2048,
                  framePointerBytes=count * 2, foregroundShadowBytes=0)
    write_json(output / 'sizing.json', sizing)
    print(json.dumps(sizing), flush=True)
    assert MOVIE_START + len(payload) <= 0xd000, 'Selected clip does not fit; no frames were dropped. See sizing.json.'
    (output / 'movie.bin').write_bytes(payload)
    (output / 'font.bin').write_bytes(font)
    (output / 'initial-screen.bin').write_bytes(screens[0].tobytes().ljust(1024, b'\0'))
    pointers = b''.join((MOVIE_START + offset).to_bytes(2, 'little') for offset in offsets)
    (output / 'frame-pointers.bin').write_bytes(pointers)
    prelude = [f'.const frameCount={count}', f'.const holdFields={hold_fields}']
    for variable, file in [('fontData', 'font.bin'), ('initialScreen', 'initial-screen.bin'),
                           ('movieData', 'movie.bin'), ('framePointers', 'frame-pointers.bin')]:
        prelude.append(f'.var {variable}=LoadBinary("{file}")')
    prelude.append(f'.import source "{HERE / "movie-player.asm"}"')
    (output / 'main.asm').write_text('\n'.join(prelude) + '\n')
    result = subprocess.run([str(Path.home() / '.local/bin/kickass'), 'main.asm', '-odir', str(output),
                             '-o', str(output / 'player.prg'), '-symbolfile'], cwd=output, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (output / 'build.log').write_text(result.stdout)
    assert result.returncode == 0, result.stdout
    labels = {name: int(value, 16) for name, value in re.findall(
        r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)', (output / 'main.sym').read_text())}
    assert labels['font'] == 0x2000 and labels['font_end'] == MOVIE_START == labels['movie_data']
    write_json(output / 'labels.json', labels)
    program = (output / 'player.prg').read_bytes()
    load_start = int.from_bytes(program[:2], 'little')
    assert load_start == 0x0801 and load_start + len(program) - 2 <= 0xd000
    files = ('manifest.json', 'font.bin', 'screen.frames')
    manifest = dict(passed=True, **sizing, sourceData=str(data), programSha256=sha(program),
                    fontSha256=font_sha, hardwareMode='hires', globalBackgroundC64Index=1,
                    fixedForegroundC64=0, monochrome=True, movieSha256=sha(payload),
                    sourceHashes={file: sha((data / file).read_bytes()) for file in files},
                    rawFrameCount=count, sourceExpectedDecodedRGBAHashes=expected_hashes,
                    colorRAMInitialization='Black once at boot; no per-frame ColorRAM stores',
                    screenPreparation='Copy front screen to back, then apply previous-frame screen delta',
                    movieFormat='Screen-only per-frame minimum of cursor/literal and page groups; no color fields or headers',
                    packets=records, frameAddresses=[MOVIE_START + offset for offset in offsets],
                    packetEnds=[MOVIE_START + offset + len(packet) for offset, packet in zip(offsets, packets)],
                    codeBytes=labels['player_code_end'] - 0x1000, movieStart=MOVIE_START,
                    movieEnd=MOVIE_START + len(payload), loadStart=load_start,
                    loadEnd=load_start + len(program) - 2,
                    fpsNominalPAL=PAL_CLOCK / FIELD_CYCLES / hold_fields, nativePlaybackVerified=False)
    write_json(output / 'build.json', manifest)
    host = host_verify(output, labels, manifest, screens)
    print(json.dumps(dict(passed=True, programSha256=manifest['programSha256'], movieBytes=len(payload),
                          colorBytesInMovie=0, codeBytes=manifest['codeBytes'], hostCases=host['cases'],
                          maxCpuCycles=host['maximumCpuCycles'], perFrameColorWrites=0)), flush=True)


if __name__ == '__main__':
    main()
