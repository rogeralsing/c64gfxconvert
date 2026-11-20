"""Build reusable literal character routines for common live globe edges."""

from collections import Counter, defaultdict

import ball_model
import cube_model

ASSET_NAME = "globe-replay-data.bin"
KERNEL_START = 0xE000
KERNEL_LIMIT = 0xFFFA                  # leave hardware vectors intact
STAMP_BYTES = 7                      # LDY #offset, LDX #glyph, JSR shared stamp
EMPTY_SLOT = 255


def collect_patterns(tile_to_code):
    occurrences = Counter()
    patterns = {}
    total_edges = total_stamps = 0
    for frame in range(cube_model.ROTATION_FRAMES):
        for segment in ball_model.frame_segments("globe", frame):
            x0, y0, x1, y1 = segment
            dx, dy = x1 - x0, y1 - y0
            stamps = cube_model.normalized_cells(*segment)
            total_edges += 1
            total_stamps += len(stamps)
            start = (y0 // 4) * 40 + x0 // 4
            anchor = min(cell for cell, _ in stamps)
            base_delta = anchor - start
            if not (-128 <= dx <= 127 and -128 <= dy <= 127 and -255 <= base_delta <= 0):
                continue
            if max(cell for cell, _ in stamps) - anchor > 255:
                continue

            local = ((y0 & 3) << 2) | (x0 & 3)
            key = (dx, dy, local)
            replay = tuple((cell - anchor, tile_to_code[mask] + 1) for cell, mask in stamps)
            record = (base_delta, replay)
            if patterns.setdefault(key, record) != record:
                raise AssertionError(f"Inconsistent translation for globe replay key {key}")
            occurrences[key] += 1
    return occurrences, patterns, total_edges, total_stamps


def select_replays(occurrences, patterns):
    # Multiple deltas can produce the same stamp sequence, with the same or
    # different anchor offsets. Charge for that routine once.
    by_stamps = defaultdict(list)
    for key, (_, stamps) in patterns.items():
        by_stamps[stamps].append(key)

    def value_per_byte(stamps):
        hits = sum(occurrences[key] for key in by_stamps[stamps])
        return -(hits * len(stamps)) / (1 + STAMP_BYTES * len(stamps))

    ranked = sorted(by_stamps, key=lambda stamps: (value_per_byte(stamps), stamps))
    selected = []
    kernels = {}
    kernel_bytes = 0
    for stamps in ranked:
        if len(selected) == EMPTY_SLOT:
            break
        size = STAMP_BYTES * len(stamps) + 1  # RTS
        if kernel_bytes + size > KERNEL_LIMIT - KERNEL_START:
            continue
        kernels[stamps] = len(kernels)
        kernel_bytes += size
        keys = sorted(by_stamps[stamps], key=lambda key: (-occurrences[key], key))
        selected.extend(keys[:EMPTY_SLOT - len(selected)])
    selected.sort(key=lambda key: (-occurrences[key], key))
    return selected, kernels, kernel_bytes


def pack_deltas(keys):
    """Give each dx a displacement so its dy tags land in distinct slots."""
    by_dx = defaultdict(dict)
    following = [EMPTY_SLOT] * len(keys)
    for index in reversed(range(len(keys))):
        dx, dy, _ = keys[index]
        entries = by_dx[dx & 255]
        following[index] = entries.get(dy & 255, EMPTY_SLOT)
        entries[dy & 255] = index

    displacements = [0] * 256
    dx_tags = [0] * 256
    dy_tags = [0] * 256
    heads = [EMPTY_SLOT] * 256
    for dx in sorted(by_dx, key=lambda tag: (-len(by_dx[tag]), tag)):
        entries = by_dx[dx]
        for displacement in range(256):
            if all(heads[(displacement + dy) & 255] == EMPTY_SLOT for dy in entries):
                break
        else:
            raise ValueError(f"Cannot pack globe replay deltas for dx ${dx:02x}")
        displacements[dx] = displacement
        for dy, index in entries.items():
            slot = (displacement + dy) & 255
            dx_tags[slot], dy_tags[slot], heads[slot] = dx, dy, index
    return displacements, dx_tags, dy_tags, heads, following


def emit(tile_to_code, output):
    occurrences, patterns, total_edges, total_stamps = collect_patterns(tile_to_code)
    keys, kernels, kernel_bytes = select_replays(occurrences, patterns)
    displacements, dx_tags, dy_tags, heads, following = pack_deltas(keys)

    # Number of keys, four 256-byte delta lookup tables, then four parallel
    # arrays per key: local start, next key, negative base delta, kernel ID.
    # Finally the kernel count and each kernel's stamp count and offset/code pairs.
    data = bytearray((len(keys), *displacements, *dx_tags, *dy_tags, *heads))
    for table in ((key[2] for key in keys), following, (patterns[key][0] for key in keys),
                  (kernels[patterns[key][1]] for key in keys)):
        data.extend(value & 255 for value in table)
    data.append(len(kernels))
    for stamps in kernels:
        data.append(len(stamps))
        for offset, glyph in stamps:
            data.extend((offset, glyph))
    (output / ASSET_NAME).write_bytes(data)

    depths = Counter(key[:2] for key in keys)
    return {
        "framesSampled": cube_model.ROTATION_FRAMES,
        "visibleEdges": total_edges,
        "eligibleEdges": sum(occurrences.values()),
        "replayedEdges": sum(occurrences[key] for key in keys),
        "visibleStamps": total_stamps,
        "replayedStamps": sum(occurrences[key] * len(patterns[key][1]) for key in keys),
        "lookupKeys": len(keys),
        "indexedDeltas": len(depths),
        "maxLocalChain": max(depths.values(), default=0),
        "dispatchTableBytes": 4 * 256 + 5 * len(keys),
        "kernels": len(kernels),
        "kernelBytes": kernel_bytes,
        "assetBytes": len(data),
    }
