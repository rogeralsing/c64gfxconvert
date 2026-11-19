# C64 wireframe line demo

Build and launch the rotating cube in VICE:

```sh
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py
rtk proxy /opt/homebrew/bin/x64sc -pal -autostart mydemo/linedrawer/build/linedrawer.prg
```

The PRG starts the cube immediately. It uses normal hires character mode,
a 40×25 screen, and a fixed bank of 200 line glyphs. Each glyph contains a
4×4 grid of double-width, double-height pixels. The 6502 receives two
endpoints, selects one slope, and advances one character column or row
at a time. Each step looks up one or two complete glyphs. Reserved slots
201–255 can be patched when edges share a cell.

The line drawer uses rounded Q8 slopes. The tables cover all start
positions within a cell and handle short ends, axis-aligned lines, and
diagonals. Endpoints are exact across the screen. A rounded slope can
move an intermediate step by one logical pixel.

The cube supplies a table of projected vertices and visible faces for its
256-frame rotation. The C64 draws the visible edges between those vertices.
The 160×100 logical screen has its origin at the top left. Call
`drawCharLine` directly if both endpoints are known to be on-screen
(`x=0..159`, `y=0..99`), as the cube does. For arbitrary signed 16-bit
endpoints, call `drawClippedLine`. Put the low bytes in
`lx0/ly0/lx1/ly1` and the high bytes in
`clipX0Hi/clipY0Hi/clipX1Hi/clipY1Hi`. The clipper rejects invisible
segments and rounds visible intersections to logical pixels before
calling the same character drawer. It can replace the endpoint low bytes.

The cube alternates between two screen and charset pairs. Each frame clears
the cube's screen rectangle in the hidden pair, writes its visible edges,
and patches only that pair's reserve glyphs. Both screens are cleared at
startup. The assembler derives the rectangle from the projected vertices.
One write to `$D018` in the PAL lower border presents both addresses
together. The display keeps reading the previous pair until that write.

When edges share a character cell, the renderer combines their masks and
checks one slot in a precomputed glyph dictionary. Unknown masks use a
reserve glyph. The dictionary verifies the full mask before returning a code.

Run `rtk proxy sh mydemo/linedrawer/verify.sh` to rebuild and check the
default launch in VICE. The verifier checks both addresses at every swap
through frame 198. It compares eight completed frames, including 196 and
197, with the Python reference and checks that the previous screen and
glyphs remain unchanged while the next pair is drawn.

After building, run `rtk proxy python3 mydemo/linedrawer/verify_clipped_lines.py`
to exercise signed endpoints in VICE and check that only the target
screen's 1,000 cells can change when drawing a single line.

## Earlier experiments

The following notes and measurements document earlier prototypes.

### Experimental table walker

The original lookup-only walker used a 65-direction, four-phase table
with 27,224 bytes including indices and thresholds.
Quantizing the start and reversing the end prefix can leave gaps at cell
boundaries. The current build uses the character group tables above.

### Original record design

Per line `(x0,y0)→(x1,y1)` (fat pixels, any quadrant):

1. **Snap** — upper-bound binary search over 258 exact rational thresholds
   (cross-product compares, shift-add 8×8 multiplies). The threshold table is
   generated and *proven* equal to the atan² snap for every possible input
   (dx 1..159 × dy 1..99 = 15,900 cases).
2. **Record fetch** — per direction: `kstart` + 4 entry-prefix glyphs +
   per-cell middle stream (glyph byte + 2-bit step: bit0=col+1, bit1=row+1)
   for each of the 16 entries, with an entry pointer table. 9 directions
   shipped for the demo; the code path is general.
3. **Walk** — start prefix stamp, middle cells (stamp + advance screen
   pointer by mirrored column/row steps), end prefix stamp. The END cell is
   the *reversed-draw prefix* (Bresenham is not reversible at tie-breaks, so
   the reversed prefix is the system's end definition — mirrored through the
   hv flip map; the reversed draw lives in the double-flipped frame, hence
   the complemented end entry).
4. **Mirrors** — screencode flip maps (identity/h/v/hv); mirrored quadrants
   canonicalize cells and entry sub-coords and map glyphs at stamp time.

## Original vertex joint demo

Endpoints in a wireframe are always joints of >= 2 edges. The drawer
composes them at the start/end stamps: read the cell back, reverse-map its
screencode to a pattern (joint slots resolve through the slot table), OR in
the incoming prefix pattern, then resolve as line-bank hash hit -> joint
patch slot (glyph expanded into chars 201..255 at runtime) -> fallback
overwrite. Middle cells stay plain stores. The demo adds a closed triangle
whose three corners are two-edge joints, on top of lines 1-3 which share a
triple corner at (2,2).

## Historical receipts from the first record demo

| Proof | Result |
|---|---|
| Reference vs record-drawer sweep (random lines, all quadrants) | 3,819 lines, 0 mismatches |
| Snap threshold table vs atan² snap | 15,900/15,900 inputs exact |
| Native 6502 simulator (real PRG bytes, real tables) | halt reached, signature ok, **screen byte-exact** |
| Headless VICE (x64sc, breakpoint at halt) | signature ok, **screen byte-exact** |
| Joint composition (12 segments, 5 joint slots) | sim + VICE **byte-exact** vs joint-aware reference |

Cycle receipt (simulator, per demo line incl. per-line overhead):
7.7 K–11.4 K cycles/line; whole 9-line demo ≈ 103 K cycles including init.

## Original v1 scope

- Diagonal lines only: horizontal/vertical/dot/same-cell lines return
  unsupported (fast paths designed, not implemented).
- Records shipped for the demo's 9 directions (12.8 KB for 9; full 259
  needs the rotation/phase compression measured in the viewer work).
- Performance: correct-first implementation. For a 25 fps wireframe the
  snap wants square-table multiplies (or per-frame direction caching) and
  the walk can drop its 16-bit address adds; ~2-3× headroom estimated.

## Bugs found by the verification loop (kept for the record)

1. `lda #258` silently truncated — the search bounds are 16-bit.
2. `mul8` clobbers X — callers preserve the line index.
3. Record entry pointers off by 2 (`p+32` → `p+34`).
4. Flip maps written into detached `bytearray` slices — all-zero tables.
5. Record prefixes stored as patterns instead of glyph codes.
6. A lost `sbc thiHi` in the 16-bit search-exit compare (file rewrite
   casualty) — early exits for `tlo ≥ thi&$ff`.
7. The search's `mid` legitimately reaches 256/257 in final steep steps —
   kept as 16-bit now; the byte version wrapped to 0 and looped forever.
8. `patchGlyph` clobbers X; the joint slot code is now computed before the
   call (a stale post-call `txa` stamped slot 201+nibble everywhere).
9. The Python joint reference dropped the pattern of cells already holding
   a joint slot code (revmap[201+] = 0) — same class of bug the asm guarded
   against.

## Files

- `linedrawer.py` — font/records/reference drawer + sweep proof
- `main.asm` and `char_walk.asm` — the player and character line drawer
- `clip_line.asm` and `clip_math.asm` — the signed viewport entry and intersections
- `build_linedrawer.py` — table generation and Kick Assembler build
- `char_tables.py` and `cube_model.py` — character tables and cube reference
- `verify_linedrawer.py` / `verify.sh` — headless VICE byte-exact check
- `verify_clipped_lines.py` — headless VICE checks for the clipping entry


## Historical rotating cube (direct rasterizer)

The earlier cube used direct rasterization:
Bresenham over fat pixels, per-cell pattern accumulation, bank-hash stamping
and the same joint composition — no records, no snap (the saturation proof
makes every cell pattern a bank glyph). The 3D pipeline (yaw/pitch/roll in
8.8 fixed point, perspective via a reciprocal table) has an integer-exact
Python twin (`cube_model.py`) for checking screen cells and composed glyphs.

Historical measurements (native sim, real PRG bytes, frames 1-4):

| frame | byte-exact | cycles (incl. receipt screen) |
|---|---|---|
| 1 | yes | 436,030 |
| 2 | yes | 725,298 |
| 3 | yes | 1,007,859 |
| 4 | yes | 1,290,147 |

~289 K cycles per cube frame (12 edges, unoptimized) — ~3.4 fps at PAL.
Next optimization: square-table multiplies in mul16s and caching sin/cos
per frame instead of per vertex-multiply (the transform dominates).

Cube bugs found by the verify loop (in addition to the drawer's list):
10. zp $60 collision: `inc pPtr+1` in the vertex loop was also the frame
    counter — every vertex bumped the frame count.
11. mul16s clobbers X: the vertex loop kept its counter in X.
12. drawSeg clobbers X/Y: the edge loop moved its counter to zp.
13. The y-step tie test used the Z flag of the high-byte subtract only —
    y stepped on every pixel where the high byte was zero (diagonal drift).
14. The endpoint pixel was never plotted (exit check ran after the step).
15. The cell bit was ORed before the cell-change check — first pixel of
    every new cell landed in the previous cell's pattern (lost on reset).
16. zp $71 collision: `dtmp+1` (reciprocal pointer high) overlapped the
    frame counter relocated to $71 — moved to $74.
17. The first pixel of a line never initialized the current cell (curCX
    stayed $FF), so the whole line accumulated into one pattern.
