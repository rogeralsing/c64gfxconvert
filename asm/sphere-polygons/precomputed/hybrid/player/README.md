# Smooth checker-ball playback on PAL C64

The default [front-delta player](front-delta/README.md) writes lag-one patches directly to the visible `$0400` screen, at **50.124529 FPS** measured on PAL. It advances yaw by 0.9375° per displayed frame, with pitch fixed at 22° and roll at 12°. A physical revolution takes 384 displayed frames, about **7.66 seconds**. The checker pattern repeats after 60°, so only 64 frames need storage; this visible period lasts about **1.28 seconds**. The generator verifies that the endpoint exactly matches frame zero; the loop contains no duplicate endpoint. The same 72-face checker images and fixed font are preserved.

These are precomputed character frames using the existing fixed 256-glyph font. The C64 parses the HD64 stream and its closing delta into one ordinary 40×25 character screen. It performs no runtime projection or polygon rasterization. The animation and camera path are fixed by the movie. The legacy double-buffered delta player and three independent HC64 players remain available as comparisons.

## Run

From the repository root, with Node.js, KickAssembler and PAL VICE installed:

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/player/run.sh
```

`VICE` can select another VICE executable. `run.sh` prepares the smooth HC64/HD64 and closing-delta assets, builds the front-delta player, and launches VICE at 100% speed with warp disabled. Output is `front-delta/build/player.prg`. No Python or py65 dependency is required to build and play.

## Measured native results

All five implementations display the same smooth checker frames and use the same 2,048-byte font. The default reads the original 15,169-byte HD64 movie plus a 254-byte closing record, 15,423 source bytes in total. The legacy delta comparison uses the original HD64 alone; the independent baselines decode a 19,096-byte HC64 movie. PRG sizes include load addresses and gaps between occupied memory regions.

| Player | Movie bytes | Decoder code and lookup bytes | PRG bytes | Mean render cycles | Mean FPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Front delta, default](front-delta/README.md) | **15,423** | **803** | **26,688** | **13,548** | **50.124529** |
| [Legacy double-buffered delta](delta/README.md) | 15,169 | 898 | 26,434 | 24,671 | 25.062 |
| [Compact HC64](compact/README.md) | 19,096 | 620 | 33,433 | 78,529 | 11.196 |
| [Fused HC64](fused/README.md) | 19,096 | 16,387 | 48,729 | 13,538 | 50.125 |
| [Unrolled HC64](unrolled/README.md) | 19,096 | 19,700 | 46,233 | 12,453 | 50.125 |

Render cycles include VIC bus stalls. Presentation FPS also includes raster waiting. The front-delta mean includes the first timed frame-zero no-op; its 193 steady updates average 13,617.93 clocks and peak at 16,177. There is no full-screen copy or decoded-key cache. Writes begin at lower-border line 256 and proceed in ascending destination order; `frame_done` follows the complete visible scan.

The legacy delta row includes the full front-to-back synchronization copy, real packet-header parsing and delta writes. Its cached initial key waits one additional raster wrap outside the render interval to maintain the same two-field cadence as predictive images. The compact HC64 player alternates between four and five PAL fields per image; its median FPS is 12.530. The fused and unrolled HC64 players generate destination-specific code shared by every frame, rather than a separate routine for each image.

The [front scanout receipt](../results/front-delta/verification.json) verifies **194 consecutive actual VIC field images and three loop wraps**: all 12,416,000 active pixels and 194,000 screen bytes match exactly. It checks immutable font/source data and the fixed `$0400` screen. Presentation intervals range from 19,650 to 19,662 clocks, averaging 19,656.005. The separate [beam deadline proof](../results/front-delta/beam-report.json) traces 31,082 ordered stores, retaining at least 1,524 clocks of margin after conservative VIC-stall and start-jitter allowances.

The [legacy delta receipt](../results/player-delta/delta/verification.json) covers **194 consecutive frames and three loop wraps**, comparing 194,000 screen bytes exactly. It checks the fixed font and complete encoded HD64 stream throughout, and compares three actual VIC screenshots pixel for pixel. Render clocks range from 11,315 to 27,549; presentation intervals range from 39,302 to 39,320 clocks, averaging 39,312.031. The measured mean is 25.062251 FPS.

The [independent-HC64 receipts](../results/player-smooth/) cover 66 consecutive frames per baseline, including `63 → 0 → 1`, with 66,000 compared screen bytes, font checks and three exact VIC screenshots each. All measurements use PAL timing, speed 100%, and warp off. Music and interrupt workloads are disabled and have not been included.

To repeat native verification after preparing and building a variant:

```sh
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/player/front-delta/verify-pal.py \
  --frames 194 \
  --expected-program-sha256 196d57512765fb2902009b2573ab5cf40ec3cdbedeb85f94a4ee6e3a12b31277
```

The verifier captures every completed field, starts and closes only its own VICE process, and leaves other sessions untouched. It requires Pillow. The [measurement contract](CONTRACT.md) distinguishes this post-scan checkpoint from legacy double-buffered presentation. All PAL measurements use speed 100%, warp off and no music or IRQ workload; new workloads require their own timing proof.

## Delta compression with smaller steps

The same smooth 64-frame movie produces these complete serialized sizes, including headers and layout metadata:

| Reference | Bytes | Reduction versus independent HC64 |
| --- | ---: | ---: |
| Independent HC64 frames | 19,096 | — |
| Previous image, t−1 | 15,169 | 20.56% |
| Previous contents of alternating target screen, t−2 | 19,067 | 0.15% |

The t−1 stream contains one keyframe and 63 patches. About 91.7 characters change between successive images, excluding the initial keyframe. Both native delta players use those same t−1 packets. The visible screen already contains the correct reference in the front-delta player, so its CPU synchronization copy disappears. This is not a t−2 size gain. The legacy player copies the complete 1,024-byte front screen into the back screen before each patch; applying t−2 directly would avoid that synchronization but changes about 131.3 cells and provides almost no size saving here.

The default decodes the initial key once with display disabled. Later loop wraps apply an actual 252-byte closing patch with its two-byte length, adding 254 source bytes. Loaded code, font, combined source and BASIC startup total **18,287 bytes**. Runtime storage is **one 1,024-byte screen, 60 fill-scratch bytes and 30 zero-page bytes**, plus color RAM. No second screen or decoded-key cache is used. See the [front-delta memory map](front-delta/README.md).

The legacy player instead caches its decoded initial key and copies that cache at each loop wrap. Its loaded code, font, movie and BASIC startup remain 18,128 meaningful bytes before address gaps. Runtime storage adds a 1,024-byte key cache, 60-byte fill scratch and 30 zero-page bytes, alongside two 1,024-byte screen buffers and color RAM. See the [legacy delta memory map](delta/README.md).

The HD64 streams also pass three-loop host decoding checks. The t−2 alternative remains an offline size comparison; the current native implementation uses t−1. Run `rtk proxy node asm/sphere-polygons/precomputed/hybrid/player/motion-delta.cjs` to reproduce the comparison without changing the playback asset. Normal asset preparation automatically generates and verifies the HD64 stream used by the default player.

The earlier compression and code-generation studies use a different, faster three-axis trajectory. Their results are documented separately in the [format study](../README.md). `prepare-assets.cjs --motion=fast` reproduces that original 64-frame movie; invoking it without the flag restores the smooth default.

## Sources

- [motion.cjs](motion.cjs): floating-point offline angles, existing character rasterizer, exact loop assertion.
- [prepare-assets.cjs](prepare-assets.cjs): serialized HC64 assets and independent verification reference.
- [delta-assets.cjs](delta-assets.cjs): original HD64 asset, closing delta and host loop checks.
- [motion-delta.cjs](motion-delta.cjs): keyframe/patch size comparison and loop checks.
- [front-delta/main.asm](front-delta/main.asm): default t−1 decoder writing the visible screen, with no synchronization copy or key cache.
- [delta/main.asm](delta/main.asm): legacy double-buffered comparison and cached-key playback.
- [CONTRACT.md](CONTRACT.md): native player checkpoints and buffer rules.
- [front-delta/verify-pal.py](front-delta/verify-pal.py): every-field VIC scanout, native RAM and PAL cadence proof.
- [verify.py](verify.py): legacy/baseline native RAM, selected VIC screenshots and PAL cadence proof.
