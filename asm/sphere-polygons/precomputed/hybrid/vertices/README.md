# Projected geometry, edge atlases and native character filling

Precomputed lookup paths work: actual PAL playback improves from **4.68117 FPS**
with runtime edge walking, to **7.16065 FPS** with an edge atlas, and
**8.35409 FPS** with a face-span atlas. The measured edge/preparation stage
falls from110.88 ms to40.87 ms and then29.58 ms per frame. Filling and glyph
resolution now dominate the fastest version.

All published comparisons retain the same 72-face checker mesh.

This is a runnable geometry-storage benchmark, not the default animation
player. The [front-delta character player](../player/front-delta/README.md) is
the default, with verified50.124529 FPS playback on one visible screen. The
legacy double-buffered delta comparison remains25.062 FPS. `vertices/run.sh` launches
the span-atlas benchmark; it does not replace that normal animation player.

## What is stored and executed

The PV64 variants use `generate.cjs` to freeze the same64 smooth checker poses as projected X/Y bytes
for **all62 shared vertices**, with shared white-face topology and precomputed
front-face visibility. There is no runtime3D rotation, projection or back-face
culling. The movie has36 white faces:12 triangles and24 quads. Black faces are
the implicit background.

The actual **2,607-byte PV64 file** contains:

| Item | Bytes |
| --- | ---: |
| Global header | 12 |
| Shared white-face headers and vertex indices | 168 |
| Fifteen signed X/Y delta pairs | 30 |
| First frame's62 projected X/Y pairs and visibility | 129 |
| Following63 frames:31 packed vertex-delta bytes +5 visibility bytes | 2,268 |
| **Total** | **2,607** |

Each subsequent vertex uses a four-bit index into the shared delta-pair book.
All positions and visibility bits are decoded during playback. At the loop
boundary the player restores the first projected state.

The native pipeline clears an eight-probe-per-character coverage buffer, walks
the visible polygons' integer edges, fills their sample spans, resolves the
coverage through the unchanged font lookup, and applies the existing safe
circle remap. It uses the **existing exact span edge walker and filler**.
It does **not** compose the image by calling the separate isolated Q8
[`draw_line` primitive](../lines/native/README.md), whose independently selected
boundary glyphs cannot by themselves combine corners and crossings.

`fast-player` replaces the span filler while preserving the same projected
inputs, coverage masks and final1,000-character image. The rational edge
walker, font and silhouette treatment remain the reference behavior.

## What the atlas variants reuse

[`edge-atlas`](edge-atlas/README.md) adds1,034 normalized edge paths. Each
four-byte use restores the path's position, then combines exact crossings into
the face's left/right spans. It replaces quotient/remainder DDA with pool reads
and min/max aggregation. The26,240-byte EA64 atlas includes its9,200-byte pool,
all4,224 edge-use records, offsets and header. It retains the2,607-byte PV64
movie for XY, visibility and face bounds: **28,847 source bytes** in total.

[`span-atlas`](span-atlas/README.md) goes further: it stores completed face
crossing spans, so runtime needs neither vertex decoding nor DDA/minmax edge
aggregation. Its **24,981-byte SA64 movie** includes a20,005-byte shared pool,
4,928 bytes of frame visibility/references, and48 header/face-count bytes.
The pool contains1,028 normalized span patterns for1,152 visible-face instances.
The C64 decompresses these spans and runs the same fast native filler and
font/silhouette resolver. This is stored polygon crossing data, not finished
character frames or new glyphs.

Both atlases are bounded to this64-pose checker movie. They are not dense
tables for every possible slope, phase or future motion. Changing geometry,
projection or poses requires regenerating their assets. Their complete shared
pools and frame records are included in the sizes below; unused DDA tables are
omitted from the atlas players.

## Actual PAL measurements

All four variants passed66 complete displayed images, the63-to-0 wrap, all66,000
screen codes, immutable font/movie checks and three actual screenshots.
Separate stage profiles cover all64 unique poses and768 visible quad fills.
Each frame has six visible triangles and11–13 quads, averaging12 quads.

| Measured work | Baseline XY | Fast-fill XY | Edge atlas | Span atlas |
| --- | ---: | ---: | ---: | ---: |
| One visible quad's fill, mean | 4.03 ms | 3.27 ms | 3.28 ms | 3.29 ms |
| All quad fills per frame, mean | 48.35 ms | 39.24 ms | 39.41 ms | 39.52 ms |
| All triangle and quad fills per frame | 56.16 ms | 46.73 ms | 46.81 ms | **46.80 ms** |
| Edge work or atlas preparation per frame | 110.58 ms | 110.88 ms | 40.87 ms | **29.58 ms** |
| Glyph resolve and circle remap per frame | 28.95 ms | 28.80 ms | 29.01 ms | 29.07 ms |
| Complete rendering,64-pose profile mean | 210.17 ms | 200.91 ms | 131.16 ms | **114.70 ms** |
| Displayed images/s,66-image verification mean | 4.55678 | 4.68117 | 7.16065 | **8.35409** |

These are emulated PAL machine clocks, including VIC bus stalls. The whole
player rate includes raster waiting and screen flips. Unchanged stages can
have slightly different elapsed clocks because each variant changes when they
encounter VIC bus stalls. Edge-atlas presentation takes seven PAL fields;
span-atlas presentation takes six. The span-atlas29.58 ms interval is
**decompression and span preparation**, not DDA. It leaves46.80 ms of fill and
29.07 ms of glyph/silhouette work. There is no25 FPS claim for these geometry
or span-replay players.

Across these poses, an average175.9375 of the475 circle cells use a partial
edge glyph, with166–187 per frame: about37%. The remaining cells resolve to
empty or solid glyphs. These are character-cell counts, not geometric-edge or
line-command counts.

See [stage profiling](notes-profile.md) for clocks, attribution and measurement
scope. Checked-in receipts are under [baseline results](../results/vertices/baseline/)
and [fast-fill results](../results/vertices/fast/), with the new
[edge-atlas](../results/vertices/edge-atlas/) and
[span-atlas](../results/vertices/span-atlas/) receipts alongside them. Local
detailed logs remain in each variant's ignored `build/` directory.

## Native size

| Loaded content | Fast-fill XY | Edge atlas | Span atlas |
| --- | ---: | ---: | ---: |
| Fixed font and retained raster lookup assets | 20,959 | 12,489 | 12,230 |
| Complete movie and shared atlas sources | 2,607 | 28,847 | 24,981 |
| Native code, state and included constants | 1,651 | 1,425 | 1,192 |
| BASIC startup | 13 | 13 | 13 |
| **Meaningful loaded bytes** | **25,230** | **42,774** | **38,416** |
| Actual PRG, including load address and gaps | 36,144 | 49,840 | 46,684 |

The baseline XY player has24,917 meaningful loaded bytes and a36,144-byte PRG.
The atlas variants deliberately spend more memory to remove edge work, while
dropping the now-unused ratio/DDA lookup data. Runtime coverage, span arrays,
zero-page state and the two screen buffers require additional RAM. The PV64
variants also expand XY/topology; the span-atlas player does not allocate those
geometry buffers. No decoded per-frame character screens are embedded.

## Build, run and reproduce

From the repository root:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/player/prepare-assets.cjs
rtk proxy node asm/sphere-polygons/precomputed/hybrid/vertices/generate.cjs
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/player/build.sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/fast-player/build.sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/edge-atlas/build.sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/span-atlas/build.sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/run.sh
```

Each variant writes its own `build/player.prg`. To check the assembled atlas
instructions against the independent reference:

```sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/vertices/edge-atlas/host-smoke.py
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/vertices/span-atlas/host-smoke.py
```

The proofs check exact coverage and final screens, plus XY/topology where those
are used. They exclude VIC timing. For the span-atlas PAL proof and profile:

```sh
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/player/verify.py \
  --variant asm/sphere-polygons/precomputed/hybrid/vertices/span-atlas \
  --asset asm/sphere-polygons/precomputed/hybrid/vertices/span-atlas/build/assets/spans.sa64 \
  --reference asm/sphere-polygons/precomputed/hybrid/vertices/build/assets/reference.bin \
  --font asm/sphere-polygons/precomputed/hybrid/vertices/build/assets/font.bin \
  --motion-manifest asm/sphere-polygons/precomputed/hybrid/vertices/build/assets/manifest.json \
  --frames 66
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/vertices/profile.py \
  --variant asm/sphere-polygons/precomputed/hybrid/vertices/span-atlas \
  --asset asm/sphere-polygons/precomputed/hybrid/vertices/span-atlas/build/assets/spans.sa64 \
  --frames 64 \
  --expected-program-sha256 05dc7f549efb8ec3f58fe295fb4c1ce2d458a9003a64ad67e80a1f5ad515e19d
```

For the edge-atlas verifier/profile, use its `build/native-source.bin` as the
asset; that contains PV64 and EA64 together. For either XY player, use
`vertices/build/assets/white-delta.pv64`; the host checker is
`vertices/player/host-smoke.py --variant VARIANT`. All frozen PRG/source hashes
are retained with the variant receipts and [profiling notes](notes-profile.md).
