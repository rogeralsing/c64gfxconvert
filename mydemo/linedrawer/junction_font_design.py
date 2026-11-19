"""Generate the 256 connected glyphs used by the fixed-junction globe."""

from collections import Counter
from functools import cache

import numpy as np

import cube_model
from char_tables import transpose
from linedrawer import build_font, hflip, vflip
from thin_faces import frame_segments


@cache
def orientations(mask):
    variants = set()
    for original in (mask, transpose(mask)):
        for flipped in (original, hflip(original)):
            variants.update((flipped, vflip(flipped)))
    return tuple(sorted(variants))


def neighbors(mask):
    across = mask | ((mask & 0x7777) << 1) | ((mask & 0xEEEE) >> 1)
    return (across | (across << 4) | (across >> 4)) & 0xFFFF


def connected(mask):
    reached = mask & -mask
    while True:
        expanded = neighbors(reached) & mask
        if expanded == reached:
            return reached == mask
        reached = expanded


def training_joins():
    """Count shape families in even poses, including intermediate unions at busy cells."""
    frequency = Counter()
    for frame_index in range(0, cube_model.ROTATION_FRAMES, 2):
        cells = {}
        for segment in frame_segments(frame_index):
            for cell, stamp in cube_model.normalized_cells(*segment):
                previous = cells.get(cell, 0)
                merged = previous | stamp
                if previous and merged not in (previous, stamp):
                    frequency[orientations(merged)[0]] += 1
                cells[cell] = merged
    return frequency


@cache
def glyph_masks():
    """Fill unused screen codes with connected shapes that cover frequent joins."""
    _, line_glyphs, _ = build_font()
    # A solid fallback covers any union. The fork is a regression case with
    # two oblique strokes meeting at the edge of a cell.
    bank = [0, *line_glyphs, 0xFFFF, *orientations(0xC221)]
    assert all(connected(mask) for mask in bank)
    frequency = training_joins()
    targets = np.array(sorted(frequency), dtype=np.uint16)
    weights = np.array([frequency[int(mask)] for mask in targets])

    # Candidate families include the actual join, its eight-neighbor
    # dilation, and each individual adjoining pixel.
    families = set()
    for target in targets.tolist():
        neighborhood = neighbors(target)
        families.update((orientations(target)[0], orientations(neighborhood)[0]))
        for bit in range(16):
            if neighborhood & (1 << bit):
                families.add(orientations(target | (1 << bit))[0])
    families = sorted(mask for mask in families if connected(mask))

    # For a connected glyph covering the target, all extra pixels are
    # reachable from the target. Cost is the number of extra logical pixels.
    best = np.array([min((glyph ^ target).bit_count() for glyph in bank if not target & ~glyph)
                     for target in targets.tolist()], dtype=np.int16)
    costs = np.full((len(families), len(targets)), 20, dtype=np.int16)
    pixel_counts = np.array([value.bit_count() for value in range(65536)], dtype=np.int16)
    for index, representative in enumerate(families):
        for glyph in orientations(representative):
            covered = (targets & glyph) == targets
            costs[index, covered] = np.minimum(costs[index, covered], pixel_counts[targets[covered] ^ glyph])
    slots = np.array([len(orientations(mask)) for mask in families])
    while len(bank) < 256:
        improvement = (np.maximum(0, best - costs) @ weights) / slots
        improvement[slots > 256 - len(bank)] = 0
        winner = int(improvement.argmax())
        if improvement[winner] <= 0:
            raise ValueError("Cannot fill the fixed font with distinct connected glyphs")
        bank.extend(orientations(families[winner]))
        best = np.minimum(best, costs[winner])
    assert len(set(bank)) == 256
    return tuple(bank)
