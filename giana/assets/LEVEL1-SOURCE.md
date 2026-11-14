# Original C64 Stage 1 source

The TV terrain comes from the original **The Great Giana Sisters** C64 Stage 1
map and character graphics. It is not a hand-drawn substitute level.

## Source and verification

The source disk is [`The Great Giana Sisters ORIGINAL.d64`](https://github.com/Zibri/The-Great-Giana-Sisters-C64-D64/blob/f99e2b9477badce359ad068d7b3f5f981082a73c/The%20Great%20Giana%20Sisters%20ORIGINAL.d64),
from the Zibri preservation repository at commit
`f99e2b9477badce359ad068d7b3f5f981082a73c`.

The downloaded D64 contains 174,848 bytes and has SHA-256
`6fffb9168171d5d8b6bc65b5a5f43f0eb5d29c7a495d2270a1dda8a525a7c15a`.
Its directory file `1` contains 63,443 bytes, including its `$0820` load address,
and has SHA-256
`0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880`.
That is the original-program hash independently recorded by the
[`giana-sisters-native` extractor](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-extract/src/lib.rs).
The original program file is uncompressed; its bytes are placed at `$0820`
without executing it or applying patches.

Only these graphics data slices are retained as build inputs:

| File | Original C64 addresses | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `original-level1-map.bin` | `$AC00..$BFFF` | 5,120 | `e75d388d6b80e7ec82064fc6a9309c16dadedf34a73425b52e4712be1fe7c99c` |
| `original-charset.bin` | `$C000..$C7FF` | 2,048 | `eb453a70a5c3cdf177e19868cdb663b8e0182e90a4368d78b25edbbbe24ea668` |
| `original-char-colors.bin` | `$AB00..$ABFF` | 256 | `74ccc485e71ad8505c1c30932f07f728624f822e9277fecb659f63209287966a` |

The map and color-table hashes also match the native port's
[extraction manifest](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-extract/src/derive.rs).
The port's [column-scrolling implementation](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/scroll.rs)
documents the 256-column, 20-row layout. Its
[character renderer](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-render/src/tiles.rs)
documents the original character color attributes and video-bank addresses.

## Reduction for the TV

The complete source playfield is 256×20 characters, or 2,048×160 physical
pixels. The offline preparer renders the original character data, including
the distinction between hires and multicolor characters. Stage 1 uses
background color 14 and shared multicolors 8 and 9.

The output is 1,024×64 physical pixels, or 512×64 multicolor pixels. Horizontal
scale is 1/2 and vertical scale is 2/5. Sampling uses the center of each output
pixel's source region. No source map rows or columns are cropped. The unequal
axis scales fit the complete map height into the TV; fine artwork is reduced.

The original light-blue sky keeps color `$E`. Other original colors are mapped to the
closest RGB color among brown `$9`, light blue `$E`, orange `$8`, green `$5`, and yellow `$7`,
using the same Peptoette A palette as the surrounding picture. The local
`peptoette-a.vpl` is an unchanged copy of `../../palettes/peptoette-a.vpl`.
Hardware pixel codes are 0 = brown, 1 = light blue, 2 = orange, and 3 = the cell accent.
The terrain shares the `giana5` picture's brown global background `$9` and uses
screen colors `$E8`. Both assembler constants are derived from the packed-code mapping.
The 2,417 sampled original black pixels become dark brown to keep three shared
colors and the existing green/yellow accent format.
The accent is green for bushes and yellow for pipes and bonus blocks. White
pipe highlights map to yellow. Plain brick graphics use orange and brown.

`level1-accents.bin` retains the green/yellow meaning independently of the
deduplicated patterns. Its 512 bytes contain four 128-column fine-scroll phases.
The byte at `phase * 128 + world_column` packs eight character-row flags, with
row 0 in bit 0. A set bit selects yellow; a clear bit selects green. Each flag
is computed from the corresponding four-pixel-wide, eight-line window in the
reduced source image, including wraparound and the fine-scroll phase. Yellow
wins when its count is nonzero and at least the green count; otherwise green wins.

There are no windows with mixed green/yellow accents across the four phases.
All 843 reduced accent pixels retain their semantic color at every fine-scroll
phase: 3,372 accent pixel occurrences are verified independently before the
patterns are deduplicated. Green bushes and yellow pipes/bonus blocks remain distinct.

The reduced image is divided into 4×8 multicolor-pixel storage tiles. Identical
tiles are deduplicated. These storage tiles do not redefine the original
objects: features can cross tile boundaries, and their positions come entirely
from the original map. The result contains 136 tiles, 1,088 bytes of graphics,
and a 128×8 map containing 1,024 one-byte tile IDs, plus the 512-byte accent table.
The terrain payload contains no actor pixels. Tiny original characters are
prepared separately; see [sprites-SOURCE.md](sprites-SOURCE.md).

## Fixed perspective trial

The TV uses four character-column regions with boundaries `[0, 3, 5, 7, 10]`.
The top edge therefore steps at columns 3 and 7; the bottom edge keeps its step
at column 5. All four regions share unchanged center lines 28–35.

| Region | TV columns | Black mask lines | Upper sampling | Lower sampling |
| --- | --- | --- | --- | --- |
| 0 | 0–2 | 0, 1, 63 | Lines 2–27 read source `y-2` | Lines 36–62 read source `y+1` |
| 1 | 3–4 | 0, 63 | Lines 1–27 read source `y-1` | Lines 36–62 read source `y+1` |
| 2 | 5–6 | 0 | Lines 1–27 read source `y-1` | Lines 28–63 keep their source line |
| 3 | 7–9 | None | Identity | Identity |

`terrain.asm` exports four compile-time source-row lists, the five column
boundaries, and three neighboring-region transfer lists. Each transfer row
finds the displayed row in the right neighbor with the same original source Y;
`-1` denotes a mask line. Every non-mask transfer is verified against both
source-row lists. The four black-character-row masks are `[$81, $81, $01, $00]`.

The regular terrain patterns, map, and accent table remain byte-for-byte unchanged.
Three separate 512-byte phase tables recompute the accent from the vertically
sampled semantic pixels:

| Region | Asset | Verified accent pixel occurrences |
| --- | --- | ---: |
| 0 | `level1-perspective-accents.bin` | 3,312 |
| 1 | `level1-perspective-middle-accents.bin` | 3,316 |
| 2 | `level1-perspective-right-accents.bin` | 3,368 |
| 3 | Regular `level1-accents.bin` | 3,372 |

All four use the same phase/column flag layout and have zero mixed-accent
windows. The three warped tables correct ten visible flag differences from
using the regular table unchanged. `TERRAIN_PERSPECTIVE_ACCENT_MAPS` lists their
assembler addresses in region order, with the regular table last.

The renderer reserves code 3 and color RAM 0 only in the 12 character cells
containing black mask lines. Their retained visible lines contain no green/yellow
accent pixels anywhere in the complete map at any fine-scroll phase. The masks
therefore lose no accent detail. The importer checks this condition separately
for each warped region before writing its table.

## Rebuild

From the repository root, regenerate the six binary assets, `terrain.asm`, and
the machine-readable `level1-import.json` receipt without network access:

```sh
python3 giana/tools/prepare-level1.py
```

To repeat the source extraction from the documented D64 as well:

```sh
python3 giana/tools/prepare-level1.py --disk /path/to/original.d64
```

The preparer verifies the original program and retained inputs by SHA-256. It
also reconstructs all 32,768 reduced multicolor pixel codes from the final tile
map and patterns to check their ordering. `level1-import.json` records the
dimensions, source and semantic colors, palette conflicts, tile usage, and output hashes.

The original game is by Rainbow Arts, with graphics by Manfred Trenz. The
original game data retain their original ownership.
