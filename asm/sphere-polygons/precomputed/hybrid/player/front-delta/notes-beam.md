# Single-front-screen PAL scanout proof

`verify-pal.py` checks the frozen front-delta player in its own minimized PAL
VICE instance, speed100%, warp disabled. It verifies **every completed visible
field**, rather than comparing only the final screen RAM or a few selected
screenshots. No other VICE process is controlled or closed.

The native ordering is part of the verification contract:

1. Startup decodes key0 with the display disabled.
2. The display is enabled at the lower-border256 boundary. The first timed
   frame0 update is a no-op, followed by a complete visible field.
3. Each later update starts at that lower border and writes the visible
   `$0400` screen in ascending address order.
4. `render_end` marks completion of packet writes. The player waits for the
   next lower-border256 boundary.
5. `frame_done` identifies the now fully scanned image, before its index
   advances or the next update begins. Later frame0 instances use the actual
   closing delta from frame63, rather than copying a cached key screen.

## Reproduction

After the native build is frozen, from the repository root:

```sh
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/player/front-delta/verify-pal.py \
  --frames 194 \
  --expected-program-sha256 196d57512765fb2902009b2573ab5cf40ec3cdbedeb85f94a4ee6e3a12b31277
```

The default source is `build/native-source.bin`, containing the complete HD64
movie and closing delta. Before VICE launches, its bytes must exactly match
the PRG's `animation..animation_end` block. The default reference/font are the
shared player's64 smooth checker screens and immutable mathematical font.
`--asset`, `--reference`, `--font`, `--motion-manifest`, `--variant`, `--output`
and `--vice` allow explicit inputs. `--help` does not launch VICE.

The source is15,423 bytes with SHA-256
`cff2690a827a9a91e50976bd795a37ae029774cec740faf14e0f2be2de102d1c`.
The program hash above identifies the original frozen front-screen build;
results must name the actual PRG hash if the program changes.

## What proves scanout

At every `frame_done`, the verifier requires raster256–257 and saves an actual
PNG from VICE's VIC canvas. It compares all320×200 pixels against the expected
frame rendered through the fixed font. There is no adjacent-frame or screenshot
latency fallback. The active-area crop origin must remain constant across all
fields. A screenshot mismatch fails even when screen RAM is already correct.

Render-start and completed-field intervals must each be exactly one PAL field,
within one raster line of boundary polling tolerance. This prevents the proof
from silently skipping an intermediate visible field. The194-image run covers
all64 poses and three loop wraps. The initial no-op is reported separately
from steady-state render costs.

The screenshot path was cross-checked against official VICE sources:

- [C64 machine screenshot dispatch](https://github.com/VICE-Team/svn-mirror/blob/main/vice/src/c64/c64.c)
  calls the VIC screenshot hook.
- [VIC-II screenshot state](https://github.com/VICE-Team/svn-mirror/blob/main/vice/src/viciisc/vicii.c)
  delegates its pixel image to the raster screenshot helper.
- [Raster screenshot helper](https://github.com/VICE-Team/svn-mirror/blob/main/vice/src/raster/raster.c)
  supplies the canvas draw buffer.
- [Normal screenshot conversion](https://github.com/VICE-Team/svn-mirror/blob/main/vice/src/screenshot.c)
  converts lines from that draw buffer. The normal PNG driver is used, rather
  than a native screen-memory export format.

`+refreshonbreak` disables forced monitor refresh so capture preserves the
already-rasterized image. The comparison therefore concerns the field's actual
pixel buffer, rather than an image synthesized by this verifier from current
RAM. The expected image is synthesized independently only as the comparison
target. Screenshots include the normal border; the entire active area is tested.

This observable proof does not depend on an assumed per-character fetch-cycle
formula. A separate instruction/store-deadline trace can quantify timing margin;
the PNG proof checks the resulting actual scanout for the frozen input.

## Other checked invariants

Every completed field also checks:

- Exact1,000-byte screen RAM at `$0400`, frame index and16-bit counter.
- VIC bank0, a single fixed `$0400` text screen, font `$2000`, normal40×25 hires
  text, fixed scroll, disabled sprites, white character color and black border
  and background.
- Immutable2,048-byte font and complete encoded HD64/closing-delta source.
- The unused `$0c00..$0fff` screen region unchanged at every boundary.
- Frozen program, symbols, ASM sources, reference and asset files unchanged
  during verification.

The last check on the unused screen is a boundary invariant, not an instruction
trace of all stores. The separate assembled-code proof owns the stronger
no-other-buffer-writes and ascending-store invariants. The actual scanout proof
does not infer them solely from a correct final screen.

Results are written under `build/pal-beam-proof/`: `verification.json`, one
PNG for every captured field, raw monitor/VICE logs and final memory snapshots.
Render clocks include VIC stalls; presentation clocks include raster waiting.
The helper closes only its own emulator and records its exit status.

This proof covers the tested fixed movie, font, PAL mode and interrupt-free
workload. It establishes observed field correctness, not an unmeasured guarantee
for arbitrary future animations or added IRQ/music workloads.

## Measured result

The frozen PRG identified above passed **194 consecutive actual visible
fields**, including all64 poses and three loop wraps. Every `render_start` and
every post-scan `frame_done` occurred on raster256. All194 PNGs matched the
expected active image exactly at the same crop origin `(32,35)`:

| Checked output | Amount |
| --- | ---: |
| Actual VIC PNG scanouts | 194 |
| Active scanout pixels | 12,416,000 |
| Exact screen-memory bytes | 194,000 |
| Immutable font bytes | 397,312 |
| Complete immutable encoded source | 15,423 bytes, checked every field |

The visible screen stayed at `$0400`; the unused `$0c00..$0fff` region remained
unchanged. The movie/font, source files and program hashes also remained
unchanged, and the verifier's owned VICE process exited successfully.

| PAL clock measurement | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| Steady render/update,193 timed updates | 11,449 | 13,617.93 | 16,177 |
| Completed-field interval,193 intervals | 19,650 | 19,656.005 | 19,662 |

The measured mean presentation rate is **50.12453 images/s**, with median
50.12454. Steady update time averages13.82 ms and peaks at16.42 ms, including
VIC stalls. Presentation includes the lower-border wait. The one initial timed
frame0 no-op takes15 clocks and is excluded from the steady render statistics;
the real closing-frame0 delta takes13,951 clocks at each of the three wraps.

This directly establishes pixel-exact, tear-free observed scanout for every
tested field of the frozen movie. The receipt is
`build/pal-beam-proof/verification.json`; its194 PNG files and raw monitor log
preserve the visual and timing evidence. No screenshot-latency adjustment or
adjacent-frame substitution was used.
