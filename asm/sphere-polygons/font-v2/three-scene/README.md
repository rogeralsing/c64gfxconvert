# Three.js to C64 character film

The first checkpoint is Three.js scene → RGBA frames → calibrated 1-bit film.
Inspect this film before converting anything to characters. The build stops at
that checkpoint by default.

Calibration currently certifies the black/white checker reference. It rejects
gray or colored GPU output rather than guessing how to quantize new lighting
or shading. Those materials need their own reference checks before conversion.

## Gray sides and bitmap dithering

Run the separate bitmap-only experiment:

```sh
rtk proxy node asm/sphere-polygons/font-v2/three-scene/build-dither.cjs
```

`demo-dither.mjs` reuses the approved first five seconds exactly. From five to
six seconds, the cube's checker pattern fades into continuous gray gradients
within each side. Interpolated vertex colors make the tone vary across a side;
the sides no longer have one flat gray value each. It keeps rotating until
eight seconds. `grayContrast: 1.15` increases contrast around the sRGB midpoint
before the endpoints are converted to linear light. Three.js renders ordinary
gray pixels; the exporter then applies
its fixed screen-aligned 4 × 4 Bayer matrix to produce the 1-bit film.

The verifier checks the approved 125-frame prefix, actual tone variation within
individual faces, and every exported bit independently. A known 64/128/192
gray ramp checks the Bayer matrix's 4/8/12 white-pixel coverage per 4 × 4 block;
the cube itself contains continuous gradients. The preview GIF is decoded and
compared against all 200 packed frames, covering exactly eight seconds. No
character conversion runs in this experiment.

Outputs are in ignored `../build/three-scene-dither/`: `render/` holds RGBA,
packed bitmap and mask data; `verification.json` records the checks; `preview/`
contains `bitmap.gif`, a side-by-side `comparison.gif`, and a contact sheet.
`bitmap-detail.gif` enlarges the final two seconds with nearest-neighbor pixels;
its crop is recorded in `media.json`.

After inspecting that bitmap, build its C64 version:

```sh
rtk proxy node asm/sphere-polygons/font-v2/three-scene/build-dither-player.cjs
rtk proxy python3 asm/sphere-polygons/font-v2/verify-scene.py --root asm/sphere-polygons/font-v2/build/three-scene-gradient-c64/native
```

The original 168-glyph palette cannot reproduce most Bayer tones. The builder
first appends the 13 missing exact tone patterns. `optimize-dither-font.cjs`
then measures actual target tiles across the film and appends up to 75 more
patterns, producing one shared 256-glyph font (2,048 bytes). Each greedy step
chooses the observed pattern with the largest frequency-weighted reduction in
pixel error, subject to the silhouette mask. Existing glyph bytes stay unchanged.
All new glyphs are eligible from frame zero; the approved first 125 bitmap
frames stay unchanged, while their character approximation can improve.
`--glyph-limit 181`, `224`, or `240` builds smaller comparison fonts.

On the contrast-adjusted film, gradient-section object error falls from 4.836%
with 181 glyphs to 2.214%, 2.084%, and 1.915% with 224, 240, and 256 glyphs.
Every uniformly empty or filled interior tile remains exact, with zero white
pixels outside the silhouette. The independent audit reconstructs all target
contexts, checks every candidate at every greedy step, and compares all 200
production screens against its own 16-bit matcher.

Measured 256-glyph native playback is 25.0623 fps over 200 images and 400 actual
PAL VICE fields. The player uses 23,364 meaningful loaded bytes, including
20,424 bytes of delta, plus 1 KiB of screen RAM and 5 zero-page bytes. The
contrast/font comparison and native receipts are in
`../build/three-scene-contrast-font/`. Default build outputs remain in
`../build/three-scene-gradient-c64/`.

## Rubik's cube layer turns

`demo-rubik.mjs` keeps the first three seconds of the checkerball entrance.
The sphere then zooms to 270 physical pixels across, extending beyond the
200-pixel-high viewport. It keeps its spherical shape throughout the zoom in.
During the zoom out it morphs into a cube at the original scale. The checker surface
gradually blends into six grayscale sticker identities while the cubie gaps
open, with one fixed pose throughout the transition:

- 3–4 seconds: the sphere zooms in and centers on the screen.
- 4–5.4 seconds: it zooms out and morphs into a cube.
- 5.4–6.2 seconds: the cube becomes a 3 × 3 × 3 Rubik's cube without a cut.
- 6.3–7.1 seconds: the top layer turns 90° clockwise, viewed from above.
- 7.35–9.1 seconds: the left layer turns 180° counterclockwise, viewed from its left side.
- 9.1–10 seconds: the final cube holds still.

The second move selects the left layer after the first move's permutation.
All 27 cubies retain their sticker identities and orientations. Sampling the
scene at any time reconstructs the same pose without depending on frame order.

Build and inspect the bitmap first, then convert that verified export:

```sh
rtk proxy node asm/sphere-polygons/font-v2/three-scene/build-rubik.cjs --output asm/sphere-polygons/font-v2/build/three-scene-rubik-raw
rtk proxy node asm/sphere-polygons/font-v2/three-scene/build-rubik.cjs --output asm/sphere-polygons/font-v2/build/three-scene-rubik-raw --characters
rtk proxy python3 asm/sphere-polygons/font-v2/verify-scene.py --root asm/sphere-polygons/font-v2/build/three-scene-rubik-raw/c64/native --variant literal-front
```

Outputs are in `../build/three-scene-rubik-raw/`. The first command stops at the
bitmap checkpoint. `--characters` consumes that export, checks its source and
data hashes, revalidates it, and fits a shared 256-glyph font before building
the delta player. The clip has 250 source frames at 25 fps. Export
metadata declares the unchanged 75-frame entrance explicitly, so the font
studies and receipts do not claim that the old five-second sequence survived
the requested zoom and morph changes.

Rubik builds now default to `--codec literal`. Each delta repeats a skip count,
a literal length, and that many raw character bytes, in screen order, until
the cursor reaches 1,000 cells. Counts use unsigned LEB128; values above 127
take two bytes. Runs can cross screen pages. A fully unchanged frame is
`$E8,$07,$00`: skip 1,000 cells, write zero. The first blank screen remains
implicit. All 256 character codes are valid literal data.

The existing `precomputed/hybrid/delta.cjs` dynamic-programming encoder chooses
the runs and may include short unchanged gaps when that saves record headers.
The frozen film needs 35,118 bytes, versus 46,672 for sparse pairs, with the
same font and all 250 character screens unchanged. `--codec sparse` retains
the previous player for comparisons. The native builder itself still defaults
to sparse for compatibility with older callers. Measurement can use
`--codec=literal` to avoid imposing sparse's 255-changes-per-page limit on
legal literal runs.

The native literal player uses 38,710 meaningful loaded bytes, plus 1 KiB of
screen RAM, 1 KiB of color RAM, and 9 zero-page bytes. Its 35,118-byte movie
fits the original 40 KiB data arena with 5,842 bytes remaining. PAL VICE
verification matches all 250 images in both fields (500 actual fields total)
at 25.0623 fps, including the final hold and script counters. Mean render cost
is 3,503.84 cycles and the maximum is 18,669, compared with 3,425.61 and 18,477
for sparse. This is a storage reduction, with about 2.3% more mean decoder CPU
on this clip; playback still takes exactly two fields per image.
The published [raw-chunk player and receipts](results/rubik-raw/README.md)
include the PRG, actual native GIF, shared font and bitmap/native audits.

The previous sparse zoom clip needs 46,672 bytes. Larger films place whole
frame patches in unused RAM at `$0900`, `$1400`, and `$2800`, as well as the
original `$3000`–`$CFFF` arena. The existing frame-pointer table selects those
patches; the sparse format and scanout order stay unchanged. Pooled builds align
the source pointer and start Y at its former low byte, avoiding indexed-read
page penalties during the dense zoom. Total data capacity is
47,872 bytes, leaving 1,200 bytes. `sourceRegions` in the native manifest lists
every occupied range and its hash. Smaller films retain their original layout.
That sparse player, font, pointers and film use 49,716 meaningful loaded bytes,
plus 1 KiB of screen RAM, 1 KiB of color RAM, and 5 zero-page bytes.
Its aligned decoder is verified in PAL VICE at 25.0623 fps: all 250 images
match in both actual video fields (500 fields total), with a maximum render
cost of 18,477 cycles and the correct final hold. The earlier unaligned build
left previous-frame pixels in the bottom rows at frame 104; its failed proof
is retained separately in `../build/three-scene-rubik-zoom/c64/native-failed-scanout/`.

Edit `demo.mjs`. It exports `config` and `createScene(THREE)`, which returns a
normal Three.js scene, camera, and deterministic `update(time)` function.
The example starts with our black/white 14 × 7 checker sphere and its accepted
growing corkscrew entrance. It then morphs into a checker cube. The reference
material uses pure black and white without lighting or dithering. Positions,
lights, materials, and textures are ordinary Three.js objects.

From the repository root:

```sh
rtk proxy npm ci --prefix asm/sphere-polygons/font-v2/three-scene
rtk proxy node asm/sphere-polygons/font-v2/three-scene/build.cjs
```

The exporter uses Three.js WebGPURenderer and Dawn directly in Node, with a
Metal GPU backend on macOS. It renders to an offscreen texture and reads the
pixels back; no browser or local web server is involved. Three.js and Dawn
versions are pinned in the package lock. Building the PRG also requires
KickAssembler (`KICKASS` can override the executable path). GIF export requires
Python 3 and Pillow.

Outputs are in ignored `../build/three-scene-calibrated/`:

- `render/`: actual GPU RGBA frames, silhouette mask, and source metadata.
- `calibration/`: selected packed 1-bit film, threshold measurements, metadata,
  and bitmap-only previews.
- `pipeline.json`: confirms that character conversion has not run.

The default export is 160 × 100 logical pixels, each displayed as 2 × 2 C64
pixels. Each source frame is 2,000 bytes: rows run top to bottom, with the
leftmost pixel in bit 7 of each byte. Metadata declares dimensions, frame count,
and frame rate. Calibration tests all 256 thresholds against the actual GPU
pixels and selects the middle of a measured stable interval. The bitmap
checkpoint uses no dithering. RGBA and packed bitmap film are host assets;
neither is included in C64 playback memory.

After the bitmap checkpoint has been inspected, `build.cjs --characters` also
runs the existing character converter, delta measurement, native builder, and
character preview. Those later outputs are in `characters/`, `storage/`,
`native/`, and `preview/`. The C64 receives only the font, character deltas, and
playback commands. This flag is deliberately not part of the first-check command.

`bitmap-to-chars.cjs` is independent of Three.js. It also accepts 320 × 200
packed films (8,000 bytes per frame). It picks the existing glyph with the fewest
wrong pixels for each tile, recording every tile's error. It does not change the
font or impose a sphere silhouette. This makes loss from bitmap conversion
measurable separately from 1-bit quantization.

When metadata supplies `objectMaskFile`, the converter requires every white
glyph pixel to lie inside that packed silhouette mask. The Three exporter
provides this mask. This prevents partial edge characters from sticking out of
the object. A film without a mask retains unconstrained nearest-glyph matching;
silhouette diagnostics are then reported as unknown.

To convert a film from another renderer:

```sh
rtk proxy node asm/sphere-polygons/font-v2/bitmap-to-chars.cjs --frames /absolute/movie.frames --metadata /absolute/metadata.json --output /absolute/characters
```

For the current native player, use 25 fps, 2–255 unique frames, and a blank
first frame. The converter's `--prepend-blank` option can add that startup image
explicitly. The native build rejects a film exceeding its delta memory arena.
Frame complexity determines storage and playback cost; this pipeline does not
guarantee 25 fps for every source film.

The later character stage has its own focused checks:

```sh
rtk proxy node asm/sphere-polygons/font-v2/bitmap-to-chars.cjs --self-test
rtk proxy node asm/sphere-polygons/font-v2/verify-scene-preview.cjs asm/sphere-polygons/font-v2/build/three-scene-calibrated/characters asm/sphere-polygons/font-v2/build/three-scene-calibrated/preview/three-scene.html asm/sphere-polygons/font-v2/build/three-scene-calibrated/characters/playback.json
rtk proxy python3 asm/sphere-polygons/font-v2/verify-scene.py --root asm/sphere-polygons/font-v2/build/three-scene-calibrated/native
```

Native verification requires VICE and Pillow. Use `--vice /absolute/x64sc` to
override the workstation default. It compares both actual VIC fields for every
displayed image, including the final hold.

## Verified C64 result

The published [player.prg](results/player.prg) plays the five-second animation
at 25.0623 fps in PAL VICE. All 125 images and 250 actual video fields match
their character references, including the final hold. The [native receipt](results/native-verification.json)
records timing and hashes; [c64.gif](results/c64.gif) is captured from VICE.

Delta data occupies 14,042 bytes. Font, pointers, playback commands, player code
and data together use 16,128 meaningful loaded bytes, plus 1 KiB of screen RAM
and 5 zero-page bytes. PRG address gaps are reported separately.

The [bitmap calibration](results/bitmap-calibration.json) verifies zero bit
errors from the GPU image to the [1-bit film](results/bitmap.gif). Font fitting
is a separate approximation: the [character audit](results/character-audit.json)
measures 7.233% pixel error within the actual object mask, with zero white pixels
outside it. Every uniformly empty or filled interior tile is exact. The
[bitmap/C64 comparison](results/bitmap-vs-c64.png) shows the remaining edge and
junction differences. The existing 168-glyph font is unchanged.

Primary API references: [Three.js WebGPURenderer](https://threejs.org/manual/pages/webgpurenderer),
[Dawn for Node](https://github.com/dawn-gpu/node-webgpu).
