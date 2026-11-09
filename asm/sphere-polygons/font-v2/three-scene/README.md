# Three.js to C64 character film

The first checkpoint is Three.js scene → RGBA frames → calibrated 1-bit film.
Inspect this film before converting anything to characters. The build stops at
that checkpoint by default.

Calibration currently certifies the black/white checker reference. It rejects
gray or colored GPU output rather than guessing how to quantize new lighting
or shading. Those materials need their own reference checks before conversion.

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
