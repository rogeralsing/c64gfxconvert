# Native PV64 player with faster span filling

This benchmark composes the existing PV64 vertex-movie player with the frozen
[`fast-fill/kernel.asm`](../fast-fill/kernel.asm). It uses the same 2,607-byte
movie, 62 decoded XY vertices, 36 white-face topology records, visibility bits,
font, edge DDA and strict character resolution as the
[baseline player](../player/README.md). Only the block from `raster_fill_span:`
up to `resolve_screen:` is replaced.

The resulting player measures **4.68117 FPS** on PAL, compared with 4.55678 FPS
for the baseline. It does not reach 25 FPS. The ordinary playback launcher
continues to use the [25 FPS HD64 delta player](../../player/README.md); this
geometry renderer is an explicit benchmark. See the
[geometry benchmark overview](../README.md) for the launcher and comparisons.

## Composition and fill change

[`build-fast.cjs`](../build-fast.cjs) reads the unchanged baseline `main.asm`
and `raster.asm`, replaces the span-function block with the frozen kernel, and
writes the composed sources under `build/src/`. Asset paths are resolved to the
shared immutable `vertices/build/assets/`. The generated `composition.json`
records hashes of the driver, baseline raster, selected kernel and PRG.

Build from the repository root:

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/fast-player/build.sh
```

The replacement reuses a coverage-row pointer across the face and avoids some
unneeded interior-mask setup. When all three sample spans in a character row
have matching left and right character columns, it combines their masks before
writing coverage. Boundary cells retain OR composition; a full interior cell
can safely receive `$ff` directly. Partial rows and changing endpoints use the
ordinary per-sample OR path. The
[kernel notes](../fast-fill/README.md) describe this rule and its separate
assembled-code proof.

The selected kernel adds 313 bytes: 461 bytes of replacement code/table versus
148 bytes for the original block. It adds no zero-page allocation, startup
state, framebuffer or extra glyph-resolution path. PV64 decoding, geometry
topology, visibility traversal and edge construction remain the baseline
algorithms. Strict limb remapping remains enabled.

## Correctness and native PAL verification

The integrated [host proof](build/host-smoke.json) passed 66 images including
`63 → 0 → 1`: 66,000 exact screen bytes, 66,000 exact coverage bytes and 8,184
exact XY bytes. The font, complete raster assets and movie remained unchanged.

The separate [PAL verification](build/verification/verification.json) passed
the same 66 displayed images, with all screen bytes exact, immutable font/source
checks and three pixel-exact actual VIC screenshots. It ran at PAL speed 100%
with warp disabled, and closed only its owned emulator process.

Measured mean presentation is **4.681171 FPS**. The mean presentation interval
is 210,470.4 PAL clocks. The median remains 4.55682 FPS: some images fit ten PAL
fields, while the others need eleven. There is no additional FPS cap.

The frozen PRG SHA-256 is
`5ebfa91747512764fea1359ed177e38ce68c69e95623eeca98486ff04121a229`.
The selected kernel SHA-256 is
`7c2fa7f0864360deb0c2b10479c0ee0a6663c56a573f1001f347b16382472a15`.
Both players use PV64 SHA-256
`dffbb663da9a15a85bac1bd57e9d1d9af7d499f237979140a1bdd039f56e936c`.

## Full-period PAL profile

The [64-image profile](build/pal-profile/profile.json) includes VIC bus stalls
in all stage clocks, and excludes startup and presentation waiting. The
baseline column uses its corresponding full-period profile.

| Work | Baseline mean clocks | Faster fill mean clocks | Faster fill milliseconds |
| --- | ---: | ---: | ---: |
| One visible quad's fill | 3,970.135 | **3,221.957** | **3.27** |
| One visible triangle's fill | 1,281.560 | 1,229.245 | 1.25 |
| All face filling per image | 55,330.984 | **46,038.953** | **46.73** |
| Complete render per image | 207,068.250 | **197,941.297** | **200.91** |

The integrated full-period fill stage is 16.79% cheaper, and the complete render
is 4.41% cheaper. Actual mean presentation improves 2.73%, because screen swaps
wait for raster boundaries. Quad measurements cover 768 visible calls; triangle
measurements cover 384 calls.

Edge construction still averages 109,240.80 PAL clocks per image, or 110.88 ms,
and remains the largest stage. Decode averages 4,974.80 clocks, coverage clear
7,002.70, resolution/remapping 28,377.06, and remaining driver work 2,306.98.
Small PAL-clock changes outside the replaced block reflect VIC stall alignment
and instruction placement; these algorithms were not optimized here. The
64-image profile and 66-image correctness run sample slightly different image
distributions, so their render means are reported separately.

## Footprint and state

Native code and included state/table bytes increase from 1,338 to **1,651**.
The raster/font assets remain **20,959 bytes**, including the 2,048-byte font,
and the movie remains **2,607 bytes**. Including the 13-byte BASIC startup,
meaningful loaded bytes total **25,230**. The actual PRG remains **36,144 bytes**:
the added code occupies existing padding before the fixed asset region.

Runtime storage is unchanged from the baseline: two 1,024-byte screens,
1,024-byte coverage, 128 allocated XY bytes, two 75-byte span arrays, five
visibility bytes, 432-byte expanded topology, and 59 reserved zero-page bytes.
No prepared character frames are imported into this renderer. The measurement
labels and per-face triangle/quad state follow the same
[PV64 contract](../CONTRACT.md).
