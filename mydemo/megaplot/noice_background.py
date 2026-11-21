"""Encode a compact NOICE wordmark in Megaplot's existing line font."""

from megaplot import FW, PH, PW, bresenham


# Adjacent vertical and horizontal strokes touch across character cells.
STROKES = (
    # N
    ((19, 3), (19, 24)),
    ((20, 3), (35, 24)),
    ((36, 3), (36, 24)),
    # O
    ((51, 3), (60, 3)),
    ((60, 3), (64, 7)),
    ((64, 7), (64, 20)),
    ((64, 20), (60, 24)),
    ((60, 24), (51, 24)),
    ((51, 24), (47, 20)),
    ((47, 20), (47, 7)),
    ((47, 7), (51, 3)),
    # I
    ((72, 3), (82, 3)),
    ((77, 4), (77, 23)),
    ((72, 24), (82, 24)),
    # C
    ((107, 7), (103, 3)),
    ((103, 3), (95, 3)),
    ((95, 3), (91, 7)),
    ((91, 7), (91, 20)),
    ((91, 20), (95, 24)),
    ((95, 24), (103, 24)),
    ((103, 24), (107, 20)),
    # E
    ((115, 3), (115, 24)),
    ((116, 3), (139, 3)),
    ((116, 13), (135, 13)),
    ((116, 24), (139, 24)),
)


def build_noice_template(tile_to_code):
    """Return the 40×25 background screen with code zero for blank cells."""
    masks = [0] * (FW * (PH // 4))
    for (x0, y0), (x1, y1) in STROKES:
        for x, y in bresenham(x0, y0, x1, y1):
            assert 0 <= x < PW and 0 <= y < PH
            cell = (y >> 2) * FW + (x >> 2)
            masks[cell] |= 1 << ((y & 3) * 4 + (x & 3))
    return bytes(tile_to_code[mask] + 1 if mask else 0 for mask in masks)
