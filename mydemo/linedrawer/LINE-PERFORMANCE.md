# Drawing the large fixed-font globe

The experiment uses the globe with eight meridians, three latitude rings, live
perspective, face culling and fixed glyphs. A cell receiving different glyphs
becomes blank for the rest of that frame. All measurements use the same 256
poses and camera sweep in PAL VICE. Edge time starts after recording the clear
bounds and ends before waiting to flip. It includes dispatch, clipping checks,
glyph selection, screen reads and writes, and VIC-II bus stalls. FPS uses the
interval between actual buffer flips.

## Drawing connected edges together

The globe has 56 model edges. An average frame draws 23.40 visible edges
and attempts 224.10 character stamps. These reach 168.49 distinct cells.
The screen ends up with 136.67 visible cells and 31.82 blank collision cells.

| Experiment on the original walker | Edge clocks/frame | FPS | Image |
|---|---:|---:|---|
| Original | 51,054 | 9.10 | Reference |
| Draw high-degree vertices first | 51,054 | 9.10 | Identical |
| Use an exact slope lookup for short edges | 46,870 | 9.66 | Identical |
| Select the clipping path once and unroll mesh edge dispatch | 47,715 | 9.55 | Identical |
| Skip the cells containing the two endpoints | 47,912 | 9.55 | 1.98 changed cells/frame |

An empty cell receives one write for its first glyph. A second, different glyph
causes one more write to mark the cell blank. Subsequent attempts leave it
blank. Consequently, every ordering of the same stamps does exactly 200.31
screen stores per average frame. Starting at a pole changes the order of reads.

The two ends of the visible lines contribute 46.62 stamps across 13.61 endpoint
cells per frame. Combining every contribution before writing could eliminate
at most 33.01 endpoint stamp attempts. The group would still have to determine
which glyphs agree. Following edges out from a common vertex gives 9.37 repeated
two-cell address prefixes per frame, but only 0.47 have identical glyphs in
both cells. Another 18.79 blank collision cells are entirely inside edges.

A second native comparison unrolled the edges, then grouped the same endpoint
loads and skipped wholly hidden groups. Grouping cut edge time from 47,612 to
47,449 clocks. Both displayed the same 256 screens. The simpler in-bounds
dispatcher fits in 1,303 bytes.

Skipping endpoint cells entirely changes only 0.57 lost and 4.25 added fat
pixels per average frame, but these changes are at the joins. This approximation
was measured independently with the old walker.

## Parallel edges and reusable patterns

Of 5,990 visible lines, 287 repeated the projected direction of another line
in that frame, allowing either sign. Sharing a walker needs more than an angle.
For the measured edge directions, requiring the same octant, Q8 slope and
start position modulo four leaves 17 opportunities. Only 12 complete walks
had identical sequences of relative screen addresses and glyphs. A slope
dictionary still helps because each short edge can use its entry independently.

## Native 6510 results

| Large globe, same image and motion | Edge clocks/frame | Whole-demo FPS |
|---|---:|---:|
| Original character walker | 51,054 | 9.104 |
| Exact decision windows, indexed middle blocks and mesh dispatch | 33,590 | 10.694 |
| Direction-specific four-block loops with specialized ends | 28,730 | 11.823 |
| Same loops with independent stamp selection per block | 27,445 | 12.115 |

The four-block build spends 43.7% fewer PAL clocks drawing edges. The complete
demo gains 29.9% FPS. The last step alone cuts edge time by 14.5%. Frame
preparation takes 80,345 clocks on average. Of 255 intervals between flips,
194 span four PAL fields and 61 span five.

In the 11.823 FPS build the C64 selects an exact Q8 rate per edge. A precomputed byte describes eight
minor-axis steps. Reading one byte per four logical samples covers every
alignment inside a character. For spans through 56 logical pixels, the rate
comes directly from a triangular lookup. Longer clipped lines use the same
rounded division as the original walker.

Each of the eight directions has a loop with fixed glyph-table addresses and
fixed screen steps. On a steep edge, one ADC uses the carry bit to advance a
row and, when needed, move one column. The high byte changes only on a page
crossing. Four copies of the block body share a loop test. The runtime enters
at the appropriate copy for the requested length. The shorter first and last
groups jump to fixed-address glyph loads. A one-sample tail reads its dot
glyph directly. Short-run tests used the same endpoints, motion and glyphs.

| Isolated middle-loop test with the same endpoint handler | Edge clocks/frame | FPS |
|---|---:|---:|
| One block per loop | 31,622 | 11.201 |
| Two blocks | 30,950 | 11.361 |
| Four blocks | 30,577 | 11.422 |

Instruction profiling of the 11.823 FPS build measured 26,097 CPU cycles per frame for the
line calls, including loading the second endpoint. Stepping cell addresses and
the minor coordinate took 4,055 cycles. Loop and endpoint control took 3,927.
The actual screen stores took 1,202 cycles, or 4.6%. These CPU counts exclude
VIC-II bus stalls. The edge-stage PAL figures above include stalls and edge
dispatch. All instructions in the selected renderer are documented NMOS 6502
opcodes.

In that build glyph and decision tables occupy 16,616 bytes, compared with 12,032 in the
original character walker. These counts exclude the screen font, the short
rate table and the specialized machine code. The fixed-font build places the
unrolled bodies in RAM otherwise used for reflection and joint lookup data.
Geometry, depth and rotations are calculated on the C64.

All 256 completed screens matched the independent glyph model and the PAL
scanouts. Another 3,360 signed single-line tests exercised both buffers, all
octants and lengths around the short-rate cutoff. A separate 30-pose mesh test
moved the globe partly and fully outside the screen. It checked 108 clipped
segments and 276 rejected segments alongside 337 in-bounds segments.

## Choosing stamps from the start position

For a line from (0, 0) to (6, 24) in logical pixels, the fixed font produces
the following screen codes in order. Offsets are relative to the first screen
cell, on a 40-column display.

| Relative offset | 0 | 40 | 80 | 120 | 121 | 161 | 201 | 241 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Glyph code | 6 | 22 | 38 | 40 | 16 | 6 | 22 | 23 |

The pair at offsets 120 and 121 straddles a character boundary. After four
rows the motif starts again one column farther right. The last cell uses a
shorter glyph to end at the specified point. A specialized 6510 routine
with literal glyphs and offsets averaged 289 PAL clocks against 963 for the
previous general walker. The test drew the same line at 40 cell-aligned
origins on empty screens, including screen addressing and collision checks.

The globe drew 5,990 edges across the sweep. They yielded 5,769 distinct
whole-line stamp sequences after removing translation. Storing a one-byte
address step and a one-byte glyph for each stamp in these distinct sequences
would take 111,152 bytes before indexing.

The current renderer shares smaller sequences across all lines. A slope
selects one of 257 streams. Each byte encodes seven step decisions and the
minor-axis displacement modulo four at the start of that four-sample block.
Seven decisions are enough for any of the four alignments. Across all slopes
there are 54 distinct decision patterns, so all four displacements and their
patterns fit in 216 byte values.

The start coordinates select the decoder for the aligned middle blocks once.
Each entry supplies a glyph-pair index, including whether the next block
crosses a cell boundary on the minor axis. The loop advances its stream
index and screen address. Each block obtains its local position independently.
The existing screen code still determines how to handle a collision.

In 256 PAL frames the edge stage dropped from 28,730 to 27,445 clocks.
Four-field flip intervals rose from 194 to 220 out of 255. The sum of
assembled code and data sections grew by 265 bytes. All 256 scanouts and
3,360 signed-line checks matched the reference. A second 256-pose check
alternated scale and depth extremes and verified projected vertices and
every resulting screen cell.

Run from the repository root with Kick Assembler and PAL VICE installed.

```sh
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py --shape globe --crossing-holes
rtk proxy python3 mydemo/linedrawer/profile_line_draw.py mydemo/linedrawer/build/globe-holes/globe-holes.prg
rtk proxy python3 mydemo/linedrawer/study_line_batches.py
rtk proxy python3 mydemo/linedrawer/verify_clipped_lines.py --crossing-holes
```
