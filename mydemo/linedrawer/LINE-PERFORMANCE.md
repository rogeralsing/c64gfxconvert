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

## Generated replay blocks with junction handling

The replay study assembles motifs whose glyph codes and offsets are instruction
operands. The caller supplies the 16-bit screen base and advances it once per
motif. Each stamp reads the destination first. A blank accepts the literal code,
an identical code skips the write, and a different code enters the regular
`stampJoint` path. The compact variant shares those instructions through a
subroutine. The regular walker handles the tail after each last full period.

The study compares three long lines, including a reverse line and a steep line,
and uses both screen buffers. For each line it tests blank cells, identical redraws, crossings,
a collision in the second cell of a split block, previously composed joins,
near-parallel overlap, and a full 55-slot junction bank. All three routines must
produce the same screen codes, charset bytes and allocation counts.

The timing includes screen base setup, motif repeats, junction handling and the
tail. The fixture chooses the motif before timing and supplies in-bounds lines.
Each five-stamp motif occupies 111 bytes inline or 36 bytes with the shared
routine, plus the common handlers. The cube reference across 256 poses hits an
occupied cell on 3,324 of 11,506 stamps. Only 94 of 2,108 edges contain two whole
periods. Many cube edges are short, and a full period can exceed the edge length.

For the 50-stamp line from (0, 3) to (156, 42), the cycle counts were:

| Initial contents | Current walker | Inline replay | Compact replay |
|---|---:|---:|---:|
| Blank | 6,817 | 2,416 | 3,037 |
| Crossings with 15 occupied cells | 12,665 | 8,490 | 8,919 |
| Near-parallel with 40 occupied cells | 16,613 | 12,734 | 12,896 |
| Saturated joint bank | 39,960 | 35,896 | 36,201 |

Build the default assets and run the standalone study in PAL VICE.

```sh
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py
rtk proxy python3 mydemo/linedrawer/study_replay_blocks.py
```

## Globe replay comparison

`--globe-replay` builds a separate globe with the default camera, geometry,
font and junction handling. The clipper passes live endpoints to the replay
lookup. A signed delta and the starting position within the 4×4 cell select a
routine with literal glyph codes and offsets. The standard walker draws every
unmatched line. The generator samples the default poses to choose common
patterns. At runtime the C64 still computes the vertices and visible edges.

Across 256 poses in PAL VICE, the globe presented 7.287 FPS with the standard
walker and 7.321 FPS with replay. All corresponding screen and charset bytes
matched. The instrumented build replayed 551 of 7,218 edges (7.6%). The code
bank held 201 routines in 8,181 bytes, and the lookup tables used 2,034 bytes.

| Stage | Standard PAL clocks/frame | Replay PAL clocks/frame |
|---|---:|---:|
| Buffer selection and clear | 1,127 | 1,127 |
| Position | 849 | 850 |
| Rotation and projection | 32,821 | 32,817 |
| Face culling | 13,273 | 13,274 |
| Screen bounds | 1,985 | 1,985 |
| Edge drawing, including clipping, lookup and joins | 80,494 | 79,721 |
| Presentation and frame advance | 4,547 | 4,697 |
| **Total** | **135,096** | **134,471** |

The profiler uses the PAL clock, including time when the VIC-II owns the bus.
The FPS figures come from the completed display fields in the verifier.

```sh
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py --shape globe
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py --globe-replay
rtk proxy python3 mydemo/linedrawer/verify_linedrawer.py --shape globe --all-frames
rtk proxy python3 mydemo/linedrawer/verify_linedrawer.py --globe-replay --all-frames
rtk proxy python3 mydemo/linedrawer/profile_line_draw.py mydemo/linedrawer/build/globe/globe.prg
rtk proxy python3 mydemo/linedrawer/profile_line_draw.py mydemo/linedrawer/build/globe-replay/globe-replay.prg
```

## Reusable blocks for globe line interiors

`--globe-motifs` builds native stamp routines for one or two full groups.
An eight-sample block is selected using its Q8 decision pattern, local
position and orientation. The line length controls the number of blocks and
the tail. It does not select the kernel. Each kernel contains literal
screencodes and screen offsets. A destination read skips identical glyphs or
uses the stock junction merge when the incoming glyph differs.

When the two-group bank has no match, the walker calls two generated
single-group routines. The single-group bank handles every aligned group.
The existing partial writer handles the head and tail.

The VICE coverage pass counts one- and two-group calls in each pose. It compares
their combined group count with the independent line model and observes
the same two-group routine on two different line lengths. The clipping
verifier covers signed endpoints, all octants and every position within a cell.

Across 256 default globe poses, 3,693 two-group calls and 12,209 one-group
calls accounted for all 19,595 full groups. VICE observed the same two-group
routine on lines with major spans of 14 and 22 logical pixels. The complete
screen and charset bytes matched the stock globe on all 256 poses. All 339
standalone line cases also matched the clipping and glyph reference.

The default motif build uses an exact lookup for Q8 rates with spans up to
32 logical pixels. The separate stock control enabled the same table with
`:globeShortRates=1`.

| PAL VICE build | FPS |
|---|---:|
| Stock globe | 7.287 |
| Short blocks with the original rate calculation | 7.205 |
| Stock walker with the short-rate lookup | 7.550 |
| Short blocks with the short-rate lookup | 7.457 |

For the standalone line from (0, 3) to (156, 42), the full motif build took
6,506 PAL clocks versus 7,458 for the stock walker, including clipping
dispatch. Its span exceeds the short-rate lookup limit. The reverse line
took 7,274 versus 6,857 clocks.

```sh
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py --globe-motifs
rtk proxy python3 mydemo/linedrawer/verify_linedrawer.py --globe-motifs --motif-coverage --all-frames
rtk proxy python3 mydemo/linedrawer/verify_clipped_lines.py --globe-motifs
rtk proxy python3 mydemo/linedrawer/profile_line_draw.py mydemo/linedrawer/build/globe-motifs/globe-motifs.prg
```

## One repeating native motif per line

`--globe-repeat` is the fixed-motif variant. After clipping and an optional
partial head, it selects one native routine for a whole period. The kernel
contains literal glyph codes and relative screen offsets. The caller moves
the base address by a fixed signed step and counts down. It leaves the Q8
phase and local position intact. Each stamp checks for existing ink. The
stock walker uses the same phase and slope for the remaining samples.

A cell gets a private glyph when neither of its two line glyphs contains
the other. Later arms OR into the same two-byte mask. The renderer expands
each mask into the hidden charset before the frame flip. A full pool
triggers a redraw of the current bounding box with the shared allocator.

The bank covers exact Q8 rates 0, 64, 128 and 256, with periods of 1, 4, 2 and
1 character steps. It includes all octants and reachable start phases for
those rates. The stock walker handles other rates and lines that have room for
fewer than two complete periods. The generator fits 226 distinct native
routines in 5,894 bytes.

```sh
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py --globe-repeat
rtk proxy python3 mydemo/linedrawer/verify_linedrawer.py --globe-repeat --all-frames
rtk proxy python3 mydemo/linedrawer/verify_clipped_lines.py --globe-repeat
rtk proxy python3 mydemo/linedrawer/profile_line_draw.py mydemo/linedrawer/build/globe-repeat/globe-repeat.prg
```

The PAL verifier traces each line entry, motif selection, and literal kernel
jump. The 256-pose sweep found 460 selections and 1,278 kernel calls across
7,218 lines. It checked the private slots and matched the completed PAL
scanout to the exact line masks. Peak allocation was 37 of 55 slots. The
clipping suite passed 478 signed and aligned cases in both buffers, including
clipped lines with major spans of exactly 32 and 33.

| Renderer | Edge stage cycles per pose | PAL FPS |
|---|---:|---:|
| Immediate glyph writes with linear slot search | 80,561 | 7.291 |
| Immediate glyph writes with a hash index | 61,771 | 8.404 |
| Private cell masks with deferred glyph writes | 53,338 | 9.034 |
| Private cell masks and short-line rate lookup | 48,600 | 9.623 |

All runs used the same 256 poses, geometry, and culling. The edge stage
includes the deferred glyph writes. Earlier tests of the private-cell
renderer covered near and far depth sweeps, clipping, and 32 forced pool
exhaustion cases with the shared allocator fallback.

The current build uses the 594-byte exact Q8 rate table for non-axis,
non-diagonal lines with a major span up to 32. Longer lines use the divider.
The screen and charset bytes match the private-cell baseline for every pose.
The assembler option `:immediateGlobeJoins=1` selects the shared allocator
for comparisons using the current line setup.
The two quarter-slope test lines from (0, 3) to (156, 42) and (92, 26) both
use the same native kernel, with nine and five calls after a single selection.

## Reproduce the globe studies

Run from the repository root with Kick Assembler and PAL VICE installed.

```sh
rtk proxy python3 mydemo/linedrawer/build_linedrawer.py --shape globe --crossing-holes
rtk proxy python3 mydemo/linedrawer/profile_line_draw.py mydemo/linedrawer/build/globe-holes/globe-holes.prg
rtk proxy python3 mydemo/linedrawer/study_line_batches.py
rtk proxy python3 mydemo/linedrawer/verify_clipped_lines.py --crossing-holes
```
