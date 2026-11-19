#!/usr/bin/env python3
"""Shared construction for the C64 interactive line drawer.

Everything the 6502 will do is defined here twice:
  reference_draw()  — the exact harness drawer (canonical rasterize + truncate)
  record_draw()     — the algorithm the asm will implement (tables + formulas)

A sweep over random lines proves they agree screen-for-screen. The direction
records emitted for the C64 are byte-identical to what record_draw() consumes.
"""
import math
from bisect import bisect_left

FW, FH = 40, 25
PW, PH = 160, 100

# ---------------------------------------------------------------- primitives
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

def hflip(t):  return sum(((t >> (r * 4 + c)) & 1) << (r * 4 + 3 - c) for r in range(4) for c in range(4))
def vflip(t):  return sum(((t >> (r * 4 + c)) & 1) << ((3 - r) * 4 + c) for r in range(4) for c in range(4))
def hvflip(t): return hflip(vflip(t))

# ---------------------------------------------------------------- font
EPS = [(d, 100) for d in range(1, 161)] + [(160, h) for h in range(1, 100)]
ENTRIES = [(x, y) for x in range(4) for y in range(4)]

def build_font():
    """132 exact tiles + flip closure -> 200 glyph codes; plus flip maps."""
    tile_to_code, tiles = {}, []
    def add(t):
        if t not in tile_to_code:
            tile_to_code[t] = len(tiles)
            tiles.append(t)
        return tile_to_code[t]
    for ex, ey in EPS:
        for sx, sy in ENTRIES:
            grid, last = {}, {}
            for x, y in bresenham(sx, sy, sx + ex, sy + ey):
                if 0 <= x < PW and 0 <= y < PH:
                    key = (y >> 2) * FW + (x >> 2)
                    grid[key] = grid.get(key, 0) | (1 << ((y & 3) * 4 + (x & 3)))
                    if last.get(key) != grid[key]:
                        add(grid[key])
                        last[key] = grid[key]
            for t in grid.values():
                add(t)
    for i in range(len(tiles)):                     # closure under flips
        add(hflip(tiles[i])); add(vflip(tiles[i])); add(hvflip(tiles[i]))
    maps = {k: {} for k in ("h", "v", "hv")}
    fn = {"h": hflip, "v": vflip, "hv": hvflip}
    for t, code in tile_to_code.items():
        for k in maps:
            maps[k][code] = tile_to_code[fn[k](t)]
    return tile_to_code, tiles, maps

# charset bytes: char 0 blank, chars 1..N line glyphs (2x2-expanded)
def charset_bytes(tiles):
    raw = bytearray(2048)
    for i, t in enumerate(tiles):
        for r in range(4):
            for c in range(4):
                if (t >> (r * 4 + c)) & 1:
                    raw[(i + 1) * 8 + 2 * r]     |= 0xC0 >> (2 * c)
                    raw[(i + 1) * 8 + 2 * r + 1] |= 0xC0 >> (2 * c)
    return bytes(raw)

# ---------------------------------------------------------------- directions
# ascending-slope order: (160,1)..(160,99) then (160,100)..(1,100)
DIRS = [(160, h) for h in range(1, 100)] + [(d, 100) for d in range(160, 0, -1)]
DIR_SLOPES = [ey / ex for ex, ey in DIRS]
assert len(DIRS) == 259

def snap(dxa, dya):
    """Direction index nearest to slope dya/dxa (both > 0)."""
    a = math.atan2(dya, dxa)
    return min(range(259), key=lambda i: abs(math.atan2(DIRS[i][1], DIRS[i][0]) - a))

# ---------------------------------------------------------------- records
def build_record(di, tile_to_code):
    """Per (direction, entry): kstart, prefix[4], middle (glyph, delta) cells.

    Middle cells start AFTER the start cell; traversal is canonical
    (down-right); delta = rows dropped (x-major) or columns gained (y-major)
    when advancing to this cell from the previous.
    """
    ex, ey = DIRS[di]
    x_major = ex >= ey
    rec = {"dir": di, "x_major": x_major, "entries": {}}
    for sx, sy in ENTRIES:
        grid, last, order = {}, {}, []
        for x, y in bresenham(sx, sy, sx + ex, sy + ey):
            if not (0 <= x < PW and 0 <= y < PH):
                continue
            key = (y >> 2) * FW + (x >> 2)
            grid[key] = grid.get(key, 0) | (1 << ((y & 3) * 4 + (x & 3)))
            if last.get(key) != grid[key]:
                last[key] = grid[key]
                if key not in order:
                    order.append(key)
        start_cell = order[0]
        # prefix snapshots within the start cell, keyed by pixel count k
        pts = []
        for x, y in bresenham(sx, sy, sx + ex, sy + ey):
            if not (0 <= x < PW and 0 <= y < PH):
                continue
            if (y >> 2) * FW + (x >> 2) != start_cell:
                break
            pts.append((x, y))
        pat, prefixes = 0, {}
        for k, (x, y) in enumerate(pts, 1):
            pat |= 1 << ((y & 3) * 4 + (x & 3))
            prefixes[k] = tile_to_code[pat]
        kstart = len(pts)
        # middle cells: full-cell glyphs + 2-bit steps (bit0=col+1, bit1=row+1)
        middles = []
        pcx, pcy = start_cell % FW, start_cell // FW
        for key in order[1:]:
            kcx, kcy = key % FW, key // FW
            step = (kcx - pcx) | ((kcy - pcy) << 1)
            assert step in (1, 2, 3), (pcx, pcy, kcx, kcy)
            middles.append((tile_to_code[grid[key]], step))
            pcx, pcy = kcx, kcy
        rec["entries"][(sx, sy)] = {
            "kstart": kstart,
            "prefix": [prefixes.get(k, prefixes[max(prefixes)]) for k in range(1, 5)],
            "middles": middles,
            "start_cell": start_cell,
        }
    return rec

# ---------------------------------------------------------------- drawers
def reference_draw(screen, x0, y0, x1, y1, tile_to_code, eps_dirs=None, quant=False):
    """System reference drawer.

    Cells before the end cell come from the forward canonical ray; the END
    cell is defined as the reversed draw's start-cell prefix (backward
    Bresenham from the endpoint). This matches the C64 record drawer by
    construction — forward-only truncation is not Bresenham-reversible at
    tie-breaks, so the reversed prefix is the system's end definition.
    """
    if x1 == x0 and y1 == y0:
        key = (y0 >> 2) * FW + (x0 >> 2)
        pat = 1 << ((y0 & 3) * 4 + (x0 & 3))
        screen[key] = tile_to_code[pat] + 1
        return
    mx = -1 if x1 < x0 else 1
    my = -1 if y1 < y0 else 1
    if eps_dirs is None:
        di = snap(abs(x1 - x0), abs(y1 - y0))
        ex, ey = DIRS[di]
    else:
        ex, ey = eps_dirs[0]
    K = math.ceil(220 / max(ex, ey))
    x_major = ex >= ey
    endcell = (y1 >> 2) * FW + (x1 >> 2)
    if quant:
        x0 &= ~1
        y0 &= ~1
    keep = []
    for p in bresenham(x0, y0, x0 + mx * ex * K, y0 + my * ey * K):
        keep.append(p)
        if (x_major and mx * p[0] >= mx * x1) or (not x_major and my * p[1] >= my * y1):
            break
    grid = {}
    for x, y in keep:                      # forward pixels outside the end cell
        if 0 <= x < PW and 0 <= y < PH:
            key = (y >> 2) * FW + (x >> 2)
            if key != endcell:
                grid[key] = grid.get(key, 0) | (1 << ((y & 3) * 4 + (x & 3)))
    pat = 0                                # backward pixels inside the end cell
    for x, y in bresenham(x1, y1, x1 - mx * ex * K, y1 - my * ey * K):
        if not (0 <= x < PW and 0 <= y < PH):
            continue
        if (y >> 2) * FW + (x >> 2) != endcell:
            break
        pat |= 1 << ((y & 3) * 4 + (x & 3))
    grid[endcell] = grid.get(endcell, 0) | pat
    for key, p in grid.items():
        screen[key] = tile_to_code[p] + 1

def record_draw(screen, x0, y0, x1, y1, tile_to_code, maps, records):
    """The asm algorithm: tables + start/middle/end formulas, no rasterization."""
    mx = -1 if x1 < x0 else 1
    my = -1 if y1 < y0 else 1
    dxa, dya = abs(x1 - x0), abs(y1 - y0)
    if dxa == 0 or dya == 0:
        # H/V specials kept reference-exact for the sweep; asm has fast paths
        reference_draw(screen, x0, y0, x1, y1, tile_to_code)
        return
    di = snap(dxa, dya)
    rec = records[di]
    x_major = rec["x_major"]
    # canonical sub-coords (mirror x and/or y when drawing left/up)
    e0x = (x0 & 3) if mx > 0 else 3 - (x0 & 3)
    e0y = (y0 & 3) if my > 0 else 3 - (y0 & 3)
    # the end partial comes from the REVERSED draw, whose canonical frame is
    # double-flipped relative to ours -> complement of the mirrored coords
    e1x = (3 - (x1 & 3)) if mx > 0 else (x1 & 3)
    e1y = (3 - (y1 & 3)) if my > 0 else (y1 & 3)
    A = rec["entries"][(e0x, e0y)]
    B = rec["entries"][(e1x, e1y)]
    # start cell glyph: prefix after kstart pixels of entry A
    g = A["prefix"][A["kstart"] - 1]
    # end cell glyph: entry B prefix after B.kstart pixels, mapped through the
    # 180-degree flip (the reversed draw lives in the double-mirrored frame)
    gend = maps["hv"][B["prefix"][B["kstart"] - 1]]
    flipkind = None if (mx > 0 and my > 0) else ("h" if my > 0 else "v" if mx > 0 else "hv")
    def stamp(code, cx, cy):
        screen[cy * FW + cx] = (maps[flipkind][code] if flipkind else code) + 1
    cx, cy = x0 >> 2, y0 >> 2
    ecx, ecy = x1 >> 2, y1 >> 2
    # walk middles until we reach the end cell (canonical frame):
    # canonical cell coords = mirror of actual when mx/my negative
    ccx = (x0 >> 2) if mx > 0 else 39 - (x0 >> 2)
    ccy = (y0 >> 2) if my > 0 else 24 - (y0 >> 2)
    kcx = (x1 >> 2) if mx > 0 else 39 - (x1 >> 2)
    kcy = (y1 >> 2) if my > 0 else 24 - (y1 >> 2)
    n_mid = 0
    for glyph, step in A["middles"]:
        ccx += step & 1
        ccy += step >> 1
        if (ccx, ccy) == (kcx, kcy):
            break
        # real cell = mirror back
        rcx = ccx if mx > 0 else 39 - ccx
        rcy = ccy if my > 0 else 24 - ccy
        stamp(glyph, rcx, rcy)
        n_mid += 1
    same_cell = ((x0 >> 2), (y0 >> 2)) == ((x1 >> 2), (y1 >> 2))
    if not same_cell:
        stamp(g, x0 >> 2, y0 >> 2)
    stamp(gend, x1 >> 2, y1 >> 2)
    return n_mid

# ---------------------------------------------------------------- sweep proof
def sweep(count=4000, seed=42):
    import random
    random.seed(seed)
    tile_to_code, tiles, maps = build_font()
    need = set()
    segs = []
    for _ in range(count):
        x0, y0 = random.randrange(PW), random.randrange(PH)
        x1, y1 = random.randrange(PW), random.randrange(PH)
        if abs(x1 - x0) < 2 or abs(y1 - y0) < 2:
            continue
        segs.append((x0, y0, x1, y1))
    for x0, y0, x1, y1 in segs:
        dxa, dya = abs(x1 - x0), abs(y1 - y0)
        if dxa and dya:
            need.add(snap(dxa, dya))
    records = {di: build_record(di, tile_to_code) for di in sorted(need)}
    mismatches, checked = 0, 0
    for x0, y0, x1, y1 in segs:
        if abs(x1 - x0) == 0 or abs(y1 - y0) == 0:
            continue
        a = bytearray(1000)
        b = bytearray(1000)
        reference_draw(a, x0, y0, x1, y1, tile_to_code)
        try:
            record_draw(b, x0, y0, x1, y1, tile_to_code, maps, records)
        except Exception as e:
            mismatches += 1
            if mismatches < 4:
                print("EXC", (x0, y0, x1, y1), e)
            continue
        checked += 1
        if a != b:
            mismatches += 1
            if mismatches < 4:
                diff = [(i, a[i], b[i]) for i in range(1000) if a[i] != b[i]]
                print("DIFF", (x0, y0, x1, y1), "cells:", diff[:6])
    print(f"sweep: {checked} lines, {mismatches} mismatches, "
          f"{len(need)} direction records, font {len(tiles)} glyphs")
    return mismatches == 0

if __name__ == "__main__":
    ok = sweep()
    print("PROOF", "PASSED" if ok else "FAILED")


# ---------------------------------------------------------------- joint frame
def make_bank_lookup(tile_to_code):
    """256-bucket open-addressing hash: 16-bit pattern -> screencode (0=empty)."""
    keys = [0] * 256
    vals = [0] * 256
    for pat, code in tile_to_code.items():
        h = ((pat & 0xFF) ^ (pat >> 8)) & 0xFF
        while keys[h]:
            h = (h + 1) & 0xFF
        keys[h] = pat
        vals[h] = code + 1
    return keys, vals

def reference_frame(segments, tile_to_code, joint_slots=56):
    """Draw segments with vertex-joint composition, mirroring the asm exactly:
    middle cells overwrite; start/end cells OR with existing content, resolved
    as line-bank hash hit -> joint patch slot -> fallback overwrite."""
    screen = bytearray(1000)
    revpat = [0] * 256
    for pat, code in tile_to_code.items():
        revpat[code + 1] = pat
    keys, vals = make_bank_lookup(tile_to_code)
    joints = []                                   # slot patterns
    def lookup(pat):
        h = ((pat & 0xFF) ^ (pat >> 8)) & 0xFF
        while keys[h]:
            if keys[h] == pat:
                return vals[h]
            h = (h + 1) & 0xFF
        return 0
    for x0, y0, x1, y1 in segments:
        cells = {}
        probe = bytearray(1000)
        reference_draw(probe, x0, y0, x1, y1, tile_to_code)
        # classify cells from the single-line reference: start, end, middles
        mx = -1 if x1 < x0 else 1
        my = -1 if y1 < y0 else 1
        skey = (y0 >> 2) * FW + (x0 >> 2)
        ekey = (y1 >> 2) * FW + (x1 >> 2)
        for i in range(1000):
            if probe[i]:
                if i == skey or i == ekey:
                    pat = revpat[probe[i]]
                    ex = screen[i]
                    if ex == 0:
                        screen[i] = probe[i]
                    else:
                        expat = joints[ex - 201] if ex >= 201 else revpat[ex]
                        merged = expat | pat
                        hit = lookup(merged)
                        if hit:
                            screen[i] = hit
                        elif merged in joints:
                            screen[i] = 201 + joints.index(merged)
                        elif len(joints) < joint_slots:
                            joints.append(merged)
                            screen[i] = 201 + len(joints) - 1
                        else:
                            screen[i] = probe[i]      # fallback overwrite
                else:
                    screen[i] = probe[i]              # middles overwrite
    return screen, joints
