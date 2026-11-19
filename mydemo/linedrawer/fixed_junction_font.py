"""Compile fixed-font covering glyphs to the 6510's direct rows and decision lists."""

from collections import Counter
from functools import cache

import numpy as np

from junction_font_design import glyph_masks
from linedrawer import charset_bytes
import thin_faces


DIRECT_BASE = 0xE800
LIST_BASE = 0xF000
# Ties between equally sized glyphs favor fewer lit pixels on cell edges.
BORDER_MASK = 0xF99F


@cache
def _ranked_codes():
    masks = glyph_masks()
    return sorted(range(len(masks)),
                  key=lambda code: (masks[code].bit_count(), (masks[code] & BORDER_MASK).bit_count(), code))


@cache
def _covering_codes():
    """Full host reference: choose the smallest connected glyph containing the union."""
    masks = glyph_masks()
    unions = np.arange(65536, dtype=np.uint16)
    result = np.zeros(len(unions), dtype=np.uint8)
    for code in reversed(_ranked_codes()):
        glyph = masks[code]
        result[(unions & glyph) == unions] = code
    assert np.all((np.array(masks, dtype=np.uint16)[result] & unions) == unions)
    return result.tobytes()


@cache
def assets():
    masks = glyph_masks()
    covering_codes = _covering_codes()
    # The eight most frequent high bytes of single line stamps get full
    # 256-byte rows. Other high bytes share sequences of (forbidden bits, code).
    counts = Counter(mask >> 8 for mask in masks[1:201])
    hot_rows = {high: i for i, (high, _) in enumerate(counts.most_common(8))}
    addresses = []
    packed = bytearray()
    offsets = {}
    for high in range(256):
        candidates = []
        for code in _ranked_codes():
            glyph = masks[code]
            if high & ~(glyph >> 8):
                continue
            low = glyph & 255
            # If an earlier candidate already covers this entire low byte,
            # no possible input can select the later glyph.
            if any((low & ~earlier) == 0 for earlier, _ in candidates):
                continue
            candidates.append((low, code))

        assert len(candidates) <= 127  # the 6510 walks pairs with an 8-bit index
        row = bytes(next(code for bits, code in candidates if not low & ~bits) for low in range(256))
        assert row == covering_codes[256 * high:256 * (high + 1)]
        sequence = bytes(value for bits, code in candidates for value in (bits ^ 255, code))
        if sequence not in offsets:
            offsets[sequence] = len(packed)
            packed.extend(sequence)

        if high in hot_rows:
            address = DIRECT_BASE + 256 * hot_rows[high]
        else:
            address = LIST_BASE + offsets[sequence]
        addresses.append(address)

    assert LIST_BASE + len(packed) <= 0xFFFA
    return {
        "charset": charset_bytes(masks[1:]),
        "cover-lo": bytes(address & 255 for address in addresses),
        "cover-hi": bytes(address >> 8 for address in addresses),
        "cover-lists": bytes(packed),
        "cover-direct": b"".join(covering_codes[256 * high:256 * (high + 1)] for high in hot_rows),
    }


def expected_screen(index):
    masks, _ = thin_faces.expected(index, {})
    cover = _covering_codes()
    screen = bytearray(1000)
    for cell, mask in masks.items():
        screen[cell] = cover[mask]
    return bytes(screen)
