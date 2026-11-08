# Retained merged sample-row spans

This experimental raster kernel rebuilds the union of white polygon spans on every frame, retains the previous union, and changes persistent character coverage only on the symmetric difference. It does not cache projected faces, consume host-generated spans, or store animation frames. The baseline geometry, mathematical font, lookup assets, and `resolve_screen` instructions remain unchanged.

The result is byte-exact but slower than the baseline. It is retained as a measured alternative, not selected for the live renderer.

## Method

The existing native edge DDA computes each white front-facing polygon's crossings. Each resulting sample-line interval is converted into ordered probe indices. This canonicalization ignores edge motion between sample positions. Intervals are inserted into a sorted list and overlapping or adjacent intervals are merged.

After all faces have contributed, each of the 75 sample rows is compared with its previous union. An endpoint sweep updates only probes where old and new coverage differ. Updates use OR or AND on the appropriate coverage bit. The current union then becomes the retained history for that row. Changing models requires no special reset because the new complete union replaces the previous one.

`delta_init` initializes empty interval counts and clears all 1,024 coverage bytes once. The shared builder inserts its call into native startup; the replay harness calls it once before the complete mixed sequence. Unoccupied endpoint slots are never read.

Each row has 36 interval slots. This also bounds transient insertion: the checker mesh has only 36 white faces, the football has 20, and each face contributes at most one interval to any sample row. The insertion path merges before growing its list and includes an overflow trap.

## Memory

| Range | Use |
| --- | --- |
| `$c000..$ca8b` | Current left endpoints, 75 × 36 bytes |
| `$ca8c..$cad6` | Current counts, 75 bytes |
| `$cad7..$cb21` | Previous counts, 75 bytes |
| `$cb22..$cdb2` | Union and delta helper code |
| `$e000..$ea8b` | Current right endpoints, 75 × 36 bytes |
| `$ea8c..$f517` | Previous left endpoints, 75 × 36 bytes |
| `$f518..$ffa3` | Previous right endpoints, 75 × 36 bytes |

The high RAM buffers use address labels rather than emitted data, so the PRG does not span I/O. Probe-index and address lookup tables are part of the code region below `$4000`. The font, screen buffers, projected vertices, I/O, vectors, and frozen static assets retain their parent addresses.

## Reproduction

From `asm/sphere-polygons`:

```sh
rtk proxy python3 optimization/common/build_variant.py optimization/retained-spans
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 optimization/common/benchmark.py --variant optimization/retained-spans --frames 32
```

The assembled NMOS 6502 replay checked 112 frames: 32 animated frames per model, orientation jumps and pauses, independent-axis motion, and repeated model switches. All 112,000 coverage bytes and 112,000 resolved screen bytes matched the frozen host model. The fixed font and static assets remained unchanged. Initialization cost 7,535 CPU cycles once.

| Mean CPU cycles | Baseline | Retained spans | Change |
| --- | ---: | ---: | ---: |
| Raster, all cases | 159,415.5 | 278,056.5 | +74.42% |
| Raster plus resolve, all cases | 185,991.4 | 304,485.4 | +63.71% |
| Raster, checker animation | 176,829.3 | 337,459.5 | +90.84% |
| Raster, football animation | 147,232.1 | 225,270.5 | +53.00% |

Union insertion, endpoint comparison, and history maintenance cost more than the avoided fill work. The resolve routine's small timing difference comes from instruction placement after substitution, not a different resolution algorithm.

These are replay instruction cycles. They exclude geometry, VIC bus stalls, IRQs, and presentation waiting, and must not be interpreted as native FPS. The exact report is generated at `build/benchmark.json`.
