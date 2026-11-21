"""Per-vertex sine offsets and reference geometry for the line scroller."""

import math

from letters import stroke_geometry

START_X = 184
LEFT_LIMIT = -24
SPACING = 34
SCROLL_STEP = 1
WAVE_CENTER = 49
POINT_STEP = 5


def sine_offsets(amplitude):
    return tuple(round(amplitude * math.sin(math.tau * phase / 256)) for phase in range(256))


SINE_X1 = sine_offsets(3)
SINE_X2 = sine_offsets(2)
SINE_Y1 = sine_offsets(26)
SINE_Y2 = sine_offsets(3)


def build_assets():
    # Point codes are indexed row-first. Each component is a 35-byte table.
    points = [((column - 2) * POINT_STEP, (row - 3) * POINT_STEP)
              for row in range(7) for column in range(5)]
    components = [(x, y, 2 * x + 3 * y + 32, 3 * x - 2 * y + 160,
                   2 * x + y // 2, 3 * x - y + 64) for x, y in points]
    return {
        "scroll-sine": bytes(value & 255 for wave in (SINE_X1, SINE_X2, SINE_Y1, SINE_Y2)
                             for value in wave),
        "scroll-vertices": bytes(value & 255 for table in zip(*components) for value in table),
    }


def vertex_position(center, column, row, time):
    x = center + (column - 2) * POINT_STEP
    y = (row - 3) * POINT_STEP
    dx = SINE_X1[(2 * x + 3 * y - 2 * time + 32) & 255]
    dx += SINE_X2[(3 * x - 2 * y + 3 * time + 160) & 255]
    # The main Y wave moves to the right while the glyph moves left.
    dy = SINE_Y1[(2 * x + y // 2 - 3 * time) & 255]
    dy += SINE_Y2[(3 * x - y - 2 * time + 64) & 255]
    return x + dx, WAVE_CENTER + y + dy


def state_at(frame, message_len):
    left = START_X - SCROLL_STEP * frame
    skipped = max(0, (LEFT_LIMIT - left + SPACING - 1) // SPACING)
    return left + SPACING * skipped, skipped % message_len


def clip_x(a, b):
    """Intersect a short, Y-safe segment with the 160-pixel-wide viewport."""
    if (a[0] < 0 and b[0] < 0) or (a[0] >= 160 and b[0] >= 160):
        return None
    points = []
    for (x, y), (other_x, other_y) in ((a, b), (b, a)):
        if 0 <= x < 160:
            points.append((x, y))
            continue
        boundary = 0 if x < 0 else 159
        dx = abs(other_x - x)
        dy = other_y - y
        distance = (abs(dy) * abs(boundary - x) + dx // 2) // dx
        points.append((boundary, y - distance if dy < 0 else y + distance))
    return (*points[0], *points[1])


def segments(frame, message):
    if message[-1:] == b"\xff":
        message = message[:-1]
    left, index = state_at(frame, len(message))
    phase = frame // 2
    result = []
    for center in range(left, START_X, SPACING):
        glyph = message[index]
        index = (index + 1) % len(message)
        if glyph == 26:
            continue
        vertices, edges = stroke_geometry(chr(65 + glyph))
        points = [vertex_position(center, x, y, phase) for x, y in vertices]
        for start, end in edges:
            clipped = clip_x(points[start], points[end])
            if clipped is not None:
                result.append(clipped)
    return result
