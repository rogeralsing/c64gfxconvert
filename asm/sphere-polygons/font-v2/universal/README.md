# Universal drawing font

One fixed 256-glyph charset intended to serve every scene — a systematic
"better than PETSCII" drawing vocabulary — instead of the per-film
frequency-reordered fonts. The parametric drawing sections are frozen; only a
trailing content section is optimized once, against a tile census spanning all
films.

## Slot map

| Slots | Section |
| --- | --- |
| 0 | empty |
| 1..8 | H:left thickness 1..8 (8 = full) |
| 9..15 | H:right thickness 1..7 |
| 16..22 | V:top thickness 1..7 |
| 23..29 | V:bottom thickness 1..7 |
| 30..85 | four complete 45-degree half-plane chains (all thresholds) |
| 86..141 | eight sampled 1:2 / 2:1 chains, stride 3 thresholds |
| 142..171 | H/V bands: 1px at each row/column, 2px at each offset |
| 172..175 | checker phases (2x2, 4x4) |
| 176..190 | Bayer 4x4 tones 1..15 |
| 191..255 | content glyphs, optimized once over the multi-corpus census |

Every ramp chain is contiguous and ascending in thickness, so a decoder can
draw a line as `code = chain.base + thickness` — "start char plus increment" —
with a fixed-point slope accumulator.

`font.cjs` builds the font deterministically. `optimize-content.cjs` runs the
census and the greedy content-slot optimizer. `line-encode.cjs` tests a
ramp-run opcode against the screen-order literal codec.

The corpora (ideal tiles and character screens) are generated artifacts under
`build/` of each film in the sphere-font worktree; this study reads them from
`UNIVERSAL_CORPORA_ROOT` (default: `../build` beside this directory).
Regenerate corpora with the documented per-film build commands
first.

```sh
rtk proxy node font.cjs
rtk proxy node optimize-content.cjs
rtk proxy node line-encode.cjs
```

## Census

The original eight corpora together contain only **271 unique ideal tiles**.
The ninth corpus, the flagship star, adds no new ideal tiles. The
content is heavily quantized, which is why one fixed font can cover it.

## Generic tax (d12 stride 3: 191 fixed + 65 content slots)

| Corpus | Error vs its own target |
| --- | --- |
| solid star | 0.0 px/frame (exact) |
| dithered star | 0.0 px/frame (exact) |
| glass star | 0.0 px/frame (exact) |
| glass diamond | 0.0 px/frame (exact) |
| tumbling star | 0.2 px/frame (0.00%) |
| glass outline | 0.4 px/frame (0.00%) |
| gradient dither cube | 0.4 px/frame (0.00%) |
| sphere-to-cube zoom | 299.1 px/frame (3.74%) |

Seven of eight corpora are pixel-exact or near-exact. The zoom film — measured
against its own fully-tuned 256-glyph font — is the one payer; its continuous
scaling creates band offsets the fixed sections only partially cover. Stride 2
(finer 1:2 sampling, fewer content slots) measures worse: the extra 32 content
slots beat the finer diagonal sampling (zoom 4.76% with 33 content slots vs
3.74% with 65).

## Ramp-run opcode: rejected for these films

With the universal font, a per-frame codec of greedy geometric ramp-lines
(fixed 5-byte ops, fixed-point slope walk, per-line 5% error budget) followed
by the screen-order literal codec was measured against the pure literal codec
on identical screens:

| Corpus | lines+literal | pure literal | Result |
| --- | ---: | ---: | --- |
| solid star (5% budget) | 211.6 B/f | 174.4 B/f | 21% worse |
| tumbling star (0%) | 206.4 B/f | 173.6 B/f | 19% worse |
| glass star (0%) | 261.1 B/f | 184.6 B/f | 41% worse |
| glass diamond (5%) | 246.4 B/f | 202.0 B/f | 22% worse |

The lines work exactly as intended (6-10 per frame, mean ~8 cells, captured
silhouette sweeps within the budget), but the changed cells of these renders
are screen-order contiguous, and the literal codec already encodes contiguous
runs at roughly one byte per cell with a shared header. A 5-byte line op only
wins when a single line replaces ten or more scattered cells, which these
frame deltas never produce. The measured loss also includes line-introduced
wrong glyphs that the literal pass must repair.

The ramp-run idea remains viable for content where changes are geometrically
aligned but screen-order scattered (wireframe drawing, fast full-silhouette
rewrites), or as a full-frame drawing format. It is rejected as a delta
refinement for these films.

## Status

The ramp-run codec remains a host-side study. The flagship star now uses the
fixed universal font in its native player and has PAL VICE verification;
see [the flagship build instructions](../three-scene/README.md#flagship-star-very-large-lit-endless-rotation).
Other per-film players retain their own fonts. The content optimizer is
greedy and does not claim a global optimum; receipts are in
`build/font-stride3.bin`, `build/content-rows-stride3.json`. The selected
2,048-byte font is also shipped as `../three-scene/universal-font.bin`.
