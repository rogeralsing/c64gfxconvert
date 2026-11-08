# Mathematical charset sphere on a C64

This standalone PAL C64 experiment selects every screen character on the 6510. It uses a fixed, mathematically generated font of 256 patterns. It stores no rendered screen frames or animation deltas.

The sphere is 188 pixels in diameter, covers 476 character positions and has a 12 × 6 checker pattern. It spins around its own fixed axis, tilted by 22 degrees. This first native version deliberately fixes the camera, size and axis so their geometric fields can be prepared once.

## Build and run

The local toolchain uses Node.js, KickAssembler and VICE:

Native verification and profiling also require Python 3 with Pillow (`python3 -m pip install Pillow`).

```sh
./build.sh
./run.sh
```

The runnable file is `build/sphere.prg`. Start it on a PAL C64 or load it with VICE's PRG autostart. `run.sh` starts a separate emulator at normal speed and does not modify saved VICE settings.

- **F1:** switch between analytic tangent selection and nine sparse probes.
- **Space:** pause or resume rotation.

## What runs on the C64

For every active tile, the runtime adds the current rotation phase to the tile's base longitude. It then determines whether the tile is constant or crossed by a checker boundary. Direction and distance select a glyph through fixed tables. A second boundary selects an XOR combination. Difficult pole and silhouette tiles use nine analytic phase tests and a 512-byte lookup instead. Silhouette tiles then use a static safety remap that selects only glyphs entirely inside the sphere's exact circle. The displayed screen remains a map of fixed-font characters.

The fixed-axis rotation makes latitude independent of the frame. Longitude changes by one global phase. Static tables contain local geometry, tangent directions, scale categories and font choices. They contain neither screen-code frames nor pixel images.

Both 1,000-byte screen buffers are rendered in hires text mode with a fixed white foreground. The program switches buffers at PAL raster wrap after a complete render. It does not modify the font during animation.

## Verification

```sh
node --test polarity-regression.cjs
node --test silhouette-regression.cjs
python3 verify-c64.py
```

The verifier launches its own PAL VICE process and checks normal assembled code. At presentation checkpoints it compares all 1,000 screen bytes against `native-model.cjs`, verifies the 2,048-byte font and VIC configuration, and measures render and presentation cycles. Actual VIC screenshots are captured after scanout, then checked against the same visible screen. The verifier closes only its own emulator.

`assets/manifest.json` records the geometry, memory sizes and image error against independent ray–sphere intersections. `NATIVE-CONTRACT.md` describes the binary layout and native character-selection rules.

## Measured PAL results

The receipt in `build/verification-silhouette-fixed-final/verification.json` was measured in VICE 3.10 at 100% speed, with warp disabled and normal VIC bus stalls.

| Mode | Mean render cycles | PAL frames per presentation | Presentations per second |
| --- | ---: | ---: | ---: |
| Analytic tangent selection | 136,071 | 7 | 7.16 |
| Nine probes | 226,477 | 12 | 4.18 |

All 33 analytic frames and four probe frames matched the host model byte for byte. The analytic run included the complete phase cycle and verified that phase 124 advances to phase 0 with exactly the original screen. The font remained unchanged. Six native VIC screenshots also matched the visible screen's pixel reconstruction exactly.

`build/verification-silhouette-fixed-final/mode-0-native.gif` shows the complete native phase cycle at the measured timing. It reconstructs actual emulator screen RAM through the verified fixed charset, rather than rendering frames with the browser model.

The polarity regression compares analytic tiles with independent sphere intersections over all 128 phases. The filled side is taken before rounding the tangent offset: a small positive offset that rounds to zero must not invert the entire glyph. This checks geometric correctness independently of the native-to-model byte comparison.

The silhouette regression checks every lit pixel against the circle equation over all 128 phases in both modes. The emulator verifier independently applies the same geometric requirement to actual C64 screen RAM. No pixels may extend outside the circle. This catches stray stems from glyph pixels that the nine sparse probes do not sample.

## Memory

| Region | Purpose |
| --- | --- |
| `$0400–$07ff` | Screen buffer 1 |
| `$0c00–$0fff` | Screen buffer 2 |
| `$2000–$27ff` | Fixed mathematical font |
| `$3000–$331b` | 6510 code and mutable state |
| `$4000–$c1e1` | Geometry and lookup tables, including alignment |

Binary assets total 34,810 bytes, including the font and 10,210 bytes of safe silhouette remaps. Native code adds 796 bytes. The single-load PRG also includes gaps between these regions.

The generated model's mean image error is about 3.3% over 16 rotation phases. The nine-probe comparison mode gives about 4.2%. These are errors relative to the sphere's area. All lit pixels stay within the silhouette. Free camera motion or a changing rotation axis would require a more general runtime or rebuilding the geometric fields.
