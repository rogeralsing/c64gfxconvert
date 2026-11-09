# Fill payload study

`fill.cjs` exports five real byte encoders and independent decoders through
`codecs`. Every decoded result contains one binary fill value per selected
character cell. Glyph **0 fixes a zero**, glyph **15 fixes a one**, and every
other glyph leaves the fill bit free because the edge layer overwrites it.
The two `edge0-…-control` codecs instead force all edge-cell bits to zero.

All 512 reference screens passed every codec in all three layouts. The proof
checks exact fixed cells across the entire 1,000-cell output, including cells
omitted from cropped layouts. It performed **6,579,720 fixed-cell comparisons**.
Payloads are serialized `Uint8Array` values, not size estimates. The report is
`build/fill-report.json`, with each frame's size, min/mean/max/total statistics,
source hashes, and the exact trajectory.

## Actual mean bytes per frame

The two values in each result column are **checker / football**, 256 frames
each. These are fill payloads only.

| Layout | Cells | Raw packed | Wildcard PackBits | Edge-zero PackBits control | Wildcard alternating | Edge-zero alternating control |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full screen | 1,000 | 125 / 125 | 100.332 / 106.125 | 101.055 / 106.320 | 77.555 / 67.148 | 95.156 / 75.844 |
| Rectangle | 600 | 75 / 75 | 64.992 / 67.063 | 65.949 / 67.309 | 76.844 / 65.758 | 94.883 / 75.703 |
| Circle | 475 | 60 / 60 | **58.086 / 59.633** | 59.496 / 59.969 | 76.750 / 65.531 | 94.883 / 75.703 |

Wildcard optimization is real: on the full screen it saves 4,506 checker bytes
and 2,226 football bytes in alternating streams over the edge-zero controls.
For circle PackBits it saves 361 and 86 bytes respectively. The circle's raw
bitfield is already compact; wildcard PackBits saves only 490 checker bytes and
94 football bytes against that raw baseline over all 256 frames. Its largest
payload is 61 bytes, so it does not improve every individual frame.

Circle wildcard PackBits totals are **14,870 checker bytes** and **15,266
football bytes**, before edge data and framing. Circle row metadata adds
50 bytes once per stored layout. Rectangle metadata adds 4 bytes once. Full
layout needs no metadata. The combined container additionally charges its
header and per-frame fill/edge lengths; the font remains separate. No adaptive
per-frame choice or uncounted mode flag is assumed by these results.

## Byte formats and optimization

`raw-bits` stores eight consecutive layout cells per byte, most significant bit
first. Unused final bits are zero. The layout cell count is supplied externally.

`wildcard-packbits` uses standard bounded PackBits packets:

- Controls 0–127 precede 1–128 literal bytes.
- Controls 129–255 precede one byte repeated 128–2 times.
- Control 128 is reserved and rejected.

Each packed byte has a fixed-bit mask and required-one bits. A repeat packet is
possible exactly when the union of required-one bits does not intersect the
union of required-zero bits across the packet. Its chosen byte satisfies every
constraint. A suffix dynamic program examines every legal literal and repeat
packet, charging `1 + literalLength` or `2` bytes. Packet choices do not share
bits, so this gives a **global optimum for this particular packet grammar and
fixed layout order**, including free padding bits. It is not a claim of optimal
compression among all possible formats.

`wildcard-alternating-uleb` starts with zero fill and stores canonical ULEB128
run lengths. The decoder alternates the fill bit after every length. Zero
lengths are allowed before completion to switch phase; they occupy one byte.
The known layout cell count terminates decoding. The stream must end exactly
there: trailing runs, truncated integers and overflowing runs are rejected.
Runs of 128 or more use ordinary ULEB128 continuation bytes, without escapes or
ambiguous marker values. No starting-bit flag is omitted from the accounting:
an initial one run requires an explicitly encoded zero run first.

The alternating dynamic program considers every positive run that contains no
opposing fixed cell, plus the one-byte phase switch. Two consecutive zero runs
are always redundant in a shortest stream. It therefore gives a global minimum
for this run grammar. Both encoders optimize offline; their host optimization
cost is not a C64 rendering or playback measurement.

## Reproduction and independent checks

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/fill.cjs --self-test
rtk proxy node asm/sphere-polygons/precomputed/hybrid/fill.cjs --measure
```

The self-test passed 1,555 codec round trips, 9,841 exhaustive short ternary
alternating cases, and 256 PackBits cases with independently enumerated free-bit
assignments. Ordinary concrete-byte packet optimization and direct binary run
counting provide independent size oracles for those bounded cases. Known byte
streams test decoding separately from encoding, including long ULEB runs,
padding and malformed payload rejection. A concrete wildcard bridge takes two
PackBits bytes; forcing its edge cells to zero takes four.

These results concern host-verified packing and decoding. No native decoder,
6510 cycle count, PAL playback rate or FPS saving is claimed.
