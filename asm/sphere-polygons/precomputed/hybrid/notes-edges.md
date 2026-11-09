# Exact edge overlays

`edges.cjs` exports two codecs with `encode(screen)` and `decode(payload, outputScreen)`. An edge cell is exactly a screen code other than 0 or 15. The decoder changes only those cells and preserves the supplied background everywhere else. The fill layer may therefore choose either fill value beneath an edge glyph.

Both formats include a two-byte little-endian record count in every frame. Records write each edge exactly once. There are no hole cells, implicit palettes, shared stroke tables or hidden frame metadata.

## Straight horizontal and vertical runs

`edges-hv-best` uses a 16-bit little-endian record header:

- Bits 0–9: absolute screen offset, 0–999.
- Bits 10–14: character count minus one, 0–31.
- Bit 15: direction, 0 for right (`+1`) and 1 for down (`+40`).

The header is followed by one raw glyph byte per character. Horizontal runs cannot cross character-row boundaries. A contiguous horizontal run longer than 32 characters is split.

The encoder chooses the shortest result among four covers: all horizontal, all vertical, and two longest-run mixed greedy covers with opposite direction tie-breaks. All four share the same wire format. This is the best of those candidates, not a claim of globally optimal horizontal/vertical covering.

## Monotone right/down paths

`edges-monotone-minpaths` treats edge cells as a DAG with arcs to an adjacent right or down edge cell. Maximum bipartite matching yields a vertex-disjoint path cover with minimum path count. Every monotone path fits in 64 cells on the 40×25 screen.

Its 16-bit little-endian header uses:

- Bits 0–9: starting screen offset.
- Bits 10–15: character count minus one, 0–63.

The record then stores all raw glyph bytes, followed by `ceil((count−1)/8)` direction bytes. Direction bit zero means right; one means down. Bits start at the least-significant bit, with one bit for each transition. A one-cell path has no direction bytes.

Four deterministic maximum matchings are considered, varying right/down preference and node order. The smallest serialized result is retained. The number of paths is globally minimum, but the byte count is not claimed to be globally optimal: direction-byte rounding also matters.

## Measured payload sizes

The shared corpus contains 256 complete frames per model, beginning at yaw/pitch/roll `(0,24,0)` and advancing by `(2,1,1)`. Values below include each frame's record count, every record header, all glyph bytes and all path direction bytes. They exclude the fill payload, the combined container framing and shared font; the parent study counts those separately.

| Model | Codec | Mean bytes/frame | Maximum | Total, 256 frames | Mean records |
| --- | --- | ---: | ---: | ---: | ---: |
| Checker | Straight H/V | 341.891 | 387 | 87,524 | 77.398 |
| Checker | Monotone paths | 354.113 | 395 | 90,653 | 61.977 |
| Football | Straight H/V | 200.758 | 231 | 51,394 | 48.660 |
| Football | Monotone paths | 217.574 | 253 | 55,699 | 43.262 |

Checker frames contain 185.094 edge cells on average; football frames contain 101.438. Monotone paths reduce record counts, but their direction bytes outweigh that header saving. Choosing H/V or paths per frame with an additional one-byte mode tag also loses on average: 342.680 bytes for checker and 201.742 for football.

## Validation and limits

All 512 real frames passed both codecs against three backgrounds: all zero, all solid, and a nonconstant arbitrary byte pattern. All 3,072 overlays restored every exact edge glyph and preserved every non-edge cell. Synthetic cases include no edges, solid fill, a full edge grid, 40-cell horizontal runs, 25-cell vertical runs, a 64-cell monotone path and sparse randomized grids. The path count was also checked against an independent exhaustive matcher for all 512 subsets of a 3×3 grid.

`build/edges-report.json` records corpus hashes, the codec source hash and per-frame byte counts. These are offline compression and decoder measurements. No C64 decoder, native code-size measurement or timing result is implied. Per-record glyph compression was not added.
