# Normalized edge-curve cache

Rejected by the assembled comparison: raster CPU increased **3.443%** over the
112-case mixed trace (`--frames 32`). The football animation increased 1.781%
and checker animation increased 8.960%. Pauses and repeated jumps can benefit,
but do not offset miss construction and lookup costs in normal motion.

The cache has 64 directly mapped entries. Its exact key is absolute `dx`, `dy`,
the direction of the ordered edge, and `y0 mod 8`. A hit translates the stored
relative curve by the live `x0`, then updates the current face's min/max spans.
A miss executes the original rational DDA and stores its generated crossings;
all lookup, write and generation work executes inside `render_polygons`.
Oversized curves use scratch and are never published. No host edge curves,
source bitmap, prepared animation, or runtime font matching is used.

Private retained state is **1,920 bytes**, `$e000..$e77f`, including 128 bytes of
scratch. Additional loaded helpers and pointer constants occupy **280 bytes**,
`$c000..$c117`; small dispatch/store additions are in the cloned raster.
Initialization takes 2,575 CPU cycles once and is reported separately.

`host-analysis.cjs` is a separate hit-rate study over 512 frames per model and
axis mode. Its static report is `host-hits.json`; it is not input to the native
renderer. The chosen cheap 64-slot XOR mapping hits 14.12% of active edges over
that study. Increasing the key hit rate alone would not account for extra hash
or miss costs.

The 32-frame receipt is preserved as `build/benchmark-32.json`:

| Group | Raster CPU change | Raster + resolve change |
| --- | ---: | ---: |
| All 112 cases | +3.443% | +2.872% |
| Checker animation | +8.960% | +7.710% |
| Football animation | +1.781% | +1.424% |
| Jumps / pauses | −2.772% | −2.435% |
| Single axis | +2.153% | +1.769% |
| Model switches | +0.574% | +0.412% |

All 112,000 coverage bytes and 112,000 resolved screen bytes matched, with
immutable font and static geometry/LUT assets. The benchmark measures assembled
NMOS 6502 instructions in py65, excluding projection, VIC stalls, IRQs and
presentation waits. These results are CPU costs rather than PAL frame rates.
The unchanged resolver runs 147 cycles faster per case because relocating it
changes branch page crossings; the raster-only column isolates the strategy.

Run from `asm/sphere-polygons`:

```sh
rtk proxy python3 optimization/common/build_variant.py optimization/edge-cache
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 optimization/common/benchmark.py --variant optimization/edge-cache --frames 32
```

The compared baseline PRG SHA-256 is
`1379a1c305d1ef6553aead15fd74da1f093538cb88a0c4d57b5c71f7bb34b25c`.
The candidate SHA-256 is
`7aa0b1a0eac7d28147ea651edb551dbb93149865d3b3e68702fe884944addf46`.
