# Compact native lag-one delta player

This player decodes the smooth 64-image checker loop from the actual
`checker-64-smooth-delta1-lag1.hd64` stream. It uses the unchanged 256-glyph font
and alternates the `$0400` and `$0c00` character screens. There is no geometry,
bitmap rendering or host-supplied decoded animation during playback.

The target is approximately 25 displayed images per second on PAL, which allows
the small decoder to retain a full screen-copy loop. After rendering, the player
waits for the next PAL raster wrap and swaps screens. Predictive images need
two PAL fields; the cheaper cached first image waits one additional wrap to
preserve the same cadence. Actual PAL timing and presentation results are recorded
by the shared [native player verification](../README.md). The instruction counts
below are not an FPS measurement.

## Stream and screen synchronization

The fixed HD64 stream has a 14-byte header, 50 bytes of circle-layout metadata,
one initial key image and 63 predictive images. Each image starts with a
little-endian 16-bit payload length; bit 15 identifies a key image. The selected
patch codec is `delta-packets64`, codec ID 1, with reference lag 1. Packet bits
7–6 select skip, literal or repeat, and bits 5–0 store length minus one for
1–64 character cells. Skips retain the reference cell. Literals and repeats
write exact glyph values, including empty or full cells that replace old edges.

Before every predictive image, the player copies all 1,024 bytes of the current
front screen to the alternating back screen. This supplies the actual `t−1`
reference despite double buffering. It then parses the image header and applies
the real packet stream to that back screen. The synchronization copy, header
parsing, packet decoding and writes are all inside `render_start` to `render_end`.

Startup decodes the real first key image using its PackBits fill and edge-mask
payload, then caches that decoded screen once. Frame zero and every loop wrap
copy this cache into the back screen; this per-image copy is timed. Only the
initial key is cached. The first key decode and initial screen/color setup occur
before playback. The fixed input has no later keys; an unexpected key tag during
predictive playback is rejected.

## Build and host proof

Prepare the shared assets from `player/`, then build this directory:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/player/prepare-assets.cjs
rtk proxy sh asm/sphere-polygons/precomputed/hybrid/player/delta/build.sh
```

The build writes `build/player.prg`, `build/main.sym` and assembler debug data.
It validates the fixed stream's dimensions, codecs, lag, first key tag and
15,169-byte size. The immutable input SHA-256 is
`02b30be1cfce012df591149371e357d5e1c1a3f948f5dd6f2b5f867c35dadc70`.

The included assembled-code smoke check uses py65 and the separately generated
verification reference screens:

```sh
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 \
  asm/sphere-polygons/precomputed/hybrid/player/delta/host-smoke.py
```

The proof executes the actual PRG through 194 presented images, including three
wraps, and compares all 194,000 screen bytes exactly. It checks that the font,
encoded HD64 stream and key cache remain unchanged, the front screen remains
unchanged during rendering, unused screen bytes stay empty, and the VIC screen
selection follows the front buffer. Plain py65 has no VIC, so the test bypasses
only the raster-wait subroutine. The result is written to `build/host-smoke.json`.

Measured CPU instruction cycles from this proof:

| Work | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| Predictive image, including full synchronization copy | 21,675 | 23,677 | 26,051 |
| Cached first image, including loop wrap | 10,588 | 10,588 | 10,588 |

Startup costs 102,058 instruction cycles, including decoding and caching the
first key. These figures exclude VIC stalls, interrupts, raster waiting and
presentation. The root PAL verifier measures those separately.

## Actual PAL verification

The shared verifier passed 194 displayed images and three loop wraps in normal
PAL VICE. All 1,000 character codes matched the reference on every image, the
font and serialized source remained unchanged, and three actual VIC screenshots
matched exactly. The verifier's owned emulator process was closed afterward.

| PAL clock measurement | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| Rendering, including VIC stalls | 11,315 | 24,671.12 | 27,549 |
| Presentation interval, including raster waits | 39,302 | 39,312.031 | 39,320 |

Measured presentation rate was **25.062251 FPS mean**, with a 25.062271 FPS
median. The extra cached-key raster wait preserves the same two-field cadence
at the loop boundary. This proof used PRG SHA-256
`e2ee27741a40e22adefff26f2cf4d6dc7e162dd9731cc574e8fdde8489ba6f8f`.

## Memory and size

| Region | Purpose | Bytes |
| --- | --- | ---: |
| `$0002–$001f` | Decoder pointers and scratch | 30 |
| `$0400–$07ff`, `$0c00–$0fff` | Alternating screen buffers | 2,048 |
| `$1000–$103b` | Startup key's unpacked fill bits | 60 |
| `$1400–$17ff` | Decoded initial-key cache | 1,024 |
| `$2000–$27ff` | Fixed mathematical font | 2,048 |
| `$3000–$3381` | Player code, state and shared copy loop | 898 |
| `$3400–$6f40` | Entire serialized HD64 stream | 15,169 |

The BASIC startup is 13 bytes. Meaningful loaded code, font and encoded data
total 18,128 bytes including that startup. The actual PRG is 26,434 bytes because
it includes the address gaps and load address. The 1,084-byte key cache/fill
scratch and 30 zero-page bytes are runtime storage, additional to the shared
screen buffers and color RAM. Code and load data stay below I/O and vectors.

The exported measurement labels are `render_start`, `render_end`, `frame_done`,
`frame_index`, `frame_counter`, `front_screen_hi`, `back_screen_hi`, `animation`
and `animation_end`. At `frame_done`, the index identifies the image that has
just been displayed; it advances afterward.

For the format's offline size comparison and the distinction between lag-one
and lag-two streams, see the [hybrid study](../../README.md). Native delta
playback adds explicit synchronization work to the smaller 15,169-byte stream;
compressed bytes alone do not determine playback cost.
