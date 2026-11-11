# Large checker sphere on C64

Exact character playback of the HTML preview settings: 256-character average
font, 20 × 10 checker cells, 290-pixel diameter and 65° tilt. Initial angle is
0.38 radians because the supplied settings screenshot did not specify a pose.
The 320 × 200 display clips 45 pixels at both the top and bottom of the sphere.

Build and verify from the repository root:

```sh
rtk proxy node asm/sphere-polygons/font-v2/c64-preview/generate.cjs
rtk proxy node asm/sphere-polygons/font-v2/c64-preview/build-player.cjs
rtk proxy python3 asm/sphere-polygons/font-v2/c64-preview/verify.py
```

The generator exports all 384 poses of a complete turn for measurements. The
standalone PRG uses the first 48 poses, a 44.0625° arc, and reverses smoothly at
each end. It reuses 47 reversible XOR patches; it does not jump between
unrelated endpoints or claim a shorter checker-pattern rotation is a full loop.

## Native result

PAL VICE 3.10 at 100% speed, warp disabled, verified 96 displayed poses and 190
actual VIC image fields. All 64,000 active pixels matched the fixed-font
reference in every checked field. Refresh on monitor break was disabled.
Both reversals were covered. New images arrived every two PAL fields:
**25.0623 fps**, conventionally 25 fps.

The C64 renders no geometry or bitmap reference during playback. It XORs sparse
character changes into a persistent hidden 1,000-byte screen at `$0800`, then
copies characters in ascending order to the visible screen at `$0400`.
The copy starts at raster line 256 and stays ahead of the next visible scan.
The 2,048-byte font at `$2000` remains unchanged.

| Resource | Bytes |
| --- | ---: |
| Font | 2,048 |
| Initial character screen | 1,000 |
| 47 reversible XOR patches | 35,674 |
| Code and patch pointers | 1,203 |
| Standalone PRG, including address gaps | 45,915 |

Measured work per new image: hidden updates 14,202–17,712 PAL clocks; visible
copy 10,003–10,004 clocks. This result covers this clip without music or other
interrupt workloads. The complete 384-pose turn needs 260,707 bytes with the
ordinary previous-frame packet codec, plus the 2,048-byte font; it does not fit
the standalone C64 memory budget.

Generated files live in ignored `build/`:

- `player.prg`: standalone native animation.
- `sphere-c64.gif`: animation made from actual VICE scanout PNGs.
- `sphere-c64.png`: first displayed pose, cropped from VICE scanout.
- `metadata.json`: settings, full-turn statistics and reference hashes.
- `player-build.json`: native clip format and memory layout; cadence is pending
  until the separate PAL verification has passed.
- `pal-proof/verification.json`: native timing and scanout evidence.

The first pose uses 185 glyphs. Font approximation differs from the mathematical
pixel reference by 1,201 pixels: 2.2657% of the visible sphere, or 1.8766% of the
entire screen. Pixel measurement and grid controls are diagnostics only.
