# Rimrunner graphics study

Original C64 graphics were extracted from a running PAL copy of the UCG release
of Rimrunner. The source archive is recorded in
`build/research/rimrunner/download.json`:

- [CSDb release](https://csdb.dk/release/?id=49543)
- [C64 screenshot and artwork reference](https://gamesdb.launchbox-app.com/games/images/109362-rimrunner)
- [Original instructions](https://www.lemon64.com/doc/rimrunner/492)

The local files are under `build/research/rimrunner/extracted/`. They are ignored
build artifacts, not part of the published repository.

## Assets

`asset-pack.zip` and its `asset-pack/` directory contain:

- Fourteen distinct observed sprite variants as transparent PNGs and raw C64
  sprite data, with a numbered atlas.
- Three observed character sets as 2,048-byte BIN files and glyph-sheet previews.
- Screen codes and Color RAM for eight raster states.
- A static background reconstruction without sprites, plus a landscape view
  below the status panel.
- An observed composition of the green sprite parts. The rider and dinosaur
  can be separate actors in this captured scene.
- A manifest with original addresses, C64 palette indices, positions, source
  hashes, and limitations.

Each sprite BIN contains 64 bytes without a PRG load address. Its first 63 bytes
encode 24 by 21 source pixels. Multicolor sprites use the palette order
transparent, shared color 1, local color, shared color 2. PNG previews use
Colodore RGB; the manifest retains native C64 indices. Character-sheet palettes
are previews; actual colors depend on each screen cell and raster region.

This asset pack is one captured viewport. The separate
[scenery-map extractor](RIMRUNNER-LEVELS.md) recovers the original background and
tile maps for three scenery sets reused across nine levels. The viewport pack
does not contain every animation frame. Its background preview is a static
reconstruction of observed raster regions, not a cycle-exact frame renderer.

## Reproduce from the saved captures

The decoding and packaging tools require Python 3 and Pillow. In a Python
virtual environment, install Pillow with `python3 -m pip install Pillow`.

From the repository root, use a new empty output directory:

```sh
rtk proxy python3 asm/tools/rimrunner-assets.py \
  --capture asm/build/research/rimrunner/extracted/captures/raster-00 \
  --output /tmp/rimrunner-raster-00
```

The decoder expects `ram.bin`, `vic.bin`, `color.bin`, and `cia2.bin` from the
same paused emulator state. Each capture also contains a VICE snapshot and a
native screenshot. The eight decoded directories can be packaged with:

```sh
rtk proxy python3 asm/tools/package-rimrunner.py \
  --decoded asm/build/research/rimrunner/extracted/decoded \
  --output /tmp/rimrunner-asset-pack \
  --source-receipt asm/build/research/rimrunner/download.json
```

## Capture and validation

The original PRG was preserved. Emulator execution entered the intro's existing
exit routine at `$b07c`; a single simulated joystick fire read at `$836d` entered
the game. Eight consecutive stops at `$8610` captured the game's raster states.
The character set, palettes, and sprite pointers changed during the frame, so
one border snapshot was not sufficient to decode the visible assets.

Independent checks compared every capture against its same-stop VICE snapshot:
all 65,536 RAM bytes and all 1,024 Color RAM low nibbles matched. The selected
bank is `$4000`; observed character sets are at `$4000`, `$4800`, and `$5000`.

The highscore reconstruction matched 60,800 visible logical pixels with no
geometry differences after mapping VICE's RGB palette. Three gameplay sprites
also matched their native screenshot: 182, 128, and 170 opaque pixels, with no
mismatches.

## Reuse

These are extracted original game graphics. No explicit free reuse license was
found. Extraction does not itself grant permission to redistribute the artwork
in another game. See [PRV's guidance for game developers](https://www.prv.se/sv/spelutveckling/hantera-spelkoncept-strategiskt/upphovsratt/).
