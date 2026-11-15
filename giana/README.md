# Giana demo part

Standalone C64 part showing `giana5` with the original Giana Sisters Levels 1
and 2 scrolling inside the TV and automatic screen light on the room.
The asset in `assets/giana5.koa` is an unchanged copy of `../images/giana5.koa`.
`../images/giana5.json` supplies the `GameArea` and `ScreenLight` tile masks.
The earlier `giana2.koa` asset remains available unchanged.

Build requirements: Python 3 with Pillow, and KickAssembler. Running and native
verification require PAL-capable VICE (`x64sc`; music reference checks use `vsid`).

Build with KickAssembler:

```sh
./build.sh
```

Run the resulting `build/giana.prg` in PAL VICE:

```sh
./run-vice.sh
```

`KICKASS` and `VICE` can override the executable paths. The PRG starts with
`RUN` after loading and repeats Level 1, Level 2, then Level 1 again.

Both stages use the original maps and character graphics at the same reduced
scale and scroll speed. Level 1 retains its 512-step camera cycle. Level 2
ends at step 472, when the last map column reaches the right edge of the TV;
this keeps Giana in front of the original solid end wall. During each change,
the TV briefly fills with brown while forty incoming columns replace the old
terrain. The refill runs across PAL frames and skips room-light update frames,
so music continues at one native tick per frame. Giana and the glass highlight
return when the complete next stage is ready.

The picture uses standard multicolor bitmap mode: bitmap at `$2000`, screen
colors at `$0400`, color RAM at `$D800`, a dark-brown global background, and a
black border. The TV occupies the full character rectangle at physical pixels
`[184,264) × [24,88)`, or 40×64 multicolor pixels: character columns 23–32
and rows 3–10. These are exactly the 80 cells marked by `GameArea`, matching
the previous demo's viewport. Tiny original Giana and owl characters use three
hardware sprites inside that area. A fourth hires sprite adds the cyan glass
highlight at the TV's upper-left corner. Four black hires corner masks round
the opening; all eight hardware sprites are in use.

The demo also plays Chris Hülsbeck's original first-level music, corresponding
to subtune 3 of `Great_Giana_Sisters.sid`.

The TV cells share brown, light blue and orange. Their fourth color follows
the map: green for bushes and yellow for pipes and bonus blocks. Twelve
top/bottom edge cells reserve that color for the black perspective mask.

## Original in-game music

`tools/prepare-music.py` imports the complete 7,709-byte original player and
score module from the retained SID. The module stays at `$41C0..$5FDC` without
byte patches. Startup selects internal cue 1 with `LDA #1; CLC; JSR $41C9`;
the selector initializes the player itself. Its native score loops independently
of the terrain. Source hashes and the original-game cue mapping are in
[`assets/MUSIC-SOURCE.md`](assets/MUSIC-SOURCE.md).

The scene calls `$41C0` once per PAL frame at raster 64, before the graphics
update at raster 144. This keeps music out of the terrain renderer's next-frame
deadline. The driver uses zero page `$A4..$B9`; graphics retain `$FB..$FE`.
Cue 1 leaves the original optional sampler disabled and uses the SID's three
native voices. The VICE launcher selects reSID/MOS6581, matching the source.

Terrain data occupies RAM beneath BASIC at `$A000..$B0FF`; startup selects
`$01=$36` while retaining KERNAL and I/O. The bitmap stays at `$2000..$3F3F`.
Its startup screen/color sources live at `$C000..$C7CF`, leaving the music's
original addresses free. The PRG ends below the I/O window at `$D000`.

Level 2 uses the same original music cue. Its source background is black and
its shared terrain colors are light red and red. The TV maps that background
to the room's fixed brown color and uses screen byte `$A2`, retaining the
green/yellow cell accents. In the twelve cells reserved for the stepped black
edges, accent pixels appear black because the hardware color slot is shared
with the edge mask. Level 1's pixels and accent tables remain unchanged.
Level 2's tiles and map occupy CPU RAM at `$1000..$19FF`; its four accent tables
occupy `$B200..$B9FF`. Its owl-ground and Giana-route tables use `$BA00..$BCFF`.
The first region is data for the CPU, not sprite art: VIC bank 0 sees character
ROM at `$1000..$1FFF`. Source extraction and hashes are documented in
[`assets/LEVEL2-SOURCE.md`](assets/LEVEL2-SOURCE.md).

The upper perspective step reduces one of Level 2's 24-source-pixel tunnels
below the first stage's 10-pixel Giana. Level 2 therefore uses eight-row area
samples of the same four original poses; Level 1's accepted sprite atlas and
route stay unchanged. The extra eight sprite planes occupy `$1A00..$1BFF` as
CPU source data and reuse the same VIC-visible work buffers. Owl markers are
omitted where the real tunnel has no room for a supported jump over them.

The current layout leaves a conservative 9,116 bytes (8.90 KiB) directly
available across its unused RAM ranges. The 2,000-byte startup color sources
at `$C000..$C7CF` could also be reused after initialization.

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

## Tiny original characters

Giana uses four original walking poses reduced to 12×10 physical pixels. Two
overlaid multicolor sprite planes preserve yellow hair and blue clothes. The
Stage 1 horned owl uses two original poses, with a 12×8 visible bounding box.
Both use transparent padding in standard 24×21 hardware sprite containers.
The shared colors are skin/light red 10 and red 2; individual colors are
yellow 7, blue 6 and owl white 1. Only Giana's white highlights approximate
skin color. Source hashes, original frame indices and reduction details are in
[`assets/sprites-SOURCE.md`](assets/sprites-SOURCE.md).

The original collision table supplies a 256-byte owl-ground lookup. Giana's
512-byte demonstration route uses solid surfaces throughout the map, including
floating platforms. Takeoffs require support under her feet; gravity and the
first surface crossed on descent determine landings. The route favors walking
and uses short jumps where obstacles or owls require them. Collision checks
include the visible character poses and the terrain's perspective bands.
Horizontal clipping clears pixels outside the TV in three working buffers.

Sprite animation and buffer copies run on frame phase 0, terrain on phase 3,
and room-light changes on phase 1. This keeps the larger jobs separate. Actor
positions therefore follow a terrain step one PAL frame later.

The 640-byte immutable atlas and three 64-byte work buffers occupy
`$0C00..$0F3F`, below the VIC's character-ROM window. The 64-byte hires highlight
follows at `$0F40..$0F7F`. It uses hardware sprite 4, at bitmap position
`(184,27)`, three raster lines below the top edge, so its cyan pixels remain
inside the picture and in front of the game characters. Black source pixels
are transparent. A curved dithered patch follows the rounded corner, with
coverage fading inward like the upper-left quadrant of shaded spherical glass.
`tools/prepare-tv-highlight.py` rebuilds this sprite from its readable native art.
Sprite helpers, clipping
tables, ground lookup, demonstration route and corner masters occupy `$9000..$97FF`.
`build.sh` regenerates the sprite assets offline with `tools/prepare-sprites.py`.

Four black hires sprites in hardware slots 0–3 cover the rounded corners in
front of the highlight and actors. The eight-row cut profile is
`[6,4,3,2,1,1,0,0]`, offset to the existing perspective edges. Each corner masks
17 physical pixels. These overlays preserve the unmasked bitmap stream and all
cell colors, so hidden right-edge pixels scroll into view intact.

The four 64-byte frames are copied to `$0200..$02FF` after SYS. This standalone
part disables interrupts and never returns to BASIC, leaving that workspace
available without moving the PRG's load address. The right masks start at VIC
X 264, so their fixed X high bits remain set alongside the moving owl's bit.
`tools/prepare-tv-corners.py` rebuilds the masks from the readable arc profile.

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
four PAL frames, four times slower than the first test. Two carry shifts move
each pixel stream and insert the next source bits at its right edge. Each
region reads its old right neighbor before that neighbor changes. A 64-byte incoming column keeps
the current tiles' eight scanlines; shifting it selects the next pixel within
each tile. Every fourth pixel step (16 PAL frames), the player advances the map
column and reads eight new tile IDs. The map wraps after 2,048 PAL frames,
returning from the original level ending to its start.

After every pixel step, the player updates the 80 color-RAM cells from the
four regional 512-byte tables. Four fine-scroll phases each contain 128 column bytes; each
byte's eight bits select green or yellow for the eight TV rows. The visible
column is derived from the incoming column and fine-pixel state. Colors remain
limited to character cells, so the dominant accent wins where green and yellow
share a cell. This palette produces no green/yellow conflicts across the
four phases of the reduced level.

## Perspective trial

Two upper seams after character columns 3 and 7 (physical X=208 and X=240)
move the upper stream down one raster line each. These are 30% and 70% of
the TV width, rounded to character boundaries from the requested thirds.
The lower stream keeps its single upward step at column 5 (physical X=224).
The eight center lines stay straight.

Four regions span character columns `[0,3)`, `[3,5)`, `[5,7)` and `[7,10)`.
Their upper offsets are two, one, one and zero raster lines; their lower
offsets are one, one, zero and zero lines. Black masks cover the resulting
stepped edges. The mapping is fixed in screen space and does not accumulate.

Twelve edge character cells use black as the accent color. In Level 1, their
retained pixels contain no green/yellow accents anywhere in the level. Each region
has a 512-byte accent table following its shifted row windows; the final
region retains the original unwarped table.

The Level 1 map uses 1,024 bytes, its tiles use 1,088 bytes, its four accent tables use 2,048
bytes, and the incoming column uses 64 bytes. A fully expanded bitmap for the
reduced terrain would use 8,192 bytes. Tiles and map live at `$A000`, with the
accent tables at `$A900..$B0FF`; the entry and frame controller stay below `$0C00`.
The shared renderer, color updater, lighting tables and incoming column start
at `$6000`, and level selection/refill code starts at `$9800`. Zero-page bytes
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

The retained terrain inputs contain map, character graphics and character colors.
The player uses the generated tile map rather than running the original game.

Run native verification after building:

```sh
python3 tools/verify-scene.py --frames 5205
python3 tools/verify-scene.py --frames 35 --autostart-mode 2
```

The first run uses `prepare-music-reference.py` to capture an independent native
VSID reference from the retained source SID. Later runs reuse that ignored
reference when its source identity matches. The second command checks ordinary
1541 disk autostart with the same PRG.

Native verification compares all 64,000 screen pixels with an independent
Koala and original character/map decode. It also checks the color-RAM choices
for all 80 TV cells and the green bush/yellow pipe in the same native frame.
It checks automatic lighting, all protected color masks, unchanged cells outside
both regions, all 512 Level 1 scroll positions, the 473 visible Level 2 camera
positions, four accent phases and both automatic level changes. It verifies
the uniform-brown refill frames and continuous native music/light scheduling.
The receipt and actual VICE animation are `build/levels-verification.json` and
`build/levels.gif`; `build/level2-selected.png` shows the second stage.
The disk-start receipt is `build/levels-startup-verification.json`. The earlier verification
remains in `build/giana2-color-verification.json` and `build/giana2-color.gif`.

The native receipt records the checked frames, protected pixel counts and
timing. The perspective reference checks the fixed row mapping, both black
masks, shifted accent colors and the unchanged right half. Sky and object
probes follow the projected pixel positions. The native receipt records all
camera states, both level changes, three light levels and completion timing
before the next music call at raster 64. Sprite verification also checks
animation poses, work-buffer pixels, clipping, hardware X high bits and
composited native screenshots through the actor-loop restart. It requires
visible Giana art in every active stage frame, clearance throughout staged owl encounters,
and contact with the rendered solid surfaces during walking and landing.
The highlight check reads the approved native art independently and checks
its hires mode, cyan color, fixed position, immutable data and foreground priority.
Corner checks cover all eight hardware slots, the static black profile, the
copied VIC-visible frames and the unchanged underlying scroll pixels.
The two-stage native pass checked 5,206 PAL checkpoints and 706 complete
screenshots with zero pixel differences. It covered both full maps and both
level changes, with 512 Level 1 actor states and 472 Level 2 actor states.
All 5,206 music calls and 116,480 SID register writes matched the original,
including the full score loop. The longest graphics job used 13,297 cycles.

The preserved Level 1 integration reference
checked 5,206 PAL checkpoints and 354 complete screenshots with zero pixel
differences. All actor poses and both edge clips passed, with no opaque pixels
outside the TV or over its black masks. The longest terrain update used
13,250 cycles and ended at raster 42; the longest actor update used 5,164
cycles and ended at raster 226 on its separate update frame. The independent
contact audit found 303 terrain contacts, four owl-head supports, and 205
unsupported jump/fall states. No body penetrations, midair relaunches, or
missed descending landings occurred. The four rounded ballistic apices each
last four displayed steps; the former long height-clamped plateaus are gone.

All 116,480 SID register writes matched the original subtune's per-call sequence,
including the score loop at call 5,181. Mutable player state and bookmarks also
matched. Music calls took 598–2,860 elapsed cycles and finished by raster 109,
before the graphics update at 144. The complete normal-demo recording includes
the music loop with terrain, actors, corner masks and lighting active.
