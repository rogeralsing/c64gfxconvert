# Alternating fill runs with edge and ordinary-cell literals

This is an offline size study. Every frame is independent and starts with black glyph 0 as its current fill. White is glyph 15. The encoder and decoder operate on exact character codes, with no approximation, hidden dictionaries, or inter-frame history. No C64 playback speed is claimed.

`alternating.cjs` exports `encode`, `decode`, `encodeValues`, `decodeValues`, `variants`, `syntheticChecks`, and `reportCorpus`. The full-screen API requires exactly 1,000 output bytes. The generic value API accepts an explicit known output length, so a separately accounted layout container can pack cropped sequences.

## Escaped alternating grammar

| Bytes | Meaning |
| --- | --- |
| `1..254` | Emit that many copies of the current fill, then toggle black/white. |
| `255` | Emit 255 copies of the current fill without toggling. This continues long runs. |
| `0,0` | Toggle the fill without emitting a cell. |
| `0,g` where `g` is neither 0 nor 15 | Emit that exact edge glyph; do not toggle. |
| `0,15,n` followed by values | Emit an unrestricted literal block; do not toggle. `n=1..255` gives its length; `n=0` means 256 values. |

No terminator is emitted. Decoding stops at the known output length, and the decoder rejects trailing bytes, truncation, or output overruns. The edge-only variant disables unrestricted literal blocks but uses the same decoder grammar.

## Strict paired grammar

Every packet is `[runLength][literalCount][literalValues...]`. Both lengths are unsigned bytes from 0 through 255. Emit `runLength` copies of the current fill, toggle the fill even when that length is zero, then emit exactly `literalCount` literal values. A zero literal count means no literal values.

The unrestricted version permits all character codes in the literal section, including a genuine blank or full cell. Consuming such a cell can repair the fill phase before the following run. It never inserts an extra cell: the literal must match the next actual source cell, and the following run is correspondingly shorter. The comparison variant restricts the literal section to nonbinary edge glyphs.

Run 255 still toggles in this grammar. Long same-color runs may therefore require an additional `[0,0]` packet to restore the phase. Consecutive edge groups likewise use zero-length runs when needed.

## Optimization and validation

The encoder uses dynamic programming over source position and fill phase. It minimizes the complete serialized payload, including every tag, length, and zero-length phase change. Sliding minima make unrestricted literal choices efficient. The decoder is a separate packet parser and does not use the encoder's transitions or optimization tables.

All 256 frames of each model round-trip exactly for all four variants: 2,048,000 compared character bytes. Synthetic cases include empty and full frames, 1,000 adjacent edge glyphs, alternating binary cells, long runs, arbitrary glyph bytes, and parity repair by consuming a real blank or full cell. An independent shortest-path enumeration also verified optimal byte counts for 4,372 short cases. Malformed payload checks cover truncation, output overrun, and trailing data.

The blank-repair example costs 20 bytes with unrestricted strict pairs versus 23 bytes with edge-only pairs. Its full-cell counterpart costs 22 versus 25 bytes. These totals include the complete 1,000-cell synthetic frame payload.

## Full-screen corpus results

The following payload sizes come from actual emitted byte arrays. Container totals add the shared study's two-byte payload length per frame and 12-byte shared header. The fixed 2,048-byte font and optional random-access table are separate.

| Format | Checker payload | Football payload |
| --- | ---: | ---: |
| Escaped alternating, literals allowed | 118,436 | 73,878 |
| Escaped alternating, edge-only | 140,304 | 77,061 |
| Strict pairs, ordinary literals allowed | **104,719** | **68,368** |
| Strict pairs, edge-only literals | 121,288 | 70,904 |

For the best unified format, the 256-frame container excluding the font is 105,243 bytes for the checker sphere and 68,892 bytes for the football. Mean payloads are 409.06 and 267.06 bytes per frame. Allowing ordinary blank/full literals saves 16,569 and 2,536 payload bytes compared with strict edge-only pairs.

These figures use the full 1,000-cell layout. Other fill/edge schemes and cropped-layout containers are measured separately by the shared study; this result is not a claim that the unified format is globally smallest.

Run:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/alternating.cjs
```

The report, including input hashes and every frame size, is written to the ignored `build/alternating-report.json` beside the module.
