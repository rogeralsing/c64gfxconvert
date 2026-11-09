# Smooth checker-ball playback on PAL C64

The default movie advances yaw by 0.9375° per displayed frame, with pitch fixed at 22° and roll at 12°. Both optimized players present one image per PAL field: approximately 50.125 FPS. A physical revolution takes 384 displayed frames, about 7.66 seconds. The checker pattern repeats after 60°, so only 64 frames need storage. The generator verifies that the 60° endpoint exactly matches frame zero; the loop contains no duplicate endpoint.

These are precomputed character frames using the existing fixed 256-glyph font. The C64 parses and decodes the compressed movie into ordinary 40×25 character screens. It performs no runtime projection or polygon rasterization. The animation and camera path are fixed by the movie.

## Run

From the repository root, with Node.js, KickAssembler and PAL VICE installed:

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/player/run.sh
```

`VICE` can select another VICE executable. `run.sh` prepares the smooth movie, builds the unrolled player, and launches VICE at 100% speed with warp disabled. Output is `unrolled/build/player.prg`. No Python or py65 dependency is required to build and play.

## Measured native results

All three implementations decode the same 19,096-byte HC64 movie and use the same 2,048-byte font. PRG sizes include load addresses and gaps between occupied memory regions.

| Player | Decoder code and lookup bytes | PRG bytes | Mean render cycles | Mean FPS |
| --- | ---: | ---: | ---: | ---: |
| [Compact](compact/README.md) | 620 | 33,433 | 78,529 | 11.196 |
| [Fused](fused/README.md) | 16,387 | 48,729 | 13,538 | 50.125 |
| [Unrolled](unrolled/README.md) | 19,700 | 46,233 | 12,453 | 50.125 |

Render cycles include VIC bus stalls. Presentation FPS also includes raster waiting. The compact player alternates between four and five PAL fields per image; its median FPS is 12.530. Its smaller decoder trades speed for memory. The optimized players generate destination-specific code shared by every frame, rather than a separate routine for each image.

The [checked-in receipts](../results/player-smooth/) cover 66 consecutive frames per implementation, including `63 → 0 → 1`. Each run compares 66,000 screen bytes, checks the fixed font throughout, and compares three actual VIC screenshots pixel for pixel. VICE uses PAL timing, speed 100%, and warp off. The test disables music and interrupts; those workloads have not been included.

To repeat native verification after preparing and building a variant:

```sh
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/player/verify.py --variant asm/sphere-polygons/precomputed/hybrid/player/unrolled
```

The verifier starts and closes its own VICE process. It leaves other sessions untouched. It requires Pillow and NumPy.

## Delta compression with smaller steps

The same smooth 64-frame movie produces these complete serialized sizes, including headers and layout metadata:

| Reference | Bytes | Reduction versus independent HC64 |
| --- | ---: | ---: |
| Independent HC64 frames | 19,096 | — |
| Previous image, t−1 | 15,169 | 20.56% |
| Previous contents of alternating target screen, t−2 | 19,067 | 0.15% |

The t−1 stream contains one keyframe and 63 patches. About 91.7 characters change between successive images, excluding the initial keyframe. A persistent canonical previous image is required; alternating display buffers need copying or equivalent synchronization. Applying t−2 directly avoids that synchronization, but changes about 131.3 cells and provides almost no size saving here.

The current native players use independent HC64 frames. The HD64 delta streams have passed three-loop host decoding checks; native delta FPS has not been measured. Run `rtk proxy node asm/sphere-polygons/precomputed/hybrid/player/motion-delta.cjs` to reproduce the comparison without changing the playback asset.

The earlier compression and code-generation studies use a different, faster three-axis trajectory. Their results are documented separately in the [format study](../README.md). `prepare-assets.cjs --motion=fast` reproduces that original 64-frame movie; invoking it without the flag restores the smooth default.

## Sources

- [motion.cjs](motion.cjs): floating-point offline angles, existing character rasterizer, exact loop assertion.
- [prepare-assets.cjs](prepare-assets.cjs): serialized HC64 assets and independent verification reference.
- [motion-delta.cjs](motion-delta.cjs): keyframe/patch size comparison and loop checks.
- [CONTRACT.md](CONTRACT.md): native player checkpoints and buffer rules.
- [verify.py](verify.py): native RAM, VIC screenshots and PAL cadence proof.
