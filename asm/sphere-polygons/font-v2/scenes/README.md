# Scripted checker sphere

Edit `spiral.scene.cjs`. Its `frame(time)` function returns the sphere's center,
diameter, visibility, and yaw/pitch/roll. Positions use the C64's 320 × 200 screen
pixels; angles use radians. `checks: 14` means 14 × 7 checker squares. Each font
dot occupies 2 × 2 screen pixels, using the existing deduplicated 168-character
font.

The supplied scene starts with a five-second entrance at 25 fps. It grows and
travels for three seconds while tumbling, then holds its position and 96-pixel
diameter. During the fifth second it smoothly settles into a fixed diagonal
tilt. It then spins around its own tilted axis using a repeating 32-frame loop.
The HTML and native player follow the same playback script: the entrance once,
the spin six times, then hold the final image.

Run these commands from the repository root:

```sh
rtk proxy node asm/sphere-polygons/font-v2/generate-scene.cjs --write-frames
rtk proxy node asm/sphere-polygons/font-v2/measure-scene.cjs
rtk proxy node asm/sphere-polygons/font-v2/build-scene-preview.cjs --summary-file asm/sphere-polygons/font-v2/build/scene-storage/spiral/study.json
```

The generator accepts `--scene /absolute/path/to/scene.cjs` and
`--output /absolute/path/to/output`. It writes a 1,000-byte character screen for
every frame when `--write-frames` is supplied. `reference.frames` concatenates
those screens. `font.bin` contains the shared font; `scene.json` records every
sampled pose. Pixel references are host-side verification assets, not C64 data.

Frame `i` samples time `i / fps`. The 157 stored images consist of 125 entrance
images (including the initial empty image) and 32 loop images. The scene declares
`loop: {startFrame: 125, frameCount: 32, periodRadians: 4 * Math.PI / 14}`.
Its unique timeline lasts 6.28 seconds; every repeat adds 1.28 seconds without
more stored images. Two checker columns restore the same color pattern, so the
loop only needs 51.43 degrees of rotation. The generator checks that its
mathematical endpoint exactly matches the loop's first character screen.

Memory measurements include 156 forward deltas and the closing delta from
frame 156 back to frame 125. The first screen is cleared at startup, so it
needs no stored 1,000-byte seed. The report compares sparse pairs, character
groups, and a hybrid, all without Huffman or disk streaming.

Build the native player with:

```sh
rtk proxy node asm/sphere-polygons/font-v2/build-scene-player.cjs
```

The build requires KickAssembler. Set `KICKASS` to its executable path to
override the workstation default. Native verification requires Python 3,
Pillow (`python3 -m pip install Pillow`), and VICE's `x64sc`:

```sh
rtk proxy python3 asm/sphere-polygons/font-v2/verify-scene.py --vice /absolute/path/to/x64sc
```

The verifier defaults to the workstation's VICE path when `--vice` is omitted.

Edit `spiral.playback.json` to change the C64 playback without generating new
frames. `repeat` is the total number of times to play that range:

```json
[
  {"op": "play", "startFrame": 0, "frameCount": 125, "repeat": 1},
  {"op": "play", "startFrame": 125, "frameCount": 32, "repeat": 6},
  {"op": "hold"}
]
```

This plays 317 images, lasting 12.68 seconds at nominal 25 fps. The two `play`
commands and final `hold` occupy 11 bytes. Each extra repetition reuses the
same 32 images and adds 1.28 seconds without more animation data. The player
supports repeat counts from 1 to 65,535, plus `"forever"` for an endless spin.
The build rejects jumps without a matching stored delta.

Use `--script=/absolute/path/to/playback.json` with the native builder for a
different script. For HTML or GIF export, use
`--playback-script /absolute/path/to/playback.json`. Their default script is
the same `spiral.playback.json`. HTML playback and GIF export accept finite
integer repeat counts; `"forever"` is supported by the native player.

The native build report separates delta payload, frame pointers, font, player
code, and working screen RAM. PRG address-gap padding is reported separately
from meaningful loaded bytes.

The published [PRG](results/player.prg) and [PAL VICE proof](results/verification-summary.json)
verify all 317 displayed images and 634 video fields, including the final hold.
The player uses 20,083 meaningful loaded bytes, plus 1 KiB of screen RAM and
5 zero-page bytes. Measured playback is 25.06 fps.

Export a finite demonstration with six repetitions of the stored loop:

Media export requires Python 3 and Pillow (`python3 -m pip install Pillow`).

```sh
rtk proxy python3 asm/sphere-polygons/font-v2/export-scene-media.py --loop-repeats 6
```

The GIF plays the entrance once and then the repeated spin, rather than looping
the entire entrance. Its default export follows the playback JSON; the explicit
`--loop-repeats` option overrides the spin count for a demonstration. A longer
demonstration does not increase C64 storage.
