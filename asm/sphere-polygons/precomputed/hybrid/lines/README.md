# Precomputed mathematical character lines

This experiment implements reusable line drawing through the existing fixed font. A line stores its direction, fractional start phase and filled side. A shared mathematical table supplies the eight coverage probes for each affected character. There are no captured per-frame glyph strings in this line table and no runtime pixel bitmap or nearest-glyph search.

The default checker movie remains the [native HD64 delta player](../player/delta/README.md): it preserves the current image and presents at 25.062 FPS. The tested line formats do not beat its storage at the same fidelity.

## Callable C64 routine

The [native routine](native/README.md) provides `JSR draw_line`. The caller supplies the screen pointer, slope, phase, anchor, filled side, tie rule and finite major-axis interval. The routine advances phase once per character and writes the selected partial glyphs. Its footprint is:

| Item | Bytes |
| --- | ---: |
| Code, inputs and address constants | 367 |
| Shared Q8 mask and glyph tables | 1,888 |
| Zero-page workspace | 22 |

The existing 2,048-byte font belongs to the caller. The assembled conformance proof passed 6,400 calls and 6,400,000 character-buffer bytes against an independent integer line equation, including all 4,224 line descriptors from the 64 checker poses. It checks negative slopes, both axes and fill sides, equality, finite intervals, screen clipping, guard bytes and preservation of existing content outside the partial line.

This is an isolated-line primitive. Drawing separate boundary glyphs over one another does not combine corners or crossings. The complete checker format below composes coverage masks and records residual exceptions. A full GL64 movie player has not been implemented on the C64; the native routine's instruction counts are not movie FPS measurements.

## On/off fill plus finite lines

[geometry-lines.cjs](geometry-lines.cjs) implements the requested frame representation:

1. Decode compressed on/off fill into the fixed circle layout.
2. Read finite mathematical line descriptors and visit their candidate character cells.
3. Intersect boundaries within each white face, then combine white contributions where faces share a cell.
4. Resolve coverage through the fixed glyph lookup and apply literal exceptions for exact output.

Each finite line uses four bytes, including a three-byte direction/phase/side descriptor. The movie stores about 66 lines and 57.5 fill bytes per frame. The edge pass visits about 222 character cells and performs about 3,090 mask operations per frame. It avoids the full polygon baseline's repeated tests over all 475 circle cells.

The GL64 decoder reads the actual serialized lookup tables, face counts, row layout, frame lengths, fills, lines and exceptions. It reconstructs all 64 exact frames byte for byte. These are complete serialized sizes, with shared tables included and the common 2,048-byte font separate:

| Format for the same 64 frames | Bytes | Fidelity |
| --- | ---: | --- |
| HD64 character delta, current default | 15,169 | Exact |
| HC64 independent characters | 19,096 | Exact |
| GL64 Q8 on/off fill and finite lines | 36,814 | Exact, including exception patches |
| GL64 Q16 on/off fill and finite lines | 36,061 | Exact, including exception patches |

Short checker edges provide limited amortization: a line descriptor can cost as much as the few edge glyphs it replaces. Quantized direction and phase also differ from the existing polygon sampler at corners and boundaries. The exception bytes restore the original image, including its strict circle silhouette. Longer edges or a different error budget may change this tradeoff; this bounded experiment does not establish a global optimum.

Removing exceptions makes the raw line versions smaller but changes the image and introduces dots outside the circle. The optional existing circle-remap table removes those protrusions at an additional 9,728 shared bytes; the resulting approximate Q8 movie is 33,126 bytes. Neither approximate edge format replaces the current player.

## Other bounded comparisons

[dictionary-lines.cjs](dictionary-lines.cjs) stores reusable horizontal/vertical glyph motifs with start/phase commands and literal residual edges. Four motifs recur across many frames, but cover only 5.2% of the edge cells. Its exact movie is 18,969 bytes, saving 127 bytes over HC64 while remaining larger than HD64. See [notes-dictionary.md](notes-dictionary.md).

[parameter-delta.cjs](parameter-delta.cjs) applies the existing skip/literal/repeat codec to serialized line-program bytes in a persistent 1,000-byte workspace. This uses the full polygon half-plane baseline, rather than the finite edge pass. It includes shared line tables and verifies three complete loops. The exact on/off-fill variant is 28,722 bytes. Its uncorrected variants are fidelity experiments, not equivalent replacements for the current image or native movie benchmarks.

See [notes-geometry.md](notes-geometry.md) for the GL64 layout, all configurations, quality measurements and source hashes. Checked-in [results](../results/lines/) preserve the study reports and assembled native conformance receipt.

## Reproduce

From the repository root:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/lines/geometry-lines.cjs
rtk proxy node asm/sphere-polygons/precomputed/hybrid/lines/dictionary-lines.cjs
rtk proxy node asm/sphere-polygons/precomputed/hybrid/lines/parameter-delta.cjs
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/lines/native/build.sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 asm/sphere-polygons/precomputed/hybrid/lines/native/verify.py
```

The geometry study generates the mathematical tables consumed by the native build. Generated movies, references, tables and local reports stay under ignored `build/` directories.
