"""Character stamps for groups of one to four major-axis pixels.

The index is `(u*4+n-1)*256 + v*64 + shape`. The local start is (u,v)
and n is the group length. Shape packs the positive minor-axis offsets
at pixels 1, 2 and 3, two bits per offset. Offsets beyond the group length
are ignored.
"""

from linedrawer import hflip, vflip


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
