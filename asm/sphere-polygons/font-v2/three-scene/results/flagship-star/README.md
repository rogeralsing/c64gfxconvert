# Flagship star with PAL-correct proportions

[C64 program](player.prg) · [PAL display preview](c64.gif) · [Raw raster preview](c64-raw.gif) · [Before and after](pal-before-after.png)

The star retains its six tips, cube half-extent 8.5, tip distance 54, fixed
world light, six gray levels and continuous 96-frame symmetry loop. Only the
camera projection changes. The locked 256-glyph font remains byte-identical:
`1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.
No glyph optimization or character-set regeneration runs in this correction.

The former square camera widened the 3D image by 1.6 before font conversion.
The corrected orthographic half-extents are horizontal 79.415873 and vertical 53:
`horizontal = vertical * (160 / 100) * (59 / 63)`. This accounts for the PAL
pixel width/height ratio 59/63 exactly once. The 320 × 200 raster remains intact;
source bitmap samples are still replicated uniformly 2 × 2. Vertical fit still
limits the maximum proportional star size. Actual GPU masks touch no borders,
and a 960-pose sweep retains 0.692 world units of vertical margin. The opaque
source geometry occupies at most 180 × 196 native raster samples.

The [GPU circle calibration](pal-aspect-calibration.png) uses a 48-unit circle
and the exact same camera. Its 96 × 90 logical-sample bounds give a displayed
PAL width/height ratio 0.998941799; the analytic
unit-axis ratio is exactly 1.0. The old square-camera negative control gives
1.498412698 and is rejected. The circle remains rasterized, so the bounding-box
roundness check permits 2.5% quantization error; observed error is 0.106%.

`base * periodicWobble * diagonalSpin` advances the unwrapped spin by 120 degrees
per period. All 14 vertices and 24 facets permute under the actual model-space
(1,1,1) symmetry, including lighting. GPU renders at 120 and 240 degrees match
the first image without resetting the driver. Angular velocity stays continuous.

| Measured item | Result |
| --- | ---: |
| PAL playback including waits | 25.06227 fps |
| Stored frames | 97: blank plus 96 rotation frames |
| Nominal / measured symmetry period | 3.84 / 3.83046 seconds |
| Displayed images checked in both fields | 289 |
| Exact visible PAL fields | 578 |
| Real loop wraps checked | 2 |
| Delta movie including closing patch | 15,272 bytes |
| Locked font | 2,048 bytes |
| Meaningful loaded code, tables, font and data | 18,563 bytes |
| Screen plus zero-page working memory | 1,033 bytes |
| Ordinary main RAM for those items | 19,596 bytes |
| PRG including padding and load address | 25,513 bytes |
| Free in current 40,960-byte data arena | 25,688 bytes |

Separate color RAM uses 1,024 four-bit cells. The initial blank plays once,
then frames 1–96 repeat indefinitely. A complete 360-degree spin takes three
symmetry periods: 288 frames, nominally 11.52 seconds. No music or IRQ workload
is included in the playback measurement.

The font remains the existing experimental locked font; this makes no new
optimality claim. Character matching has 2.621% error within active image
bounds and 1.121% over the whole screen. No white pixels spill outside the
object mask. All 2,149 entirely filled and 80,217 entirely empty source tiles
remain exact.

The main GIF uses actual verified VICE screenshots cropped to the active
320 × 200 raster and displayed at 599 × 400, approximating PAL pixel aspect 59/63.
The nearest integer width introduces -0.0609% pixel-pitch rounding error.
`c64-raw.gif` preserves square raster samples at 640 × 400 for inspection. Both
GIFs decode exactly to their declared resampled screenshot crops across all
96 frames. Their 40 ms frame times approximate native PAL timing. Live VICE
playback should use `-VICIIaspectmode 2` (true aspect), rather than stretching
the active area to 4:3.

Receipts: [PAL camera and circle](pal-aspect-calibration.json),
[native playback](native-verification.json), [native build](native-build.json),
[GPU symmetry and Bayer proof](bitmap-verification.json),
[geometric fit](analytic-fit.json), [character matching](character-audit.json),
[assembled decoder](host-proof.json), [summary](summary.json),
[scene source](demo-flagship-star.mjs), [source hashes](source-manifest.json),
and [unchanged builder compatibility fixtures](metadata-compatibility.json).
Commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`44c815dbd54221f19246de0c879abca3a3067514cec60306dda0c4d542c101ad`.
