"""Exact viewport clipping for the character drawer's Python reference."""

from fractions import Fraction


WIDTH = 160
HEIGHT = 100


def visible_segment(segment):
    """Intersect with the viewport, rounding each endpoint half up."""
    x0, y0, x1, y1 = segment
    delta = x1 - x0, y1 - y0
    enter, leave = Fraction(0), Fraction(1)
    for start, step, edge in zip((x0, y0), delta, (WIDTH - 1, HEIGHT - 1)):
        if not step:
            if not 0 <= start <= edge:
                return None
            continue
        near, far = sorted((Fraction(-start, step), Fraction(edge - start, step)))
        enter = max(enter, near)
        leave = min(leave, far)
        if enter > leave:
            return None

    rounded = []
    for position in (enter, leave):
        for start, step in zip((x0, y0), delta):
            value = start + position * step + Fraction(1, 2)
            rounded.append(value.numerator // value.denominator)
    return tuple(rounded)
