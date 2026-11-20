"""Build the 4×4 logical-pixel line font for Megaplot. Glyph zero is blank."""

FW = 40
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
        add(hflip(tiles[i]))
        add(vflip(tiles[i]))
        add(hvflip(tiles[i]))
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
                    raw[(i + 1) * 8 + 2 * r] |= 0xC0 >> (2 * c)
                    raw[(i + 1) * 8 + 2 * r + 1] |= 0xC0 >> (2 * c)
    return bytes(raw)
