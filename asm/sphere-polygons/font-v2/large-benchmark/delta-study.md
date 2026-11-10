# Large-ball character-delta comparison

All native timings use the same analytic HTML reference: 290-pixel diameter,
20 × 10 checks, 65° tilt, the selected 256-character font `e4071e1e…`, initial
angle 0.38 radians and 0.9375° steps around the existing camera Y axis. The
motion has 384 distinct poses. It was not replaced with an own-axis symmetry
loop.

| Native path | Measured PAL fps | Stored prefix poses | Prefix payload bytes | Prefix duration |
| --- | ---: | ---: | ---: | ---: |
| Sparse page updates directly to visible screen | 50.12453 | 55 | 40,390 | 1.097 s |
| Same sparse updates to hidden mirror, then visible copy | 25.06229 | 55 | 40,390 | 2.195 s |
| Packets64 to hidden mirror, then visible copy | 16.70819 | 62 | 40,430 | 3.711 s |

These storage counts start at pose zero and use a 40,960-byte data arena at
`$3000–$cfff`. The 2,048-byte font, 1,000-byte raw seed and native code/pointer
tables are outside this arena and included in each build manifest. The first
sparse prefix covers 50.625°; the packet prefix covers 57.1875°. Each standalone
PRG plays its real prefix once and stops on the final pose. A longer physical
duration at lower fps does not mean that it contains more rotation.

The full-turn timing sweep loaded all 384 transitions through separate
RAM-sized programs. This includes the true `383 → 0` transition. It does not
claim that all 384 frames fit at once. Normal PAL VICE, 100% speed, warp and
monitor forced refresh disabled, verified 392 direct sparse visible fields,
776 hidden sparse fields and 775 hidden packet fields against all 64,000 active
pixels. The fixed font and movie data remained unchanged.

Direct sparse updates took 11,547–17,159 PAL clocks. Hidden sparse updates took
11,618–17,240 clocks plus a 10,001–10,003-clock copy. Hidden packets took
26,238–30,750 clocks plus the copy. Music and other interrupt work are absent.

Packets64 directly to the front screen was rejected. Its final-image cadence
was 25 fps, but the first visible update field contained both old and new
poses. The conditional native monitor probe captured that completed field at
raster line 254 without inserting instructions or refreshing the display.

For a full 384-pose turn, sparse payloads need 289,560 bytes and ordinary packet
payloads 258,939 bytes, before seed, pointers and font. Independent common-glyph
RLE needs 262,315 payload bytes; its decoder was verified only on the host and
has no native fps claim in this study.

An additional native comparison uses exactly the 200-face geometry renderer's
images, allowing a direct geometry-versus-character-delta comparison. These
different images fit 74 sparse poses, 72 packet poses or 68 RLE poses in the
same arena. Both sparse native paths were verified across all 384 transitions:

| Flat-geometry image playback | Measured PAL fps | Stored prefix poses | Prefix duration | Actual VIC fields checked |
| --- | ---: | ---: | ---: | ---: |
| Sparse updates directly to visible screen | 50.12458 | 74 | 1.476 s | 390 |
| Sparse updates to hidden mirror, then copy | 25.06228 | 74 | 2.953 s | 774 |

The 74-pose prefix needs 40,850 payload bytes and covers 68.4375°. Direct sparse
updates took 8,231–13,205 clocks; hidden updates took 8,326–13,347 clocks plus
the copy. The packet and RLE geometry-image counts remain storage-only results.
The geometry uses flat faces and eight-probe character masks; it is not
pixel-identical to the analytic reference. Separate hashes and native receipts
are recorded in `build/delta/geometry-native/summary.json`.

Reproduce from the repository root:

```sh
rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/delta-study.cjs
rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/delta-study.cjs --geometry
rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/build-delta.cjs --chunks sparse-front sparse-hidden packets-hidden
rtk proxy python3 asm/sphere-polygons/font-v2/large-benchmark/verify-delta.py --chunks sparse-front sparse-hidden packets-hidden
rtk proxy python3 asm/sphere-polygons/font-v2/large-benchmark/verify-delta.py --summary-only
rtk proxy node asm/sphere-polygons/font-v2/large-benchmark/build-delta.cjs --geometry --chunks sparse-front sparse-hidden
rtk proxy python3 asm/sphere-polygons/font-v2/large-benchmark/verify-delta.py --geometry --chunks sparse-front sparse-hidden
rtk proxy python3 asm/sphere-polygons/font-v2/large-benchmark/verify-delta.py --geometry --summary-only
```

`build/delta/summary.json` is the compact combined receipt. Each native program
has `build.json`, its PRG and a `pal-proof/verification.json` receipt. The
rejected direct packet path and its intermediate-field probe can be rebuilt
and rerun separately with the `packets-front` variant.
