# Dithered three-axis star

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

The long-arm opaque star makes full compound rotations around all three axes:
360 degrees around X, 720 around Y and 360 around Z. The 240-frame loop lasts
9.6 seconds at nominal 25 fps, or about 9.576 seconds on the measured PAL
player. Orientation and angular velocity match at the loop boundary.

Continuous lighting gives the flat triangular facets different gray values.
Actual GPU pixels contain 159 object-gray levels, from 59 to 229 on the 0–255
sRGB scale. A light floor keeps shadowed arms visible. The exporter converts
these pixels to a fixed screen-aligned 4 × 4 Bayer pattern. All 17 uniform
Bayer densities already exist in the shared 256-character font.

| Measured item | Result |
| --- | ---: |
| PAL playback, including waits | 25.0623 fps |
| Stored images | 241: one blank plus 240 rotation frames |
| Displayed images verified in both fields | 721 |
| Exact visible PAL fields | 1,442 |
| Real loop wraps verified | 2 |
| Delta movie, including closure | 31,959 bytes |
| Font | 2,048 bytes |
| Other loaded code, tables and state | 1,531 bytes |
| Meaningful loaded content | 35,538 bytes |
| Working screen plus zero page | 1,033 bytes |
| Total ordinary main RAM used by those items | 36,571 bytes |
| PRG including address gaps and load address | 42,200 bytes |
| Unused in current 40,960-byte data arena | 9,001 bytes |

Color RAM uses 1,024 separate four-bit cells. The existing player and font are
unchanged; no music or IRQ workload is included in the timing. The initial
blank plays once, then the embedded script repeats the rotation indefinitely.

The existing builder can use another 6,144 bytes from three extra pools,
giving a 47,104-byte payload ceiling and up to 15,145 bytes of headroom here.
Whole frame patches remain contiguous, so pool fragmentation can prevent
using every byte. The current eight-bit frame format supports at most 255
stored images: only 14 additional image entries remain despite the free RAM.
At 25 fps those entries represent 0.56 seconds; loop repetition is unlimited.

Character fitting has 1.689% pixel error within the active image bounds and
4.276% within the actual object mask. No output white pixels spill outside
that mask. Errors concentrate along silhouettes and facet boundaries; the
210,933 entirely empty source tiles remain exact.

The GIF contains actual verified VICE screenshots cropped to the active
picture. All 240 decoded frames match those crops; 40 ms frame durations
approximate native PAL timing. The [scene source](demo-dithered-star.mjs) and
both imported sources are saved here with their [hash manifest](scene-sources.json).
Earlier scene results remain available separately.

Receipts: [native playback](native-verification.json), [grayscale and Bayer proof](bitmap-verification.json),
[actual GPU gray calibration](gpu-gray-calibration.json), [character matching](character-audit.json),
[assembled decoder](host-proof.json), and [summary](summary.json).
Build commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`679cb91a855c705c4f972782d59c6ee02af6272b1f280346128a4aee3973e28b`.
