# Same-frame shared-edge cache

This bounded alternative reduces assembled raster CPU **1.496%** across the
112-case mixed trace (`--frames 32`). The football animation improves 3.347%;
checker animation costs an additional 0.192%. It provides a small football
improvement, rather than a general solution to edge DDA cost.

The football has 30 edges shared by two white hexagons. `topology.json` maps
these static face/edge pairs to direct cache entries. Each rendered football
frame advances a generation tag. The first visible white face generates a
shared edge's absolute crossings with the original live rational DDA; a second
face in the same frame replays those crossings into its min/max spans. Every
lookup, miss, curve store, generation update, and span update is measured.
No host-generated crossing, old pose, or prepared animation is reused.

The checker selects the unchanged baseline edge routine once per render. For
football, ineligible edges also use the original DDA. The cache contains 32
entries with 24 crossings each. Oversized curves fall back to disposable
scratch. Generation wrap clears all tags before continuing at generation one.
All retained tags are explicitly initialized once at startup.

Private retained state is **928 bytes**, `$e000..$e39f`, including 128 bytes of
scratch. Additional loaded helpers, the duplicate cache-aware edge routine,
pointer constants and static topology occupy **579 bytes**, `$c000..$c242`.
Small dispatch additions are in the cloned raster. Initialization takes
339 CPU cycles once, reported separately.

The 32-frame receipt is preserved as `build/benchmark-32.json`:

| Group | Raster CPU change | Raster + resolve change |
| --- | ---: | ---: |
| All 112 cases | −1.496% | −1.361% |
| Checker animation | +0.192% | +0.094% |
| Football animation | −3.347% | −2.921% |
| Jumps / pauses | −1.468% | −1.329% |
| Single axis | −1.705% | −1.543% |
| Model switches | −1.563% | −1.420% |

Mean raster cycles across all cases are 159,415.5 baseline and 157,031.15
candidate. Football animation averages 147,232.125 and 142,303.72 respectively.
All 112,000 coverage bytes and 112,000 post-clipping screen bytes match exactly;
the font and parent geometry/LUT assets remain immutable.

The replay measures assembled NMOS 6502 instructions in py65. It excludes
projection, VIC bus stalls, IRQs and presentation waits, so it is not a PAL FPS
measurement. The unchanged resolver runs 147 cycles faster per case because its
new address changes branch page crossings; the raster-only result isolates
this strategy.

The final gate passed: 560 replay cases, including a complete rotation period
and generation wrap, plus 46 native PAL VICE frames and 18 actual screenshots.
The 16 sampled football animation poses measured 5.012 median FPS, compared
with the reference's 4.557. Checker remained at 3.856 FPS. See the parent
[experiment comparison](../README.md) for scope, complete-cycle CPU results
and reproduction. Run `./optimization/shared-edge-cache/run.sh` from
`asm/sphere-polygons` to build and open this variant.

`generate-source.py` recreates the cloned raster/helper source from the frozen
baseline and static topology. Run from `asm/sphere-polygons`:

```sh
rtk proxy python3 optimization/shared-edge-cache/generate-source.py
rtk proxy python3 optimization/common/build_variant.py optimization/shared-edge-cache
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 optimization/common/benchmark.py --variant optimization/shared-edge-cache --frames 32
```

The compared baseline PRG SHA-256 is
`1379a1c305d1ef6553aead15fd74da1f093538cb88a0c4d57b5c71f7bb34b25c`.
The candidate SHA-256 is
`80c328509a5e5e5f127c67dcbe9e6f9efdfc30986fc5d12c9cecd92cbdb5be98`.
