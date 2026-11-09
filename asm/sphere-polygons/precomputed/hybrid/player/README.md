# Smooth checker-ball playback on PAL C64

The default delta player advances yaw by 0.9375° per displayed frame, with pitch fixed at 22° and roll at 12°. It presents one image every two PAL fields: **25.062 FPS** measured. A physical revolution takes 384 displayed frames, about **15.32 seconds**. The checker pattern repeats after 60°, so only 64 frames need storage; this visible period lasts about **2.55 seconds**. The generator verifies that the 60° endpoint exactly matches frame zero; the loop contains no duplicate endpoint.

These are precomputed character frames using the existing fixed 256-glyph font. The C64 parses the HD64 keyframe/delta stream into ordinary 40×25 character screens. It performs no runtime projection or polygon rasterization. The animation and camera path are fixed by the movie. The three independent HC64 players remain available as size and speed baselines.

## Run

From the repository root, with Node.js, KickAssembler and PAL VICE installed:

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/player/run.sh
```

`VICE` can select another VICE executable. `run.sh` prepares the smooth HC64 and HD64 assets, builds the delta player, and launches VICE at 100% speed with warp disabled. Output is `delta/build/player.prg`. No Python or py65 dependency is required to build and play.

## Measured native results

All four implementations display the same smooth checker frames and use the same 2,048-byte font. The default delta player decodes a 15,169-byte HD64 movie; the independent baselines decode a 19,096-byte HC64 movie. PRG sizes include load addresses and gaps between occupied memory regions.

| Player | Movie bytes | Decoder code and lookup bytes | PRG bytes | Mean render cycles | Mean FPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| [Delta, default](delta/README.md) | **15,169** | **898** | **26,434** | 24,671 | **25.062** |
| [Compact HC64](compact/README.md) | 19,096 | 620 | 33,433 | 78,529 | 11.196 |
| [Fused HC64](fused/README.md) | 19,096 | 16,387 | 48,729 | 13,538 | 50.125 |
| [Unrolled HC64](unrolled/README.md) | 19,096 | 19,700 | 46,233 | 12,453 | 50.125 |

Render cycles include VIC bus stalls. Presentation FPS also includes raster waiting. Delta rendering includes the full front-to-back synchronization copy, real packet-header parsing and delta writes. Its cached initial key waits one additional raster wrap outside the render interval to maintain the same two-field cadence as predictive images. The compact HC64 player alternates between four and five PAL fields per image; its median FPS is 12.530. The fused and unrolled HC64 players generate destination-specific code shared by every frame, rather than a separate routine for each image.

The [delta receipt](../results/player-delta/delta/verification.json) covers **194 consecutive frames and three loop wraps**, comparing 194,000 screen bytes exactly. It checks the fixed font and complete encoded HD64 stream throughout, and compares three actual VIC screenshots pixel for pixel. Render clocks range from 11,315 to 27,549; presentation intervals range from 39,302 to 39,320 clocks, averaging 39,312.031. The measured mean is 25.062251 FPS.

The [independent-HC64 receipts](../results/player-smooth/) cover 66 consecutive frames per baseline, including `63 → 0 → 1`, with 66,000 compared screen bytes, font checks and three exact VIC screenshots each. All measurements use PAL timing, speed 100%, and warp off. Music and interrupt workloads are disabled and have not been included.

To repeat native verification after preparing and building a variant:

```sh
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/player/verify.py \
  --variant asm/sphere-polygons/precomputed/hybrid/player/delta \
  --frames 194 \
  --asset asm/sphere-polygons/precomputed/hybrid/player/build/assets/checker-64-smooth-delta1-lag1.hd64
```

The verifier starts and closes its own VICE process. It leaves other sessions untouched. It requires Pillow and NumPy.

## Delta compression with smaller steps

The same smooth 64-frame movie produces these complete serialized sizes, including headers and layout metadata:

| Reference | Bytes | Reduction versus independent HC64 |
| --- | ---: | ---: |
| Independent HC64 frames | 19,096 | — |
| Previous image, t−1 | 15,169 | 20.56% |
| Previous contents of alternating target screen, t−2 | 19,067 | 0.15% |

The t−1 stream contains one keyframe and 63 patches. About 91.7 characters change between successive images, excluding the initial keyframe. The native delta player copies the complete 1,024-byte front screen into the back screen before applying each patch, explicitly providing the immediately preceding image. Applying t−2 directly avoids that synchronization, but changes about 131.3 cells and provides almost no size saving here.

The initial key is decoded from the real HD64 stream once at startup and cached; the timed frame-zero path copies that cache at each loop wrap. The player's loaded code, font, movie and BASIC startup total 18,128 meaningful bytes before address gaps. Runtime storage adds a 1,024-byte key cache, 60-byte fill scratch and 30 zero-page bytes, alongside the two 1,024-byte screen buffers and color RAM. See the [delta memory map](delta/README.md) for exact addresses.

The HD64 streams also pass three-loop host decoding checks. The t−2 alternative remains an offline size comparison; the current native implementation uses t−1. Run `rtk proxy node asm/sphere-polygons/precomputed/hybrid/player/motion-delta.cjs` to reproduce the comparison without changing the playback asset. Normal asset preparation automatically generates and verifies the HD64 stream used by the default player.

The earlier compression and code-generation studies use a different, faster three-axis trajectory. Their results are documented separately in the [format study](../README.md). `prepare-assets.cjs --motion=fast` reproduces that original 64-frame movie; invoking it without the flag restores the smooth default.

## Sources

- [motion.cjs](motion.cjs): floating-point offline angles, existing character rasterizer, exact loop assertion.
- [prepare-assets.cjs](prepare-assets.cjs): serialized HC64 assets and independent verification reference.
- [delta-assets.cjs](delta-assets.cjs): serialized default HD64 asset and three-loop checks.
- [motion-delta.cjs](motion-delta.cjs): keyframe/patch size comparison and loop checks.
- [delta/main.asm](delta/main.asm): compact native t−1 decoder, synchronization copy and cached-key playback.
- [CONTRACT.md](CONTRACT.md): native player checkpoints and buffer rules.
- [verify.py](verify.py): native RAM, VIC screenshots and PAL cadence proof.
