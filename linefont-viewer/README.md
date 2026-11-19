# Line Font Lab

Interactive HTML/JS replica of the precomputed line-drawing scheme for the
film ECM font's 4×4 fat-pixel grid. Open `index.html` (no build step, no
dependencies — `python3 -m http.server` or plain `file://` both work).

The font is generated at load time from the same construction that was
measured in Python; the page runs a self-test at startup and prints the
receipt in the stats line.

## Join glyph study

Open [Join study](join-study.html) to compare the current cube, football,
and globe in the native Q8 character format. The study ranks raw line
stamps and final glyphs separately and shows exact and approximate screens
side by side. The models include each vertex's incident edges. The study
checks whether those visible edges alone reconstruct the entire cell.

Even-numbered poses select the fixed glyphs. The 128 odd-numbered poses
per shape measure their coverage. The compact plan keeps line glyphs
seen on completed training screens and uses the other slots for fixed
joins and patch fallback. A hybrid replacement retains every source pixel
and adds at most two connected pixels. The fixed-only comparison uses
nearest glyphs with a penalty for losing boundary pixels.

Run `rtk proxy python3 linefont-viewer/build_join_study.py` after changing
the native meshes or font. The exported assets contain object-space
topology and lookup tables. The browser computes the poses and stamps.

## Scheme

- Grid: 40×25 chars, 4×4 fat pixels per char (160×100), each glyph 2×2-expanded to 8×8.
- 259 canonical directions: `(d,100) d=1..160` and `(160,h) h=1..99`, plus exact H/V.
- 16 entry cells (start fat pixel within its char).
- Rasterize every direction × entry, snapshot every prefix → **132 exact tiles**;
  closing under h/v/hv flips → **200 glyphs**. Horizontal/vertical tiles are
  already inside the 132 as truncation variants.
- Combined with the film font (64 glyphs, 14 shared): **250 of 256** charset slots.

## Modes and the entry/direction trade (measured)

| Mode | Exact tiles | Bank (flip-closed) | Deviation mean / max (fat px) |
|---|---|---|---|
| 259 dirs · free start (16 entries) | 132 | 200 | 0.70 / 0.92 |
| 259 dirs · 2×2 start (4 entries) | 96 | 194 | 1.04 / 1.72 |
| 519 dirs · free start | 132 | 200 | 0.69 / 0.79 |
| 519 dirs · 2×2 start | 96 | 194 | 1.04 / 1.72 |
| dynamic hires (runtime patching) | — | unlimited | true 1px lines |

Deviation = perpendicular distance from the requested raw segment to the
stamped fat pixels (300 random segments, worst point per segment).

Findings:

- **The 2×2 start lattice buys almost nothing.** The exact union drops
  132 → 96, but after flip closure the shipped bank only drops 200 → 194 —
  other directions regenerate most dropped tiles. Cost: start jumps of up to
  1.7 fat px (mean deviation +50 %), worst at polyline joins.
- **Direction count is free.** 519 directions (endpoints on the hires border)
  produce the *identical* 132/200 bank — the 4×4 pattern alphabet saturates at
  259 directions. It slightly improves worst-case slope fit (0.92 → 0.79).
  Saturation proof: all 38 992 reduced slopes in the quadrant (dx ≤ 320,
  dy ≤ 200, gcd = 1) × 16 entries rasterized exhaustively — 0 tiles outside
  the 132. The alphabet is complete for *any* slope; a direction set only
  chooses sequences, and its real cost is table bytes (519 × 16 rows vs
  259 × 16), never charset slots.
- **The fat lattice is the smoothness ceiling.** With exact (unsnapped) slopes
  the deviation floor is 0.68 mean; slope snapping adds only 0.02. No font
  optimization inside the fat system can beat that.
- **True smooth lines need per-line hires glyphs.** A static hires-thin font
  is 1 774+ glyphs even at 4 entries. The "dynamic hires" mode simulates the
  viable architecture: runtime charset patching (≤ ~20 glyphs per line, well
  within the 192 free slots of the movieplayer charset).

## 3D wireframe proof

The **3D** button animates a perspective wireframe (cube / tetra / octa in the
`SHAPES` registry — add vertices + edges to expand) whose every edge is routed
through the active font mode's drawer. It tumbles on all three axes; drag the
stage to rotate manually (auto-tumble pauses while dragging), scroll or use the
slider to scale 0.3–2.2× (overflow past the 160×100 grid clips safely). Because a
rotating wireframe sweeps all slopes continuously, the per-frame misses counter
is a live coverage soak: 60 fps, ~110 chars/frame, misses 0 across all modes
(measured). The same frame renders ~1190 lit pixels in fat modes vs ~660 in
dynamic hires — the thin-line difference, on identical geometry.

## Joints (connectors) — shadow OR + patched slots

Two lines sharing a cell should show the OR of their patterns. That space is
unbounded: a 40 s soak (3 tumbling shapes, scale 0.5–2.0, + random polylines)
produced **6 806 distinct OR patterns**, and frequency-selecting 56 of them
covers only **36.4 %** of occurrences — a static joint bank does not work.

The working architecture (what "Joints" toggles on):

1. Keep a 16-bit **shadow bitmap** per cell (2 KB on the C64).
2. Compose each stamp as `shadow | pattern`. If the OR is already a line
   glyph (18.6 % of occurrences), it renders for free from the static bank.
3. Otherwise **patch** it into a spare glyph slot (codes 200–255; exactly the
   256 − 200 = 56 spare chars of a standalone charset). Rotating objects churn
   joint patterns every frame, so in 3D the slots are per-frame scratch —
   ≤ 40 joints × 8 bytes ≈ 320 bytes per frame, writable in the border.
4. Budget exhausted (never observed: max 43 joints/frame without culling) →
   fallback to plain overwrite.

Measured joint load (40 s soak, all 3 shapes): without culling 18.1/frame avg,
p95 33, max 43. **With backface culling 12.8 avg, max 40** — and line stamps
drop 121 → 87/frame, so culling makes the C64 frame cheaper as well as cleaner.

In manual drawing, patch slots persist (your crossings keep their glyphs);
undo restores screen + shadow together.

## Drawer rules (what the C64 runtime will do)

1. Keep the start fat pixel; snap the slope to the nearest canonical direction.
2. Walk the canonical ray — the slope is never re-rounded. A rounded endpoint
   like (155,30) instead of the snapped (160,31) changes the rasterization and
   leaves the font.
3. Truncate the rasterized point list at the requested endpoint; the truncated
   last cell is a prefix tile that exists in the font.
4. Stamp ~44 chars on average. Crossing lines overwrite shared chars — merged
   patterns are not in the font (normal char-graphics behaviour).

## Measured receipts (Python, this design session)

| Variant | Distinct glyphs |
|---|---|
| Fat 4×4 tiles, 259 dirs × 16 entries, exact lengths | 132 |
| Same, closed under h/v/hv flips | 200 |
| Film font (64) + closed line set | 250 of 256 |
| Hires thin 1px lines, 2px entry grid | 1 986 |
| Hires thin 1px lines, 1px entry grid | 3 072 |

- Per line: max 20 distinct forms, avg 15, avg 43.8 chars.
- Matching line tiles against the film font's 64 glyphs: 15.2 % exact,
  mean error 7.4/64 bits — hence the dedicated bank.
- 10-segment receipt (all quadrants + H/V): 279 stamps, 0 uncovered.
  The page runs the same ten segments at startup.

Thin hires lines don't fit a static charset; the fat 2×2-expanded bank is
exact by construction and keeps joins gap-free in every direction.
