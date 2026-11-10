#!/usr/bin/env python3
"""Generate compact, signed vertical sine geometry for the PAL MCI player.

The 240-frame cycle runs at one geometry frame per MCI phase pair. Each frame
maps 200 output rows to source rows. Its vertical displacement stays within four
pixels, has zero mean before rounding, and fixes both image edges. The traveling
wave completes three periods while its strength smoothly rises and falls once.

RLE records contain an exclusive output-row end (1..200) and signed displacement
as an eight-bit two's-complement byte. The previous end is the next run's start;
an end of 200 finishes a frame. Frame offsets are 240 little-endian uint16 values
relative to the first RLE byte. Only geometry is stored, never image frames.
"""

import argparse
import json
import math
from pathlib import Path
import struct

HEIGHT = 200
FRAME_COUNT = 240
WAVE_PERIOD_FRAMES = 80
WAVELENGTH = 128
PEAK_DISPLACEMENT = 4


def generate_row_maps():
    """Return all source-row maps as 240 immutable, 200-element tuples."""
    envelope = [math.sin(math.pi * y / (HEIGHT - 1)) ** 2 for y in range(HEIGHT)]
    angles = [2 * math.pi * (y - (HEIGHT - 1) / 2) / WAVELENGTH for y in range(HEIGHT)]
    total_weight = sum(envelope)
    mean_sine = sum(weight * math.sin(angle) for weight, angle in zip(envelope, angles)) / total_weight
    mean_cosine = sum(weight * math.cos(angle) for weight, angle in zip(envelope, angles)) / total_weight
    normalization = max(weight * math.hypot(math.sin(angle) - mean_sine, math.cos(angle) - mean_cosine)
                        for weight, angle in zip(envelope, angles))
    frames = []
    for frame in range(FRAME_COUNT):
        strength = PEAK_DISPLACEMENT * (1 - math.cos(2 * math.pi * frame / FRAME_COUNT)) / 2
        phase = 2 * math.pi * frame / WAVE_PERIOD_FRAMES + math.pi / 2
        rows = []
        for y, (weight, angle) in enumerate(zip(envelope, angles)):
            displacement = strength * weight * ((math.sin(angle) - mean_sine) * math.cos(phase)
                            - (math.cos(angle) - mean_cosine) * math.sin(phase)) / normalization
            rows.append(max(0, min(HEIGHT - 1, round(y + displacement))))
        frames.append(tuple(rows))
    return tuple(frames)


def encode_row_maps(row_maps):
    """Return (little-endian frame offsets, endY/displacement RLE bytes)."""
    if len(row_maps) != FRAME_COUNT:
        raise ValueError(f"Expected {FRAME_COUNT} geometry frames.")
    offsets = bytearray()
    records = bytearray()
    for rows in row_maps:
        if len(rows) != HEIGHT or rows[0] != 0 or rows[-1] != HEIGHT - 1:
            raise ValueError("Each geometry frame must preserve both edges of 200 rows.")
        if any(not isinstance(source_y, int) or not 0 <= source_y < HEIGHT for source_y in rows):
            raise ValueError("Source rows must be integer image coordinates.")
        if any(first > second for first, second in zip(rows, rows[1:])):
            raise ValueError("Sine geometry must preserve source-row order.")
        displacements = [source_y - y for y, source_y in enumerate(rows)]
        if max(map(abs, displacements)) > PEAK_DISPLACEMENT:
            raise ValueError("Geometry exceeds the four-pixel displacement budget.")
        offsets.extend(struct.pack('<H', len(records)))
        displacement = displacements[0]
        for y in range(1, HEIGHT):
            if displacements[y] != displacement:
                records.extend((y, displacement & 0xff))
                displacement = displacements[y]
        records.extend((HEIGHT, displacement & 0xff))
    return bytes(offsets), bytes(records)


def build(output):
    """Write build payloads and an uncompressed verification reference."""
    frames = generate_row_maps()
    offsets, records = encode_row_maps(frames)
    changes = [sum(first != second for first, second in zip(frames[index - 1], frames[index]))
               for index in range(FRAME_COUNT)]
    summary = {
        'frames': FRAME_COUNT, 'height': HEIGHT, 'peak_displacement_pixels': PEAK_DISPLACEMENT,
        'wavelength_pixels': WAVELENGTH, 'wave_period_frames': WAVE_PERIOD_FRAMES,
        'offset_bytes': len(offsets), 'rle_bytes': len(records),
        'total_native_bytes': len(offsets) + len(records), 'max_changed_rows': max(changes),
        'rle': 'exclusive endY, signed two-complement displacement; endY 200 finishes each frame',
    }
    payloads = {
        'frame-offsets.bin': offsets, 'row-maps.rle': records,
        'geometry-rows.bin': bytes(row for frame in frames for row in frame),
        'geometry.json': (json.dumps(summary, indent=2) + '\n').encode(),
    }
    output.mkdir(parents=True, exist_ok=True)
    for name in payloads:
        if (output / name).exists():
            raise FileExistsError(f"Refusing to replace {output / name}")
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    build(parser.parse_args().output)
