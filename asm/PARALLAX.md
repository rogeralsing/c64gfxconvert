# Rimrunner PAL C64 parallax

This standalone C64 program uses the extracted Rimrunner world and a mounted
rider. The moons and city scroll at two pixels per PAL field, the road
at four pixels, and the near foreground at six pixels. Eight running poses
use seven multicolor hardware sprites. The rider faces right while the world
moves left. The scene starts automatically.
Press **SPACE** to pause or resume. A gray border indicates pause.

Building requires Python 3 with Pillow, Java, and a KickAssembler wrapper at
`~/.local/bin/kickass`. The run script uses Homebrew VICE at
`/opt/homebrew/bin/x64sc`. Install Pillow in a Python virtual environment with
`python3 -m pip install Pillow`, then run the commands below from that environment.

From the repository root:

```sh
rtk proxy ./asm/build-parallax.sh
rtk proxy ./asm/run-parallax.sh
```

The build prepares the captured original graphics, then writes
`asm/build/parallax.prg` and debug symbols. It requires the local raw captures
described in [RIMRUNNER.md](RIMRUNNER.md); those build artifacts are not bundled
with a fresh source checkout. The resulting PRG runs on a stock PAL C64 or PAL
VICE without an expansion unit.

## How scrolling works

The screen uses multicolor character mode, the original world character sets,
and a 38-column viewport. `$d016` bits 0–2 move the picture by zero to seven hires
pixels. When this counter wraps, the program shifts the band's character codes
one column left and inserts a new column from its looping scenery map.

Raster IRQs change the scroll position, character set, and palette between
regions. Each band has its own fine-scroll counter and map position. The main
loop copies each band's character codes after the raster has drawn that band.
The captured world has a constant Color RAM value across each world row, so
horizontal movement needs no Color RAM copy.

The rider's seven sprite tiles form a 72 by 63 pixel figure with the rider
seated on the animal. The preparation tool composes the original mounted
renderer parts, preserves opaque black outlines, mirrors the figure to face
right, and repacks it into seven hardware tiles. Eight poses advance every two
PAL fields. The feet can pass behind foreground graphics through sprite priority.

The world loops one captured 40-column viewport. It is not the complete original
level map, and its edge join may be visible. This remains an automatic parallax
experiment without movement controls or collision detection. Timing targets PAL.

Source: [src/parallax.asm](src/parallax.asm).

Asset preparation: [tools/prepare-rimrunner-parallax.py](tools/prepare-rimrunner-parallax.py).

| Data | Address |
| --- | --- |
| Runtime | `$0801` |
| Screen | `$4000` |
| Original world character sets | `$4800`, `$5000` |
| Header character set | `$5800` |
| Eight mounted running poses | `$6000`–`$6fff` |
| Looping world screen, colors, and sprite offsets | `$8000`, `$8400`, `$8800` |

## Local validation

PAL VICE at normal speed completed 65 consecutive checkpoints without missing
a video frame. Over 64 frames, the measured scroll distances were 128, 256 and 384
pixels. Screen-memory captures confirmed movement in all three bands while
the header stayed fixed. All eight mounted poses appeared, advancing every two
fields, and the 4,096 sprite bytes loaded in RAM matched the prepared assets exactly.

An independent baseline screenshot comparison checked 65 captures and all eight
poses: 70,300 opaque sprite pixels matched their prepared PNGs exactly, without
palette fitting. The final foot rows were excluded because foreground graphics
may cover them. That comparison is in `build/rimrunner-parallax-validation/`.
The current faster animation and timing receipt are in
`build/rimrunner-parallax-world-fast-validation/`.

References:

- Commodore's *Programmer's Reference Guide*: [smooth scrolling sequence and
  38-column mode](https://www.devili.iki.fi/Computers/Commodore/C64/Programmers_Reference/Chapter_3/page_129.html),
  [fine-scroll registers](https://www.devili.iki.fi/Computers/Commodore/C64/Programmers_Reference/Chapter_3/page_130.html).
- Christian Bauer's [VIC-II technical reference](https://www.cebix.net/VIC-Article.txt).
