#!/usr/bin/env python3
"""Measure endpoint overlap and translated-line reuse on the large crossing-holes globe."""
import json
from collections import Counter, defaultdict
from math import gcd

import ball_model
import cube_model


def measure(segments):
    contributions = defaultdict(list)
    parallel = Counter()
    synchronized = Counter()
    translated = Counter()
    fan_cells = Counter()
    fan_glyphs = Counter()
    counts = Counter(visibleLines=len(segments))

    for x0, y0, x1, y1 in segments:
        stamps = cube_model.normalized_cells(x0, y0, x1, y1)
        end_cells = {stamps[0][0], stamps[-1][0]}
        for cell, mask in stamps:
            contributions[cell].append((mask, cell in end_cells))
        counts["stampAttempts"] += len(stamps)
        if len(stamps) >= 2:
            # Read each existing line from its common vertex outward.
            # Reversing the endpoints and rerasterizing may change Q8 rounding.
            for origin, prefix in (((x0, y0), tuple(stamps[:2])),
                                   ((x1, y1), tuple(reversed(stamps[-2:])))):
                fan_cells[origin, tuple(cell for cell, _ in prefix)] += 1
                fan_glyphs[origin, prefix] += 1

        dx, dy = x1 - x0, y1 - y0
        divisor = gcd(dx, dy) or 1
        direction = (dx // divisor, dy // divisor)
        parallel[max(direction, (-direction[0], -direction[1]))] += 1

        major = max(abs(dx), abs(dy))
        minor = min(abs(dx), abs(dy))
        rate = (512 * minor + major) // (2 * major) if major else 0
        octant = (dx < 0, dy < 0, abs(dy) > abs(dx))
        synchronized[octant, rate, x0 % 4, y0 % 4] += 1
        translated[tuple((cell - stamps[0][0], mask) for cell, mask in stamps)] += 1

    for occurrences in contributions.values():
        masks = {mask for mask, _ in occurrences}
        endpoint_masks = [mask for mask, endpoint in occurrences if endpoint]
        interior_masks = {mask for mask, endpoint in occurrences if not endpoint}
        counts["touchedCells"] += 1
        counts["holeCells"] += len(masks) > 1
        counts["endpointStamps"] += len(endpoint_masks)
        if endpoint_masks:
            counts["endpointCells"] += 1
            counts["redundantEndpointStamps"] += len(endpoint_masks) - 1
        else:
            counts["interiorOnlyHoleCells"] += len(masks) > 1

        # In crossing-holes mode a cell is visible only if all stamps agree.
        actual = next(iter(masks)) if len(masks) == 1 else 0
        omitted = next(iter(interior_masks)) if len(interior_masks) == 1 else 0
        counts["omitEndpointChangedCells"] += actual != omitted
        counts["omitEndpointLostFatPixels"] += (actual & ~omitted).bit_count()
        counts["omitEndpointAddedFatPixels"] += (omitted & ~actual).bit_count()

    for name, groups in (("parallelReuse", parallel), ("synchronizedWalkReuse", synchronized),
                         ("completeTranslatedWalkReuse", translated)):
        counts[name] = len(segments) - len(groups)
    counts["fanTwoCellReuse"] = fan_cells.total() - len(fan_cells)
    counts["fanTwoGlyphReuse"] = fan_glyphs.total() - len(fan_glyphs)
    return counts


def main():
    totals = Counter()
    poses = cube_model.ROTATION_FRAMES
    for frame in range(poses):
        segments = ball_model.frame_segments("globe", frame, camera=ball_model.HOLES_CAMERA,
                                             y_sweep=ball_model.HOLES_Y_SWEEP)
        totals.update(measure(segments))
    print(json.dumps({"frames": poses, "total": totals,
                      "perFrame": {key: value / poses for key, value in totals.items()}}, indent=2))


if __name__ == "__main__":
    main()
