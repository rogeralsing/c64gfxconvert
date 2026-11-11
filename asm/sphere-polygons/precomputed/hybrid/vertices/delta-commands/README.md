# Precomputed geometry-mask deltas with dirty font resolution

This is an independent alternative to runtime old/new span comparison. The
offline generator derives exact changes to geometric probe coverage from the
72-face projected checker mesh. The movie stores eight-probe XOR masks and
position runs, not character codes or rendered character frames. On the C64,
each nonzero mask changes maintained geometric coverage, selects the fixed-font
glyph, applies the strict circle remap, and queues that one dirty character.

The serialized geometry movie is **16,100 bytes**, versus 24,981 bytes for the
complete per-face span atlas. This narrower precomputed format requires the
specific 64-pose animation; it is not an arbitrary-angle geometry renderer.
The same 256-glyph mathematical font, radius94 and original checker motion are
preserved. There is no lower-polygon mesh.

The native single-front-buffer queue variant passes 194 presented frames and
three wraps in py65. Its flush is conservatively bounded before the first
next-field matrix fetch. Actual PAL cadence and scanout verification are
separate coordinator-owned checks; no measured FPS is claimed by this host
proof.

## Reproduce

Generate the existing frozen 72-face span-atlas assets first. Then, from
`asm/sphere-polygons`:

```sh
rtk proxy node precomputed/hybrid/vertices/delta-commands/build.cjs
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 precomputed/hybrid/vertices/delta-commands/verify.py
```

`build/census.json` records overlap, dirty-cell and encoding statistics.
`build/geometry.gd64` is the actual movie imported at `animation` through
`animation_end`. `build/verification.json` records native CPU/correctness and
timing-bound results; `build/writes.jsonl.gz` contains every visible store.

## Geometry census and XOR validity

Across every one of the 64 poses and all 8,000 character probes, the maximum
number of white-face contributions is **one**. Static counts are therefore
always zero or one. A sequential per-face old/new update can temporarily reach
two, but final parity still equals final white coverage if font resolution waits
until all face contributions have been updated. The independently implemented
runtime-span alternative can use that fact as well.

Here the generator computes the net change directly. For each probe bit:

```text
delta[t] = coverage[t] XOR coverage[t-1]
maintainedCoverage ^= delta[t]
```

The generator asserts the disjoint endpoint condition and rejects a corpus
that violates it. This is a proved property of the current movie, not a claim
that all quantized polygon arrangements are disjoint.

The circular 64-frame census averages 93.453125 changed coverage cells and
91.953125 changed font glyphs per frame. Exact geometric interval add/remove
commands would average 319.015625 commands and cost 61,379 bytes across the
loop. Coalesced per-cell add/remove masks cost 18,351 bytes before initial
geometry. The selected XOR/run format is smaller than both.

## Actual GD64 wire format

The 12-byte header is:

| Offset | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 4 | ASCII `GD64` |
| 4 | 1 | Version1 |
| 5 | 1 | Frame count64 |
| 6 | 1 | Probe bits per character,8 |
| 7 | 1 | Disjoint endpoint coverage flag,1 |
| 8 | 2 | Initial geometry length, little-endian539 |
| 10 | 2 | Circular delta record count, little-endian64 |

Initial geometry stores one visible-face count followed by 18 face records:
first sample index, sample count, and raw left/right crossing bytes for every
sample. This seed contains 251 sample spans, taking 539 bytes. Startup decodes
them with DEN off through the unchanged native fast filler, then resolves frame0
with the original font. The seed contains geometric coordinates only.

The following 64 records are transitions 0→1, 1→2, ..., 63→0. Every record has
a little-endian 16-bit payload length. Payloads use the existing 64-cell packet
shape: control high bits select skip, literal XOR masks, or repeated XOR mask;
low six bits give length minus one. Position runs cover exactly1,000 character
cells in row-major order. Literal zero masks may bridge small gaps but produce
no font lookup or queue entry. The 64 length-prefixed records occupy 15,549
bytes; header, initial geometry and every length are included in the total.

The host parses these actual bytes and verifies three complete loops against
all original coverage and character references. No source character data is
available to the native decoder.

## Native pipeline and sparse glyph queue

The only geometric state is a 1,024-byte coverage allocation. A nonzero XOR
mask updates its eight-bit signature. Glyph selection uses the existing
256-byte lookup. A 1,024-byte cell-to-clip-class map and 122 bytes of class
pointers route limb cells to the unchanged fixed-font circle remap.

The selected glyph is queued with its screen address in three 128-byte arrays.
The 384-byte queue has capacity128; the measured maximum is111 entries. The
queue occupies `$1400..$157f`, reusing the initial crossing-array area after
startup. No second screen or whole-screen synchronization copy is used.

While image `n` is visible, `compute_start/end` prepares coverage and the sparse
queue for `target_update_index = n+1`. At the next line256 boundary,
`frame_done` identifies the fully scanned current image `n`. Only then does
`flush_start/end` apply the ascending queue for `n+1`. After the flush,
`frame_index` advances and computation of the following target begins.

`render_start/end` measures future-target computation. `frame_done` and
`flush_start` share a PC: the image is still `frame_index` at that checkpoint;
its queued successor is `target_update_index`. Coverage is already that future
target. A verifier must not confuse current visible characters with future
geometric coverage. The initial image0 is resolved with DEN off and scanned
while image1 is computed; there is no recurring key-frame copy.

## Frozen assembled proof

The 194-frame native proof checks 194,000 coverage bytes, 194,000 presented
character bytes, queue addresses/glyphs, all three closing wraps, the immutable
font/movie/tables, and absence of visible writes during computation. Every
visible write occurs in the ascending flush. Both the reference and exact
output retain the original zero-spill circle silhouette.

| Native CPU measurement | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| Future geometry computation and queueing | 19,976 | 24,649.3505 | 28,483 |
| Visible queue flush | 2,260 | 3,012.6598 | 3,572 |
| Queue entries | 70 | 93.5206 | 111 |

These are NMOS6502 instruction cycles, not PAL clocks. The timing bound reserves
1,075 clocks per field for 25 badlines with up to43 stalled clocks each, and63
clocks for start variation. The entire worst flush is therefore bounded by
`3572 + 1075 + 63 = 4710`, before the conservative first-row deadline6741
clocks after line256. It has 2,031 clocks of global blanking headroom without
using later per-row deadlines.

For the pipeline, the conservative independent maxima are
`28483 + 3572 + 128 + 2*1075 + 63 = 34396` clocks, including a128-clock
driver allowance, below two PAL fields39312. The
minimum computation alone exceeds one field19656 clocks. These bounds support
two-field scheduling under the specified no-sprite/no-IRQ workload; actual
PAL verification owns the resulting frame rate. The [VIC-II timing model](https://www.cebix.net/VIC-Article.txt)
and [6569/8565 timing chart](https://www.linusakesson.net/programming/vic-timing/victiming.pdf)
support the reserved stall and matrix-fetch timing.

The first direct-write prototype passed final RAM comparisons but failed its
beam bound. It is rejected and is not the shipped native source. Its numerical
failure is retained in `build/rejected-front-verification.json`; final RAM
equality alone is not a tear-free proof.

## Footprint

| Component | Bytes |
| --- | ---: |
| Native code and embedded initial-fill mask tables | 1,207 |
| Fixed font | 2,048 |
| Fixed lookup data | 10,736 |
| GD64 movie, including initial geometry | 16,100 |
| BASIC stub | 13 |
| Meaningful code/data total | 30,104 |
| Code/table and internal lookup alignment | 153 |
| Coverage allocation | 1,024 RAM |
| Sparse queue | 384 RAM |

The lookup block occupies 10,816 bytes including80 bytes of internal alignment.
The PRG is 38,437 bytes including address gaps. Its end-exclusive address is
`$9e24`, below I/O. The source contains no 8 KiB ratio tables, full-frame glyph
cache, font search or runtime projection.

```text
queued native PRG SHA-256
d8665b5c2efbf994ad8616567ab00c40432108ec39bb3225a970ec6b01cdaa2f
```
