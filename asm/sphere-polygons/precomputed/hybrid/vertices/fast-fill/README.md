# Faster native character-span fill

`kernel.asm` is a drop-in replacement for the parent's `raster_fill_span` and
`raster_next_sample` block. Replace from `raster_fill_span:` up to, but excluding,
`resolve_screen:`. The existing `raster_face` enters the span routine once after
constructing all edge crossings. The replacement loops internally over the
remaining samples. All current zero-page labels, crossing arrays and mask-table
labels retain their existing meanings. There is no new zero-page allocation,
startup initialization, framebuffer, font, or screen-resolution path.

The kernel preserves white-polygon OR composition. It computes the coverage row
pointer once per face and advances it by 40 at each three-sample row boundary.
It skips unused full-interior-mask setup for a single-character span and keeps
the interior mask in X for the ordinary OR loop.

For a complete three-sample character row whose left endpoint columns match and
whose right endpoint columns match, the faster path combines the three disjoint
sample-mask groups before writing coverage. Left and right boundary masks still
OR with existing coverage. Every interior character receives `$ff` once. This
store is safe because OR with `$ff` is `$ff` regardless of earlier white-face
contributions. Partial top/bottom rows and changing endpoint columns retain the
ordinary per-sample OR path. Corners and shared polygon cells therefore retain
the same eight-bit coverage signature.

`compact-kernel.asm` keeps row-pointer reuse and the ordinary OR loop, without
the three-sample combination. It is a documented size/speed tradeoff; the root
integration selects the faster `kernel.asm`.

## Assembled CPU proof

Run from `asm/sphere-polygons`:

```sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 precomputed/hybrid/vertices/fast-fill/verify.py
```

The script copies the current parent main, geometry and static assets into its
own ignored build directories, assembles both baseline and replacement, and
runs NMOS 6502 instructions in py65. Inputs and expected coverage/screens come
from the existing independent host model trace. It checks every one of the
1,000 coverage bytes and resolved screen bytes on 56 checker cases, including
32 rotating poses, jumps, pauses and single-axis cases. The historical trace's
`model-switch` group is filtered to checker cases; this proof does not claim a
football or mixed-model test. Memory starts poisoned with `$a5`.

`build/verification.json` records source and program hashes, exact comparison
counts, PC-classified span CPU cycles, whole-raster CPU cycles, and per-case
results. Geometry, resolution and presentation waiting are outside the reported
raster timing. Span timing includes the complete dispatch, triplet checks,
fallback, pointer updates, boundary writes and interior writes. Native VIC bus
stalls and frame rate require the separate integrated PAL VICE measurement.

| 32-frame rotation mean | Original | Compact | Merged, selected |
| --- | ---: | ---: | ---: |
| Span CPU cycles | 54,456.5625 | 47,562.09375 | 46,813.625 |
| Whole raster CPU cycles | 176,829.3125 | 169,934.84375 | 169,186.375 |
| Span CPU change | — | −12.66% | −14.03% |
| Whole raster CPU change | — | −3.90% | −4.32% |
| Span code and added table bytes | 148 | 240 | 461 |
| Additional zero-page bytes | — | 0 | 0 |

The 75-byte full-mask table is included in both replacement sizes. The compact
result was measured on the same assembled checker trace before adding the
merged path; its source is preserved separately. The selected merged version
passed 56,000 coverage-byte and 56,000 screen-byte comparisons. Across all 56
cases its span CPU decreased 14.55% and whole-raster CPU decreased 4.50%.

The stronger merge has limited scope: common full interiors average 1.1465
characters across complete three-sample rows in this rotation trace. The merge
therefore gains only about 748 additional CPU cycles per frame over the compact
variant. Edge DDA construction is unchanged and remains outside this fill-only
optimization.

These measurements use the older native three-axis trace, not the separate
smooth PV64 movie. The root integration independently verifies that movie and
measures the assembled complete player in PAL VICE.

## Frozen identity

```text
kernel.asm SHA-256
7c2fa7f0864360deb0c2b10479c0ee0a6663c56a573f1001f347b16382472a15

compact-kernel.asm SHA-256
1fd16a2d04969338b556ed8316253dc8c58ff5d859400101f0136dc392a78245

selected replay PRG SHA-256
512045bb3629b725d1cdc817f31c4e66683990d9b35256c0eb85fdea20824a5e
```
