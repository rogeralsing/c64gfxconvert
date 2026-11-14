# Giana demo part

Standalone C64 part showing `giana5` with the original Giana Sisters Level 1
scrolling inside the TV and automatic screen light on the room.
The asset in `assets/giana5.koa` is an unchanged copy of `../images/giana5.koa`.
`../images/giana5.json` supplies the `GameArea` and `ScreenLight` tile masks.
The earlier `giana2.koa` asset remains available unchanged.

Build with KickAssembler:

```sh
./build.sh
```

Run the resulting `build/giana.prg` in PAL VICE:

```sh
./run-vice.sh
```

`KICKASS` and `VICE` can override the executable paths. The PRG starts with
`RUN` after loading and loops the terrain indefinitely.

The picture uses standard multicolor bitmap mode: bitmap at `$2000`, screen
colors at `$0400`, color RAM at `$D800`, a dark-brown global background, and a
black border. The TV occupies the full character rectangle at physical pixels
`[184,264) × [24,88)`, or 40×64 multicolor pixels: character columns 23–32
and rows 3–10. These are exactly the 80 cells marked by `GameArea`, matching
the previous demo's viewport. There are no sprites.

All 80 cells share brown, light blue and orange. Each cell's fourth color follows
the map: green for bushes and yellow for pipes and bonus blocks. Terrain
continues across the entire rectangle.

## Screen light

The 169 cells in `ScreenLight` have three color levels: original, +1 and +2.
The demo cycles original, +1, +2, +1, holding each level for 16 PAL frames
(320 ms). Black `$0`, brown `$9`, red `$2`, dark gray `$B` and dark blue `$6`
remain unchanged as pixel masks. White stays white. Orange occupies local
color slots and can brighten too.

| Original color | +1 | +2 |
| --- | --- | --- |
| Black 0 | Black 0 | Black 0 |
| White 1 | White 1 | White 1 |
| Red 2 | Red 2 | Red 2 |
| Cyan 3 | Yellow 7 | White 1 |
| Purple 4 | Light red 10 | Light gray 15 |
| Green 5 | Light gray 15 | Yellow 7 |
| Dark blue 6 | Dark blue 6 | Dark blue 6 |
| Yellow 7 | White 1 | White 1 |
| Orange 8 | Light red 10 | Light gray 15 |
| Brown 9 | Brown 9 | Brown 9 |
| Light red / pink 10 | Light gray 15 | Yellow 7 |
| Dark gray 11 | Dark gray 11 | Dark gray 11 |
| Gray 12 | Light gray 15 | Yellow 7 |
| Light green 13 | White 1 | White 1 |
| Light blue 14 | Light gray 15 | Yellow 7 |
| Light gray 15 | Yellow 7 | White 1 |

Each level reads the original Koala colors. The effect never accumulates
brightness or changes bitmap pixels. Only the two screen-color nibbles and
the color-RAM nibble of marked cells change. Cells outside `ScreenLight`
retain their source colors, apart from the separate scrolling `GameArea`.
The masks do not overlap.

`build.sh` runs `tools/prepare-scene.py` before assembly. It validates both
marker masks and the brown background, copies the Koala unchanged, and
generates `assets/scene.asm`, `assets/scene.json`, and the 1,014-byte
`assets/lighting.bin`. Render a comparison of all three levels with:

```sh
python3 tools/prepare-scene.py --preview
```

Light updates start at raster 250, after the final picture line. They run
two frames apart from terrain updates, so both jobs never share a frame.

## Terrain scrolling

`terrain.asm` loads 136 tiles of eight bytes each and a 128×8 map of one-byte
tile IDs. Each storage tile is one character: 4×8 multicolor pixels, occupying
8×8 physical pixels. The map and graphics come from the original C64 Stage 1.
The complete 2,048×160-pixel level is reduced to 1,024×64 physical pixels so
its full height fits inside the TV. Features can cross storage-tile boundaries.
The original light-blue sky is preserved. Black game details become dark brown;
white highlights become yellow. The remaining colors use the shared colors
and the cell's green or yellow accent.

The 40×64-multicolor-pixel viewport scrolls left by one multicolor pixel every
four PAL frames, four times slower than the first test. Two right-to-left carry
shifts move each bitmap scanline and insert
the next pair of source bits at its right edge. A 64-byte incoming column keeps
the current tiles' eight scanlines; shifting it selects the next pixel within
each tile. Every fourth pixel step (16 PAL frames), the player advances the map
column and reads eight new tile IDs. The map wraps after 2,048 PAL frames,
returning from the original level ending to its start.

After every pixel step, the player updates the 80 color-RAM cells from a
512-byte table. Four fine-scroll phases each contain 128 column bytes; each
byte's eight bits select green or yellow for the eight TV rows. The visible
column is derived from the incoming column and fine-pixel state. Colors remain
limited to character cells, so the dominant accent wins where green and yellow
share a cell. This palette produces no green/yellow conflicts across the
four phases of the reduced level.

The map uses 1,024 bytes, the tiles use 1,088 bytes, the accent table uses 512
bytes, and the incoming column uses 64 bytes. A fully expanded bitmap for the
reduced terrain would use 8,192 bytes. Tiles and map live at `$4800`, with the
accent table at `$5100..$52FF`; setup stays below `$2000`, while the renderer,
color updater, lighting tables and incoming column occupy `$6000..$81F4`. Zero-page bytes
`$FB/$FC` address tile graphics and accent phases; `$FD` holds the color flags.

Terrain updates begin at PAL raster line 144, after the TV's last visible line, and
finish before the next TV refresh. Global bitmap mode and scrolling registers
remain fixed. Lighting changes only the room's marked color cells.

Original-source URLs, checksums, reduction details and attribution are in
[`assets/LEVEL1-SOURCE.md`](assets/LEVEL1-SOURCE.md). Regenerate the derived
graphics and map offline with:

```sh
python3 tools/prepare-level1.py
```

The source assets contain only map, character graphics and character colors.
The player uses the generated tile map rather than running the original game.

Run native verification after building:

```sh
python3 tools/verify-scene.py
```

Native verification compares all 64,000 screen pixels with an independent
Koala, tile-map and accent-table decode. It also checks the color-RAM choices
for all 80 TV cells and the green bush/yellow pipe in the same native frame.
It checks automatic lighting, all protected color masks, unchanged cells outside
both regions, all 512 scroll positions, four accent phases and the
2,048-PAL-frame wrap. The receipt and actual VICE animation are
`build/giana5-verification.json` and `build/giana5.gif`. The earlier verification
remains in `build/giana2-color-verification.json` and `build/giana2-color.gif`.

The native receipt records the checked frames, protected pixel counts and
timing. The sky probe checks light blue directly, alongside green bushes and
yellow pipes and bonus blocks. The giana5 pass verified 2,049 PAL checkpoints,
the full map wrap, 129 light transitions and 69 complete screenshots with zero
pixel differences. All 3,330 protected multicolor pixels stayed fixed. The
longest update used 11,918 cycles; light changes finished at raster 293.
