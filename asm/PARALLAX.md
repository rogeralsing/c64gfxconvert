# Rimrunner MCI parallax for PAL C64

The demo combines two True Paint MCI images into one 320×200 picture and adds
Rimrunner's mounted rider. Both image phases, screen attributes, and Color RAM
are preserved without scaling or color fitting.

| Band | Picture lines | Source | Average movement per PAL field |
| --- | --- | --- | --- |
| Sky | 0–95 | Background image, lines 0–95 | Static |
| Fence | 96–127 | Road image, lines 0–31 | 0.5 display pixels |
| Road | 128–159 | Road image, lines 32–63 | 1 display pixel |
| Front | 160–199 | Road image, lines 64–103 | 2 display pixels |

The world moves left and the rider faces right. SPACE pauses world movement
and the running animation; MCI phase switching continues. The program targets a
stock PAL C64, without REU or another expansion.

## Build and run

Requirements: Python 3 with Pillow and NumPy, Java, a KickAssembler wrapper at
`~/.local/bin/kickass`, and Homebrew VICE at `/opt/homebrew/bin/x64sc`.
In a Python virtual environment, install dependencies with
`python3 -m pip install Pillow numpy`.

From the repository root:

```sh
rtk proxy ./asm/build-parallax.sh
rtk proxy ./asm/run-parallax.sh
```

The default source images are `../c64demo/images/rimrunner-bg.mci` and
`../c64demo/images/rimrunner-road2.mci`, relative to the repository root. The
scripts accept custom background and road paths as their first two arguments.
Use absolute paths for custom files. Original image files remain unchanged.

The mounted rider still requires the saved original-game capture described in
[RIMRUNNER.md](RIMRUNNER.md). The source images, captures, and generated assets
are local prerequisites, not part of a fresh source checkout.

The build writes `asm/build/parallax.prg`. The compositor also writes a complete
`asm/build/rimrunner-mci-composite/composite.mci`, native BIN files, a source
manifest, and decoded phase previews. The phase-average PNG approximates the
combined colors; it does not simulate native temporal flicker.

## Bitmap scrolling

The moving bands use 38-column mode to hide fine-scroll edge bytes; the composite
file retains all 40 columns. The entire picture stays in multicolor bitmap mode.
MCI alternates phases every
PAL field, with phase B displaced one display pixel to the right. World camera
positions advance in two-pixel steps so both phases retain the same character
alignment and shared Color RAM values.

Each phase has two bitmap areas. The sky always uses the first. Each lower band
independently chooses which bitmap contains its current visible data. The other
bitmap prepares that band's next eight-pixel step in small work units. When it
is ready, the program commits the matching attributes and switches the band's
bitmap selection at its raster boundary. Columns wrap within each source band.

This prototype uses buffered bitmap copying rather than VSP. Work is weighted
between bands to match their different speeds. There is no full-screen bitmap
copy on every video frame.

Phase B's first bitmap crosses the CPU's I/O window. Copy bursts temporarily map
physical RAM and remain interruptible. Each raster interrupt saves the CPU's
memory mapping, enables I/O for its register writes, and restores the previous
mapping before returning. Eight-column jobs avoid waiting for hidden-I/O copy
windows, allowing all three bands to sustain their requested speeds.
The phase's unused upper area in its second bitmap holds screen and sprite data.

## Mounted rider

Eight running poses use seven multicolor hardware sprites. The original sprite
pixels are mirrored to face right and packed without losing opaque black.
Deduplication retains 41 unique 64-byte tiles and a 56-byte pose-to-tile map.
Both VIC banks contain the tiles, so phase changes do not require copying poses.
The rider's base hardware Y position is 131, twenty display pixels above the
previous position. Foreground priority can cover the actor's feet.

## Memory and sources

| Data | Phase A | Phase B |
| --- | --- | --- |
| VIC bank / first bitmap | `$4000` | `$c000` |
| Screen attributes | `$6000` | `$e000` |
| Mounted sprite tiles | `$6400` | `$e400` |
| Second bitmap, visible lower portion | `$6f00`–`$7f3f` | `$ef00`–`$ff3f` |

Runtime: [src/parallax.asm](src/parallax.asm).
Asset imports: [src/rimrunner-parallax-assets.asm](src/rimrunner-parallax-assets.asm).
Image composition: [tools/prepare-rimrunner-mci-composite.py](tools/prepare-rimrunner-mci-composite.py).
Actor preparation: [tools/prepare-rimrunner-parallax.py](tools/prepare-rimrunner-parallax.py).

The original character-map extraction remains documented in
[RIMRUNNER-LEVELS.md](RIMRUNNER-LEVELS.md). The current bitmap demo uses the supplied
MCI scenery instead of those character maps.

## Validation

Composition was checked over both phases: 64,000 logical multicolor pixels
matched the two source crops exactly. Re-expanding all 56 deduplicated actor
tiles also matched the original packed poses exactly. Build receipts and native
emulator captures remain under the ignored `asm/build` directory.

The faster road2 build completed 641 consecutive normal-speed PAL fields with
no missed fields or stalled camera steps. Independent decoding of the two
source MCI files matched 34,167,864 native background pixels, excluding the
actor box and hardware borders, with zero differences. Measured travel over
640 fields was 320, 640, and 1,280 pixels: exactly 0.5, 1, and 2 display pixels
per PAL field. Each band wrapped at least once. The receipt and captures are in
`build/rimrunner-road2-fast-validation/`.

A separate runtime check compared 462 hardware sprite tile fetches across both
VIC banks against the original packed poses. All eight poses appeared, and all
seven hardware Y positions confirmed the rider's twenty-pixel upward move.
Pause froze all cameras and the gait while MCI phases continued alternating;
resume restarted all bands. See `build/rimrunner-road2-fast-actor-pause-validation/`.
