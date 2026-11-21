"""Original stroke glyphs and their packed C64 tables."""

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
RECORD_SIZE = 16
EDGE_END = 0xff

# Points lie on a 5×7 grid. Consecutive points in a stroke form one line.
STROKES = {
    "A": (((0, 6), (2, 0), (4, 6)), ((1, 3), (3, 3))),
    "B": (((0, 0), (0, 6)), ((0, 0), (4, 1), (0, 3), (4, 5), (0, 6))),
    "C": (((4, 0), (1, 0), (0, 3), (1, 6), (4, 6)),),
    "D": (((0, 0), (2, 0), (4, 2), (4, 4), (2, 6), (0, 6), (0, 0)),),
    "E": (((4, 0), (0, 0), (0, 6), (4, 6)), ((0, 3), (3, 3))),
    "F": (((4, 0), (0, 0), (0, 6)), ((0, 3), (3, 3))),
    "G": (((4, 0), (1, 0), (0, 3), (1, 6), (4, 6), (4, 3), (2, 3)),),
    "H": (((0, 0), (0, 6)), ((4, 0), (4, 6)), ((0, 3), (4, 3))),
    "I": (((0, 0), (4, 0)), ((2, 0), (2, 6)), ((0, 6), (4, 6))),
    "J": (((0, 0), (4, 0), (4, 5), (3, 6), (1, 6), (0, 5)),),
    "K": (((0, 0), (0, 6)), ((4, 0), (0, 3), (4, 6))),
    "L": (((0, 0), (0, 6), (4, 6)),),
    "M": (((0, 6), (0, 0), (2, 3), (4, 0), (4, 6)),),
    "N": (((0, 6), (0, 0), (4, 6), (4, 0)),),
    "O": (((1, 0), (3, 0), (4, 2), (4, 4), (3, 6), (1, 6), (0, 4), (0, 2), (1, 0)),),
    "P": (((0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)),),
    "Q": (((1, 0), (3, 0), (4, 2), (4, 4), (3, 6), (1, 6), (0, 4), (0, 2), (1, 0)),
          ((2, 4), (4, 6))),
    "R": (((0, 6), (0, 0), (3, 0), (4, 1), (3, 3), (0, 3)), ((2, 3), (4, 6))),
    "S": (((4, 0), (1, 0), (0, 2), (4, 4), (3, 6), (0, 6)),),
    "T": (((0, 0), (4, 0)), ((2, 0), (2, 6))),
    "U": (((0, 0), (0, 5), (1, 6), (3, 6), (4, 5), (4, 0)),),
    "V": (((0, 0), (2, 6), (4, 0)),),
    "W": (((0, 0), (1, 6), (2, 3), (3, 6), (4, 0)),),
    "X": (((0, 0), (4, 6)), ((4, 0), (0, 6))),
    "Y": (((0, 0), (2, 3), (4, 0)), ((2, 3), (2, 6))),
    "Z": (((0, 0), (4, 0), (0, 6), (4, 6)),),
    " ": (),
}


def stroke_geometry(letter):
    """Return unique points and split each stroke at all its existing joins."""
    strokes = STROKES[letter]
    points = list(dict.fromkeys(point for stroke in strokes for point in stroke))
    indices = {point: index for index, point in enumerate(points)}
    edges = []
    for stroke in strokes:
        for start, end in zip(stroke, stroke[1:]):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length_squared = dx * dx + dy * dy
            joins = [(0, indices[start]), (length_squared, indices[end])]
            for index, (x, y) in enumerate(points):
                x -= start[0]
                y -= start[1]
                along = x * dx + y * dy
                if 0 < along < length_squared and x * dy == y * dx:
                    joins.append((along, index))
            order = [index for _, index in sorted(joins)]
            edges.extend(zip(order, order[1:]))
    return points, edges


def build_assets():
    """Pack each glyph into a 16-byte point record and a 16-byte edge record."""
    coordinates = bytearray()
    edges = bytearray()
    counts = bytearray()
    for letter in ALPHABET:
        points, lines = stroke_geometry(letter)
        assert len(points) <= 10 and len(lines) < RECORD_SIZE
        assert all(0 <= x < 5 and 0 <= y < 7 for x, y in points)
        counts.append(len(points))
        coordinates.extend(y * 5 + x for x, y in points)
        coordinates.extend(b"\x00" * (RECORD_SIZE - len(points)))
        edges.extend((start << 4) | end for start, end in lines)
        edges.extend(bytes([EDGE_END]) * (RECORD_SIZE - len(lines)))
    return {"letter-coords": bytes(coordinates), "letter-edges": bytes(edges), "letter-counts": bytes(counts)}


def encode_message(message):
    """Encode uppercase ASCII letters and spaces as glyph indices."""
    normalized = message.upper()
    for letter in normalized:
        if letter not in ALPHABET:
            raise ValueError(f"Unsupported scroller character {letter!r}")
    return bytes(ALPHABET.index(letter) for letter in normalized)
