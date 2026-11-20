"""Sine lookup tables and moving joints for the Megaplot polyline."""

import math

MIN_SEGMENTS = 4
MAX_SEGMENTS = 48
DEFAULT_SEGMENTS = 24
PHASE_STEPS = 256


def sine_table(amplitude):
    return tuple(round(amplitude * math.sin(math.tau * i / PHASE_STEPS))
                 for i in range(PHASE_STEPS))


X_PRIMARY = sine_table(50)
X_SECONDARY = sine_table(28)
Y_PRIMARY = sine_table(31)
Y_SECONDARY = sine_table(17)


def sine_assets():
    tables = {"wave-x1": X_PRIMARY, "wave-x2": X_SECONDARY,
              "wave-y1": Y_PRIMARY, "wave-y2": Y_SECONDARY}
    return {name: bytes(sample & 255 for sample in table) for name, table in tables.items()}


def nodes(frame, segments=DEFAULT_SEGMENTS):
    """Return the ordered joints in 160×100 logical screen coordinates."""
    if not MIN_SEGMENTS <= segments <= MAX_SEGMENTS:
        raise ValueError(f"segments must be between {MIN_SEGMENTS} and {MAX_SEGMENTS}")
    points = []
    for i in range(segments + 1):
        # Leave part of the period open so the ends trace distinct paths.
        phase = 235 * i // segments
        x = 79 + X_PRIMARY[(2 * phase + 2 * frame + 32) & 255]
        x += X_SECONDARY[(5 * phase - 3 * frame + 11) & 255]
        y = 49 + Y_PRIMARY[(3 * phase - 2 * frame + 53) & 255]
        y += Y_SECONDARY[(4 * phase + 3 * frame) & 255]
        points.append((x, y))
    return points
