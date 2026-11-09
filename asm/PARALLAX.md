# Rimrunner PAL C64 parallax

This standalone C64 program combines a static MCI sky with the extracted
Rimrunner scenery maps and a mounted rider. The sky uses the top 96 pixels of
the supplied 320×200 True Paint image, without scaling or color conversion.
The city scrolls at two pixels per PAL field, the middle tile band at four,
and the near foreground at six. Eight running poses use seven multicolor
hardware sprites. The rider faces right while the world moves left.
Press **SPACE** to pause or resume. A gray border indicates pause.

Building requires Python 3 with Pillow and NumPy, Java, and a KickAssembler wrapper at
`~/.local/bin/kickass`. The run script uses Homebrew VICE at
`/opt/homebrew/bin/x64sc`. Install the Python dependencies in a virtual environment
with `python3 -m pip install Pillow numpy`, then use that environment below.

From the repository root:

```sh
rtk proxy ./asm/build-parallax.sh
rtk proxy ./asm/run-parallax.sh
```

The default sky source is `../c64demo/images/rimrunner-bg.mci`, relative to the
repository root. Pass another source as the first argument to either script.
The original MCI file remains unchanged. The build prepares the captured
original graphics and the cropped sky, then writes
`asm/build/parallax.prg` and debug symbols. It requires the local raw captures
described in [RIMRUNNER.md](RIMRUNNER.md); those build artifacts are not bundled
with a fresh source checkout. The resulting PRG runs on a stock PAL C64 or PAL
VICE without an expansion unit.

## MCI sky and scrolling

The top twelve character rows, 96 of the 200 picture lines, use multicolor bitmap
mode. MCI alternates two bitmap phases every PAL video frame, with phase B shifted
one hires pixel to the right. The scene itself remains static. Phase switching
continues while SPACE pauses the scenery and mounted animation.

At the sky's lower edge, a raster interrupt switches VIC bank, screen, graphics
mode, and fine scroll to the original character-based scenery. The sky and city
occupy separate horizontal bands. The bitmap is not copied or scrolled each frame.

Below the sky, the screen uses the original character sets and a 38-column
viewport. `$d016` bits 0–2 move the picture by zero to seven hires pixels. When
this counter wraps, the program shifts the band's character codes one column
left and inserts a column from the original native map format.

Raster IRQs change the scroll position, character set, and palette between
regions. Each moving band has its own fine-scroll counter and map position.
The main loop copies each band's character codes after the raster has drawn it.
The visible character rows have constant Color RAM values across each row, so
horizontal movement needs no Color RAM copy. The sky has its own static Color
RAM values in rows 0–11.

The rider's seven sprite tiles form a 72 by 63 pixel figure with the rider
seated on the animal. The preparation tool composes the original mounted
renderer parts, preserves opaque black outlines, mirrors the figure to face
right, and repacks it into seven hardware tiles. Eight poses advance every two
PAL fields. The feet can pass behind foreground graphics through sprite priority.

The demo uses original scenery set 1: an 80-column direct background map, a
120-column map of 4×2-character tiles, and a 188-column map of 4×4-character
tiles. New tile columns are expanded during execution. The road's two rows
contain blank character zero, as in the original. The upper map rows hidden by
the sky remain present in the native map data.

All three original scenery sets and their nine level assignments are exported;
this demo displays set 1. See [RIMRUNNER-LEVELS.md](RIMRUNNER-LEVELS.md). This
remains an automatic parallax experiment without movement controls or collision
detection. Timing targets PAL.

Source: [src/parallax.asm](src/parallax.asm).

Asset preparation: [tools/prepare-rimrunner-parallax.py](tools/prepare-rimrunner-parallax.py).

| Data | Address |
| --- | --- |
| Runtime | `$0801` |
| Screen | `$4000` |
| Original world character sets | `$4800`, `$5000` |
| Header character set | `$5800` |
| Eight mounted running poses | `$6000`–`$6fff` |
| Native scenery maps, tile definitions, colors, and sprite offsets | `$8000`–`$8996` |
| MCI phase A screen / bitmap | `$8c00` / `$a000` |
| MCI phase B screen / bitmap | `$cc00` / `$e000` |

## Local validation

Before adding the sky, PAL VICE at normal speed completed 385 consecutive
checkpoints without missing a video frame. Across those checkpoints, 308,000
character cells matched an independent reader of the original RAM maps. All
three cameras wrapped their full map width. Eight mounted poses advanced every
two fields, and loaded sprite bytes matched the prepared assets exactly.
That receipt is in `build/rimrunner-native-levels-validation/`.

An independent baseline screenshot comparison checked 65 captures and all eight
poses: 70,300 opaque sprite pixels matched their prepared PNGs exactly, without
palette fitting. The final foot rows were excluded because foreground graphics
may cover them. That comparison is in `build/rimrunner-parallax-validation/`.
The sky preparation receipt is `build/rimrunner-mci-sky/manifest.json`; its PNGs
include decoded phases and a 50/50 phase-average preview. The average does not
simulate temporal MCI flicker.

With the MCI sky enabled, normal-speed PAL VICE also completed 385 consecutive
checkpoints without a dropped video frame. Independent decoding of the supplied
MCI file matched 3,764,736 captured sky pixels across both phases, with zero
differences. This comparison covers all 96 sky lines and the inner 304 columns.
All native sky payloads matched their source bytes in runtime RAM. The same run
checked 308,000 scenery character cells, all map wraps, the mounted animation,
and continued MCI phase switching while the world was paused. The receipt and
captures are in `build/rimrunner-mci-sky-96-validation/`.

References:

- Commodore's *Programmer's Reference Guide*: [smooth scrolling sequence and
  38-column mode](https://www.devili.iki.fi/Computers/Commodore/C64/Programmers_Reference/Chapter_3/page_129.html),
  [fine-scroll registers](https://www.devili.iki.fi/Computers/Commodore/C64/Programmers_Reference/Chapter_3/page_130.html).
- Christian Bauer's [VIC-II technical reference](https://www.cebix.net/VIC-Article.txt).
