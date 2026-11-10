# Large-sphere measured results

290-pixel diameter, 20 × 10 checker cells, 65° tilt, fixed selected 256-glyph font. The existing camera-axis motion uses 384 poses per 360° turn, 0.9375° per pose.

## Exact HTML images

| Variant | PAL FPS | Stored frames | Source bytes | Estimated seconds | Rotation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sparse character delta, direct front screen | 50.125 | 55 | 40,390 | 1.10 | 50.63° |
| Sparse character delta, hidden screen plus copy | 25.062 | 55 | 40,390 | 2.19 | 50.63° |
| Packet character delta, hidden screen plus copy | 16.708 | 62 | 40,430 | 3.71 | 57.19° |

## Identical geometry images

| Variant | PAL FPS | Stored frames | Source bytes | Estimated seconds | Rotation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sparse character delta, direct front screen | 50.125 | 74 | 40,850 | 1.48 | 68.44° |
| Sparse character delta, hidden screen plus copy | 25.062 | 74 | 40,850 | 2.95 | 68.44° |
| Raw face spans, individual sample lines | 4.335 | 11 | 23,506 | 2.54 | 9.38° |
| Raw face spans, combined character rows | 4.480 | 11 | 23,506 | 2.46 | 9.38° |
| Compressed face spans, combined character rows | 4.583 | 28 | 23,579 | 6.11 | 25.31° |
| Precomputed individual edge paths | 2.959 | 16 | 23,324 | 5.41 | 14.06° |
| Raw projected XY, runtime edge crossings | 1.240 | 26 | 23,815 | 20.98 | 23.44° |
| Compressed projected XY, runtime edge crossings | 1.186 | 217 | 24,000 | 182.91 | 202.50° |

Geometry character images differ from HTML because the renderer uses flat faces and an eight-probe glyph lookup. The geometry delta rows provide the image-identical comparison with native filling.

Character players have 40,960 source bytes at $3000–$cfff. Geometry players have 24,064 source bytes at $7200–$cfff after 12,612 bytes of glyph/mask/silhouette tables. Font, code, first-image/XY state and working buffers are separately accounted in results.json. Unused address gaps have not been repacked; stored-frame counts describe these tested layouts.

Geometry capacity is the largest actual encoded prefix that fits the arena, not a mean-byte estimate. Geometry FPS comes from native rendering of 16 poses spread across the full turn; each pose's source is loaded while emulation is paused. Native XY-delta decoding, edge preparation, filling and glyph resolution are included. Geometry full-prefix playback has not been measured. Durations are frame-count/FPS estimates.

All accepted cases passed actual VIC scanout checks with refresh-on-break disabled. The packet decoder writing directly to the front screen is rejected: an intermediate field contains both old and new pixels, despite a 25 FPS final-image cadence.

[Machine-readable results](results.json) · [CSV](results.csv)
