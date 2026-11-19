#!/usr/bin/env python3
"""Integer-exact reference for the C64 cube geometry and character drawer.

The transform uses defined 8.8 fixed-point arithmetic. Lines use a normalized
Q8 minor-axis rate with a half-pixel initial error. This reference samples
pixels only while building or verifying; the native drawer selects precomputed
character forms. It also emits geometry tables and checks visible-edge coverage.
"""
from pathlib import Path

from clip_reference import visible_segment

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"

# ------------------------------------------------------------ constants
SIN_BITS = 8                  # sin table: round(sin*256), int16, 256 phases
YAW0, PITCH0, ROLL0 = 32, 16, 11
YAW_INC, PITCH_INC, ROLL_INC = 2, 1, 3
POSITION_PHASES = (0, 64, 96)
POSITION_INCREMENTS = (3, 2, 1)
POSITION_AMPLITUDES = (320, 176, 256)
CAM = 1280                    # 5.0 in 8.8
F = 96
CX, CY = 80, 50
DMIN, DMAX = 352, 2503        # projection depth domain in 8.8
SIZE_MIN, SIZE_MAX, SIZE_DEFAULT = 48, 80, 64  # Q6
FRAMES_TO_VERIFY = 4
ROTATION_FRAMES = 256

VERTS = [(-256, -256, -256), (256, -256, -256), (256, 256, -256), (-256, 256, -256),
         (-256, -256, 256), (256, -256, 256), (256, 256, 256), (-256, 256, 256)]
EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
         (0, 4), (1, 5), (2, 6), (3, 7)]
FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (3, 7, 6, 2),
         (0, 4, 7, 3), (1, 2, 6, 5)]
EDGE_FACES = [
    tuple(index for index, face in enumerate(FACES) if a in face and b in face)
    for a, b in EDGES
]

import math

def build_sin():
    return [round(math.sin(2 * math.pi * i / 256) * 256) for i in range(256)]

def build_recip():
    # recip[d-DMIN] = round(F * 65536 / d)
    return [round(F * 65536 / d) for d in range(DMIN, DMAX + 1)]

SIN = build_sin()
RECIP = build_recip()
SIZE_INVERSE = tuple(round(16384 / size) for size in range(SIZE_MIN, SIZE_MAX + 1))

def cos(ph):
    return SIN[(ph + 64) & 255]

def mul16s(a, b):
    return a * b

def rotated_vertices(n):
    yaw = (YAW0 + n * YAW_INC) & 255
    pit = (PITCH0 + n * PITCH_INC) & 255
    rol = (ROLL0 + n * ROLL_INC) & 255
    cy, sy_ = cos(yaw), SIN[yaw]
    cx_, sx_ = cos(pit), SIN[pit]
    cr, sr = cos(rol), SIN[rol]
    out = []
    for x, y, z in VERTS:
        x1 = mul16s(x, cy) + mul16s(z, sy_) >> 8        # yaw
        z1 = mul16s(z, cy) - mul16s(x, sy_) >> 8
        y1 = mul16s(y, cx_) - mul16s(z1, sx_) >> 8      # pitch
        z2 = mul16s(y, sx_) + mul16s(z1, cx_) >> 8
        x2 = mul16s(x1, cr) - mul16s(y1, sr) >> 8       # roll
        y2 = mul16s(x1, sr) + mul16s(y1, cr) >> 8
        out.append((x2, y2, z2))
    return out

def frame_position(n, size=SIZE_DEFAULT):
    """Position and camera depth in units of the scaled cube."""
    x, y, z = (
        SIN[(phase + n * inc) & 255] * amplitude >> 8
        for phase, inc, amplitude in zip(POSITION_PHASES, POSITION_INCREMENTS, POSITION_AMPLITUDES)
    )
    size = max(SIZE_MIN, min(SIZE_MAX, size))
    inverse = SIZE_INVERSE[size - SIZE_MIN]
    return x * inverse >> 8, y * inverse >> 8, (CAM + z) * inverse >> 8

def frame_vertices(n, size=SIZE_DEFAULT):
    """Project the eight rotated vertices to signed screen coordinates."""
    tx, ty, camera_depth = frame_position(n, size)
    out = []
    for x, y, z in rotated_vertices(n):
        depth = max(DMIN, min(DMAX, camera_depth + z))
        r = RECIP[depth - DMIN]
        ox = (mul16s(x + tx, r) + 32768) >> 16
        oy = (mul16s(y + ty, r) + 32768) >> 16
        out.append((CX + ox, CY - oy))
    return out

def face_is_visible(points, face):
    """Positive winding faces the viewer when screen y increases downward."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = (points[index] for index in face)
    signed_area_twice = (x2 - x0) * (y3 - y1) - (y2 - y0) * (x3 - x1)
    return signed_area_twice > 0

def frame_segments(n, size=SIZE_DEFAULT):
    pts = frame_vertices(n, size)
    visible = [face_is_visible(pts, face) for face in FACES]
    segments = []
    for (a, b), (left, right) in zip(EDGES, EDGE_FACES):
        if visible[left] or visible[right]:
            clipped = visible_segment((*pts[a], *pts[b]))
            if clipped is not None:
                segments.append(clipped)
    return segments

# ------------------------------------------------- direct rasterization
def bresenham(x0, y0, x1, y1):
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        pts.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return pts

def direct_cells(x0, y0, x1, y1):
    """Per-cell patterns of the true-slope line (no snapping)."""
    cells = {}
    order = []
    for x, y in bresenham(x0, y0, x1, y1):
        key = (y >> 2) * 40 + (x >> 2)
        if key not in cells:
            cells[key] = 0
            order.append(key)
        cells[key] |= 1 << ((y & 3) * 4 + (x & 3))
    return [(k, cells[k]) for k in order]

def normalized_points(x0, y0, x1, y1):
    """Build-time samples for the Q8 character walk, with error initially 128.

    The major axis advances once per sample. Its minor displacement is
    round(k * rate / 256), where rate itself is rounded half up. For spans
    below 256 pixels, the final displacement is exactly the requested minor
    distance: rate rounding accumulates less than half a pixel of error.
    """
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    y_major = dy > dx
    major, minor = (dy, dx) if y_major else (dx, dy)
    rate = (512 * minor + major) // (2 * major) if major else 0
    sx = -1 if x1 < x0 else 1
    sy = -1 if y1 < y0 else 1
    points = []
    for step in range(major + 1):
        displacement = (128 + step * rate) >> 8
        xstep, ystep = (displacement, step) if y_major else (step, displacement)
        points.append((x0 + sx * xstep, y0 + sy * ystep))
    return points

def normalized_cells(x0, y0, x1, y1):
    """Ordered character masks for the Q8 reference; no native pixel loop."""
    cells = {}
    for x, y in normalized_points(x0, y0, x1, y1):
        key = (y >> 2) * 40 + (x >> 2)
        cells[key] = cells.get(key, 0) | (1 << ((y & 3) * 4 + (x & 3)))
    return list(cells.items())

def prove_normalized_endpoints(max_major=159):
    """Check every rate input in the 160x100 screen's major-span envelope."""
    if not 0 <= max_major <= 255:
        raise ValueError("The Q8 exact-endpoint proof requires a span below 256 pixels")
    cases = 0
    for major in range(max_major + 1):
        for minor in range(major + 1):
            points = normalized_points(0, 0, major, minor)
            if points[0] != (0, 0) or points[-1] != (major, minor):
                raise AssertionError(f"Q8 endpoint mismatch for span {(major, minor)}")
            cases += 1
    return cases

def frame_screen(n, tile_to_code, size=SIZE_DEFAULT):
    """Joint-composed screen for cube frame n using normalized Q8 lines."""
    import linedrawer as L
    screen = bytearray(1000)
    revpat = [0] * 256
    for pat, code in tile_to_code.items():
        revpat[code + 1] = pat
    keys, vals = L.make_bank_lookup(tile_to_code)
    def lookup(pat):
        h = ((pat & 0xFF) ^ (pat >> 8)) & 0xFF
        while keys[h]:
            if keys[h] == pat:
                return vals[h]
            h = (h + 1) & 0xFF
        return 0
    joints = []
    for x0, y0, x1, y1 in frame_segments(n, size):
        for key, pat in normalized_cells(x0, y0, x1, y1):
            ex = screen[key]
            if ex == 0:
                screen[key] = lookup(pat)          # saturation: always a hit
            else:
                expat = joints[ex - 201] if ex >= 201 else revpat[ex]
                merged = expat | pat
                hit = lookup(merged)
                if hit:
                    screen[key] = hit
                elif merged in joints:
                    screen[key] = 201 + joints.index(merged)
                elif len(joints) < 55:
                    joints.append(merged)
                    screen[key] = 201 + len(joints) - 1
                else:
                    screen[key] = lookup(pat)
    return screen, joints

def emit():
    BUILD.mkdir(exist_ok=True)
    (BUILD / "sin.bin").write_bytes(b"".join(v.to_bytes(2, "little", signed=True) for v in SIN))
    (BUILD / "recip.bin").write_bytes(b"".join(v.to_bytes(2, "little") for v in RECIP))
    (BUILD / "size-inverse.bin").write_bytes(
        b"".join(v.to_bytes(2, "little") for v in SIZE_INVERSE))
    (BUILD / "edges.bin").write_bytes(b"".join(bytes(e) for e in EDGES))
    (BUILD / "faces.bin").write_bytes(bytes(vertex for face in FACES for vertex in face))
    (BUILD / "edgefaces.bin").write_bytes(
        bytes((1 << left) | (1 << right) for left, right in EDGE_FACES))

def coverage_receipt(tile_to_code, frames=ROTATION_FRAMES, size=SIZE_DEFAULT):
    """Every normalized-Q8 cube cell over the full motion period is
    a bank glyph (the saturation proof, on the cube's actual lines)."""
    bad = 0
    for n in range(frames):
        for x0, y0, x1, y1 in frame_segments(n, size):
            for key, pat in normalized_cells(x0, y0, x1, y1):
                if pat not in tile_to_code:
                    bad += 1
    return bad

if __name__ == "__main__":
    import linedrawer as L
    t2c, tiles, maps = L.build_font()
    endpoint_cases = prove_normalized_endpoints()
    emit()
    bad = coverage_receipt(t2c)
    for n in range(FRAMES_TO_VERIFY):
        screen, joints = frame_screen(n, t2c)
        (BUILD / f"expected_frame{n}.bin").write_bytes(screen)
    report = {"coverageMisses": bad, "framesChecked": 256,
              "normalizedEndpointsProven": endpoint_cases,
              "expectedFrames": FRAMES_TO_VERIFY,
              "frame0Segments": frame_segments(0)}
    print(__import__("json").dumps(report))
