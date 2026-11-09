# PAL stage profiling

`profile.py` measures the assembled projected-vertex and atlas players with its own
minimized PAL VICE instance, speed100%, warp disabled. It imports the existing
native monitor utilities and uses a free monitor port. It closes only the
process it launched. Run it only after the player binary and sources are frozen.

All results retain the same72-face checker mesh. Per-face samples count the
currently visible white subset, rather than a reduced mesh.

From the repository root:

```sh
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/vertices/profile.py \
  --variant asm/sphere-polygons/precomputed/hybrid/vertices/player \
  --frames 64 \
  --expected-program-sha256 FROZEN_PRG_SHA256
```

`--variant` also accepts an optimized clone or atlas player with the same checkpoint ABI.
`--asset`, `--output`, and `--vice` override the defaults. Without `--asset`, the
helper chooses a candidate only when its bytes exactly match the PRG's embedded
`animation` block, using the load address and animation labels. An explicit
asset must pass the same check; a wrong file is rejected before VICE launches.
The default output is the variant's `build/pal-profile/`. `--help` loads and
checks the helper without launching VICE. For reproducibility, pass the source
explicitly: `edge-atlas/build/native-source.bin` contains PV64 and EA64 together;
`span-atlas/build/assets/spans.sa64` is the complete SA64 source. The XY players
use `vertices/build/assets/white-delta.pv64`.

The helper installs instruction-PC breakpoints at these paired labels:

| Work | Start | End |
| --- | --- | --- |
| Vertex/visibility packet parsing and decoding | `decode_start` | `decode_end` |
| Coverage clearing | `clear_start` | `clear_end` |
| One visible white face's bounds and edge work | `face_edges_start` | `face_edges_end` |
| That face's sample-span filling | `face_fill_start` | `face_fill_end` |
| Coverage-to-glyph resolution and silhouette treatment | `resolve_start` | `resolve_end` |

The label names are shared, but work inside them is variant-specific. For the
edge atlas, `face_edges` includes face bounds, span reset and stored crossing
aggregation. For the span atlas it is normalized-span decompression/preparation,
with **no DDA**. Its `decode` interval only sets up frame pointers/visibility;
there are no projected vertices to decode.

`render_start`, `render_end` and `frame_done` bound the complete render and
presentation. Stage start and end PCs must differ. Adjacent stage labels may
share a PC; the helper closes an ending stage before opening the next one.
The legacy `edge_start/end` and `fill_start/end` aliases are not installed as
additional breakpoints, avoiding duplicate events at one instruction.

At each face edge start, `raster_vertex_count` determines triangle versus quad.
`current_face_index`, if present, supplies the white-topology index. The helper
requires one edge pair and one fill pair per face and keeps their attribution
together, including paired stages for faces with no active sample span. It
requires one decode, clear and resolve interval per frame.

## What the clocks mean

Every interval is the difference of VICE's emulated machine clocks, so it
includes **VIC bus stalls** incurred during that exact stage. Monitor pauses do
not advance the emulated clock. This is not the instruction-only built-in
profiler's cycle total. Different geometry and raster phases can give different
fill durations even for the same face kind.

The JSON reports:

- Per-frame decode, clear, all face-edge work, all face-fill work and resolve.
- Every visible face's topology index, vertex count, edge duration and fill
  duration.
- Minimum, median, mean and maximum duration for individual quad fills and
  triangle fills.
- Total quad-fill and triangle-fill durations per complete frame.
- Complete render clocks, stage shares and remaining driver/bookkeeping clocks.
- Presentation intervals observed while profiling, separately from render work.

It checks that named stage intervals do not overlap and that their sum does not
exceed the complete render duration. The residual is reported as unattributed
driver work. It preserves the program, symbol, asset and available ASM source
hashes and fails if those files change during the run. Raw VICE and monitor
logs accompany `profile.json`.

The profile is deliberately **not another screen correctness proof**. The
shared native verifier separately compares all1,000 output codes, immutable
font/movie data, actual screenshots and loop wraps. Startup is outside the
render measurements. Quad fill clocks are a component cost; they are not movie
FPS. The root verifier owns the complete validated presentation-rate result.

## Measured baseline

The frozen baseline PRG
`2d8d0b551efdd9145c34c1a5469f80b406c16db03ff064ddeca649cfb48c9adc`
passed the complete64-frame PAL profile. Its receipt is
`player/build/pal-profile/profile.json`. Every frame's stage durations plus
unattributed driver work sum exactly to its complete render duration.

| Work, per complete frame | Mean PAL clocks | Mean time | Share of rendering |
| --- | ---: | ---: | ---: |
| Decode projected geometry and visibility | 4,970.77 | 5.05 ms | 2.40% |
| Clear coverage | 6,993.41 | 7.10 ms | 3.38% |
| Face bounds and edge stepping | 108,944.86 | 110.58 ms | 52.61% |
| All face sample-span fills | 55,330.98 | 56.16 ms | 26.72% |
| Resolve glyphs and silhouette | 28,519.19 | 28.95 ms | 13.77% |
| Remaining driver work | 2,309.05 | 2.34 ms | 1.12% |
| **Complete rendering** | **207,068.25** | **210.17 ms** | **100%** |

There are1,152 face samples:768 quads and384 triangles. Each frame has six
triangles and11–13 quads, averaging12 quads. Individual quad fills take
689–6,319 PAL clocks, averaging **3,970.14 clocks /4.03 ms**. Summing all quad
fills in each complete frame gives45,357–49,435 clocks, averaging
**47,641.63 clocks /48.35 ms**. Triangle fills average1,281.56 clocks per face.
These are actual measured fill intervals, including their VIC stalls.

The separate native verification passed66 displayed images,66,000 screen bytes,
the loop wrap and three actual screenshots for this same PRG. It measured
**4.55678 displayed images per second**, with presentation intervals of about
216,216 PAL clocks. Its66-image render mean is206,988.59 clocks; the small
difference from the64-image profile mean comes from repeating the first two
poses. The profile and independent verification both closed their owned VICE
process successfully. No projection cost or movie FPS is inferred from an
isolated quad-fill timing.

## Measured optimized filler

The optimized PRG
`5ebfa91747512764fea1359ed177e38ce68c69e95623eeca98486ff04121a229`
passed the same64-pose profile and a separate66-image native verification.
Receipts are `fast-player/build/pal-profile/profile.json` and
`fast-player/build/verification/verification.json`, also preserved in the
[checked-in optimized results](../results/vertices/fast/). The baseline receipts
are preserved in [baseline results](../results/vertices/baseline/).

| Work, per complete frame | Mean PAL clocks | Mean time | Share of rendering |
| --- | ---: | ---: | ---: |
| Decode projected geometry and visibility | 4,974.80 | 5.05 ms | 2.51% |
| Clear coverage | 7,002.70 | 7.11 ms | 3.54% |
| Face bounds and edge stepping | 109,240.80 | 110.88 ms | 55.19% |
| All face sample-span fills | 46,038.95 | 46.73 ms | 23.26% |
| Resolve glyphs and silhouette | 28,377.06 | 28.80 ms | 14.34% |
| Remaining driver work | 2,306.98 | 2.34 ms | 1.17% |
| **Complete rendering** | **197,941.30** | **200.91 ms** | **100%** |

The same768 quads and384 triangles were measured. Individual optimized quad
fills take926–5,602 clocks, averaging **3,221.96 clocks /3.27 ms**, about
**18.85% less time** than baseline. The sum of all quad fills per complete frame
averages **38,663.48 clocks /39.24 ms**, compared with48.35 ms before. Triangle
fills average1,229.24 clocks per face. All face fills together average46.73 ms
per frame, compared with56.16 ms before.

The improved filler changes the raster phase of later work, so unchanged
stages can acquire slightly different VIC-stall costs. Face bounds and edge
stepping still dominate at110.88 ms per frame. Every optimized frame again
passes exact stage-sum accounting; no stage interval is counted twice.

The separate66-image PAL proof passed66,000 exact screen bytes,135,168 font
bytes, immutable PV64 data, the loop wrap and three screenshots. Its render
mean is197,864.85 clocks; its presentation mean is210,470.40 clocks, giving
**4.68117 displayed images/s**. Some frames now fit10 PAL fields while others
still need11; median presentation FPS is4.55682. These whole-player figures
are separate from the faster isolated quad-fill result. The default HD64
character-delta player remains the verified25.062 FPS option.

## Measured edge and span atlases

The exact edge-atlas and span-atlas players passed the same64-pose profile and
independent66-image PAL verification. Each has1,152 profiled visible-face calls:
768 quads and384 triangles, with six triangles and11–13 quads per frame. All
named intervals plus reported driver work sum exactly to each complete render.

| Per-frame stage | Edge atlas PAL clocks | Edge atlas time | Span atlas PAL clocks | Span atlas time |
| --- | ---: | ---: | ---: | ---: |
| Decode/setup | 5,000.98 | 5.08 ms | 215.14 | 0.22 ms |
| Coverage clear | 6,993.56 | 7.10 ms | 6,744.45 | 6.85 ms |
| Edge aggregation / span preparation | 40,264.95 | 40.87 ms | 29,144.84 | 29.58 ms |
| Fast sample-span fill, all faces | 46,123.14 | 46.81 ms | 46,111.36 | 46.80 ms |
| Glyph resolve and circle remap | 28,577.14 | 29.01 ms | 28,642.05 | 29.07 ms |
| Remaining driver work | 2,266.22 | 2.30 ms | 2,147.05 | 2.18 ms |
| **Complete rendering** | **129,226.00** | **131.16 ms** | **113,004.89** | **114.70 ms** |

The fast-fill XY player's edge stage was110.88 ms. Exact lookup paths reduce
that to40.87 ms; replaying completed face spans reduces preparation to29.58 ms.
The latter interval measures actual source decoding and crossing-array writes,
not a zero-cost table lookup and not runtime edge stepping. Fill and resolution
now cost46.80 ms and29.07 ms, dominating the span-atlas render.

Individual quad fills average3,235.50 clocks /3.28 ms with the edge atlas and
3,244.63 clocks /3.29 ms with the span atlas. All quad fills per frame average
38,825.98 clocks /39.41 ms and38,935.50 clocks /39.52 ms respectively. The filler
is the same frozen fast kernel; differences from its3.27 ms XY result reflect
instruction/raster placement and VIC stalls, rather than a new filler.

The edge-atlas whole-player proof measured **7.16065 FPS**, seven PAL fields
per image; the span-atlas proof measured **8.35409 FPS**, six PAL fields per
image. Their66-image render means are129,206.88 and112,994.08 clocks, while
presentation means are137,592.00 and117,936.05. Profile means use64 unique poses;
the66-image proof repeats the first two after wrap. Both proofs checked66,000
exact screen bytes,135,168 font bytes, complete immutable encoded sources and
three actual screenshots, and closed their owned emulators successfully.

| Frozen artifact | PRG SHA-256 |
| --- | --- |
| Edge atlas | `b9ad5085060e8d3efce46b69fd1a19f105c251f2f1087fc83f9207c34e44f64f` |
| Span atlas | `05dc7f549efb8ec3f58fe295fb4c1ce2d458a9003a64ad67e80a1f5ad515e19d` |

Complete immutable sources occupy28,847 bytes for PV64+EA64, or24,981 bytes
for SA64. These include every shared pattern and per-frame record. They are
bounded atlases of the current64 poses, not a dense universe of all straight
lines; changed geometry or motion requires regeneration. The SA64 source is a
20,005-byte pattern pool,4,928 frame-record bytes and48 header/count bytes.

The edge-atlas meaningful loaded footprint is42,774 bytes (49,840-byte PRG);
the span-atlas footprint is38,416 bytes (46,684-byte PRG). Both figures include
font, retained raster/clip tables, code, complete source and BASIC stub; PRGs
also include address gaps. The corresponding fast-fill XY figures were25,230
and36,144 bytes. The measured speed improvement therefore comes with a larger
resident source representation, while omitting unused DDA tables.

Receipts are archived under [edge-atlas results](../results/vertices/edge-atlas/)
and [span-atlas results](../results/vertices/span-atlas/). These playable
benchmarks do not replace the normal character-delta movie's25.062 FPS path.
