# Original C64 Stage 2 source

This terrain is the complete original **The Great Giana Sisters** C64 Stage 2,
decoded from its original map-compression stream. It is not a hand-drawn level.
Stage 1 inputs and generated assets remain unchanged.

## Original data

The preserved source is the same [original D64](https://github.com/Zibri/The-Great-Giana-Sisters-C64-D64/blob/f99e2b9477badce359ad068d7b3f5f981082a73c/The%20Great%20Giana%20Sisters%20ORIGINAL.d64)
documented in [LEVEL1-SOURCE.md](LEVEL1-SOURCE.md). Its directory file `1` loads
at `$0820` and has SHA-256
`0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880`.
The pointer at `$6002` selects Stage 2's stream at `$62BE`.

| Retained file | Original addresses | Bytes |
| --- | --- | ---: |
| `original-level2-stream.bin` | `$62BE..$643A` | 381 |
| `original-level2-block-pointers.bin` | `$9200..$9261` | 98 |
| `original-level2-block-data.bin` | `$9286..$9494` | 527 |
| `original-level2-map.bin` | Decompressed map at `$AC00..$BFFF` | 5,120 |

`original-level2-source.json` records the retained slices' SHA-256 values.
The decompressed map's SHA-256 is
`2a2b29e84ae20b88172fe7ec4d23f2531360403ca8b9c8365a5a29f211bc487c`.
The original charset at `$C000..$C7FF` and character attributes at
`$AB00..$ABFF` are shared unchanged with Stage 1.

Each stream record contains block ID, destination offset low/high, horizontal
repeat count, and vertical repeat count. `$FF` ends the stream. The destination
is an offset from `$AC00`, not an absolute address. Repeat counts are literal;
the repeated blocks abut. The block pointer is read from `$9200 + 2*ID`.
Each block starts with width-minus-one and height-minus-one, followed by
row-major character IDs. All 76 records are decoded on every offline rebuild.
The original decompressor is also documented by the native port's
[`decompress_stage_sub_9936`](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/enemy.rs).

Original palette routine `$0D39` uses stage-minus-one to index background table
`$604E`, shared multicolor tables `$6075/$609C`, and underground flag `$60C3`.
Stage 2 therefore reads black 0 from `$604F`, pink 10 from `$6076`, red 2 from
`$609D`, and underground flag 1 from `$60C4`. The native game's Stage 2 music
cue remains 1, so this demo continues the same native music across the change.

## TV conversion

The full 256×20-character map is rendered using the original charset and
attribute bit 3 to select hires or multicolor characters. The complete
2,048×160 physical-pixel playfield becomes 1,024×64 physical pixels, using the
same centered nearest sampling as Stage 1: horizontal scale 1/2 and vertical
scale 2/5. No source map rows or columns are cropped. Fine artwork and aspect
are approximated by this reduction.

The TV shares the surrounding scene's brown global background 9. Stage 2's
original black background becomes brown; pink 10 and red 2 remain separate
shared colors. Hardware codes are 0=brown9, 1=pink10, 2=red2, 3=green5/yellow7
cell accent, with screen byte `$A2`. Empty-background pixels use code 0.
Other colors choose the nearest RGB entry among these five colors using the
retained Peptoette A palette. The receipt records every source-color mapping.

There are 181 deduplicated 4×8-multicolor-pixel patterns (1,448 bytes) and a
128×8 map (1,024 bytes). All 32,768 packed codes are reconstructed from these
two final assets during preparation. `terrain-level2.asm` places patterns at
`$1000`, the map at `$1600`, and four 512-byte accent tables at `$B200..$B9FF`.
These pattern/map addresses are CPU data; the VIC does not fetch them directly.

The four accent tables use the established Stage 1 perspective geometry and
phase/column layout: offset `phase*128+worldColumn`, with bit 0 for row 0.
Yellow wins a cell when its pixel count is nonzero and at least the green
count. Mixed green/yellow windows number 222 for regular sampling and
194/204/204 for perspective regions 0/1/2. These are hardware color
approximations; source pixel positions are retained.

The existing 12 black-mask character cells require color RAM 0. Their visible
lines therefore darken source code-3 accents to black. Across the full world,
regions 0/1/2 contain 75/87/21 unique reduced accent samples in these cell rows,
or 300/348/84 occurrences across all fine-scroll windows. The importer records
these losses explicitly and keeps the original packed codes unchanged.

## Offline rebuild

```sh
python3 giana/tools/prepare-level2.py
```

The default uses only the retained source slices, shared charset/attributes,
and display palette. It requires no network, game execution, or cached D64.
The existing Stage 1 preparer supplies the shared, unchanged TV geometry.
To re-extract the retained compression slices from the verified original file:

```sh
python3 giana/tools/prepare-level2.py --program /path/to/original-file1.prg
```

`level2-import.json` contains dimensions, palette decisions, reconstruction
proof counts, perspective color limitations, and generated asset hashes.
The original game and data retain their original ownership.
