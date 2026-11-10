# Exact per-face span atlas

This alternative precomputes exact polygon crossing spans for the current
64-frame smooth checker motion. The C64 reads those spans, fills eight-sample
character coverage with the frozen fast-fill kernel, and resolves the existing
fixed font and circle remap. It performs no vertex projection, edge DDA, glyph
search, or character-frame decoding. The movie contains polygon span records,
not character codes or custom glyph sequences.

The measured storage/speed tradeoff is deliberate: removing runtime edges costs
a 24,981-byte span movie, compared with the 2,607-byte projected-vertex movie.
The verified PAL player presents **8.3541 frames per second**. A separate
64-frame PAL profile measures 113,005.516 clocks, or 114.70 ms, for rendering.
This geometry benchmark does not reach 25 FPS. The separate
[front-delta player](../../player/front-delta/README.md) is the standard
playback choice at50.124529 FPS.

## Build and reproduce

From `asm/sphere-polygons`:

```sh
rtk proxy node precomputed/hybrid/vertices/generate.cjs
rtk proxy node precomputed/hybrid/vertices/span-atlas/build.cjs
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 precomputed/hybrid/vertices/span-atlas/host-smoke.py
```

The first command creates the shared projected-geometry reference assets used
by this comparison. It assumes the parent sphere-polygon font/table assets have
already been generated. Those reference screens are never imported by assembly.

`generate.cjs` reads the existing smooth projected geometry and independently
computes integer half-open edge crossings at the 75 global sample heights.
It serializes and parses the complete SA64 movie, rebuilds coverage from the
decoded spans, and checks all 64,000 coverage and 64,000 resolved character
bytes against the existing reference. References are verifier input only;
neither assembly nor the native movie imports them.

`build.cjs` generates its own ABI and raster include in `build/`. It reuses the
unchanged parent zero-page declarations, the frozen
`../fast-fill/kernel.asm`, and the unchanged parent `resolve_screen` routine.
The DDA and ratio tables are omitted. Only generated files in this directory
are written.

`host-smoke.py` executes the compiled player through 66 frames, including the
64-to-0 wrap. It checks all 66,000 coverage and 66,000 visible-screen bytes,
frame order/counter, front-buffer preservation while drawing, font identity,
and all static movie/table bytes. RAM begins poisoned with `$a5`. The actual
6502 instructions execute every span lookup, preparation, fill, clear and
font-resolution operation. Raster waiting is bypassed only after rendering.

## SA64 v1 wire format

The header is 12 bytes:

| Offset | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 4 | ASCII `SA64` |
| 4 | 1 | Version 1 |
| 5 | 1 | White-face count, 36 |
| 6 | 2 | Frame count, little-endian 64 |
| 8 | 2 | Normalized pattern-pool bytes, little-endian 20,005 |
| 10 | 1 | Paired-delta codec, 1 |
| 11 | 1 | Reserved zero |

Next are 36 face vertex counts, used for triangle/quad profiling. No vertex
indices, normals, coordinates or geometry table are required by the player.
The normalized pattern pool begins at offset 48. Frame records immediately
follow the pool; all bytes are charged.

Each frame starts with five LSB-first visibility bytes for the shared 36 white
faces. For every set bit in ascending face order it stores four bytes:

```text
first global sample index, base X, pattern offset low, pattern offset high
```

A pattern begins with a sample count. A nonempty pattern then stores normalized
initial left/right X values. Every later sample stores one paired-delta byte:
low nibble is `leftDelta + 7`, high nibble is `rightDelta + 7`. Valid deltas are
−7 through +7; byte `$ff` instead introduces absolute normalized left and right
bytes. Normalization subtracts the minimum endpoint X across the whole face
span sequence. Adding the record's base X reconstructs exact integer crossings.

The pool deduplicates complete normalized patterns by their serialized bytes.
It contains 1,028 patterns for 1,152 visible-face instances. The source spans
would occupy 32,332 endpoint bytes without normalization/delta packing. No
lossy slope quantization or hash collision is used.

| Movie component | Bytes |
| --- | ---: |
| Header | 12 |
| Shared face vertex counts | 36 |
| Pattern pool | 20,005 |
| Frame visibility and references | 4,928 |
| Total SA64 movie | 24,981 |

There are 17–19 visible white faces per frame, averaging 18, so each frame's
visibility and references take 73–81 bytes, averaging 77. The runtime frame pointer advances through those
records; frame zero restores the first-record address after each wrap.

## Native fill and profiling contract

`decode_start/end` measures frame-pointer and visibility parsing.
`face_edges_start/end` measures normalized span lookup and preparation of the
existing `span_left`/`span_right` arrays. It does not measure DDA: none runs.
Each visible face then enters `face_fill_start/end` around the frozen native
character filler. `raster_vertex_count` is 3 or 4 and `current_face_index` is set
before each face's span preparation. Every visible face executes both paired
stages once. Each start/end pair occupies distinct instruction addresses.

Coverage is cleared once per frame, white-face masks compose with OR, and the
existing fixed-font resolver and strict circle remap run unchanged. There is no
projected-vertex decode stage. The fixed-font silhouette therefore remains
byte-identical to the reference, including zero outside-circle pixels.

## Frozen PAL result

The complete player passed actual PAL VICE verification for 66 frames, including
loop wrap, exact reference characters, immutable source/font data and three
screenshots. The 64-frame profile uses the same frozen PRG hash shown below and
includes VIC bus stalls. Presentation waiting is excluded from the render-stage
timings; the measured presentation rate is 8.3540871 FPS.

| Mean PAL stage per frame | Clocks | Time |
| --- | ---: | ---: |
| Frame pointer and visibility decode | 215.1406 | 0.218 ms |
| Coverage clear | 6,744.5 | 6.85 ms |
| Span lookup and preparation | 29,142.7969 | 29.58 ms |
| Character fill, all visible faces | 46,111.9844 | 46.80 ms |
| Fixed-font resolve and circle remap | 28,642.7031 | 29.07 ms |
| Complete render, including driver | 113,005.5156 | 114.70 ms |

Each visible quad averages 3,244.625 PAL clocks, or 3.293 ms, for filling.
The span-preparation row measures stored-crossing decoding, not runtime DDA.
The detailed receipts are `build/verification/verification.json` and
`build/pal-profile/profile.json`; the coordinator archives this result under
`results/vertices/span-atlas`.

## Separate assembled CPU replay

The full 66-frame host replay passed. It made 396 triangle and 792 quad calls.
The average per-face span preparation was 1,532.2534 instruction cycles and
the average per-face fill was 2,423.0354 cycles across that replay. These are
mixed triangle/quad averages. `build/host-smoke.json` retains stage distributions
and per-frame render cycles; `build/assets/manifest.json` retains the complete
serialized host proof and hashes.
The first 64 frames average 106,670.9375 CPU instruction cycles for the complete
render. These py65 numbers exclude VIC bus stalls and raster waiting, and are
separate from the PAL measurement above.

| Resident component | Bytes |
| --- | ---: |
| Player and native fill/resolve code, including embedded mask tables | 1,192 |
| Fixed font | 2,048 |
| Fixed raster/font-selection/circle tables, excluding font | 10,182 |
| SA64 movie | 24,981 |
| BASIC stub | 13 |
| Meaningful code and data total | 38,416 |
| Asset alignment padding | 88 |
| Resident blocks total, including BASIC stub and alignment | 38,504 |

Font occupies `$2000..$27ff`, code `$3000..$34a7`, and tightly packed assets and
movie `$3500..$be5a`. The end-exclusive address is `$be5b`, below I/O. The PRG is
46,684 bytes because its load image also includes address gaps and the BASIC
stub. There is no unused 8 KiB ratio table in that image. Runtime uses the
existing 1,024-byte coverage block, two 75-byte crossing arrays and five bytes
of visibility; it does not allocate projected vertices or expanded topology.

```text
SA64 movie SHA-256
127c8f6e14d44c76de7acc3ebf22a57f76e8067df3cc30bc98a1a29d5227c162

compiled player PRG SHA-256
05dc7f549efb8ec3f58fe295fb4c1ce2d458a9003a64ad67e80a1f5ad515e19d

frozen imported fast-fill/kernel.asm SHA-256
7c2fa7f0864360deb0c2b10479c0ee0a6663c56a573f1001f347b16382472a15
```
