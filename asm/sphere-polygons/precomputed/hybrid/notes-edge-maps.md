# Edge masks and Rice gaps

`edge-maps.cjs` implements five actual edge overlay codecs. All preserve
every destination cell that is not an edge in the source. The decoder writes
only exact glyph codes other than 0 and 15. There is no assumption of smooth
paths, and no generic compression stage or uncounted palette.

All five codecs passed the 512-screen reference corpus. A destination filled
with a varying sentinel pattern verifies both exact edge reconstruction and
background preservation. Synthetic cases cover empty and solid screens,
adjacent edges, row boundaries, first/last positions, large gaps, dense maps,
and declared-circle rejection. In total **2,598,000 output cells** were checked,
including 38 valid synthetic codec/case combinations.
Known independent Rice bytes and malformed payload cases also passed.

## Actual serialized edge bytes

Every local header, compressed-mask length, glyph byte and Rice padding byte is
included. Each model has 256 frames.

| Format | Checker min / mean / max | Checker total | Football min / mean / max | Football total |
| --- | ---: | ---: | ---: | ---: |
| Full PackBits presence map | 269 / 302.469 / 330 | 77,432 | 190 / 216.367 / 241 | 55,390 |
| Circle PackBits presence map | 214 / 247.094 / 275 | 63,256 | 141 / 163.270 / 181 | 41,797 |
| Full raw presence map | 277 / 310.094 / 338 | 79,384 | 204 / 226.438 / 244 | 57,968 |
| Circle raw presence map | **212 / 245.094 / 273** | **62,744** | **139 / 161.438 / 179** | **41,328** |
| Rice-coded sorted gaps | 232 / 275.957 / 311 | 70,645 | 131 / 164.012 / 188 | 41,987 |

The raw circle map has the lowest corpus total for both models. Compressing the
circle presence map costs 512 extra checker bytes and 469 football bytes over
the complete sequence, including its required length prefix. Rice can save
bytes on some football frames but costs 659 bytes more than the raw circle map
over its complete 256-frame sequence. No per-frame format selection is assumed.

The circle codec exports `requiresLayout: 'circle'`. Its **50-byte shared row
layout metadata** must be charged once by the combined container. The full map
and Rice positions need no layout metadata. Frame lengths, global container
header, fill payload and shared font remain outside these edge payload figures.

## Presence-map format

Exports are `edges-map-packbits-full` and `edges-map-packbits-circle`.

1. A one-byte length gives the compressed presence map size.
2. That many bytes contain standard PackBits applied to packed presence bits.
3. Raw edge glyph codes follow in increasing screen position order.

Every selected map cell is fixed: actual edge cells become one and all others
become zero. The map uses the existing `wildcard-packbits` packet encoder with
only glyphs 0 and 15, so **there are no wildcard map cells**. Unused final-byte
padding has no associated cell. A literal map cannot exceed 126 bytes for the
full screen, so the one-byte prefix always suffices for these layouts. The
decoder derives the edge count from set bits, then consumes exactly that many
glyph bytes. Non-edge destination cells are untouched.

The circle has 475 selected cells and a 60-byte raw mask. The encoder rejects
any edge outside that declared layout. A cropped fill and the circle edge map
can share the same metadata; it should not be charged twice.

The two raw controls, `edges-map-raw-full` and `edges-map-raw-circle`, store a
fixed 125-byte or 60-byte presence bitfield directly, followed by the raster
ordered edge glyphs. Bits are most significant first and final padding is zero.
There is **no mask-length prefix**: the chosen layout determines its fixed byte
count. The decoder derives the glyph count from the set mask bits and consumes
exactly that many raw codes. These controls show that mandatory mask compression
loses space on the already compact circle map.

## Rice-gap format

`edges-rice-gaps` starts with a little-endian 16-bit header:

- Bits 0–9 store the edge count, 0–1,000.
- Bits 10–12 store Rice parameter `k`, 0–7.
- Bits 13–15 are zero and reserved.

Sort the edge positions. Starting with previous position −1, encode
`gap = position − previous − 1`. Its quotient is that many zero bits followed
by a one; its remainder occupies exactly `k` most-significant-first bits.
The encoder tries all eight parameters and minimizes the resulting bit count,
which also minimizes its rounded byte count. After all positions, zero padding
extends to a byte boundary, followed by exactly one raw glyph byte per edge.

The count lets the decoder identify the end of the position bitstream without
another length field. It verifies the position range, exact byte boundary,
zero padding, reserved header bits and glyph count. Empty overlays are exactly
the two-byte zero header. All position and glyph information is in the payload.

## Reproduction

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/edge-maps.cjs
```

This verifies the corpus and synthetic cases and writes
`build/edge-maps-report.json`, containing source hashes, trajectory, every frame
size and aggregate statistics. The codecs use the shared API
`encode(screen)` / `decode(payload, outputScreen)`.

These are host packing and exact-decoding measurements. No native decoder,
C64 cycle count or playback FPS is claimed.
