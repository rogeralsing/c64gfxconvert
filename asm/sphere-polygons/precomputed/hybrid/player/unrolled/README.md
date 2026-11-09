# Unrolled HC64 PAL player

This runnable C64 player decodes the same compact 19,096-byte, 64-frame checker
animation as the compact player. It uses the original mathematical font and
two ordinary hires text screens. It performs no runtime geometry calculation.

See the [shared playback experiment](../README.md) for asset preparation and the
player comparison. The current smooth loop advances yaw by 0.9375 degrees per
frame at fixed pitch 22 degrees and roll 12 degrees. Sixty-four frames span the
checker's 60-degree pattern symmetry, closing the loop without a jump.

Every frame reads its actual four-byte HC64 fill/edge lengths, expands PackBits
to 60 fill bytes, copies the 60-byte raw edge map, then writes all 475 selected
characters and overlays each exact edge glyph from the serialized source.
There is no previous-frame dependency and no prepared character screen in code.
Both complete screen buffers are initialized black. Positions outside the fixed
circle layout stay black in both buffers.

The speed/space tradeoff is two generated absolute-destination routines, one
for each screen, plus eight 256-byte lookup pages. Each fill byte selects eight
0/15 glyphs through those mathematical pages. Each edge-map byte controls eight
unrolled tests; set bits consume the next raw glyph with `(glyph_ptr),Y`.
The asset's maximum edge count is 187, so the byte-sized glyph index is safe.

The generator derives destination addresses **only from the stored 50-byte row
metadata**. It validates the packet bounds and source format, without embedding
per-frame content in native instructions. The serialized HC64 file is imported
unchanged, including its header and metadata. There is no extra frame-offset
table: native code follows the actual sequential frame lengths.

## Build and verification

From the repository root, after the shared assets have been prepared:

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/player/unrolled/build.sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 asm/sphere-polygons/precomputed/hybrid/player/unrolled/verify-host.py
```

The runnable output is `build/player.prg`, with `build/main.sym` and
`build/main.vs`. The player disables CIA/VIC interrupts, configures VIC bank0,
font `$2000`, white color RAM, and screens `$0400/$0c00`. It swaps only at a PAL
raster wrap after rendering finishes. There is no additional playback cap.
`frame_done` identifies the just-presented frame before its index advances.
After frame63, the real encoded-frame pointer returns to the first packet.

The current PAL VICE receipt is `build/verification/verification.json`. At 100%
speed with warp disabled, it verifies 66 presentations, including the complete
64-frame cycle and the `63 → 0 → 1` wrap. All 66,000 screen bytes match the
independent shared reference, the font remains unchanged, and three actual VIC
screenshots match the visible screen.

Mean render time is **12,453.02 clocks**, with a **12,283–12,606-clock range**,
including VIC bus stalls. Every presentation fits one PAL field:
**50.1245 median FPS**. Presentation timing includes raster waiting. There is
no music or IRQ workload.

Verified current PRG SHA256:
`c3944f4ee6230fb1b659262131f1ee7fb0a3a67ded49f3133855291c4e0ff578`.
Shared current HC64 SHA256:
`13331a70268de1fe4e5e673c40c59f1d48fb022c89303dd3d4e9062b809edc3d`.

Earlier py65 numbers in `build/host-verification.json` belong to the original
fast three-axis asset prepared with `node prepare-assets.cjs --motion=fast`.
Run that asset command from the parent player directory. The earlier figures
are historical CPU-only evidence, not the current smooth-motion PAL
measurement. Rebuild and verify separately when selecting that alternate motion.

## Native footprint

All emitted bytes are below `$c000`; the PRG never loads through I/O or hardware
vectors. Source/generation metadata is in `build/generation.json`.

| Region | Address | Bytes |
| --- | --- | ---: |
| BASIC startup | `$0801..$080d` | 13 |
| Eight fill-bit lookup pages | `$1000..$17ff` | 2,048 |
| Scratch, explicitly overwritten every frame | `$1800..$183b`, `$1840..$187b` | 120 |
| Immutable font | `$2000..$27ff` | 2,048 |
| Startup, parsing, decoding, flip and wait core | `$2800..$2b07` | 776 |
| Two unrolled destination routines | `$3000..$71eb` | 16,876 |
| Unchanged HC64 file | `$7200..$bc97` | 19,096 |
| Zero-page working state | `$02..$10` | 15 |

The file is 46,233 bytes including its two-byte load address and zero padding
between loaded regions. The main tradeoff versus a compact decoder is the
16,876-byte layout code and 2,048-byte lookup table, rather than a larger or
less compressed animation payload.
