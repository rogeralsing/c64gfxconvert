# Live polygons through a fixed C64 charset

For the precomputed checker-only follow-up, see [compression formats](precomputed/hybrid/README.md) and [compressed PAL playback](precomputed/hybrid/player/README.md).

The measured delta/cache follow-up is in [optimization/README.md](optimization/README.md). Five kernels were tried; the shared-edge football variant passed native checks and measured 5.012 FPS on the sampled PAL poses.

This PAL C64 experiment rotates two complete 3D meshes and converts their visible white faces into characters from a fixed, mathematically generated 256-character font. Yaw, pitch and roll are independent runtime values. The 6510 calculates each frame; there are no stored animation frames or screen deltas.

| Model | Shared vertices | Faces |
| --- | ---: | --- |
| Checker sphere | 62 | 24 triangles + 48 quads |
| Football | 60 | 20 white hexagons + 12 black pentagons |

All faces remain in the model. The renderer visits every face record and paints front-facing white faces onto black. It imposes no sprite or eight-face limit.

## Run

The local scripts require Node.js, KickAssembler and VICE. Their tool paths match this workstation.

Native verification and profiling also require Python 3 with Pillow (`python3 -m pip install Pillow`).

```sh
./build.sh
./run.sh
```

Load `build/polygon-spheres.prg` on a PAL C64, or use VICE PRG autostart.

- **F1:** switch checker / football.
- **F3:** cycle all axes / yaw / pitch / roll.
- **Space:** pause / resume.

Each angle has 256 positions per turn. The default animation advances yaw by two positions and pitch and roll by one position per completed frame. The underlying projection accepts any combination of the three angles. Switching rotation mode retains the current orientation.

## Character work, not a rendered bitmap

The screen has 40 × 25 character cells. Vertex coordinates use Q3 character units: one eighth of a character. This preserves enough precision to choose a diagonal glyph without walking all 64 dots inside every tile.

For each frame:

1. Build a rotation matrix and project the shared vertices once.
2. Cull faces using their rotated outward normals.
3. Walk each white face's edges at three sample lines per character row. Rational edge stepping produces left and right crossings without per-dot traversal.
4. Fill whole character spans and partial endpoint masks. Eight sample bits represent a tile; adjacent white faces merge their masks with OR.
5. Resolve each mask through a 256-byte lookup into the fixed font. A static circle-safe remap restricts silhouette glyphs to the ball's radius.

The eight probes are a 3 × 3 grid without the center. Coordinates are `[1,4,6]` within a character. Empty and full masks always select empty and full glyphs.

Static tables hold scalar products, edge ratios, sample masks and font choices. They hold no orientations, complete screens or animation sequences. Rotation and projection execute on the C64. Dot-level loops run only in asset generation and independent host verification.

## Strategies tested

Three parallel investigations covered shared-vertex projection, character-span filling, and independent point-sampling references.

- **Point tests per tile:** easy to express, but repeats polygon edge tests for each probe.
- **Character spans:** cross polygon edges once per sample line, then fill runs of character masks. This became the native renderer.
- **Eight versus nine probes:** eight fits coverage into one byte per tile and a 256-byte lookup. Nine requires two bytes per tile and a 512-byte lookup. The preliminary 16-pose study found only a 0.074 percentage-point improvement for nine probes on the football, and a small regression on the checker sphere. Those preliminary figures use the study's own density tie-break; `verify-host.cjs` measures the font lookup actually shipped.

`strategy-study.cjs` retains the comparison. `reference.cjs` supplies an independent even-odd polygon evaluator. The reference uses dot tests for measurement only; it is absent from the C64 program.

## Measured PAL results

The final receipt is `build/verification-3axis/verification.json`, measured in VICE 3.10 at 100% speed, warp disabled, with VIC bus stalls included. FPS below is the median presentation cadence over 16 animation frames per model. The sampled poses differ between models and do not cover a complete turn.

| Model | Mean render clocks | Geometry | Character spans | Glyph resolution | Median FPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Checker | 236,490 | 15,737 | 192,199 | 28,544 | 3.856 |
| Football | 197,243 | 15,417 | 153,956 | 27,862 | 4.557 |

Most time goes to character coverage, rather than 3D rotation. Projection and matrix work consume about 6.7% of checker rendering and 7.8% of football rendering.

The earlier analytic sphere in `../sphere-math` measured 7.161 FPS with the same font and radius. Its prepared geometric fields assume a fixed camera and tilted rotation axis. This first general polygon renderer is slower, while allowing independent rotation around three axes and different meshes. The checker mesh also approximates curved patches with flat polygons, so the two images are not identical.

## Character plotting CPU costs

Run `python3 profile-c64.py` after building. The profiler uses VICE's native per-instruction counts and the assembler's source map. It measures four fixed three-axis orientations per model on the unchanged PRG. Each instruction belongs to one exclusive category; their cycles plus VICE's stolen VIC cycles equal every measured render interval exactly.

The following shares use **CPU instruction cycles**, excluding VIC bus stalls and the final raster wait. The earlier FPS table uses presentation clocks and different sampled poses.

| Work | Checker | Football |
| --- | ---: | ---: |
| Polygon edge setup and rational DDA | 44.52% | 41.53% |
| Span/mask preparation, coverage OR and filling | 24.94% | 26.70% |
| Clear coverage buffer | 3.02% | 3.44% |
| Clear per-face crossing arrays | 2.67% | 2.43% |
| Read coverage and prepare glyph index | 2.90% | 3.30% |
| Read selected glyph from font lookup | 1.93% | 2.20% |
| Write screen character codes | 2.42% | 2.75% |
| Circle-safe glyph clipping | 4.51% | 5.03% |
| Face traversal, culling and bounds | 5.36% | 4.03% |
| Rotation matrix and vertex projection | 6.86% | 7.60% |
| Resolve loops and render driver | 0.88% | 1.00% |

Mean CPU cost was 212,001 cycles for checker and 186,171 for football. VIC bus stalls added 12,225 and 10,707 clocks respectively. `build/char-cpu-profile/profile.json` preserves the exact poses, per-instruction exports, source hashes and reconciliation.

Glyph choice does not search the font. Reading the coverage byte, transferring it to an index and looking up the glyph costs 10,240 CPU cycles per frame. The lookup itself costs 4,096 cycles. The resolver writes 1,024 positions, including the 24 unused bytes at the end of screen RAM. Clearing coverage costs 6,403 cycles. The main cost is producing polygon edge crossings and character masks before resolution.

The renderer fills one polygon's character coverage at a time. Edges supply mathematical crossings rather than a drawn wireframe. Adjacent polygons may update the same tile several times before the combined mask selects its final glyph.

## Delta opportunity study

`node delta-study.cjs` measures 64 consecutive host frames per model using the default yaw/pitch/roll increments. It excludes the first two frames from comparison. It counts actual post-clipping character codes and coverage bytes; it does not implement native delta rendering or measure a speedup.

Each alternating destination screen contains the image from two presentations earlier. Comparing only with the immediately previous presentation overstates reuse for this buffer arrangement.

| Model | Changed chars versus previous presentation | Changed chars versus actual destination | Unchanged ball cells versus destination |
| --- | ---: | ---: | ---: |
| Checker | 223.29 | 282.65 | 40.50% |
| Football | 116.60 | 149.24 | 68.58% |

The percentages use the 475 cells touched by the exact integer-dot radius94 circle, rather than all 1,000 screen positions. The large permanently black exterior is excluded from this denominator. Pre-clipping coverage changes averaged 283.24 checker cells and 149.63 football cells against the two-frame-old state. No current white front face had an exactly unchanged projected polygon in either sampled trajectory.

Whole-face reuse therefore has a weak signal here. Retaining old row spans and coverage could skip unchanged span mask/address setup, rather than merely suppressing screen stores after all work has already been done. That could target more of the measured span cost. Constructing all new edge crossings would still retain the roughly 42–45% DDA cost. Endpoint comparisons, history and dirty-cell tracking have their own CPU and memory cost; changed-cell counts do not establish a native gain.

Per-face removal also needs care: the present coverage is an OR of white contributions. Removing one face must preserve neighboring white contributions. Retained merged white intervals per sample row, or explicit contribution counts, would provide a sound basis for incremental updates. State must follow each physical destination buffer, or a canonical history must propagate both intervening changes.

`build/delta-feasibility.json` records the poses, both history comparisons and source hashes. The native renderer remains unchanged.

## Verification

```sh
node verify-host.cjs
node bound-certificate.cjs
python3 verify-c64.py --output build/verification-3axis
```

The native verifier starts and closes its own PAL VICE process. It verified 46 frames: 16 animation frames per model and 14 fixed-pose, paused and independent-axis probes. It compared:

- All 1,000 screen bytes, 1,000 coverage bytes and 2,048 font bytes per frame.
- Both 64-byte projected coordinate arrays and all nine matrix coefficients.
- Full mesh records, normal depths, culling flags and traversal of all 72 / 32 faces.
- Every lit glyph dot against the radius94 circle; zero spill was allowed.
- Eighteen actual VIC screenshots against the reconstructed visible screen.

A native quarter-turn around roll independently swaps projected X/Y coordinates. Paused arbitrary orientation `(37,61,93)` remains stable. Yaw-only, pitch-only and roll-only increments are checked separately.

The independent host quality measurement covers 32 varied three-axis poses per model and compares the shipped character output with floating-point polygon projection. Error counts differing lit/unlit dots divided by the visible reference polygon area:

| Model | Mean image error | Maximum image error | Lit dots outside circle |
| --- | ---: | ---: | ---: |
| Checker | 7.319% | 11.774% | 0 |
| Football | 3.603% | 7.033% | 0 |

These figures include integer projection, sampling, font approximation and silhouette remapping. They measure the polygon model, rather than an ideal curved checker sphere. `build/host-verification.json` records every pose and the exact input hashes.

The native GIFs reconstruct actual emulator screen RAM through the verified font and use measured frame durations:

- `build/verification-3axis/checker-native.gif`
- `build/verification-3axis/football-native.gif`

Verified PRG SHA256: `1379a1c305d1ef6553aead15fd74da1f093538cb88a0c4d57b5c71f7bb34b25c`.

## Approximation limits

The separate [bitmap-tested font experiment](font-v2/README.md) evolves a
2,048-byte mathematical font across sphere orientations, sizes and checker
counts. It includes a portable HTML preview, per-glyph usage, recurring error
bitmaps and independent final-test evidence. It does not change these native
players' frozen fonts or encoded movies.

A single glyph approximates each tile's union of white faces. Multiple boundaries inside one tile, thin faces and high curvature can exceed the font's shapes. Q6 matrix and Q3 vertex rounding also move edges. Nearly edge-on quantized hexagons can fold slightly; min/max spans then approximate their narrow footprint. The strict circle remap prevents protrusions outside the ball, but can erode boundary detail. Neither native-to-host agreement nor zero circle spill proves a perfect polygon image.

The football has adjoining white hexagons without extra seam strokes. Black pentagons provide its pattern. Both meshes use orthographic projection, fixed size and a fixed white-on-black palette.

## Memory and source

| Region | Purpose |
| --- | --- |
| `$0400–$07ff`, `$0c00–$0fff` | Double-buffered character screens |
| `$1000–$13ff` | Coverage masks |
| `$1400–$154a` | Projected vertices and sample spans |
| `$2000–$27ff` | Immutable 256-glyph font |
| `$3000–$3883` | Main loop, geometry and raster code |
| `$4000–$bfaf` | Static mesh and lookup data, including alignment |

Binary assets total 32,735 bytes, including 2,048 font bytes. Forty-five scalar product pages use 11,520 bytes. The strict silhouette remap and compact index use 9,136 bytes; 148 clip records use another 592 bytes. The complete PRG also includes gaps between memory regions.

`meshes.cjs` defines the geometry. `geometry.cjs` and `geometry.asm` share integer projection rules. `raster.cjs` and `raster.asm` implement coverage and fixed-font selection. `generate-assets.cjs` creates arithmetic and glyph tables. `native-model.cjs` connects the host equivalents for native comparison. `CONTRACT.md` records the assembler ABI and boundary conventions.
