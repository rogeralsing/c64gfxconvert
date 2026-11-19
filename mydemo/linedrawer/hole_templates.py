"""Exact Q8 major-axis windows and oriented glyph pairs for the fixed-font walker."""

from char_tables import transpose
from linedrawer import hflip, vflip


def crosses_cell(key):
    minor = (key >> 3) & 3
    steps = (key & 7) | ((key & 32) >> 2)
    return minor + steps.bit_count() >= 4


def build(tile_to_code):
    # A four-step group can start at any of four offsets. Seven decisions
    # describe all four alignments. All Q8 rates together use 54 patterns.
    windows = bytearray()
    patterns = {}
    for slope in range(257):
        for start in range(0, 160, 4):
            positions = [(128 + (start + k) * slope) >> 8 for k in range(8)]
            bits = sum((b - a) << k for k, (a, b) in enumerate(zip(positions, positions[1:])))
            pattern = patterns.setdefault(bits, len(patterns))
            windows.append((positions[0] & 3) * 54 + pattern)
    assert len(patterns) == 54

    # Number full glyph pairs 0..31 for no minor-cell crossing, 32..63
    # for a crossing. CPX #32 then supplies the native address increment.
    by_crossing = sorted(range(64), key=crosses_cell)
    assert not crosses_cell(by_crossing[31]) and crosses_cell(by_crossing[32])
    token = {key: index for index, key in enumerate(by_crossing)}
    decoded = bytearray()
    for offset in range(4):
        for origin in range(7):
            for bits in patterns:
                minor = (origin + (bits & ((1 << offset) - 1)).bit_count()) & 3
                four = bits >> offset
                key = (minor << 3) | (four & 7) | ((four & 8) << 2)
                decoded.append(token[key])

    rows = {}
    row_ids = bytearray(2 * 128)
    for u in range(4):
        for count in range(1, 5 - u):
            for orient in range(8):
                slot = (u * 4 + count - 1) * 8 + orient
                first, second = [], []
                for key in range(32):
                    minor, pattern = divmod(key, 8)
                    masks = [0, 0]
                    for k in range(count):
                        y = minor + (pattern & ((1 << k) - 1)).bit_count()
                        masks[y >> 2] |= 1 << ((y & 3) * 4 + u + k)
                    for glyphs, mask in zip((first, second), masks):
                        if orient & 4:
                            mask = transpose(mask)
                        if orient & 1:
                            mask = hflip(mask)
                        if orient & 2:
                            mask = vflip(mask)
                        glyphs.append(tile_to_code[mask] + 1 if mask else 0)
                for bank, row in enumerate((first, second)):
                    row = bytes(row)
                    index = rows.setdefault(row, len(rows))
                    row_ids[bank * 128 + slot] = index
    return {
        "hole-windows": windows,
        "hole-decoded": decoded,
        "hole-unsort": bytes(by_crossing),
        "hole-glyph-rows": b"".join(rows),
        "hole-glyph-select": row_ids,
    }
