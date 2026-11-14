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

The original blue sky becomes black. Other original colors are mapped to the
closest RGB color among black `$0`, brown `$9`, orange `$8`, and green `$5`,
using the same Peptoette A palette as the surrounding picture. The local
`peptoette-a.vpl` is an unchanged copy of `../../palettes/peptoette-a.vpl`.

The reduced image is divided into 4×8 multicolor-pixel storage tiles. Identical
tiles are deduplicated. These storage tiles do not redefine the original
objects: features can cross tile boundaries, and their positions come entirely
from the original map. The result contains 148 tiles, 1,184 bytes of graphics,
and a 128×8 map containing 1,024 one-byte tile IDs. No player or enemy sprites
are included.

## Rebuild

From the repository root, regenerate the two binary assets, `terrain.asm`, and
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
dimensions, palette mapping, tile usage, and output hashes.

The original game is by Rainbow Arts, with graphics by Manfred Trenz. The
original game data retain their original ownership.
