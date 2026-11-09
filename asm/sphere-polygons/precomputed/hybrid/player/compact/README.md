# Compact independent-frame HC64 player

This is a native PAL C64 reference player for the existing 64-frame checker movie. It decodes the actual serialized independent-frame asset. It does not use pre-expanded host screen frames, geometry, delta frames, or a fixed playback-rate limiter.

See the [shared playback experiment](../README.md) for asset preparation and the comparison between players. The current compact HC64 asset is 19,096 bytes. Its smooth loop advances yaw by 0.9375 degrees per frame with fixed pitch 22 degrees and roll 12 degrees. Sixty-four frames cover the checker's 60-degree pattern symmetry, so the loop closes without a jump. The maximum edge-glyph count is 187.

The file header supplies 25 row spans. Each frame contains its two 16-bit payload lengths, PackBits-compressed fill bits, and a raw 60-byte edge-presence map followed by exact edge glyphs. The player expands 475 fill cells in the hidden screen, then patches edge glyphs in a second pass. Cells outside the fixed layout are cleared once in both screen buffers.

All per-frame parsing and decoding is inside `render_start..render_end`. The player then waits for PAL raster wrap, flips `$d018`, and reaches `frame_done`. At that checkpoint `frame_index` identifies the currently displayed frame; the increment and 63-to-0 loop reset occur afterward. No VICE process is started by the build script.

## Build

The coordinator supplies these immutable shared inputs in `../build/assets/`:

- `checker-64.hc64`: fill codec 1, edge codec 5, circle layout, 64 frames.
- `font.bin`: the fixed 2,048-byte mathematical font.

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/player/compact/build.sh
```

The PRG, `main.sym`, `main.vs`, and debug map are written under this directory's ignored `build/` folder.

## RAM

| Range | Use |
| --- | --- |
| `$02..$1e` | Decoder pointers and counters |
| `$0400..$07ff`, `$0c00..$0fff` | Alternating character screens |
| `$1000..$103b` | 60 decoded fill bytes |
| `$2000..$27ff` | Fixed font |
| `$3000..$326b` | Compact player code and state, 620 bytes |
| `$4000..$8a97` | Actual serialized movie, 19,096 bytes |

The player disables IRQ sources, uses white Color RAM, and leaves the font unchanged. Playback speed must be measured from this assembled implementation; compression ratios alone imply no FPS result.

The current single-load PRG is 33,433 bytes including its load address and gaps between regions.

## Current PAL result

`build/verification/verification.json` records the smooth-motion program in PAL VICE at 100% speed, warp disabled, with VIC bus stalls included. It verifies 66 presentations, including the complete 64-frame cycle and the `63 → 0 → 1` wrap. All 66,000 screen bytes match, the font remains unchanged, and three actual VIC screenshots match the visible screen.

Mean render time is **78,529.14 clocks**. Presentation takes a mixture of four and five PAL fields: **11.196 mean FPS**, with **12.530 median FPS**. The cadence includes raster waiting and has no extra playback-rate limiter. There is no music or IRQ workload.

Verified current PRG SHA256: `7b5a722b8ea8b1cd333d6430c1bdf4d5681b1e9267e771edc314c0b67669a9fe`.
