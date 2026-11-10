# Coverage-indexed OR font

This experiment fills the hidden character screen directly. Each character code
is the existing eight-probe coverage mask. A polygon contributes a mask with
`screen[cell] |= mask`; the fixed font translates that state into visible pixels.

This version plays stored polygon spans. For the complete runtime rotation,
projection and polygon-edge calculation, see the separate
[live OR-font renderer](../../../../or-font-live/README.md).

```text
font[mask] = originalFont[originalGlyphLut[mask]]
```

Empty is `$00`, solid is `$FF`. Full cells remain full under later OR operations.
All 256 code slots remain necessary, including visually identical glyphs: their
mask states differ. The font still occupies 2,048 bytes.

This preserves the original renderer's un-clipped bitmap for every coverage
mask, regardless of polygon order. It does not make arbitrary glyph bitmaps
closed under literal pixel OR. It removes the separate coverage buffer and the
full-screen coverage-to-character pass. Screen clearing, span decoding, polygon
filling, and the final position-dependent circle correction remain.

The baseline is the 72-face checker sphere with the same 64-frame SA64 span
movie, 94-pixel radius, fixed pitch 22 degrees and roll 12 degrees. The stored
spans replace edge intersection calculations in both versions. These timings
therefore measure the fill/font change, not runtime 3D projection or edge DDA.

The original circle pass can select glyphs absent from the mask-indexed font.
The experiment chooses the closest available glyph that stays within the circle
at each boundary cell. This approximation is applied only after all polygons
have been combined. It is not a font trained for these particular 64 frames.

## Measured result

PAL VICE 3.10, speed 100%, warp disabled. The baseline PRG was rebuilt and its
SHA-256 matched the archived native measurement. The OR variant was verified
over 66 presentations and profiled over all 64 poses with the same movie.

| Measurement | Original | OR font |
| --- | ---: | ---: |
| Presented FPS, including waits and flips | 8.3541 | 10.0249 |
| PAL fields per presentation | 6 | 5 |
| Render time, including VIC stalls | 114.70 ms | 96.48 ms |
| Full-screen resolve plus circle pass / circle pass only | 29.07 ms | 10.75 ms |
| Font | 2,048 bytes | 2,048 bytes |
| Separate coverage workspace | 1,024 bytes | 0 bytes |
| PRG file | 46,684 bytes | 46,428 bytes |

Rendering uses 15.89% fewer clocks; displayed FPS rises 20.00% because the frame
finishes one PAL field earlier. Span filling itself remains approximately
46.8 ms: the saving comes from removing the full-screen font conversion.

All 256 un-clipped mask glyphs retain their original pixels. Across the 64
poses, the silhouette approximation changes 818 pixels total: 12.78 per frame
on average, at most 33. No lit pixels protrude outside the circle. The native
verifier checked 66,000 screen bytes, immutable font/movie, loop wrap and three
exact screenshots. The assembled-CPU proof also checked that the front screen
and former coverage workspace remained untouched during rendering.

See [results.json](results.json) for hashes and stage measurements. Generated
receipts and previews live in `build/`; `build/comparison.png` shows the three
frames with the greatest difference, and `build/assets/clip-diff.png` marks the
worst frame's changed pixels.

## Run

Run from the repository root. KickAssembler, VICE 3.10, Pillow, and py65 are
required. The commands use the same local tool locations as the parent benchmark.

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/player/prepare-assets.cjs
rtk proxy node asm/sphere-polygons/precomputed/hybrid/vertices/generate.cjs
rtk proxy node asm/sphere-polygons/precomputed/hybrid/vertices/or-font/build.cjs

rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/vertices/or-font/host-smoke.py

rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/player/verify.py \
  --variant asm/sphere-polygons/precomputed/hybrid/vertices/or-font \
  --asset asm/sphere-polygons/precomputed/hybrid/vertices/or-font/build/assets/spans.sa64 \
  --reference asm/sphere-polygons/precomputed/hybrid/vertices/or-font/build/assets/reference.bin \
  --font asm/sphere-polygons/precomputed/hybrid/vertices/or-font/build/assets/font.bin \
  --frames 66

rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/vertices/profile.py \
  --variant asm/sphere-polygons/precomputed/hybrid/vertices/or-font \
  --asset asm/sphere-polygons/precomputed/hybrid/vertices/or-font/build/assets/spans.sa64 \
  --frames 64

rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/vertices/or-font/preview.py
```

The independent native verifier checks all 64 frames plus loop wrap, real screen
RAM, immutable font/movie, and three VICE screenshots. The profiler includes VIC
bus stalls. Displayed FPS includes raster waits and flips; no music or IRQ work
is present. The GIF is a visual preview with rounded frame durations.
