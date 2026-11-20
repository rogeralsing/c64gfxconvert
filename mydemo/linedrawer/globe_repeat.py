"""Generate exact literal motifs that can repeat without a new shape lookup."""

from collections import Counter
from typing import NamedTuple

import ball_model
from cube_model import ROTATION_FRAMES
from globe_motifs import literal_kernel

ASSET_NAME = "globe-repeat-data.bin"
GROUPS_PER_PERIOD = {0: 1, 64: 4, 128: 2, 256: 1}
PHASE_CLASSES = ((0, 128), (64, 0), (64, 64), (64, 128), (64, 192),
                 (128, 0), (128, 128), (256, 128))
KERNEL_BUDGET = 0xFFFA - 0xE000
STAMP_BYTES = 7  # LDY #offset, LDX #glyph, JSR or tail JMP to the stamp


class RepeatLine(NamedTuple):
    rate: int
    orientation: int
    phase: int
    minor_local: int
    head: int
    groups_per_period: int
    repeats: int


def line_plan(segment):
    """Return the repeat state reached after an ordinary partial head."""
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
    groups = GROUPS_PER_PERIOD.get(rate)
    if groups is None:
        return None
    head = (-u) & 3
    repeats = (major + 1 - head) // (4 * groups)
    if repeats < 2:
        return None
    state = 128 + head * rate
    return RepeatLine(rate, orientation, state & 255, (v + (state >> 8)) & 3, head, groups, repeats)


def kernel_for(rate, phase, orientation, minor_local, tile_to_code):
    groups = GROUPS_PER_PERIOD[rate]
    samples = groups * 4
    positions = [(phase + k * rate) >> 8 for k in range(samples)]
    bits = sum((right - left) << k for k, (left, right) in enumerate(zip(positions, positions[1:])))
    x_step = -1 if orientation & 1 else 1
    y_step = -40 if orientation & 2 else 40
    major_step, minor_step = (y_step, x_step) if orientation & 4 else (x_step, y_step)
    # The advance is a whole character in both axes. The next period has
    # the same phase and sub-character start, even if the line ends later.
    minor_cells, remainder = divmod(samples * rate, 4 * 256)
    if remainder:
        raise AssertionError(f"Q8 rate {rate} does not return to its starting alignment")
    step = groups * major_step + minor_cells * minor_step
    anchor, stamps = literal_kernel(orientation, minor_local, bits, tile_to_code, samples=samples)
    return anchor, step, stamps


def emit(tile_to_code, output):
    kernels = {}
    contexts = []
    for rate, phase in PHASE_CLASSES:
        for orientation in range(8):
            for minor in range(4):
                anchor, step, stamps = kernel_for(rate, phase, orientation, minor, tile_to_code)
                context = (kernels.setdefault(stamps, len(kernels)), anchor & 255,
                           step & 255, (step >> 8) & 255)
                contexts.append(context)

    kernel_bytes = sum(STAMP_BYTES * len(stamps) for stamps in kernels)
    if len(kernels) > 255 or kernel_bytes > KERNEL_BUDGET:
        raise ValueError("Globe repeat kernels exceed the native bank")

    # Count, then four 256-byte context pages (kernel ID, anchor, signed
    # step low/high). The code-only records share routines across contexts.
    data = bytearray([len(kernels)])
    for page in zip(*contexts):
        data.extend(page)
    for stamps in kernels:
        data.append(len(stamps))
        for offset, glyph in stamps:
            data.extend((offset, glyph))
    (output / ASSET_NAME).write_bytes(data)

    total_edges = 0
    eligible = Counter()
    repeats = Counter()
    for frame in range(ROTATION_FRAMES):
        for segment in ball_model.frame_segments("globe", frame):
            total_edges += 1
            plan = line_plan(segment)
            if plan is not None:
                eligible[plan.rate] += 1
                repeats[plan.rate] += plan.repeats
    return {
        "framesSampled": ROTATION_FRAMES,
        "supportedRates": list(GROUPS_PER_PERIOD),
        "visibleEdges": total_edges,
        "eligibleEdges": sum(eligible.values()),
        "repeatExecutions": sum(repeats.values()),
        "rates": {str(rate): {"groupsPerPeriod": groups, "eligibleEdges": eligible[rate],
                             "repeatExecutions": repeats[rate]}
                  for rate, groups in GROUPS_PER_PERIOD.items()},
        "contexts": len(contexts),
        "kernels": len(kernels),
        "kernelBytes": kernel_bytes,
        "assetBytes": len(data),
    }
