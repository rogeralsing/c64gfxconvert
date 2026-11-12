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

Requirements: Python 3 with Pillow and NumPy, Java, KickAssembler, and PAL VICE.
`KICKASS` overrides the default `~/.local/bin/kickass`; `VICE` overrides
`/opt/homebrew/bin/x64sc`.

From this directory:

```sh
./build.sh
./run.sh
```

The program is `build/parallax.prg`. The build uses the included original
`assets/rimrunner-bg.mci` and `assets/rimrunner-road2.mci`, plus the frozen
mounted-rider tiles, pose map, and offsets under `assets/mounted/`.
It does not require another repository or any files from the original ignored
`asm/build/` directory. The shared display palette remains
`../../palettes/colodore.vpl`.

Custom background and road files may be passed as the first two build/run
arguments. Use absolute paths. The compositor preserves both MCI phases,
screen attributes, and Color RAM. Generated BIN files, `composite.mci`, source
manifest, and decoded previews remain under `build/rimrunner-mci-composite/`.
The phase-average PNG approximates combined colors; it does not simulate native
temporal flicker.

This copy was collected on 2026-11-12 from `asm/src/parallax.asm`,
`asm/src/rimrunner-parallax-assets.asm`, and their preparation tools. Both runtime
assembly files are unchanged. `assets/manifest.json` records frozen-input hashes;
`assets/mounted/original-preparation.json` preserves the original actor provenance.
The full original packed poses are retained for checking the deduplicated atlas.

### Optional extraction from original captures

`tools/prepare-rimrunner-parallax.py` retains the original actor preparation
algorithm. It is separate from the default build because it needs the saved
original-game captures described in [RIMRUNNER.md](../../asm/RIMRUNNER.md):

```sh
python3 tools/prepare-rimrunner-parallax.py \
  --world-captures /absolute/path/to/captures \
  --source-ram /absolute/path/to/captures/raster-00/ram.bin \
  --output /absolute/path/to/new-preparation
```

The capture directory must contain `raster-00/ram.bin`, `raster-04/ram.bin`,
`raster-07/ram.bin`, and `raster-00/color.bin`. The extraction tool also emits
historical character-world previews, which the current MCI runtime does not use.

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
[RIMRUNNER-LEVELS.md](../../asm/RIMRUNNER-LEVELS.md). The current bitmap demo uses the supplied
MCI scenery instead of those character maps.

## Validation

The collected build is byte-identical to the current original 45,805-byte PRG:
`098210caec6b138445bc40bf18dfe17e1522e0a399eae8409bbdb914bfc99ebb`.
The import checked every composed source region in both phases and all 56
expanded rider tiles against the frozen original packed poses. A bounded PAL
VICE smoke checks startup, normal field cadence, both sprite atlases, all eight
poses, SPACE pause, continued MCI switching while paused, and resumed movement.
Fresh receipts are `build/import-check.json` and
`build/import-smoke/verification.json`. The smoke is a collection check, not a
new permanent verification suite.

The following larger native checks were performed previously on the original
PRG with the same hash. `references/baseline-proof.json` records their key
results, original receipt locations, and receipt hashes; this import did not
rerun their full excerpts.

Composition was checked over both phases: 64,000 logical multicolor pixels
matched the two source crops exactly. Re-expanding all 56 deduplicated actor
tiles also matched the original packed poses exactly. The original build receipts and native
emulator captures remain under the ignored `asm/build` directory.

The faster road2 build completed 641 consecutive normal-speed PAL fields with
no missed fields or stalled camera steps. Independent decoding of the two
source MCI files matched 34,167,864 native background pixels, excluding the
actor box and hardware borders, with zero differences. Measured travel over
640 fields was 320, 640, and 1,280 pixels: exactly 0.5, 1, and 2 display pixels
per PAL field. Each band wrapped at least once. The receipt and captures are in
`../../asm/build/rimrunner-road2-fast-validation/`.

A separate runtime check compared 462 hardware sprite tile fetches across both
VIC banks against the original packed poses. All eight poses appeared, and all
seven hardware Y positions confirmed the rider's twenty-pixel upward move.
Pause froze all cameras and the gait while MCI phases continued alternating;
resume restarted all bands. See `../../asm/build/rimrunner-road2-fast-actor-pause-validation/`.
