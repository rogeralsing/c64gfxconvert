# Universal drawing font

One fixed 256-glyph drawing vocabulary with parametric ramp chains, bands,
checker patterns and Bayer tones. A trailing content section can be optimized
once over a collection of films. The drawing sections keep their code slots.

The [frozen font used by the flagship star](../three-scene/universal-font.bin)
remains unchanged:
`1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.
It is an existing prototype, not a claim of an optimal or near-exact font.

## Slot map

For the frozen stride-3 layout there are 191 fixed and 65 content slots:

| Slots | Section |
| --- | --- |
| 0 | empty |
| 1..8 | H:left thickness 1..8; slot 8 is full |
| 9..15 | H:right thickness 1..7 |
| 16..22 | V:top thickness 1..7 |
| 23..29 | V:bottom thickness 1..7 |
| 30..85 | four complete 45-degree half-plane chains |
| 86..141 | eight sampled 1:2 / 2:1 chains, stride 3 thresholds |
| 142..171 | H/V bands: one pixel at each row/column, two pixels at each offset |
| 172..175 | checker phases |
| 176..190 | Bayer 4x4 tones 1..15 |
| 191..255 | content glyphs |

Each chain stores its thresholds in consecutive slots. A ramp walker can use
`chain.base + step` with a fixed-point step accumulator. Chains omit the empty
shape; each chain's actual bitmap range is returned by `font.cjs`.

## Corpus layout and reproducibility

`font.cjs` contains the shared corpus reader used by both studies.
`reference.frames` holds 1,000 character codes per frame. `ideal.frames`, when
present, holds a **320x200 raster of binary byte pixels: 64,000 bytes per frame**.
The reader packs an 8x8 tile into row bytes only after locating its raster
coordinates. It validates metadata, frame counts, raster length and pixel
values. Frame counts come from the files; the tumbling film has all 241 frames.

If `ideal.frames` is absent, the target is the corpus's existing character
screen decoded through its own font. This is the fallback for the zoom film;
it measures agreement with that film's character rendering, not its original
bitmap. Reports distinguish both target types.

Corpora default to `asm/sphere-polygons/font-v2/build` in this checkout.
Generate the per-film assets first, or select another build directory with
`--root DIRECTORY` / `UNIVERSAL_CORPORA_ROOT`. No user-specific checkout path
is embedded in the scripts. Commands below run from the repository root:

```sh
rtk proxy node asm/sphere-polygons/font-v2/universal/font.cjs
rtk proxy node asm/sphere-polygons/font-v2/universal/optimize-content.cjs \
  --measure-font asm/sphere-polygons/font-v2/three-scene/universal-font.bin
rtk proxy node asm/sphere-polygons/font-v2/universal/line-encode.cjs
```

The measurement command writes `universal/build/frozen-font-measurement.json`
without changing the font. The line command reads the same frozen font by
default and writes `universal/build/line-study.json`. Both accept `--output`.
The line command also accepts `--font`; its fixed prefix must match stride 3.

To generate new candidates, run `optimize-content.cjs` without `--measure-font`.
It writes separate stride-2 and stride-3 candidates under `universal/build`.
It never replaces the flagship's frozen font or its verified native program.
The greedy search uses the fixed sections and up to 1,200 census candidates;
it does not claim a global optimum.

## Corrected census and frozen-font measurement

An earlier study misread the raster as eight packed bytes per tile, truncated
some films, and used the wrong percentage denominator. Its 271-tile census,
near-exact font claims and old line-codec size table are withdrawn. The frozen
font was produced before that reader correction and is preserved for native
reproducibility; it has not been retrained here.

The corrected nine-corpus snapshot contains **4,977 unique 8x8 tiles** over
1,673 frames. This frozen snapshot includes the flagship bitmap from before
its rotation-axis correction; its input hashes remain recorded below.
Measurements use unconstrained nearest-glyph Hamming distance.
Percentages divide by all 64,000 physical pixels per frame, including empty
background. Native mask-constrained character fitting can produce different
errors; these are not active-object percentages.

| Corpus | Frames | Unique target tiles | Mismatched pixels/frame | Whole-screen error |
| --- | ---: | ---: | ---: | ---: |
| solid star | 161 | 851 | 214.67 | 0.335% |
| sphere-to-cube zoom, existing-font target | 250 | 256 | 239.07 | 0.374% |
| gradient dither cube | 200 | 3,244 | 351.84 | 0.550% |
| dithered star | 241 | 848 | 434.26 | 0.679% |
| tumbling star | 241 | 1,053 | 182.73 | 0.286% |
| glass diamond | 161 | 456 | 451.27 | 0.705% |
| glass star | 161 | 461 | 367.91 | 0.575% |
| glass outline | 161 | 908 | 488.24 | 0.763% |
| flagship star | 97 | 736 | 917.42 | 1.433% |

The [frozen-font measurement](results/frozen-font-measurement.json) identifies
the snapshot through per-corpus screen, font and ideal-raster hashes. Its
independent packed-bitmap decoding audit matches
all 91,072,000 ideal pixels across the eight bitmap corpora. A synthetic
128,000-pixel raster also checks cell boundaries and MSB-left row packing;
the reader rejects the old packed layout and mismatched frame metadata.

## Serialized ramp-run study

`line-encode.cjs` now serializes and decodes each packet instead of estimating
header sizes. Each frame contains a two-byte line count, five bytes per line,
and an exact residual through the existing global skip/literal codec.
A line packs `start10, lengthMinusOne6, chain4, step5, signedSlope8` plus seven
zero reserved bits. Direction comes from the fixed chain table.

The 0% / 5% setting bounds each candidate line's intermediate pixel error
relative to its covered white pixels. The residual repairs every wrong glyph,
so **all 1,000 final character codes are exact** in both settings. Each packet
is roundtrip-checked. Comparisons include the real loop-closing transition.
The pure-literal baseline uses the same target screens and its existing
size-optimized encoder, including its final end-of-screen skip.

| Corpus | Line budget | Lines + literal | Pure literal | Change |
| --- | ---: | ---: | ---: | ---: |
| solid star | 0% | 76.25 B/frame | 74.25 B/frame | +2.69% |
| solid star | 5% | 76.80 B/frame | 74.25 B/frame | +3.43% |
| tumbling star | 0% | 126.41 B/frame | 124.41 B/frame | +1.61% |
| tumbling star | 5% | 133.82 B/frame | 124.41 B/frame | +7.57% |
| glass diamond | 0% or 5% | 71.31 B/frame | 69.31 B/frame | +2.89% |
| glass star | 0% or 5% | 67.89 B/frame | 65.89 B/frame | +3.04% |

The [serialized line-study receipt](results/line-study.json) contains all byte
totals, input hashes and decoded-screen checks. This greedy line search does
not save data on these four corpora. Its packet
always carries the two-byte line-count header, including frames with no lines.
An adaptive per-frame format selector is not implemented in this study.
The result does not rule out other line encoders or full-frame drawing uses.

## Native status

The [flagship star](../three-scene/results/flagship-star/README.md) uses the
frozen universal font with the existing native literal player: 97 stored
images, 578 verified PAL fields, two real loop wraps and approximately
25.0623 fps. Its source, font and program have independent native receipts
in the flagship output. The line-packet codec above remains
a host-only experiment; it has no C64 player or measured native speed.
