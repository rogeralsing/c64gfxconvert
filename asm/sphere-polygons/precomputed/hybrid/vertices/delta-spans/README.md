# Dynamic incremental geometry experiment

This bounded native experiment retains character-probe coverage between images,
decodes the old and new per-face SA64 spans, and updates only their interval
differences. It preserves the original 72-face checker geometry, 64 poses,
fixed font and exact output. It performs the geometry-difference calculation on
the 6502, rather than reading precomputed difference commands or a character
movie.

The assembled implementation is byte-exact, but **it is a performance loser**:
steady updates average 218,989.92 CPU instruction cycles, compared with
106,670.94 for the complete precomputed-span player. Comparing and decoding old
and new geometry costs more than the avoided fills in this implementation. It
is not selected as the playback default.

Final glyph computation runs entirely in hidden work RAM. Changed glyphs enter
a sparse three-byte command queue; only that short queue is written to the
front screen after a PAL line-256 gate. This prevents the expensive geometry
comparison from directly modifying an image during scanout. The assembled
queue trace passes conservative fetch deadlines. Actual PAL verification
measures **3.855735 FPS**, with all 66 presented update images pixel-exact,
including the closing transition. The character-delta player remains the
normal animation option.

## Retained state and mathematical update

Two small descriptor buffers retain each face's four-byte SA64 record and five
visibility bytes. The buffers swap roles without a descriptor copy. For each
face present in either pose, the native code decodes its old/new normalized
patterns into two pairs of 75-byte span arrays. It aligns their sample rows and
constructs up to two bands for `old interval − new interval`, then up to two for
`new interval − old interval`. Empty and disjoint intervals are handled
explicitly. Unchanged interiors do not receive coverage stores.

Each changed band becomes the same eight-probe masks used by the reference
rasterizer. Changed cells are recorded in a 1,000-cell dirty bitset. After all
faces finish, only marked cells pass through the existing glyph lookup and the
same per-cell strict circular-limb remap. The resulting glyph is compared with
the current screen; equal glyphs do not enter the queue. Each changed glyph is
stored as `{cellLow, cellHigh, glyph}`, in increasing cell order. After hidden
computation, the player waits for line 256 and flushes those commands in
strictly increasing screen-address order, then waits for the next line 256
before `frame_done`. The steady loop has no full coverage clear, full fill,
full 1,024-character resolve or screen-buffer copy.

## Source-specific XOR certificate

Using XOR for arbitrary overlapping white polygons would be incorrect. This
implementation instead requires a checked property of this exact fixed movie:
every one of its 64 final poses has at most one white-face contribution at each
of the 8,000 screen probes. `build.cjs` independently reconstructs every face's
probe masks and rejects any overlap, checking 512,000 endpoint probe positions.
It also requires the exact SA64 SHA-256:

```text
127c8f6e14d44c76de7acc3ebf22a57f76e8067df3cc30bc98a1a29d5227c162
```

Under that certificate, toggling the removed and added per-face masks produces
the exact final union: endpoint contribution counts are only 0 or 1, so parity
equals OR. During the sequential update, old/new faces can temporarily overlap
and parity need not equal the union; no glyphs are resolved until every face
has finished. The intermediate coverage remains hidden work RAM. This avoids
counter bitplanes, and is explicitly restricted to the certified movie.
Changing geometry or poses requires a new disjointness proof or an ownership
counter implementation.

## Build and assembled proof

The frozen SA64 assets must already be generated in `span-atlas/build/assets/`.
From the repository root:

```sh
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/vertices/delta-spans/build.sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/vertices/delta-spans/host-smoke.py
```

The assembled proof passes **66 images including `63 → 0 → 1`**, then two
additional updates that force the native 16-bit counter through
`$ffff → $0000 → $0001`: 68,000 coverage bytes and 68,000 screen bytes match
exactly. The font, lookup assets
and source stream remain unchanged. It checks that every steady coverage store
belongs to the counted add/remove mask operations, that the dirty bitset is
fully consumed, and that actual screen stores are strictly ascending. Plain
py65 bypasses raster polling and does not validate visible scanout.

`build/certificate.json` records the source hash and disjointness certificate.
`build/host-smoke.json` records the complete execution result and per-frame rows.
The tested PRG SHA-256 is
`09ea99de4c82abfc28a1b26aa18e7119158c0ad4987f517b9c8ff0b82132c961`.

A dedicated `display_initialized` flag permits direct screen stores only during
the first display-disabled initialization. It stays set independently of the
wrapping frame counter. The forced-wrap regression verifies that a counter
value of zero cannot restore cold-start writing during visible playback.

Warm glyph computation leaves the front screen unchanged. The actual front
stores occur only at `visible_store` in the gated flush. With an allowance of
1,075 VIC-stall clocks and 63 clocks of start jitter, the smallest per-store
fetch margin is 5,790 clocks. The maximum complete flush including those
allowances is 8,051 clocks, below the 19,656-clock PAL field. The maximum queue
is 327 bytes within its 512-byte reservation. These are explicit assembled
timing bounds; actual VIC scanout remains a separate check.

## Measured instruction work

The following steady figures exclude the cold initialization image and include
the real geometry difference at the closing transition:

| Per update | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| Complete CPU instruction cycles | 200,924 | **218,989.92** | 438,611 |
| Cells marked dirty | 70 | 96.88 | 307 |
| Nonzero add-mask operations | 48 | 77.05 | 776 |
| Nonzero remove-mask operations | 46 | 77.12 | 771 |
| Retained-coverage mask stores | 98 | 154.17 | 1,547 |
| Actual character-screen stores | 70 | **92.08** | 109 |
| Hidden glyph computation and enqueue cycles | 22,513 | 26,477.37 | 38,109 |
| Sparse queue bytes | 210 | 276.23 | 327 |
| Visible queue-flush instruction cycles | 4,448 | 5,845 | 6,913 |

An add/remove operation is one nonzero character-probe mask, not a pixel count
or whole character write. The closing transition can perform many cancelling
per-face operations because geometric face identities are permuted by the
checker's 60° symmetry, even though the displayed pattern almost matches.
Final glyph comparison suppresses the corresponding redundant screen writes.

The proof confirms the intended reduction in writes. It also shows why those
write counts alone do not establish a CPU saving: old/new pattern decoding,
row alignment, interval classification, dirty tracking and clipping still run.
The queue adds safety staging rather than a geometry-speed optimization. No
additional optimizer or format search was included after this bounded result.

## Memory and size

| Content | Bytes |
| --- | ---: |
| Native comparison, mask update and sparse resolve/flush code/state | 1,429 |
| Font and mask/remap assets, including new clip-offset lookup | 13,689 |
| Complete unchanged SA64 movie | 24,981 |
| BASIC startup | 13 |
| **Meaningful loaded bytes** | **40,112** |

The actual PRG is 46,486 bytes including load address and gaps, and all emitted
data ends below I/O. Runtime state is a 1,024-byte front screen at `$0400`,
1,024-byte retained coverage at `$1000`, a 128-byte dirty bitset at `$1400`,
two 256-byte descriptor-buffer reservations at `$1500/$1600` (149 meaningful
bytes each), four 75-byte span scratch arrays within `$0c00–$0dca`, and 58
reserved zero-page bytes. A 512-byte reservation at `$1700–$18ff` holds the
sparse queue; its measured maximum is 327 bytes. There is no coverage counter
plane or full-frame glyph cache.

Exported counters are `dirty_count`, `add_masks`, `remove_masks` and
`screen_writes`, all 16-bit. Standard render/decode/clear/edge/fill/resolve
checkpoints remain available. `clear_start/end` covers counter reset rather
than a framebuffer clear. `face_edges_start/end` decodes old and new spans;
`face_fill_start/end` computes and applies their interval differences.
`resolve_start/end` computes final glyphs without warm front-screen writes;
`flush_start/end` performs the gated sparse writes through `visible_store`.
Cold initialization writes directly while DEN is off.

## Actual PAL result

`../verify-delta-pal.py` verifies the frozen PRG against the explicitly bound
SA64 movie, original font, geometric coverage and character references. It
captures the actual VIC raster buffer at every completed presented update;
all 66 captures match exactly. Held physical fields are not individually
captured. The assembled write trace separately certifies that warm screen
writes occur only in the bounded ascending flush.

The 65 presentation intervals average 255,527.9538 PAL clocks, giving
3.855734706 FPS. Updates take 12–13 PAL fields, except the closing transition
which takes 25 fields. Hidden computation averages 225,255.2923 PAL clocks;
the maximum visible flush is 6,956 clocks. The receipt is
`build/pal-queued-proof/verification.json`, archived with all 66 scanout PNGs
under `../../results/vertices/delta-spans/`.
