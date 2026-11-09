# Single-front-buffer HD64 player

This player applies the smooth checker movie's lag-one deltas directly to the
visible `$0400` character screen. It uses one screen and the unchanged
2,048-byte font at `$2000`. There is no front-to-back screen copy, decoded-frame
cache, second screen, geometry calculation or pixel bitmap during playback.

This is the default playback implementation: **50.124529 FPS** measured in PAL
VICE, with all194 actual field images pixel-exact. It retains the same72-face
checker and64 stored poses. Yaw advances0.9375° per displayed image, with pitch
22° and roll12°: a physical turn takes about7.66 seconds, while the60° symmetry
loop lasts about1.28 seconds. The [legacy double-buffered delta player](../delta/README.md)
remains available as the unchanged25.062 FPS comparison.

The stream already describes screen positions in ascending order. A skip leaves
the existing character unchanged; literal and repeat packets replace only their
ordered destination cells. The visible screen itself supplies the exact `t−1`
reference. Both players use the same `t−1` patches; the speed gain removes the
CPU synchronization copy rather than changing to a `t−2` encoding. Synchronized writes begin in the lower border so that each affected
character row can be updated before its next VIC fetch.

## Sources and loop closure

The player imports the existing 15,169-byte
`checker-64-smooth-delta1-lag1.hd64` unchanged. It contains one initial key and
63 predictive images. A separate `checker-closing.delta` contains a two-byte
little-endian payload length followed by the 252-byte exact `63 → 0` patch,
254 bytes total. Both are produced by the shared asset preparation.

The complete immutable source therefore totals **15,423 bytes**. The closing
patch avoids decoding or copying a cached key on every loop. After applying it,
the player restores the original stream pointer to predictive image 1.

Startup decodes the actual initial key into `$0400` while the display's DEN bit
is off. It then enables display on a lower-border boundary. The first timed
frame-zero render is an explicit no-op: its already decoded key is allowed to
scan completely before `frame_done`. Every later frame zero is a real closing
patch, not a no-op or screen copy.

## Raster and checkpoint order

`wait_boundary` first waits for raster bit 8 to become low, then for it to become
high. This selects the next PAL line-256 boundary. After an update finishes, the
player waits for that boundary before reporting `frame_done`; the complete
visible scan of that frame has then finished. The next update begins immediately
after the checkpoint at the same lower-border boundary.

The order is:

```text
render_start (upcoming frame_index, before its first screen store)
ascending delta stores
render_end / wait_start
wait_boundary: next line256
frame_boundary / frame_done (completed visible frame_index)
advance frame_index
next render_start
```

`front_screen_hi` and `back_screen_hi` both remain 4, and `$d018` remains `$18`.
There is no VIC screen-bank flip. Exposed store checkpoints are `literal_store`
and `repeat_store`, with their base destination pointer at `$0e/$0f`.
`key_store` and `key_edge_store` identify the display-disabled startup writes.
`wait_raster` aliases `wait_boundary` for tooling compatibility.

Correct RAM output alone is insufficient for a visible-screen update: the
stores must also precede the relevant fetch deadlines. The independent
[`beam-trace.py`](beam-trace.py) and [PAL/scanout proof](notes-beam.md) address
that timing separately. Native FPS and visible-image claims belong to the PAL
proof, rather than to the plain instruction counts below.

The independent assembled beam trace passed 194 images and 31,082 timed stores.
With a conservative allowance of 1,075 VIC-stall clocks and 63 clocks of start
jitter per field, the smallest remaining fetch margin is 1,524 clocks. The
largest bounded update is 16,503 clocks, below the 19,656-clock PAL field. These
are explicit timing bounds, separately recorded in `build/beam-report.json`;
actual VIC scanout is checked by the native proof.

## Actual PAL scanout result

The [native receipt](../../results/front-delta/verification.json) passed194
consecutive visible fields and three loop wraps. All194 actual VIC PNGs match
the reference exactly: **12,416,000 active pixels**, plus194,000 screen-memory
bytes and397,312 immutable font bytes. Every update starts and every completed
scan is captured on raster256; no intermediate field is skipped and no
adjacent-frame screenshot substitution is accepted. The complete15,423-byte
source stays unchanged. See [notes-beam.md](notes-beam.md) for the scanbuffer
capture method and its distinction from final-RAM checking.

| Measured PAL clocks | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| Steady update,193 updates after cold frame0 | 11,449 | 13,617.93 | 16,177 |
| Field/presentation interval,193 intervals | 19,650 | 19,656.005 | 19,662 |

Presentation is **50.124529 FPS mean**,50.124542 median, including raster wait.
The initial timed frame0 no-op takes15 clocks; the real closing-frame0 update
takes13,951 clocks at each wrap. All rendering clocks include VIC stalls.

The independent [beam deadline receipt](../../results/front-delta/beam-report.json)
traces31,082 ordered stores and retains at least1,524 clocks of conservative
fetch margin after allowing1,075 VIC-stall clocks and63 clocks of start jitter.
The deadline trace and actual scanout proof agree for the frozen movie. Music
and IRQ work are absent; arbitrary added work has not been timing-verified.

## Build and assembled-code proof

From the repository root:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/player/prepare-assets.cjs
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/player/front-delta/build.sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/player/front-delta/host-smoke.py
rtk proxy python3 asm/sphere-polygons/precomputed/hybrid/player/front-delta/verify-pal.py \
  --frames 194 \
  --expected-program-sha256 196d57512765fb2902009b2573ab5cf40ec3cdbedeb85f94a4ee6e3a12b31277
```

`build.cjs` assembles `main.asm` and writes `build/native-source.bin`, the exact
HD64 file followed by the length-prefixed closing patch. The native
`animation`/`animation_end` range encloses those same bytes for immutable-source
verification.

The assembled proof passed **194 complete character images and three closing
loop transitions**, comparing 194,000 screen bytes exactly. It checks:

- every timed screen store has a strictly larger address than its predecessor;
- all timed stores come from the literal or repeat instruction and fall within
  `$0400–$07e7`;
- the program makes no stores to the unused `$0c00–$0fff` screen region;
- the first timed key image performs no screen copy or stores;
- font and both encoded sources remain unchanged;
- unused screen bytes stay empty and the one-screen VIC setup remains fixed.

The proof bypasses only the raster polling subroutine because plain py65 has
no VIC. `build/host-smoke.json` records the result, and `build/write-trace.json`
records each update's stores with instruction-completion cycles. It does not
claim native FPS or beam safety.

| Actual update work, after the cold startup image | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| CPU instruction cycles | 11,019 | 13,010.93 | 15,365 |
| Character stores | 111 | 161.05 | 228 |

The closing patch takes 13,306 instruction cycles. Startup costs 86,873 cycles,
including the initial key and screen/color setup, before timed updates. These
figures exclude VIC stalls, raster waiting and presentation. The update cost
includes packet parsing, skips, literal/repeat writes and pointer resets.

## Footprint

| Loaded content | Bytes |
| --- | ---: |
| Player code and state at `$3000–$3322` | 803 |
| Original HD64 movie | 15,169 |
| Length-prefixed closing patch | 254 |
| Fixed font | 2,048 |
| BASIC startup | 13 |
| **Meaningful loaded bytes** | **18,287** |

The complete PRG is **26,688 bytes**, including the load address and address
gaps. Encoded source occupies `$3400–$703e`. Runtime storage is one 1,024-byte
screen, 60 bytes of startup fill scratch at `$1000`, 30 reserved zero-page
bytes, and the existing color RAM. No 1,024-byte key cache or second screen is
used by the program. Code and emitted data remain below I/O and vectors.

Frozen PRG SHA-256:
`196d57512765fb2902009b2573ab5cf40ec3cdbedeb85f94a4ee6e3a12b31277`.
Combined encoded-source SHA-256:
`cff2690a827a9a91e50976bd795a37ae029774cec740faf14e0f2be2de102d1c`.
