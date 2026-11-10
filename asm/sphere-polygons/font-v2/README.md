# Bitmap-tested mathematical font

The font contains 256 fixed 8×8 glyphs, occupying 2,048 bytes. Shapes come from
integer half-planes and mathematical intersections/XORs of two boundaries.
No glyph is protected from replacement. Rotation, reflection and inversion
variants are selected together; partial glyphs with only one or two filled or
empty pixels are excluded.

`general-palette.json` is the selected font. `font.cjs` also exposes the earlier
230-shape palette and the first 256-shape junction palette for comparisons.
The C64 playback and storage experiments are separate from this HTML study.

The default HTML preview converts those existing glyphs to 4 × 4 logical dots,
each covering 2 × 2 screen pixels, then removes duplicates. The result contains
168 glyphs and occupies 1,344 bytes. It preserves the original glyph selection
and remaps its character codes. The original 8 × 8 palette remains available
in the preview's font selector. See [the scripted checker sphere](scenes/README.md)
for the current C64 animation and playback script.

From this directory:

```sh
rtk proxy node build.cjs
rtk proxy node build-preview.cjs --html-only
rtk proxy node build-analysis.cjs
rtk proxy node verify-matching.cjs
```

These commands need only Node.js and the checked-in files; no npm packages or
external preview directory are required. Open `build/font-v2.html` in a browser.
Its statistics link opens `build/font-v2-analysis.html`. The report includes
all glyph-use counts, per-case results, and original bitmap/selected glyph/XOR
examples for recurring tiles with more than three wrong pixels. Downloadable
JSON contains the complete census; displayed pattern lists are explicitly
labelled subsets. Glyph usage is never truncated in the report data.

`build/atlas.html` shows the font alone. Both HTML builders accept
`--output-dir DIRECTORY` to write their outputs elsewhere. `build-analysis.cjs`
also accepts positional baseline, selected-font, search, iteration-history and
final-test JSON paths, in that order. JSON inputs may be gzip-compressed.
Without positional paths it reads the published snapshots in `results/`.

The portable inputs are checked in under `preview/` and `legacy/`; the latter
preserves the original reference and matcher bytes used by older receipts.

To reproduce the coarsened-font proofs, first regenerate the 384-frame reference
and its deduplicated font, then build all three HTML variants:

```sh
rtk proxy node c64-preview/generate.cjs
rtk proxy node font4-dedupe.cjs
rtk proxy node build-preview.cjs
rtk proxy node verify-browser-font4.cjs
rtk proxy node verify-preview4.cjs
```

These checks compare all 256 glyph conversions and remapped character codes,
the 168-glyph browser/native font bytes, and the HTML controls and pixel views.

## Measurement and search

- Training: 36 combinations of tilt, radius and checker count, with 32 yaw poses
  each: 1,152 images.
- Iteration controls: 12 different combinations, 24 poses each: 288 images.
  These controls monitor successive iterations; they are not an untouched final
  benchmark.
- Final test: 16 further combinations and 384 images, reserved until font
  selection has finished.

Every case receives equal weight. Pixel error is divided by that case's actual
visible sphere area. Raw occurrence counts and equally weighted usage shares
are both retained, so large spheres cannot dominate font selection.

`general-study.cjs` renders the actual HTML matcher and independently recounts
every tile's error. `collect-constrained.cjs` collects training bitmap/mask pairs.
`optimize-general.cjs` compares a greedy palette with the current palette and
tests improving orbit replacements. This bounded search reports its stopping
condition; it does not prove a global optimum.

The corrected matcher in `matching/` chooses the nearest font glyph that fits
inside the circle against the original target bitmap. Geometry-only methods
continue using their character lookup and remap. The original HTML shader
sources remain available for reproducing earlier measurements.

To repeat training and iteration-control evaluation from this directory:

```sh
rtk proxy node general-study.cjs --collect --prefix replay --runtime-dir matching
rtk proxy node collect-constrained.cjs build/general-train-patterns.json general-palette.json build/replay-constrained.json
rtk proxy node optimize-general.cjs build/replay-constrained.json build/replay-candidate.json --seed general-palette.json --max-swaps 32
rtk proxy node general-study.cjs --palette build/replay-candidate.json --prefix replay-candidate --runtime-dir matching
```

The first command exports training targets only. The collector pairs those
targets with circle-admissibility masks. The optimizer never reads control or
final-test targets. Omit `--runtime-dir matching` when reproducing the legacy
matcher instead. Full studies and newly generated receipts go into ignored
`build/`; the selected font does not change automatically.

Published evidence is in `results/`, including complete compressed baseline and
selected censuses, search diagnostics, iteration history and final-test metrics.
The final test was evaluated after selection froze and was not fed back into
the optimizer. Any further search should reserve a new final-test sample.
