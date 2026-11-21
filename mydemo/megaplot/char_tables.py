"""Character stamps for groups of one to four major-axis pixels.

The index is `(u*4+n-1)*256 + v*64 + shape`. The local start is (u,v)
and n is the group length. Shape packs the positive minor-axis offsets
at pixels 1, 2 and 3, two bits per offset. Offsets beyond the group length
are ignored.
"""

from megaplot import hflip, vflip


def transpose(mask):
    return sum(
        1 << (x * 4 + y)
        for y in range(4)
        for x in range(4)
        if mask & (1 << (y * 4 + x))
    )


def build_slope():
    """Q8 slope breakpoints and group shapes, one page per field."""
    lut = bytearray(7 * 256)
    for fractional_slope in range(256):
        products = [k * fractional_slope for k in range(1, 4)]
        thresholds = sorted(-p & 255 for p in products)
        for page, threshold in enumerate(thresholds):
            lut[page * 256 + fractional_slope] = threshold
        for page, phase in enumerate([0, *thresholds], start=3):
            shape = sum(((p + phase) >> 8) << (2 * k) for k, p in enumerate(products))
            lut[page * 256 + fractional_slope] = shape
    return lut


def build(tile_to_code):
    first = bytearray(4096)
    second = bytearray(4096)
    for u in range(4):
        for count in range(1, 5 - u):
            for shape in range(64):
                offsets = [0] + [(shape >> (2 * k)) & 3 for k in range(count - 1)]
                if any(b - a not in (0, 1) for a, b in zip(offsets, offsets[1:])):
                    continue

                for v in range(4):
                    masks = [0, 0]
                    for k, offset in enumerate(offsets):
                        y = v + offset
                        masks[y >> 2] |= 1 << ((y & 3) * 4 + u + k)
                    base = (u * 4 + count - 1) * 256 + v * 64 + shape
                    for table, mask in zip((first, second), masks):
                        if mask:
                            assert mask in tile_to_code, f"Missing line glyph for mask ${mask:04x}"
                            table[base] = tile_to_code[mask] + 1

    transform = bytearray(8 * 256)
    for group in range(8):
        for mask, code in tile_to_code.items():
            glyph = transpose(mask) if group & 4 else mask
            if group & 1:
                glyph = hflip(glyph)
            if group & 2:
                glyph = vflip(glyph)
            assert glyph in tile_to_code, f"Missing transform ${group:x} of mask ${mask:04x}"
            transform[group * 256 + code + 1] = tile_to_code[glyph] + 1

    return {
        "char-first": first,
        "char-second": second,
        "char-transform": transform,
        "char-slope": build_slope(),
    }


def build_packed_pairs(tile_to_code):
    """Pack both oriented characters into one indexed page per octant."""
    standard = build(tile_to_code)
    first = bytearray(8 * 256)
    second = bytearray(8 * 256)
    layouts = [(0, 4), (0, 2), (0, 3), (1, 2), (1, 3), (2, 2)]
    transform = standard["char-transform"]
    for octant in range(8):
        page = octant * 256
        for row, (u, count) in enumerate(layouts):
            for v in range(4):
                for steps in range(16 if row == 0 else 8):
                    minor = 0
                    shape = 0
                    for bit in range(3):
                        minor += (steps >> bit) & 1
                        shape |= minor << (2 * bit)
                    source = (u * 4 + count - 1) * 256 + v * 64 + shape
                    dest = page + (v * 16 + steps if row == 0
                                   else (row + 1) * 32 + v * 8 + steps)
                    first[dest] = transform[page + standard["char-first"][source]]
                    second[dest] = transform[page + standard["char-second"][source]]
        for u in range(4):
            for v in range(4):
                source = u * 1024 + v * 64
                first[page + 224 + u * 4 + v] = transform[page + standard["char-first"][source]]

    slopes = standard["char-slope"]
    for i in range(3 * 256, len(slopes)):
        shape = slopes[i]
        first_step = shape & 3
        second_step = ((shape >> 2) & 3) - first_step
        third_step = ((shape >> 4) & 3) - first_step - second_step
        assert 0 <= first_step <= 1 and 0 <= second_step <= 1 and 0 <= third_step <= 1
        slopes[i] = first_step | (second_step << 1) | (third_step << 2)
    return {"char-packed-first": first, "char-packed-second": second, "char-slope": slopes}


def build_short_decisions():
    """Pack the first 32 exact Q8 minor-axis decisions by rate."""
    result = bytearray(4 * 256)
    for rate in range(256):
        position = [(128 + step * rate) >> 8 for step in range(33)]
        bits = sum((after - before) << bit
                   for bit, (before, after) in enumerate(zip(position, position[1:])))
        for page in range(4):
            result[page * 256 + rate] = (bits >> (page * 8)) & 255
    return result
