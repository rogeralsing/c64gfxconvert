# Per-frame native code size study

This bounded checker-only experiment emits actual 6502 instructions for each
precomputed image. It compares two specified strategies, rather than searching
for a globally optimal dictionary of shared shapes or code fragments.

Run from the repository root:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/codegen-study.cjs
```

The generated report and binary archives go to the ignored `hybrid/build/`
directory. The 64-frame case uses every fourth pose of the same 256-frame full
rotation. Both cases use the existing 256-glyph font and all 475 circle-layout
cells, including cells whose current glyph is empty. Cells outside that layout
remain empty after a shared one-time native initialization.

## Actual code emitted

Strategy A groups cells by glyph. Each glyph group starts with `LDA #glyph`
(2 bytes), followed by one `STA absolute` (3 bytes) per cell. Each frame ends
with `RTS` (1 byte). The destination bank is known for each frame and alternates
between `$0c00` and `$0400`.

Strategy B keeps the same glyph grouping but considers contiguous runs within
each character row. A run uses either direct stores at `3 × length` bytes or
`LDX #length; LDY #column; JSR row_helper` at 7 bytes. It chooses the helper only
for runs of at least three cells. There are 50 shared row helpers: one per row
and screen bank, each eight bytes:

```asm
row_helper:
    sta row_address,y
    iny
    dex
    bne row_helper
    rts
```

All archive totals include the 400 helper bytes where used, a real 32-byte
initializer clearing both complete screen buffers, a 12-byte archive header,
and three bytes of file offset per frame. The common 2,048-byte font is excluded
from both sides of the comparison.

## Serialized size

| Representation | 64 frames | 256 frames |
| --- | ---: | ---: |
| A: grouped direct stores, all shared costs above | 99,052 B | 396,280 B |
| B: shared row fills, all shared costs above | 85,047 B | 339,332 B |
| Same HC64 images, data only | 19,773 B | 78,700 B |
| HC64 plus actual compact decoder and BASIC stub | 20,406 B | 79,333 B |
| HC64 plus actual fused decoder, layout code, LUT and BASIC stub | 36,173 B | 95,100 B |
| HC64 plus actual unrolled decoder, layout code, LUT and BASIC stub | 39,486 B | 98,413 B |

The 64-frame HC64 file is checked byte-for-byte against the shared native-player
asset. Decoder sizes come from the current assembled player symbol files, not
an estimate. The fused decoder consists of 427 bytes of control, 13,912 bytes
of shared layout code and a 2,048-byte lookup table. The unrolled decoder uses
776 bytes of control, 16,876 bytes of layout code and a 2,048-byte lookup table.
The compact decoder is 620 bytes. Each comparison also charges its 13-byte
BASIC stub.

Even the smaller 64-frame generated-code archive exceeds 64 KiB. Its table
therefore contains 24-bit **file offsets**, not C64 function pointers. The study
does not provide or charge a loader, bank manager or live overlay dispatcher.
The reported generated-code totals are favorable storage lower bounds for a
complete player. The HC64 decoder comparisons likewise count meaningful code,
lookup and data bytes rather than unused gaps between load addresses.

## Executable proof and cost limits

The generated opcodes run in py65 against the independently obtained 1,000-byte
reference screens. The proof executes 65 frames for each 64-frame strategy and
257 frames for each 256-frame strategy, including wrap to frame zero: 644
executions and 644,000 screen bytes compared exactly. It also checks the
opposite screen buffer, font and shared helpers remain unchanged. The actual
native initializer runs first from nonzero memory and clears both 1,024-byte
screen buffers.

| Routine, 64-frame sequence including wrap | Mean CPU instruction cycles | Range |
| --- | ---: | ---: |
| A: direct stores | 2,024 | 2,004–2,040 |
| B: shared row fills | 4,267 | 3,889–4,717 |

The initializer costs 11,529 instruction cycles once. These routine timings
exclude loading or overlaying frame code, VIC stalls, interrupts and screen
presentation. They are not native playback FPS measurements. The native HC64
players are measured separately in PAL VICE.

The direct-store representation is fast once a routine is resident, but a
three-byte store embeds a destination address for every character. Shared row
fills reduce that cost for long runs while adding loop work. Both measured
archives remain substantially larger than the movie plus a shared decoder.
The existing fused and unrolled decoders generate destination-layout code once
and retain the compact HC64 image stream; they do not duplicate that code for
each image.

## Precomputing line glyph directions

A line's orientation can be precomputed, but orientation alone does not select
the glyph. Its offset or phase within an 8×8 cell, filled-side polarity, and
start/end clipping also matter. Long straight edges can repeat motifs based on
slope and phase. Corners, two boundaries crossing one cell, and silhouette
clipping require additional cases. The fixed charset is already a small
dictionary of such local masks.

A shared line primitive or repeated shape dictionary could improve on these
two simple strategies. That has not been disproved or optimized here. A native
`JSR` already costs three bytes before its parameters, so a bytecoded display
list with one-byte operation tags can remain smaller than a native call stream.
No cross-frame macro discovery, slope-pattern dictionary, global register-state
optimization or additional strategy was included in this bounded test.
