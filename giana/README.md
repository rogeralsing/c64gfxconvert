# Giana demo part

Standalone C64 part showing `boygiana` with the original Giana Sisters Level 1
scrolling inside the TV.
The asset in `assets/boygiana.koa` is an unchanged copy of
`../images/boygiana.koa`. The converter project remains in `../images/boygiana.json`.

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
colors at `$0400`, color RAM at `$D800`, and a black background and border.
Only the TV viewport changes: physical pixels `[176,256) × [24,88)`, or
character columns 22–31 and rows 3–10. All 80 cells use the same brown,
orange and green colors, plus the global black background. There are no sprites.

## Terrain scrolling

`terrain.asm` loads 148 tiles of eight bytes each and a 128×8 map of one-byte
tile IDs. Each storage tile is one character: 4×8 multicolor pixels, occupying
8×8 physical pixels. The map and graphics come from the original C64 Stage 1.
The complete 2,048×160-pixel level is reduced to 1,024×64 physical pixels so
its full height fits inside the TV. Features can cross storage-tile boundaries.
The sky becomes black, and other colors use the fixed TV palette.

The 40×64-multicolor-pixel viewport scrolls left by one multicolor pixel every
four PAL frames, four times slower than the first test. Two right-to-left carry
shifts move each bitmap scanline and insert
the next pair of source bits at its right edge. A 64-byte incoming column keeps
the current tiles' eight scanlines; shifting it selects the next pixel within
each tile. Every fourth pixel step (16 PAL frames), the player advances the map
column and reads eight new tile IDs. The map wraps after 2,048 PAL frames,
returning from the original level ending to its start.

The map uses 1,024 bytes, the tiles use 1,184 bytes, and the incoming column uses
64 bytes. A fully expanded bitmap for the reduced terrain would use 8,192 bytes.
Tiles and map live at `$4800`; the player and incoming column fit below `$2000`.
Zero-page bytes `$FB/$FC` address the tile graphics across page boundaries.

Updates begin at PAL raster line 144, after the TV's last visible line, and
finish before the next TV refresh. Global bitmap mode, scrolling registers,
and the surrounding picture remain fixed.

Original-source URLs, checksums, reduction details and attribution are in
[`assets/LEVEL1-SOURCE.md`](assets/LEVEL1-SOURCE.md). Regenerate the derived
graphics and map offline with:

```sh
python3 tools/prepare-level1.py
```

The source assets contain only map, character graphics and character colors.
The player uses the generated tile map rather than running the original game.

Native PAL VICE verification covered all 512 scroll positions and the wrap at
PAL frame 2,048. Four-frame pacing held, all bitmap/screen/color data outside
the TV stayed unchanged, and sampled full screenshots matched all 64,000
decoded pixels. The slowest update took 10,585 elapsed cycles and finished at
raster 0, before the next TV drawing starts at raster 74. The receipt and
actual VICE animation are `build/level1-verification.json` and `build/level1.gif`.
