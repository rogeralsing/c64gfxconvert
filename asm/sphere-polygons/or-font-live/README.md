# Live polygon renderer with an OR font

This experiment changes the original live C64 renderer. Every frame calculates
the rotation matrix, projects the mesh vertices, selects front-facing white
faces, calculates polygon edge intersections with DDA, and fills the resulting
spans. The character codes are eight-probe coverage masks, accumulated directly
in the hidden screen with OR. A final pass handles the sphere silhouette.

There are no stored poses, projected frames, visibility frames, polygon spans,
or character-screen animations. The asset data consists of mesh geometry,
general arithmetic/sample tables, the 2,048-byte fixed font, and a fixed circle
correction table. The original renderer's fill routine is retained so the
comparison measures the OR-font change alone.

The earlier [span-atlas experiment](../precomputed/hybrid/vertices/or-font/README.md)
is a different implementation: its edge intersections were precomputed. Its
10.02 FPS result does not describe this live renderer.

## Measured result

Both variants passed 64 live orientations in PAL VICE 3.10, speed 100%, warp
disabled. The additional assembled-CPU audit passed 32 varied orientations.

| Measurement | Original live renderer | Live OR font |
| --- | ---: | ---: |
| Presented FPS, including waits and flips | 4.1064 | 4.4539 |
| Rotation and projection | 16.03 ms | 16.04 ms |
| Face traversal, edge DDA and span filling | 188.66 ms | 189.53 ms |
| Full-screen resolve plus clipping / clipping only | 28.79 ms | 10.37 ms |
| Complete render, including VIC stalls | 233.48 ms | 215.95 ms |
| Stored animation data | 0 bytes | 0 bytes |

The OR change reduces render clocks by 7.51% and increases presented FPS by
8.46%. It frees the separate 1,024-byte coverage workspace. The font remains
2,048 bytes. Across the 64 matched native poses, silhouette approximation changes
7.14 pixels per frame on average, at most 34; no lit pixels protrude outside the
circle. Interior mask glyphs remain identical for all 256 states.

See [results.json](results.json) for the PRG hashes and measured values. Full
native receipts and GIF previews are in `build/pal-baseline/` and `build/pal-or/`.
The native verifier checks front-screen and asset preservation between frame
boundaries; the assembled-CPU audit also catches transient writes and guards
assets from initial load.

## Build and verify

Run from the repository root. The tool locations match the original renderer's
local workflow. Only the checker sphere is tested.

```sh
rtk proxy sh asm/sphere-polygons/build.sh
rtk proxy node asm/sphere-polygons/or-font-live/build.cjs

rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/or-font-live/host-smoke.py

rtk proxy python3 asm/sphere-polygons/or-font-live/verify-pal.py \
  --baseline \
  --program asm/sphere-polygons/build/polygon-spheres.prg \
  --symbols asm/sphere-polygons/build/main.sym \
  --output asm/sphere-polygons/or-font-live/build/pal-baseline --frames 64

rtk proxy python3 asm/sphere-polygons/or-font-live/verify-pal.py \
  --program asm/sphere-polygons/or-font-live/build/player.prg \
  --symbols asm/sphere-polygons/or-font-live/build/main.sym \
  --output asm/sphere-polygons/or-font-live/build/pal-or --frames 64
```

The PAL verifier compares the same 64 live orientations in both programs:
initial yaw/pitch/roll `(0,24,0)`, advancing by `(2,1,1)` each frame. It checks
runtime projected vertices, matrices, face traversal/culling, coverage before
clipping, final character codes, immutable font/assets, screen ownership, circle
containment, and three actual VICE screenshots. Stage clocks include VIC stalls;
presented FPS includes raster waiting and flips. Music and IRQ work are absent.

The assembled-CPU proof additionally exercises fixed orientations around all
three axes and audits writes to the front buffer, font, static tables and the
former coverage workspace. It measures instruction cycles, which are not PAL FPS.

The fixed mask font preserves the original un-clipped glyph for all 256 mask
states. The circle correction approximates missing clipped glyphs with the
closest available safe glyph. The font retains duplicate bitmaps because their
coverage states differ. This is associative OR of coverage states, not literal
pixel OR between arbitrary glyph images.
