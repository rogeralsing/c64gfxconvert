"""Build exact reusable routines for full character groups of a Q8 line."""

from collections import Counter, defaultdict

import ball_model
from char_tables import transpose
from cube_model import ROTATION_FRAMES
from linedrawer import hflip, vflip

ASSET_NAME = "globe-motifs-data.bin"
KERNEL_BUDGET = 0xFFFA - 0xE000
STAMP_BYTES = 7  # LDY #offset, LDX #glyph, JSR or tail JMP to the stamp
MISS = 255


def decision_bits(rate, phase):
    """The seven minor-axis steps between eight consecutive samples."""
    positions = [(phase + i * rate) >> 8 for i in range(8)]
    return sum((right - left) << i for i, (left, right) in enumerate(zip(positions, positions[1:])))


def phase_tables():
    # Each decision can change only at a boundary of one of the samples.
    # Multiple boundaries may be equal. Their tokens are then equal too.
    cuts = [sorted((-k * rate) & 255 for k in range(1, 8)) for rate in range(256)]
    words = [[decision_bits(rate, phase) for phase in (0, *boundaries)]
             for rate, boundaries in enumerate(cuts)]
    patterns = sorted({word for row in words for word in row})
    if len(patterns) != 54 or patterns[-1] != 0x7F:
        raise AssertionError("Unexpected set of eight-sample Q8 line patterns")
    codes = {word: 4 * index for index, word in enumerate(patterns)}
    boundaries = bytes(value for page in zip(*cuts) for value in page)
    tokens = bytes(codes[word] for page in zip(*words) for word in page)
    return boundaries, tokens, codes


def full_groups(segment):
    """Yield reusable states after the ordinary head and before the ordinary tail."""
    x0, y0, x1, y1 = segment
    dx, dy = x1 - x0, y1 - y0
    orientation = int(dx < 0) | (int(dy < 0) << 1)
    u = (x0 & 3) ^ (3 if dx < 0 else 0)
    v = (y0 & 3) ^ (3 if dy < 0 else 0)
    major, minor = abs(dx), abs(dy)
    if minor > major:
        orientation |= 4
        u, v = v, u
        major, minor = minor, major
    rate = (512 * minor + major) // (2 * major) if major else 0
    length = major + 1
    for start in range((-u) & 3, length - 3, 4):
        state = 128 + start * rate
        minor_local = (v + (state >> 8)) & 3
        yield orientation, minor_local, decision_bits(rate, state & 255), length


def literal_kernel(orientation, minor_local, bits, tile_to_code, *, samples=8):
    masks = {}
    for k in range(samples):
        major_cell, x = divmod(k, 4)
        minor_cell, y = divmod(minor_local + (bits & ((1 << k) - 1)).bit_count(), 4)
        cell = (major_cell, minor_cell)
        masks[cell] = masks.get(cell, 0) | (1 << (4 * y + x))

    stamps = []
    for (x, y), pattern in masks.items():
        if orientation & 4:
            x, y = y, x
            pattern = transpose(pattern)
        if orientation & 1:
            x = -x
            pattern = hflip(pattern)
        if orientation & 2:
            y = -y
            pattern = vflip(pattern)
        stamps.append((y * 40 + x, tile_to_code[pattern] + 1))
    anchor = min(offset for offset, _ in stamps)
    return anchor, tuple((offset - anchor, code) for offset, code in stamps)


def split_tables(codes):
    """Decode both single-group IDs from one already-classified pair token."""
    first = bytearray(256)
    second = bytearray(256)
    for bits, token in codes.items():
        for minor in range(4):
            index = token | minor
            middle = minor + (bits & 15).bit_count()
            first[index] = (minor << 3) | (bits & 7)
            second[index] = ((middle & 3) << 3) | (bits >> 4)
            if middle >= 4:
                second[index] |= 128  # add the minor-axis cell step too
    return first + second


def emit(tile_to_code, output):
    boundaries, tokens, codes = phase_tables()
    occurrences = Counter()
    lengths = defaultdict(set)
    lines = []
    full_group_edges = full_group_count = 0
    for frame in range(ROTATION_FRAMES):
        for segment in ball_model.frame_segments("globe", frame):
            groups = list(full_groups(segment))
            full_group_count += len(groups)
            full_group_edges += bool(groups)
            keys = []
            for orientation, minor, bits, length in groups[:len(groups) & ~1:2]:
                key = (orientation, minor, bits)
                keys.append(key)
                occurrences[key] += 1
                lengths[key].add(length)
            lines.append(keys)

    by_kernel = defaultdict(list)
    for key in occurrences:
        by_kernel[literal_kernel(*key, tile_to_code)].append(key)

    def rank(kernel):
        stamps = len(kernel[1])
        hits = sum(occurrences[key] for key in by_kernel[kernel])
        return -hits, -stamps, kernel

    single_kernels = [literal_kernel(orientation, minor, bits, tile_to_code, samples=4)
                      for orientation in range(8) for minor in range(4) for bits in range(8)]
    single_bytes = sum(STAMP_BYTES * len(stamps) for _, stamps in single_kernels)
    selected = {}
    pair_kernels = []
    pair_bytes = 0
    for anchor, stamps in sorted(by_kernel, key=rank):
        if len(pair_kernels) == MISS:
            break
        size = STAMP_BYTES * len(stamps)
        if single_bytes + pair_bytes + size > KERNEL_BUDGET:
            continue
        kernel = (anchor, stamps)
        for key in by_kernel[kernel]:
            selected[key] = len(pair_kernels)
        pair_kernels.append(kernel)
        pair_bytes += size

    selectors = bytearray([MISS]) * (8 * 256)
    for (orientation, minor, bits), index in selected.items():
        selectors[256 * orientation + codes[bits] + minor] = index

    # Phase boundaries and tokens are indexed by the live slope. The eight
    # orientation pages index by token | minorLocal. The 256 universal
    # single-group kernels follow the pairs, in orientation/minor/moves
    # order. Each record has a non-positive base delta, stamp count, and
    # offset/glyph pairs.
    data = bytearray([len(pair_kernels)])
    data.extend(boundaries)
    data.extend(tokens)
    data.extend(selectors)
    for anchor, stamps in (*pair_kernels, *single_kernels):
        data.extend((anchor & 255, len(stamps)))
        for offset, glyph in stamps:
            data.extend((offset, glyph))
    splits = split_tables(codes)
    data.extend(splits)
    (output / ASSET_NAME).write_bytes(data)

    covered_pairs = sum(occurrences[key] for key in selected)
    return {
        "framesSampled": ROTATION_FRAMES,
        "visibleEdges": len(lines),
        "fullGroupEdges": full_group_edges,
        "fullGroups": full_group_count,
        "singleGroupsUsed": full_group_count - 2 * covered_pairs,
        "eligibleEdges": sum(bool(keys) for keys in lines),
        "coveredEdges": sum(any(key in selected for key in keys) for keys in lines),
        "eligiblePairs": sum(occurrences.values()),
        "coveredPairs": covered_pairs,
        "decisionPatterns": len(codes),
        "observedStates": len(occurrences),
        "bankedStates": len(selected),
        "statesReusedAcrossLengths": sum(len(lengths[key]) > 1 for key in selected),
        "singleGroupKernels": len(single_kernels),
        "singleGroupKernelBytes": single_bytes,
        "pairKernels": len(pair_kernels),
        "pairKernelBytes": pair_bytes,
        "kernelBytes": single_bytes + pair_bytes,
        "splitTableBytes": len(splits),
        "assetBytes": len(data),
    }
