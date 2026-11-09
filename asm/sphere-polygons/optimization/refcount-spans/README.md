# Retained face spans with contribution counts

This bounded experiment removes sorted interval unions. Each white face retains one interval per native sample row. The current native edge DDA is still executed for every current white front face. For each face, the kernel subtracts its previous intervals and adds its current intervals only where their probe coverage differs.

The implementation is byte-exact, but its measured average cost is higher than the baseline. It is not selected for the live renderer. The experiment stops after the complete 32-frame-per-model replay and its additional mixed cases.

## Ownership and interval rules

White-face slots advance for every white face, including back-facing faces. The checker mesh has 36 such slots and the football has 20. Black faces do not consume slots. A disappearing or empty face therefore removes exactly its own previous contribution.

Contribution counts are bytes for the eight character probes, not display pixels. The counter domain covers 25 character columns, 25 character rows, and eight probes per character: 5,000 bytes. The fixed geometry's radius bound places all projected samples in character columns 7 through 31. Top and bottom sample rows use three probes per column; the middle sample row uses two.

An added probe increments its count and sets the coverage bit only on a zero-to-one transition. A removed probe decrements its count and clears the bit only when the count reaches zero. Overlapping white polygons cannot erase one another's coverage. Empty and disjoint intervals have explicit paths before overlap-band subtraction, and empty bands return without touching counters. Bounds and count-underflow guards trap invalid updates.

Both canonical history endpoints are stored, including empty intervals inside a face's sample-row bounds. History outside those bounds is never read. A model switch clears counts, bounds, and coverage inside the timed render entry. `delta_init` performs the initial reset once; the shared builder also calls it at native startup.

## Memory

| Range | Use |
| --- | --- |
| `$c000..$ca8b` | Left endpoint history, 36 × 75 bytes |
| `$ca8c..$caaf` | Previous first sample row, 36 bytes |
| `$cab0..$cad3` | Previous exclusive last sample row, 36 bytes |
| `$cad4` | Previous model |
| `$cb22..$cdf4` | Native history and counter helpers |
| `$e000..$f387` | Probe contribution counts, 5,000 bytes |
| `$f388..$fe13` | Right endpoint history, 36 × 75 bytes |

The high RAM buffers are address labels, so no emitted data crosses I/O. Geometry-independent probe and address tables remain below `$4000`. The baseline geometry, static assets, font, screen buffers, projected arrays, and I/O/vectors are unchanged. `resolve_screen` retains the baseline instructions.

## Reproduction and result

From `asm/sphere-polygons`:

```sh
rtk proxy python3 optimization/common/build_variant.py optimization/refcount-spans
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 optimization/common/benchmark.py --variant optimization/refcount-spans --frames 32
```

The replay checked 112 frames: 32 animated frames per model, jumps and pauses, independent-axis motion, and model switches. All 112,000 coverage bytes and 112,000 resolved screen bytes matched the frozen host model. The font and static assets remained unchanged. Initial reset cost 34,193 CPU cycles once; subsequent model-change resets are included in the timed results.

| Mean CPU cycles | Baseline | Refcount spans | Change |
| --- | ---: | ---: | ---: |
| Raster, all cases | 159,415.5 | 257,492.7 | +61.52% |
| Raster plus resolve, all cases | 185,991.4 | 283,921.6 | +52.65% |
| Raster, checker animation | 176,829.3 | 274,417.7 | +55.19% |
| Raster, football animation | 147,232.1 | 212,672.9 | +44.45% |

Avoiding sorting reduces the previous retained-union strategy's cost, but interval history, per-probe counters, transition handling, and model resets still cost more than the baseline fill work. The unchanged resolve routine has a small instruction-placement timing difference.

The generated exact report is `build/benchmark.json`. These NMOS 6502 replay cycles exclude geometry, VIC stalls, IRQs, and presentation waiting. They are not measured native FPS. No VICE session was started for this rejected candidate.
