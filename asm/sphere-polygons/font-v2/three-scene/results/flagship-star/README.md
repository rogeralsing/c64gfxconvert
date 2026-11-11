# Flagship star with a verified symmetry loop

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

The six-tip stellated-cube star turns around its true model-space `(1,1,1)`
three-fold symmetry axis. Each period advances the unwrapped spin by 120
degrees. `base * periodicWobble * diagonalSpin` makes the final transform equal
to the first followed by a symmetry of the whole mesh. All 14 vertices and
24 triangular facets permute exactly, including their computed lighting.
The driver keeps advancing through the endpoints; it does not reset before
the GPU closure check. Position and angular velocity remain continuous.

The shape retains cube half-extent 8.5, tip distance 54 and six declared gray
levels (0, 51, 102, 153, 204, 255). A fixed world light shades each facet;
ordered 4 × 4 Bayer conversion then produces the 1-bit bitmap. The camera's
square ±53 frustum fits the corrected trajectory while retaining the 1.6×
horizontal anamorphic projection. GPU masks have no border pixels, and an
independent 960-pose sweep leaves at least 0.692 world units of margin.
The opaque geometry fits within 272 × 196 physical pixels.

| Measured item | Result |
| --- | ---: |
| PAL playback including waits | 25.06226 fps |
| Stored frames | 97: blank plus 96 rotation frames |
| Nominal / measured symmetry period | 3.84 / 3.83046 seconds |
| Displayed images checked in both fields | 289 |
| Exact visible PAL fields | 578 |
| Real loop wraps checked | 2 |
| Delta movie including closing patch | 20,419 bytes |
| Fixed font | 2,048 bytes |
| Meaningful loaded code, tables, font and data | 23,710 bytes |
| Screen plus zero-page working memory | 1,033 bytes |
| Ordinary main RAM for those items | 24,743 bytes |
| PRG including padding and load address | 30,660 bytes |
| Free in current 40,960-byte data arena | 20,541 bytes |

Separate color RAM uses 1,024 four-bit cells. The initial blank plays once,
then the embedded script repeats frames 1–96 indefinitely. A complete 360-degree
spin occupies three symmetry periods: 288 frames, nominally 11.52 seconds.
No music or IRQ workload is included in the measured playback.

The archived experimental 256-glyph font is byte-identical to the preceding
flagship experiment. It predates the content-study raster-reader correction;
this release makes no optimality claim for that font. Its measured error is
2.279% within active image bounds and 1.471% over the whole screen. No white
pixels spill outside the object mask. All 3,646 entirely filled and 72,669
entirely empty source tiles remain exact.

The preview GIF contains the actual verified VICE screenshots cropped to the
active picture. All 96 decoded images match their screenshot crops; 40 ms
GIF frame times approximate native PAL timing. The scene is saved here as
[standalone source](demo-flagship-star.mjs), with a [source hash manifest](source-manifest.json).

Receipts: [native playback](native-verification.json), [native build](native-build.json),
[unwrapped GPU symmetry and Bayer proof](bitmap-verification.json),
[960-pose geometric fit](analytic-fit.json), [character matching](character-audit.json),
[assembled decoder](host-proof.json), [metadata compatibility builds](metadata-compatibility.json),
and [summary](summary.json). Commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`32be36dcb381f22e21aca2e4bdf41db752ec3c3c96dfbd56d5c87c7f3c2fd6b2`.
