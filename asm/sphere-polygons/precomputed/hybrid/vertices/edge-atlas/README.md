# Exact precomputed edge-walk atlas

This bounded variant precomputes the exact sample-row crossings of the checker
movie's polygon edges. The C64 reads those crossings from a shared atlas,
aggregates each face's left/right spans, and then uses the unchanged fast span
filler, glyph lookup and strict circular-limb remap. It does not store new
glyphs or finished character frames.

The atlas is specific to the current 64 checker poses. It shares identical
normalized edge paths; it is not a universal lookup table for every possible
line, and this experiment does not claim an optimal dictionary. The original
2,607-byte PV64 stream is retained for XY decoding, topology, visibility and
face bounds, making the additional atlas cost explicit.

## Stored format and exactness

`generate.cjs` decodes the frozen PV64 poses and computes every visible edge's
crossing at the existing 75 sample Y positions. Crossings use the exact rational
ceiling of the line equation, matching the original quotient/remainder DDA,
including negative slopes and its top-inclusive/bottom-exclusive interval.

Each edge path is normalized by subtracting its first X crossing. Identical
normalized sequences share one pool entry. The first relative crossing is
always zero and is omitted. A pool entry contains one byte of sample count,
then signed-byte offsets for the remaining crossings. A zero count represents
an edge with no active sample rows.

Each actual edge use has a four-byte record:

| Field | Bytes |
| --- | ---: |
| First sample-row index | 1 |
| First absolute X crossing | 1 |
| Offset into the shared pattern pool, little-endian | 2 |

The EA64 file contains:

| Part | Bytes |
| --- | ---: |
| Header: magic/version, frame count, record size and section lengths | 16 |
| 64 little-endian offsets into the edge-record stream | 128 |
| 1,034 normalized patterns | 9,200 |
| 4,224 edge-use records | 16,896 |
| **Complete EA64 atlas** | **26,240** |
| Retained PV64 geometry movie | 2,607 |
| **Combined immutable movie sources** | **28,847** |

The records cover 32,332 sample crossings and 206 empty edges. Within a frame,
records follow the existing visible-white-face order and each face's original
edge order. Vertex counts and visibility remain those of PV64, so there are
no uncounted per-face pointers or hidden edge-ID tables.

The host decoder parses the actual emitted EA64 bytes, reconstructs left/right
spans, applies the original eight-probe OR rules, and resolves the same font.
All 64 frames match 64,000 coverage bytes and 64,000 final character bytes
exactly. The atlas SHA-256 is
`90ff657678f30312dadcfa9ee514416b6de4be43cc5963b8c5ea72ef5a4eace8`.

## Native composition

`build.cjs` composes the baseline PV64 driver with `edge.asm` and the frozen
[`fast-fill/kernel.asm`](../fast-fill/kernel.asm). The edge kernel reads each
four-byte record, restores absolute X crossings with byte additions, and takes
the same minimum/maximum into the face's sample spans. It performs no runtime
division, ratio-table DDA or glyph search. Empty paths still consume their
records. Empty face intervals retain paired profiling events and consume their
edge records.

The per-frame atlas-offset lookup is inside the measured decode stage. The
edge-stage interval includes face bounds, clearing span bounds, record/pool
reads and crossing aggregation. Fill and resolve retain the same stage
boundaries and composition semantics as the PV64 fast-fill player. This is
still runtime polygon filling; reading an edge path does not itself produce
the complete polygon image.

The now-unused ratio quotient/remainder tables, ratio-row offsets and sample
Y/gap arrays are omitted, saving 8,470 bytes. `first_sample` remains for face
bounds. Code moves to `$2800` and remaining static data to `$3000`, allowing
the complete player to fit below I/O.

## Build and executable proof

Prepare the shared PV64 assets and build from the repository root:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/vertices/generate.cjs
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/edge-atlas/build.sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/vertices/edge-atlas/host-smoke.py
```

The build writes the atlas, `native-source.bin` (PV64 followed by EA64), generated
ASM under `build/src/`, `player.prg`, symbols and composition hashes. The native
`animation`/`animation_end` labels encompass that complete combined source, so
the full native verifier should use `build/native-source.bin` as its asset.

The assembled py65 proof passed 66 complete images including `63 → 0 → 1`:
66,000 exact coverage bytes, 66,000 exact screen bytes, and 8,184 exact XY bytes.
It checks all read-only raster data, the font and both movie sources remain
unchanged, the front screen is preserved during rendering, and every frame
consumes exactly its edge-record interval. Per-face events cover 396 triangles
and 792 quads. Reference arrays are verifier input only and are not imported
into the player.

`build/atlas.json` and `build/host-smoke.json` contain the results. The frozen
PRG SHA-256 is
`b9ad5085060e8d3efce46b69fd1a19f105c251f2f1087fc83f9207c34e44f64f`.
The complete encoded-source SHA-256 is
`1d7fbf835ef706067b45d05f46d3d565b08c2160e5e441d2c4acfec6903ecb94`.

## Actual PAL result

The [native verification](build/verification/verification.json) passed 66
displayed images including loop wrap: all 66,000 screen bytes matched, the
font and complete 28,847-byte PV64/EA64 source remained unchanged, and three
actual VIC screenshots matched pixel for pixel. It ran at PAL speed 100% with
warp disabled and closed its owned emulator process afterward. Archived
receipts are under [edge-atlas results](../../results/vertices/edge-atlas/).

Measured presentation is **7.160649 FPS**, with seven PAL fields per image.
Presentation intervals range from 137,586 to 137,599 clocks and average
137,592. This improves on the PV64 fast-fill player's 4.68117 FPS, but does not
reach 25 FPS. The character-delta player remains the normal 25 FPS option.

The [complete 64-pose PAL profile](build/pal-profile/profile.json) includes
VIC bus stalls and excludes startup and presentation waiting:

| Stage | Mean PAL clocks per image | Mean milliseconds |
| --- | ---: | ---: |
| PV64 decode and atlas-frame lookup | 5,000.98 | 5.08 |
| Coverage clear | 6,993.58 | 7.10 |
| Face bounds, span reset and edge-atlas aggregation | **40,255.59** | **40.86** |
| Unchanged fast span fill | 46,126.39 | 46.82 |
| Glyph resolution and strict limb remap | 28,583.75 | 29.01 |
| Remaining driver work | 2,265.53 | 2.30 |
| Complete render | **129,225.83** | **131.16** |

The corresponding edge stage of the PV64 fast-fill player costs 109,240.80
PAL clocks, or 110.88 ms. The atlas replaces most of that work with table reads
and min/max aggregation; polygon fill and glyph resolution still run. Complete
rendering falls from that variant's 200.91 ms to 131.16 ms. Small elapsed-clock
differences in unchanged stages reflect instruction placement and VIC-stall
alignment. These stage measurements cover 64 unique poses; the independent
66-image screen/FPS proof also repeats the first two poses after wrap.

## Instruction costs and footprint

| Work, assembled 66-image proof | Mean CPU instruction cycles |
| --- | ---: |
| PV64 decode and atlas-frame lookup, per image | 4,829.39 |
| Coverage clear, per image | 6,403 |
| Bounds and table-driven edge aggregation, per visible face | 2,121.14 |
| Unchanged fast fill, per visible face | 2,426.04 |
| Resolve and strict limb remap, per image | 26,841.27 |
| Complete render, per image | **122,069.77** |

Complete render ranges from 117,651 to 125,502 instruction cycles. The comparable
PV64 fast-fill player averages 187,106.92 in its assembled proof. These are
CPU instruction costs without VIC stalls, raster waits or presentation, not
native FPS. The actual PAL profile and screen verification above measure
those machine and presentation costs separately.

| Loaded content | Bytes |
| --- | ---: |
| Native code, state and included constants | 1,425 |
| Remaining raster/font lookup assets, including 2,048-byte font | 12,489 |
| PV64 plus complete EA64 atlas | 28,847 |
| BASIC startup | 13 |
| **Meaningful loaded bytes** | **42,774** |

The actual PRG is **49,840 bytes**, including load address and address/alignment
gaps. Code occupies `$2800–$2d90`; read-only data ends at `$caae`, below I/O.
Runtime coverage, two screens, XY arrays, span arrays, visibility and expanded
topology remain the baseline allocations. The atlas adds only a two-byte record
pointer at `$4c/$4d`, bringing reserved zero-page state to 61 bytes.

This trades a substantially larger movie representation for less edge work.
The fixed-font character-delta player remains the normal animation option;
this is one exact edge-precomputation benchmark, not a replacement selected
from a global format search.
