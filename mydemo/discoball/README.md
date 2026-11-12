# Expanded sprite ball proof of concept

This directory imports the complete standalone scene from
`c64demo/experiments/sprite-ball/` on 2026-11-12. Runtime assembly, artwork,
and music are unchanged. `vice_support.py` preserves the original repository's
VICE monitor helpers locally. Palette lookups use this repository's identical
`palettes/colodore.vpl`.

A standalone PAL C64 demo using one expanded hires sprite per visible polygon.
The default model contains all twenty hexagons and twelve pentagons of a
truncated icosahedron. It repeats 150 hexagon poses (about six seconds), then
50 pentagon poses (about two seconds). Hexagon mode selects the eight largest
visible hexagons; pentagon mode renders all front-facing pentagons, at most six.
Surfaces outside the selected mode reveal the supplied background artwork.

Both face sets reference the same sixty shared vertices. Thirty opposite vertex pairs
are projected once, so adjoining faces always use identical edge endpoints.
Rotation, selection, culling, projection, boundary drawing, and filling run
live on the C64.

Switching face sets preserves rotation and zoom phase, lighting, music, and
background flashing. The pentagons use the exact five-sided gaps between the
hexagons, rather than the larger model from the older comparison builds.

## Intro and ending

The default build starts with music and a black screen, with sprites disabled.
Both bitmap fields fade in over about 2.8 seconds. Each 8x8 tile's two screen
colors and Color RAM color follow eight brightness levels derived from the
Colodore palette. Level zero is black and level seven exactly restores the
prepared artwork. Bitmap pixels remain unchanged throughout the fade.

Once the picture is complete, the ball grows from zero to full size over
100 PAL ticks (about two seconds). The existing rotation, zoom pulse, lighting,
background flashing, and six-second/two-second face cycle then begin.

After 9022 PAL ticks of the main scene (about three minutes), or when SPACE is
pressed, the visible hexagons detach and fly in different directions. Their
local shapes keep rotating; their screen positions no longer follow the sphere.
The fragment scale freezes at the exit size. Signed coordinates, ninth X bits,
and visibility masks prevent fragments from wrapping back onto the screen.
The background, fragment colors, and music fade out. The program finishes on
black with sprites and sound disabled. SPACE during the picture fade returns
directly to black without creating a ball.

## Build and run

Requires Python 3, Kick Assembler (`kickass`), Java, and VICE (`x64sc`).

```sh
cd /Users/rogerjohansson/git/asynkron/c64/mydemo/discoball
sh run.sh
```

`sh build.sh` builds without launching VICE. The default runnable program is
`build/hexagon/sprite-ball.prg` (`SYS2062`). `KICKASS` and `VICE` can select other
executable paths. This experiment has its own generated files and PRGs under
its ignored `build/` directory; the main demo is unchanged.

The earlier twelve-pentagon comparisons remain available:

```sh
sh run.sh baseline
sh run.sh golden
```

The golden variant reconstructs two corners from three projected corners using
the inverse golden ratio. It can differ by four logical pixels from direct
projection. The hexagon variant uses direct shared-vertex projection.
Both older comparison models can extend beyond this supplied image's circle.
Foreground sprites are not clipped to that circle.

## Music

The default hexagon demo plays [Dance Nation by Richard Bayliss](https://hvsc.c64.org/search?sid=132561),
released in 2002 by The New Dimension. The original HVSC download is preserved
as `assets/Dance_Nation.sid`. Its PAL VBI player runs once per video frame,
independently of the ball's two-frame presentation cadence. `run.sh` enables
sound and selects the tune's intended 8580 SID model.

The original player occupies `$1000..$1bb0`, which overlaps graphics data and
rendering code. `prepare_music.py` reproduces a verified sidreloc relocation to
`$b000..$bbb0` and moves its two zero-page bytes to `$de..$df`. The fixup manifest
records source hashes, attribution, and the relocation tool. Builds work
offline without sidreloc or an additional Python package.

The relocation passed 100,000 strict sidreloc calls. An independent 20,000-call
6502 comparison matched all 336,257 SID writes and CPU cycle counts. The player
costs 979..1,857 CPU cycles per call before VIC bus stalls and IRQ overhead.
At startup, both verified SID volume/filter writes are redirected through a
small RAM shadow helper, adding sixteen cycles per such write. This preserves
the tune's filter mode during the outro volume fade without reading a write-only
SID register. The relocated music asset and its source verification remain unchanged.
Fixed-endpoint edge kernels, direct compact pointer lookups, and omitted
always-zero sprite tails make room for that work without changing the pixels.
The music remains at 50.12 Hz and geometry at 25.06 fps.

Native verification checks one complete music call per PAL IRQ, traps every
missed presentation deadline, and compares the first sixteen calls with an
independent execution of the original SID. A separate CoreAudio/WAV capture
verifies non-silent 8580 audio. Run `python3 verify_music.py --ticks 2000` for timing and
SID-write verification; add `--record` for the audible recording.
Receipts are in `build/hexagon/music-verification/`.

Use the bounded 2,000-call check for this complete scene. The inherited
verifier default requests 20,000 calls, longer than the scene's lifetime;
once the ending reaches black, the runtime stops calling the music player.

## Sphere image and sprite priority

The active background is `assets/scene.mci`, an unchanged copy of the supplied
`c64demo/images/disco.mci`. The 19434-byte uncompressed True Paint image contains two
bitmaps, two screen maps, a shared Color RAM map, and one background color.
The origin manifest records the existing sphere center (160,60) in 320x200
display coordinates and binds that calibration to the source image hash.
The earlier Koala and hires sources remain in `assets/` for reference.

`background.py` and `prepare_disco.py` reserve a private color channel across
the complete black opening in each field. Its pixels use bitmap selector `11`
with initial black Color RAM. The two screen maps and boundary bitmap cells
are repacked to retain the white contour exactly. Where a boundary cell needs
more static colors than remain available, its least-used nonwhite color is
merged into a retained nonwhite color or black. Pixels outside the touched
cells remain unchanged. The supplied fields require 103/99 multicolor-pixel
substitutions (206/198 screen pixels), all outside the opening; white pixels
remain exact. No additional dithering is applied. Koala input remains
supported when the manifest selects that source asset.

Every raster IRQ switches VIC banks 0 and 1, their screen maps, and X scroll.
MCI field B is shifted one hires pixel right, matching the source format.
Color RAM is shared; only the 110 selected disco cells change after startup. Each completed sprite
pose is written into matching buffers in both banks, so either field shows the
same geometry. Both pointer tables select the completed pose together.

`$D01B=$00` keeps the hires sprites in front of the background. Sprite positions
remain fixed between geometry updates; their colors alternate normal/darker on
every video frame. Uncovered gaps reveal the background's disco lights.
Neither prepared bitmap nor either screen's 1000 color cells is
modified while running. The pointer-table bytes change with each new pose.

## Circle color animation

Bitmap selector `11` reads one Color RAM value per 8x8 screen cell. The preparer
finds the connected black opening independently in both original MCI fields,
then stamps its complete pixel mask into all 110 touched cells. Static pixels
in those cells use the other selectors, so the animated color reaches the
curved boundary instead of stopping at an 8x8 cell outline. White rim pixels
are preserved exactly; nonwhite pixels never become white during repacking.

The IRQ writes one shared blue, purple, pink or white palette color
into all 110 cells together every four PAL ticks (12.53 Hz). Colors change on field
A and remain fixed through field B. The bitmap is prepared once; runtime
animation only stores color values. The original supplied MCI file is unchanged.

A full update costs 484 CPU clocks including JSR; the guard costs 21. Ball
animation remains 25.06 fps and music remains 50.12 Hz. Background fades run
incrementally in render-idle time, capped at fifty tiles per PAL tick. Native
verification covers the main renderer and the complete scene lifecycle.

## Rendering and arithmetic

Each sprite contains 24x21 one-bit pixels in 63 bytes. X/Y expansion displays
these as 48x42 physical pixels. Each face has an independent color.

Current hexagons span at most 17x19 logical steps, or 34x38 screen pixels.
The matching pentagons span at most 14x15 logical steps, or 28x30 screen pixels.
At maximum scale, the painted ball occupies 86x86 screen pixels across the rotation;
the supplied background's opening is 86x87. Radius 24 therefore fills the
artwork's opening already. Radius 25 would reach 90x92 and cover the white rim,
even though the hardware sprites could hold larger faces.

The hexagon build gently shrinks and grows in real time. A 256-pose cycle
holds full size for 64 poses, runs a cosine pulse over 128 poses, then holds
full size for another 64. Scale ranges from 52/64 (81.25%) to 64/64 (100%);
the complete cycle lasts about 10.21 seconds at 25.06 fps. Only the five X/Y
projection coefficients are scaled. Face normals, lighting, the rotation schedule,
music, and background flashing keep their existing behavior. The artwork's
white circle and flashing opening remain fixed while the polygon patches shrink.

Yaw and pitch also have independent slow and fast periods. Yaw ranges from
0.5 to 6 angle units per presentation; pitch ranges from 0.25 to 4. Each
256-pose speed profile holds slow, eases up over 32 poses, holds fast for
64 poses, eases down over 32 poses, then holds slow again. Pitch follows
the same profile 64 poses later, so the two axes accelerate at different
times. The speed cycle lasts about 10.21 seconds. Four fractional bits per
axis retain slow movement and smooth acceleration without resetting the angles.

The camera-facing light uses the rotated face normal, restored from commit
`9e10543`. Brightness uses its Z component, already computed for culling.
The lookup index is `-normalDepth-1`. The sprite ramp is blue (6), purple (4),
pink (10), light gray (15), and white (1), with transitions at indices 6, 12,
18, and 24. A face brightens as it turns toward the camera.

One 128-byte table stores these bands. Lighting reads that table without a
separate light transform or additional products. There are no screen-position
approximations or directional palette changes. Geometry, Z-culling, and vertex
projection retain their existing calculations.

The raster IRQ alternates sprite colors every PAL frame. A newly presented
pose uses its normal front-light colors; the next video frame uses one shade
darker: white becomes light gray, light gray becomes pink, pink becomes purple,
and purple becomes blue. Blue stays blue. The IRQ reads the displayed buffer's
original colors, so the shift never accumulates. Geometry still updates at
25.06 fps; color alternation runs on every 50.12 Hz PAL tick.

Every render clears eight crossing buffers, transforms the visible faces,
draws their XOR boundaries, and prefix-XOR fills the back sprite set. Clearing
and filling are fully unrolled. Each fill consumes 456 marker bytes and
writes 456 bytes into each of two matching sprite sets. The bottom two rows of each hexagon
sprite stay zero: exhaustive geometry checks bound every face to 19 row steps.
Marker clearing includes row 19's closing crossings. Crossing buffers
use column-major layout; fill stores convert this to three bytes per sprite row.
Space between sprite rectangles has no clearing or filling cost. Hot scalar
temporaries, metadata, and the small vertex arrays use owned zero-page RAM
while ROM interrupts are disabled. This offsets the extra mirrored writes.

For equal-size faces under orthographic projection, facing depth estimates
projected area. At most ten hexagons face the camera. The selector drops the
weakest one or two when necessary, keeping the largest faces on all eight
hardware sprites. Equal depths favor the lower face index. Opposite face
normals share one depth calculation. Each selected face gathers its six
projected corners and derives its sprite bounds.

The static coordinate values have specialized multiplication tables for every
rotation coefficient. Face tests and edge dispatch are unrolled. A shared
1845-byte table stores exact short-edge crossings for `dx=1..9, dy=-20..20`.
All 65,536 yaw/pitch combinations at each of the 13 zoom scales fit
`dx<=9, abs(dy)<=10` and the 19-row fill. Two compact pointer pages address
those used combinations directly. The earlier pentagon builds
retain the full 11316-byte table and do not include music.
The half-open `[left,right)` endpoint rule and `ceil(Y)` crossings preserve XOR
parity at corners. These are arithmetic tables, not prepared animation frames.

## Memory and display

| Address | Use |
| --- | --- |
| $02..$DC / $E0..$FD | Owned zero-page metadata, vertex arrays, and render temporaries |
| $DE..$DF | Music player zero page |
| $0400 | Field A screen colors and sprite pointers |
| $0801 | Initial BASIC loader |
| $0816 | Fill B seventh sprite |
| $0A20 | Incremental tile palette fade |
| $0C00 / $0E00 | Two sprite sets in VIC bank zero |
| $1000 | Shared Color RAM source, copied to $D800 |
| $1400 | Front-facing color and darker-shade lookups |
| $1490 | Fill A final sprite |
| $16D0 | Edge-row pointer tables |
| $1800 | CPU-only crossing buffers |
| $1A00 | Unrolled marker clearing |
| $2000 | MCI field A bitmap |
| $4000 | MCI field B bitmap |
| $5F40 | Ball entrance zoom profile |
| $6000 | Shared-vertex projection |
| $6A00 | Fill B first six sprites |
| $7800 / $7A00 | Matching sprite sets in VIC bank one |
| $7C00 | Field B screen colors and sprite pointers |
| $8000 | Coordinate multiplication tables |
| $9400 | Field A screen-color source |
| $9800 / $9C00 | Edge-curve pointer tables |
| $A000 | Exact edge-crossing samples |
| $A800 / $A900 | Compact edge pointers |
| $AA00 | Compact edge index bases |
| $AB00 | Pentagon normal multiplication table |
| $AC00 | Pentagon culling, dispatch, and shared-vertex gathering |
| $B000..$BBB0 | Dance Nation player and song data |
| $BC00 | Fixed-endpoint hexagon and pentagon edge kernels |
| $C200 | Shared Color RAM disco animation and palette |
| $C410 | Sprite palette fade maps |
| $C490 | Outro sprite color fade helper |
| $C500 / $C600 | Periodic yaw and pitch speeds |
| $C700 | Intro, main scene, and ending controller |
| $C900 | Detached hexagon fragments |
| $CC34 | Fill B final sprite |
| $D000 | Immutable field B screen source beneath I/O |
| $D400..$DBFF | Packed palette fade maps beneath I/O |
| $E000 | Runtime beneath disabled KERNAL ROM |
| $F000 | Fill A first seven sprites, ending before hardware vectors |

In VIC bank zero, sprites in $1000..$1FFF would read character ROM. The display
bank-zero buffers deliberately stay below $1000. Bank one uses RAM at
$7800/$7A00. Assembly guards reject overlaps between code, tables, bitmaps,
sprite buffers, and the hardware vectors.

The palette fader briefly exposes RAM beneath I/O. The raster IRQ saves the
interrupted memory configuration, enables I/O for VIC/CIA/SID work, and restores
the previous mapping before returning. This keeps music and MCI field changes
running while the fader reads its immutable source and lookup pages.

The normal multicolor bitmap display is enabled, including its badline fetches.
Sprite pointers, positions, colors, and enable bits change in the line-zero IRQ.
The sprite-only renderer presents every two PAL frames: 25.06 fps, with
39312 clocks per nominal render budget. Rotation integrates the periodic speeds
using 256 angle units per full turn. Angles continue across speed-profile wraps;
geometry still runs live. The visible border stays black.
Startup allows one extra PAL frame before the first presentation so an arbitrary
initial raster position cannot shorten the first render's deadline.

## Verification

```sh
# Requires NumPy and Pillow.
python3 verify.py
# Two complete speed periods:
python3 verify.py --frames 513
python3 verify.py --variant baseline
python3 verify.py --variant golden
python3 verify_music.py --ticks 2000
python3 verify_scene.py
```

The scene verifier checks initial black with music, every background fade level,
the zero-to-full entrance zoom, and unchanged SID writes during banked fades.
It injects SPACE through VICE's keyboard matrix and checks the actual CIA input,
including cancellation during the first partial picture fade. The timer case
runs all 9022 PAL ticks, compares the native counter with elapsed raster clocks,
and watches every missed-deadline write. Both exit paths check 45 fragment
presentations, distinct linear velocities, continuing rotation, stable face
identities, signed edge clipping, palette fade, final black, and muted sound.
The scene receipt is `build/hexagon/scene-verification/report.json`.

Geometry checks cover all 65536 yaw/pitch pairs at all thirteen zoom scales.
Hexagon spans stay within 17x19 logical steps and pentagons within 14x15,
fitting the 24x21 sprite grid. Native verification checks 513 presentations,
covering two speed periods, fractional-angle carries, zoom wrap, and multiple
polygon cycles. It compares all 258552 sprite bytes against independent rational
polygon spans and checks
their matching copies in the other VIC bank, all 1845 edge-table samples, and actual
VIC output against the expected composition. It also checks the ranked face
selection against all twenty hexagons and twelve independently recovered
pentagons. It checks each pentagon's five original boundary edges and the
150/50-pose switch clock, including the displayed mode on the intervening field.
Eight nonempty sprite buffers are reached in hexagon mode; pentagons use at
most six. Both prepared bitmaps and both screen-color maps remain
unchanged for every presentation. Color RAM must match the independent
uniform palette model in all 110 selected cells and retain every other source
cell. Native sprite colors must match an independent
rotated-normal Z calculation and the brightness bands. All five
sprite shades must appear. Every presentation must arrive on the
two-PAL-frame cadence with zero missed deadlines.
Source verification checks the measured origin and independently derives the
complete opening from the original bitmaps, attributes and Color RAM. It
checks complete animated coverage, exact white-contour preservation, unchanged
pixels outside the touched cells, and the recorded static boundary repairs.
All sixteen possible Color RAM colors must affect only the opening pixels.
Intervening
PAL-frame checks verify field B selection, one-pixel X scroll, darker sprite
colors, unchanged geometry, matching sprite copies, and shared disco colors.
Native screenshots check both VIC fields at full scale, minimum zoom, and in
pentagon mode against the independently decoded prepared bitmap and current
palette. Every presentation
checks foreground sprite priority; native output must match the expected
foreground composition. Sprites may cover artwork because their priority
places them above the bitmap.

Screenshots, animation, monitor logs, PRG hashes, source-image hashes, and CPU
measurements are saved under `build/<variant>/verification/`.

Hardware: [Christian Bauer's VIC-II reference](https://www.cebix.net/VIC-Article.txt).
Geometry: [Wolfram MathWorld's truncated icosahedron](https://mathworld.wolfram.com/TruncatedIcosahedron.html).
