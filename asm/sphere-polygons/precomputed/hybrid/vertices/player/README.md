# Native projected-vertex movie baseline

This player decodes the 2,607-byte PV64 checker movie and runs the existing
character-span polygon rasterizer on the C64. It stores projected geometry,
rather than finished character images. Every frame decodes all 62 vertex XY
pairs and the precomputed visibility of the 36 white faces. There is no runtime
matrix projection, normal-based backface calculation, per-vertex Z rejection,
pixel bitmap, or prepared frame of character codes.

The rasterizer clears coverage, constructs sample-row spans for the visible
white polygons, ORs their eight-probe masks into character coverage, and resolves
those masks through the fixed glyph lookup. The same strict circular-limb remap
as the original renderer removes glyph dots outside the sphere. The font and
40×25 character output are unchanged.

This is a benchmark baseline. The ordinary playback launcher still defaults to
the [25 FPS HD64 delta player](../../player/README.md). The
[geometry benchmark overview](../README.md) compares this implementation with
the isolated [fast-fill variant](../fast-player/README.md).

## Build and call boundaries

The shared [asset generator](../generate.cjs) prepares `vertices/build/assets/`.
From the repository root, build with:

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/player/build.sh
```

This creates `build/player.prg`, `main.sym` and assembler debug data. The player
uses font `$2000` and alternating character screens `$0400/$0c00`, with white
color RAM and black background. It waits for the next PAL raster wrap after
rendering and then swaps screens. There is no additional frame-rate cap.

All per-frame vertex decoding, visibility loading, coverage clearing, edge/span
construction, coverage writes, glyph resolution and limb remapping occur inside
`render_start` to `render_end`. At `frame_done`, `frame_index` identifies the
image that was just presented; the index advances afterward. The encoded source
is exported as `animation` to `animation_end`.

## PV64 decode

The frozen [PV64 contract](../CONTRACT.md) defines a 12-byte header, 168 bytes
of shared white-face topology, and a 30-byte codebook of signed `(dx,dy)` pairs.
The initial image contains 124 interleaved absolute XY bytes plus five
visibility bytes. Each of the following 63 images contains 31 packed bytes
holding two four-bit codebook indices each, followed by five visibility bytes.
The low nibble addresses the earlier vertex, and visibility bits are LSB-first
in white-face topology order.

Startup expands the compact topology into 36 twelve-byte RAM records, preserving
the original rasterizer's vertex-index offsets. Normal fields are unused. The
runtime visibility-mask loop replaces the original normal-based face test.
Every loop wrap reloads the first absolute XY image from the real stream. This
is necessary because the visible checker pattern repeats after 60°, while
individual vertex identities are permuted by that symmetry.

The local `raster.asm` is derived from the existing
[`asm/sphere-polygons/raster.asm`](../../../../raster.asm). Its DDA, span
masks, coverage OR operations, glyph resolution and strict limb remap retain the
same arithmetic. A small per-face wrapper adds paired measurement checkpoints
around edge construction and span filling; this overhead is part of the actual
executed code and timing.

## Assembled-code proof

The proof executes the built PRG in py65 and compares against the separately
generated reference arrays; reference data is never imported by the player.

```sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/vertices/player/host-smoke.py
```

The run passed **66 complete images**, including `63 → 0 → 1`, with:

- 66,000 exact character-screen bytes;
- 66,000 exact coverage bytes before glyph resolution;
- 8,184 exact decoded XY bytes;
- unchanged font, encoded PV64 source and every raster lookup asset;
- unchanged front screen during back-screen rendering;
- exact startup expansion of all 36 topology records;
- paired edge/fill events for 396 visible triangle calls and 792 quad calls.

The result is saved in `build/host-smoke.json`. The frozen PRG SHA-256 is
`2d8d0b551efdd9145c34c1a5469f80b406c16db03ff064ddeca649cfb48c9adc`.
The PV64 source SHA-256 is
`dffbb663da9a15a85bac1bd57e9d1d9af7d499f237979140a1bdd039f56e936c`.

## Actual PAL result

The [native verification](build/verification/verification.json) passed 66
displayed images, including loop wrap, at PAL speed 100% with warp disabled.
All 66,000 screen bytes matched, the font and entire PV64 source remained
unchanged, and three actual VIC screenshots matched pixel for pixel. The
verifier closed its owned emulator process afterward.

Mean presentation rate is **4.55678 FPS**. Render clocks including VIC stalls
range from 196,606 to 216,087, with a 206,988.59 mean over the 66-image verification
run. Presentation intervals average 216,215.94 clocks, or eleven PAL fields.
This does not achieve 25 FPS.

The separate [64-image PAL profile](build/pal-profile/profile.json) measures
the complete stored period and attributes its render work:

| Stage | Mean PAL clocks per image | Mean milliseconds |
| --- | ---: | ---: |
| Vertex/visibility decode | 4,970.77 | 5.05 |
| Coverage clear | 6,993.41 | 7.10 |
| Face bounds, span-bound clear and edge DDA | 108,944.86 | 110.58 |
| All face filling | 55,330.98 | 56.16 |
| Glyph resolution and limb remap | 28,519.19 | 28.95 |
| Driver and remaining work | 2,309.05 | 2.34 |
| Complete render | **207,068.25** | **210.17** |

One visible quad's fill averages **3,970.14 clocks, or 4.03 ms**; triangle fill
averages 1,281.56 clocks. These per-face intervals start after edge crossings
are built, so they exclude the edge-DDA cost. The profile includes 768 quads
and 384 triangles across 64 images. All profile clocks include VIC bus stalls;
presentation waiting is outside the render stages. The small difference between
the 64-image profile mean and the 66-image verification mean comes from the
sampled images, including repeated wrap images in the latter.

The [fast-fill player](../fast-player/README.md) replaces only the span-filling
block. It reduces the full-period mean fill cost to 46,038.95 PAL clocks and
raises measured presentation to 4.68117 FPS; vertex decode and edge construction
remain the baseline algorithms.

## CPU instruction costs and profiling

| Stage | Unit | Mean instruction cycles |
| --- | --- | ---: |
| Vertex/visibility decode | Per image | 4,799.39 |
| Coverage clear | Per image | 6,403 |
| Face bounds, span-bound clear and edge DDA | Per visible face | 5,727.03 |
| Span masks and coverage OR writes | Per visible face | 2,908.01 |
| Glyph resolution and strict limb remap | Per image | 26,841.27 |
| Complete render | Per image | **195,635.52** |

Complete render costs range from 185,888 to 204,291 instruction cycles. These
figures execute all native work, including geometry-stream decoding, but py65
does not include VIC bus stalls, raster waiting or presentation. They are not
native FPS measurements. The actual PAL results above include VIC stalls and
measure presentation separately on the same frozen program.

The exported stage pairs are `decode_start/end`, `clear_start/end`,
`face_edges_start/end`, `face_fill_start/end` and `resolve_start/end`.
`edge_start/end` and `fill_start/end` are aliases for the per-face pairs.
Adjacent edge-end and fill-start events occupy distinct addresses. Empty faces
still produce paired events. At the per-face checkpoints, `raster_vertex_count`
at `$0f` identifies triangles or quads, and `current_face_index` at `$4b`
identifies the shared white-face record.

This baseline removes projection and culling work, while preserving the cost of
constructing and filling character spans. A smaller stored geometry movie does
not remove that rasterization cost.

## Memory and serialized size

| Region | Purpose | Bytes |
| --- | --- | ---: |
| `$0002–$0030` | Original raster scratch | 47 |
| `$0040–$004b` | Decoder, topology and visibility scratch | 12 |
| `$0400–$07ff`, `$0c00–$0fff` | Alternating screens | 2,048 |
| `$1000–$13ff` | Character coverage | 1,024 |
| `$1400–$147f` | Two projected-coordinate arrays, 62 used entries each | 128 |
| `$1480–$14ca`, `$1500–$154a` | Left/right bounds for 75 sample rows | 150 |
| `$1580–$1584` | Current visibility bits | 5 |
| `$1600–$17af` | Expanded topology | 432 |
| `$2000–$27ff` | Fixed font | 2,048 |
| `$3000–$3539` | Native control, decoder and character rasterizer | 1,338 |
| `$4000` onward | Raster lookup/remap assets and PV64 movie | Below `$9530` |

The shared raster/font assets total 20,959 meaningful bytes, including the
2,048-byte font. With 1,338 bytes of code, the 2,607-byte movie and a 13-byte
BASIC startup, meaningful loaded bytes total **24,917**. The actual PRG is
**36,144 bytes**, including load address, alignment and address gaps. Code and
emitted data remain below I/O and hardware vectors.
