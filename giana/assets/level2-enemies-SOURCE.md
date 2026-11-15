# Original C64 Stage 2 enemies

The additional enemy graphics and spawn records come from the verified original
**The Great Giana Sisters** C64 disk file `1`. The original program SHA-256 is
`0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880`;
disk provenance is recorded in [LEVEL2-SOURCE.md](LEVEL2-SOURCE.md).
The original native program is not needed for an ordinary offline rebuild.

## Retained source

`original-level2-enemies-source.json` lists each slice's original addresses and
SHA-256. Frame files concatenate complete, unchanged 64-byte source sprites.

| Input | Original frames or addresses | Bytes |
| --- | --- | ---: |
| `original-level2-enemies-bee.bin` | `$66,$67` at `$D980,$D9C0` | 128 |
| `original-level2-enemies-bee-right.bin` | `$69,$6A` at `$DA40,$DA80` | 128 |
| `original-level2-enemies-crab.bin` | `$71,$72,$74,$75` at `$DC40,$DC80,$DD00,$DD40` | 256 |
| `original-level2-enemies-slinky.bin` | `$9A,$9B,$9C,$9F,$A0,$A1` at `$E680,$E6C0,$E700,$E7C0,$E800,$E840` | 384 |
| `original-level2-enemies-spawns.bin` | `$3D7A..$3D98` | 31 |
| `original-level2-enemies-descriptors.bin` | Four 23-byte records at `$306B,$308D,$30C0,$30E2` | 92 |
| `original-level2-enemies-y-table.bin` | `$3205..$3220` | 28 |

The stage pointer at `$3D22` selects `$3D7A`. Its ten records contain
`storedColumn,rowParameter,type`, followed by `$FF`. Eight describe enemies:

| Source entry | Type | Appearance | Stored column | Row | Canonical TV world-left MC X | Original map-relative top Y |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 0 | 5 | Horned owl | 40 | 15 | 76 | 59 |
| 1 | 2 | Crab | 53 | 21 | 102 | 107 |
| 2 | 7 | Green spring/slinky creature | 77 | 16 | 150 | 67 |
| 4 | 2 | Crab | 112 | 15 | 220 | 59 |
| 5 | 7 | Spring/slinky creature | 148 | 23 | 292 | 123 |
| 7 | 7 | Spring/slinky creature | 185 | 15 | 366 | 59 |
| 8 | 7 | Spring/slinky creature | 192 | 15 | 380 | 59 |
| 9 | 0 | Flying bee | 236 | 11 | 468 | 27 |

Entries 3 and 6, at columns 97 and 171, have type 11. The native spawner
selects their actual object type through `$3032 + playerPowerupState`; these
are dynamic pickup sites and are kept separate from the eight enemy records.
The visual names above describe the original art rather than asserting official names.

## Coordinate and movement interpretation

The original spawner compares `storedColumn-1` with `$21`, the rightmost map
column. The initial rightmost column is 39. It places an enemy at hardware X
335, while the character matrix begins at hardware X 24 and has fine scroll F.
Consequently its original map-relative left edge is
`8*(rightmostColumn-39)+335-24-F = 8*storedColumn-9-F` physical pixels.
The demo uses canonical post-wrap F=7, yielding `8*storedColumn-16` source
pixels, or `2*storedColumn-4` TV multicolor pixels. Other native fine phases
offset this initial position by up to seven source pixels.

The Y table contains `rowParameter*8`; the spawner adds 29 for hardware Y.
The map starts at screen row 5, hardware Y 90, so source-map top Y is
`rowParameter*8-61`. Vertical scale is 2/5. The receipt preserves the exact
source Y and its scaled fraction instead of treating a spawn row as a ground
height. Grounded objects can fall and move after spawning.

The [native enemy routines](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/enemy.rs)
document spawner `$2276`, normal spawn `$2444`, movement `$255A`, tile probes
`$26ED`, and animation `$2831`. All four types use movement kind 0. Owl, crab
and slinky use support mode 0 and horizontal speed 1 source pixel per update;
the bee uses mode 2 and speed 2, skipping gravity. All initially face left.
The walking animation reload counter is 6, giving a seven-update pose hold.

For source left/top `(x,y)`, native tile probes use base column
`floor((x+3)/8)`, side row `floor((y+15)/8)`, and bottom row
`floor((y+23)/8)`. Side probes sample base/base+2; bottom probes sample three
columns. Collision bit 0 denotes solid. Without any bottom support, mode 0
adds four source pixels to Y. A solid leading side reverses direction. These
records do not use the separate ballistic enemy branch: the slinky's stretching
comes from its three-pose artwork. The demo's movement tables may adapt this
behavior to the reduced terrain and TV; these retained inputs do not implement
a complete original game engine.

## Reduced sprite data

`level2-enemies.bin` contains fourteen 64-byte multicolor sprites:

| Global actor frames | Source frames | Direction | Individual color |
| --- | --- | --- | ---: |
| 10–11 | `$66,$67` | Bee's left-facing poses | 7 |
| 12–13 | `$71,$72` | Crab left | 1 |
| 14–15 | `$74,$75` | Crab right | 1 |
| 16–18 | `$9A,$9B,$9C` | Slinky left | 5 |
| 19–21 | `$9F,$A0,$A1` | Slinky right | 5 |
| 22–23 | `$69,$6A` | Bee right | 7 |

The shared multicolors remain 10 and 2; code 0 is transparent. The existing
owl frames 8/9 and their individual color 1 remain in the unchanged old atlas.
The bee's mode 2 still checks side walls and changes direction; its two native
right-facing frames are appended after the slinky poses to preserve frame IDs.

Area votes combine four source physical X pixels into one output multicolor
pixel and 2.5 source Y pixels into one output row. Crabs use 3.5 source rows
per output row, giving a six-row canvas with five opaque rows. This extra
compression lets eight-row Giana pass above them in the reduced fourteen-row
tunnels; the ordinary nine-row canvas makes that physically impossible.
At least 50% opaque coverage
is required. Ties prefer the individual color, then the larger C64 color index.
All original 21 source rows are considered. The result occupies at most 12×9
physical pixels inside each 24×21 hardware container; unused pixels and byte
63 are zero. `level2-enemies-import.json` records every bounding box and source
frame, plus the atlas hash. The preview shows original frames above reduced art.

```sh
python3 giana/tools/prepare-enemies.py
```

This rebuild uses only retained inputs and the local display palette. Pillow
is optional and produces only `level2-enemies-preview.png`. To repeat source
extraction, add `--program /path/to/original-file1.prg`. Generated `enemies.asm`
exports the frame constants and data at the caller's chosen 64-byte-aligned PC.
The original game graphics and data retain their original ownership.
