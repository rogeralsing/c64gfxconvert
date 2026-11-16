# Giana demo part

Standalone C64 demo showing `giana5` with the original Giana Sisters Levels 1
and 2 scrolling inside the TV and automatic screen light on the room. After
Level 2, the room changes to `giana7`. The same game restarts in its marked TV,
with sprites, rounded corners, perspective and the new room's screen lighting.
After both levels finish in that room, Spindle loads the full-screen
`giana-man.mci` part. The original music continues through loading and interlace.
The asset in `assets/giana5.koa` is an unchanged copy of `../images/giana5.koa`.
`../images/giana5.json` supplies the `GameArea` and `ScreenLight` tile masks.
The earlier `giana2.koa` asset remains available unchanged.

Build requirements: Python 3 with Pillow, KickAssembler and a C compiler (`cc`).
The vendored Spindle tool builds locally without a network connection.
Running and native
verification require PAL-capable VICE (`x64sc`; music reference checks use `vsid`).

Build with KickAssembler:

```sh
./build.sh
```

Run the resulting `build/giana.d64` in PAL VICE with 1541 emulation:

```sh
./run-vice.sh
```

`KICKASS`, `CC` and `VICE` can override the executable paths. The disk boots
automatically, plays both levels in each room, then displays the MCI picture.

The [complete recording with sound](recordings/giana-complete-mci-30s.mp4)
runs for 3:14.43 and preserves the version before the opening animation. It
ends after 30 seconds of the MCI picture. Capture commands
and timing verification are in [recordings/README.md](recordings/README.md).

Level 1 starts with small Giana in both rooms. She jumps onto the first
platform, strikes the first power-up brick, and collects the released beachball.
The original electrical flash then transforms her into the familiar punk Giana.

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
the previous demo's viewport. Giana uses two overlaid hardware sprites, and two
more slots display enemies. A hires sprite adds the cyan glass highlight at the
TV's upper-left corner. Three hardware slots display four black corner masks by
reusing the left slot between the upper and lower edges. All eight hardware
sprites are in use.

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
original addresses free. Spindle restores the declared runtime segments from
disk, including the second room beneath KERNAL. Its resident loader and scratch
page occupy `$CE00..$CFFF`; loader calls use zero page `$02..$06`.

Level 2 uses the same original music cue. Its source background is black and
its shared terrain colors are light red and red. The TV maps that background
to the room's fixed brown color and uses screen byte `$A2`, retaining the
green/yellow cell accents. In the twelve cells reserved for the stepped black
edges, accent pixels appear black because the hardware color slot is shared
with the edge mask. Level 1's pixels and accent tables remain unchanged.
Level 2's tiles and map occupy CPU RAM at `$1000..$19FF`; its four accent tables
occupy `$B200..$B9FF`. Its Giana route uses `$BB00..$BCFF`.
The first region is data for the CPU, not sprite art: VIC bank 0 sees character
ROM at `$1000..$1FFF`. Source extraction and hashes are documented in
[`assets/LEVEL2-SOURCE.md`](assets/LEVEL2-SOURCE.md).

The upper perspective step reduces one of Level 2's 24-source-pixel tunnels
below the first stage's 10-pixel Giana. Level 2 therefore uses eight-row area
samples of the same four original poses; Level 1's accepted sprite atlas and
route stay unchanged. The extra eight sprite planes occupy `$1A00..$1BFF` as
CPU source data and reuse the same VIC-visible work buffers.

Level 2 retains its eight original enemy spawn records: one owl, two crabs,
four green spring creatures and one bee. Fourteen extra original poses use
896 bytes at `$1C00..$1F7F`. The two dynamic pickup sites are not enemies and
are not simulated. Enemy movement is deliberately simplified to local patrols,
falling onto the reduced terrain, and a clear bee flight lane. Original art,
facing, animation timing and source speed are retained; this is not the original
game's AI. Crabs use a shorter six-row canvas so Giana can pass them in the
reduced tunnels. Source records and reduction details are in
[`assets/level2-enemies-SOURCE.md`](assets/level2-enemies-SOURCE.md).
The settled positions, motion tables and Giana route are documented in
[`assets/LEVEL2-SPRITES.md`](assets/LEVEL2-SPRITES.md).

Six 512-byte tables store each enemy slot's X, Y and animation frame, avoiding
per-frame game AI. They occupy `$8600..$8BFF` and `$C800..$CDFF`. The slots retain
an enemy throughout its visible lifetime, and both are used where enemies
appear together. The 2,000-byte startup color sources at `$C000..$C7CF` could
also be reused after initialization.

The second room archive occupies 7,995 bytes at `$E000..$FF3A`. Its 332-byte
controller starts at `$BD00`. The game layout leaves 1,566 bytes directly available, separate
from the 2,000 bytes of startup colors and internal alignment padding.

## Level 1 opening animation

`tools/prepare-intro.py` reduces the original small-Giana, jumping, electrical,
and beachball graphics into a separate 640-byte source atlas at `$9D80`.
Two Giana sprite planes retain her clothes and transformation colors. The
beachball reuses Level 1's spare enemy slot and appears progressively above
the brick before falling into Giana.

The sequence follows the existing camera clock. Small Giana lands on the
original first platform and jumps against the first power-up brick at camera
step 80. The brick rises one pixel, then changes to the original spent-block
graphic. Source-derived patches scroll with the rest of the bitmap. The ball
touches Giana at step 92; the electrical flash lasts 28 PAL frames, and punk
Giana continues along the existing route from step 100.

Watch the [native opening preview](recordings/intro-opening-tv.gif), captured
from the actual TV output during the full VICE verification.

`tools/prepare-intro-motion.py` generates 146 bytes of choreography tables and
72 bytes of bitmap-patch data. The controller uses `$BE50..$BF29`, and its
block patcher uses `$9C80..$9CEC`. Source identities and sprite reduction are
documented in [`assets/intro-SOURCE.md`](assets/intro-SOURCE.md). Native
verification checks the complete sequence in each room, including platform
contact, the upward block strike, ball collection, and the supported flash.

## Second room and startup

`tools/prepare-ending.py` copies `images/giana7.koa` unchanged and retains the
JSON source identity and marker masks in `assets/ending-import.json`. The
80-cell `GameArea` has the same geometry as the first room. Its entire white
opening and colored side strips are replaced by the game. The 121-cell
`ScreenLight` mask uses the same protected colors and brightness cycle as the
first room. Marker-layer visibility in the editor does not disable these
user-selected regions.

Suffix-tag PackBits stores the 8,000 bitmap bytes, 1,000 screen bytes and 500
packed color-nibble pairs in 7,995 bytes beneath KERNAL. After both stages finish, the demo
blanks the display, disables sprites and stops the terrain and lighting jobs.
It restores 160 output bytes per PAL frame over the existing bitmap, screen
matrix and Color RAM, expands both color nibbles, then refills forty terrain
columns across separate frames. Level 1 and its sprites restart when the new
TV is complete. Music continues once per frame throughout, with no disk access.
The temporary `$01=$35` mapping keeps SID and Color RAM visible while reading
the archive; ordinary runtime returns to `$36` before the next music call.

The new lighting uses a 968-byte cell-address/phase table at `$8C00` and a
76-byte updater at `$3F40`. It changes only the new room's marked cells.
Terrain, actors and the lighting clock retain their separate PAL frame phases.

The build first assembles the internal `build/giana-unpacked.prg`, then
`tools/build-disk.py` creates `build/giana.d64`. The disk is the runnable
distribution. Its first Spindle job restores 27 declared runtime ranges, skips
the loader pages and I/O gap, and enters the game at `$080E`. The build rejects
any omitted nonzero runtime bytes. `build/disk-manifest.json` records source
identities, ranges and loader jobs. Runtime symbols remain in `build/main.sym`.

## MCI part and fast loading

After Level 2 in the second room, the last game picture freezes. A raster-64
IRQ continues the unchanged SID player while Spindle first loads the invisible
MCI field B and stages its shared colors. The lower-left rounded corner uses
an otherwise idle sprite during this freeze. The screen then blanks for field A
to load, and the complete MCI image is revealed in the lower border.

The MCI viewer preserves both 8,000-byte bitmaps, both 1,000-byte screen matrices
and the shared 1,000-byte Color RAM from `images/giana-man.mci`. Field A uses
`$0400/$2000`; field B uses `$8400/$A000`, protecting the music module.
It alternates complete PAL fields at raster 256, with field B shifted one hires
pixel right. CIA2 bank selection uses `$DD02`, as required by Spindle.
Source provenance and native field semantics are in
[`assets/MCI-SOURCE.md`](assets/MCI-SOURCE.md).

Loader by lft: [Spindle 3.1](https://www.linusakesson.net/software/spindle/v3manual.pdf).
The exact MIT-licensed source and generated loader tables are retained under
`vendor/spindle/`; ordinary builds need only the C compiler. The native verifier
boots the real D64 with true-drive emulation, then checks consecutive actual
VIC-II MCI fields and every continuing SID call.

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
Horizontal clipping clears pixels outside the TV in four working buffers.

Sprite animation and buffer copies run on frame phase 0, terrain on phase 3,
and room-light changes on phase 1. This keeps the larger jobs separate. Actor
positions therefore follow a terrain step one PAL frame later.

The 640-byte immutable atlas and first three 64-byte work buffers occupy
`$0C00..$0F3F`, below the VIC's character-ROM window. The 64-byte hires highlight
follows at `$0F40..$0F7F`, and the fourth work buffer uses `$0F80..$0FBF`.
The highlight uses hardware sprite 3, at bitmap position
`(184,27)`, three raster lines below the top edge, so its cyan pixels remain
inside the picture and in front of the game characters. Black source pixels
are transparent. A curved dithered patch follows the rounded corner, with
coverage fading inward like the upper-left quadrant of shaded spherical glass.
`tools/prepare-tv-highlight.py` rebuilds this sprite from its readable native art.
Sprite helpers, clipping
tables, ground lookup, demonstration route and corner masters occupy `$9000..$97FF`.
`build.sh` regenerates the sprite assets offline with `tools/prepare-sprites.py`.

Four black hires masks in hardware slots 0–2 cover the rounded corners in
front of the highlight and actors. Slot 0 shows the upper-left mask, then
switches to the lower-left mask at raster 115, ahead of its first line at 117.
The frame update restores the upper-left mask at raster 144. The eight-row cut profile is
`[6,4,3,2,1,1,0,0]`, offset to the existing perspective edges. Each corner masks
17 physical pixels. These overlays preserve the unmasked bitmap stream and all
cell colors, so hidden right-edge pixels scroll into view intact.

The four 64-byte frames are copied to `$0200..$02FF` after SYS. This standalone
part disables interrupts and never returns to BASIC, leaving that workspace
available without moving the PRG's load address. The right masks start at VIC
X 264, so their fixed X high bits remain set alongside the moving enemies' bits.
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
python3 tools/verify-scene.py --frames 8505 --name intro-chain-final
python3 tools/verify-scene.py --frames 35 --autostart-mode 2 --name intro-startup-final
```

The first run uses `prepare-music-reference.py` to capture an independent native
VSID reference from the retained source SID. Later runs reuse that ignored
reference when its source identity matches. Both commands boot the actual D64
with true 1541 emulation; the second checks the first 35 frames only.

Native verification compares all 64,000 screen pixels with an independent
Koala and original character/map decode. It also checks the color-RAM choices
for all 80 TV cells and the green bush/yellow pipe in the same native frame.
It checks automatic lighting, all protected color masks, unchanged cells outside
both regions, all 512 Level 1 scroll positions, the 473 visible Level 2 camera
positions, four accent phases and both levels in both rooms. It verifies
the uniform-brown refill frames and continuous native music/light scheduling.
The opening-animation receipt is `build/intro-chain-final-verification.json`.
It checks the complete small-Giana sequence independently in both rooms and
captures every camera step through the opening. The startup receipt is
`build/intro-startup-final-verification.json`.
The retained MCI integration receipt is `build/mci-chain-verification.json`, with the game and
MCI animations in `build/mci-chain.gif` and `build/mci-chain-mci.gif`.
The disk-start receipt is `build/mci-chain-startup-verification.json`.
`build/mci-chain-mci-phase-0.png` and `build/mci-chain-mci-phase-1.png` are actual
completed native fields. The optional `mci-chain-mci-native-average-4x.png` is
a temporal average of those two captures, not an extra native display mode.
The earlier second-room replay proof remains in `build/room7-verification.json`.
The earlier two-stage loop proof remains in `build/mobs-verification.json`.
The earlier verification
remains in `build/giana2-color-verification.json` and `build/giana2-color.gif`.

The native receipt records the checked frames, protected pixel counts and
timing. The perspective reference checks the fixed row mapping, both black
masks, shifted accent colors and the unchanged right half. Sky and object
probes follow the projected pixel positions. The native receipt records all
camera states, room and stage changes, three light levels and completion timing
before the next music call at raster 64. Sprite verification also checks
animation poses, work-buffer pixels, clipping, hardware X high bits and
composited native screenshots through the second room's last Level 2 camera. It requires
visible Giana art in every active stage frame, clearance throughout enemy encounters,
and contact with the rendered solid surfaces during walking and landing.
The highlight check reads the approved native art independently and checks
its hires mode, cyan color, fixed position, immutable data and foreground priority.
Corner checks cover all eight hardware slots, the static black profile, the
copied VIC-visible frames and the unchanged underlying scroll pixels.
The native pass checked 8,506 music calls, 8,065 game checkpoints, 1,293 game
screenshots and 263 consecutive MCI fields with zero pixel differences.
It covered both full maps in both
rooms, with 512 Level 1 actor states and 472 Level 2 actor states per room.
All eight original Level 2 enemies were checked in each room, with all sixteen enemy poses;
two opaque enemies appeared together. The independent Level 2 contact audit
found 363 terrain contacts, six enemy-head contacts and 103 unsupported
jump/fall states, with no body penetrations, missed landings or midair relaunches.
All 8,506 music calls and 190,321 SID register writes matched the original,
including the full score loop. The complete SID dump contains no additional
writes between calls, including no loader mute or volume changes.
The second room's game first appears at checkpoint 4,086 after 105 blank PAL
frames. Both stages and all three lighting levels run before the MCI handoff
after game frame 8,064. Pixels outside the TV follow the original
room7 bitmap and its 121-cell lighting mask. The compressed archive is
checked beneath KERNAL throughout the game, including real disk startup.
The left corner switch completed by raster 116, before the lower mask starts
at 117. Ordinary disk autostart also passed 36 checkpoints and nine native
screenshots with zero pixel differences. The first complete MCI field follows
the handoff after 3.56 seconds; approximately 1.66 seconds are blank, while the
earlier load job retains the exact frozen game picture. All 441 IRQ music calls
start at raster 64. The MCI field cadence remains one phase per PAL frame.

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

All 190,321 SID register writes matched the original subtune's per-call sequence,
including the score loop at call 5,181. Mutable player state and bookmarks also
matched. Game music calls took 598–2,872 elapsed cycles and finished by raster 109,
before the graphics update at 144. The complete normal-demo recording includes
the full game run in both rooms, both disk jobs and the continuing MCI/music loop.
