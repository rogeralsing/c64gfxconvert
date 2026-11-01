# Eight-sprite FLI and AFLI players

## FLI Virtual + Sprites

The converter now exports a wide-pixel FLI underlay with an independent hires sprite layer. The valid area is 208 × 200 physical pixels, or 104 wide logical columns; eight sprites cover a 192-pixel field. Each FLI tile retains the global background, one ColorRAM tile color, and two colors per row. See [the raw ZIP contract and native build workflow](FLI-LAYERS.md).

The shared layer builder, capture tool, and verifier support this format. The [native fixture PRG](prg/fli-sprites-native-20261101/fli-sprites-native-fixture/fli-sprites-native-fixture.prg), generated from the converter, uses cyan background index 3 and 4,714 white sprite pixels. Its [PAL verification](runs/fli-sprites-native-20261101/layer-verification.json) passes three captures: all 41,600 active pixels and 15,360 black pixels below the image match, visible RAM and ColorRAM have zero mismatches, and advancing frame counters accompany identical PNGs. No REU is required. The existing AFLI and checker examples below are preserved.

## Native player for converter layers

The AFLI path in the [layer builder](prg/build-layers.py) turns the converter’s version 1 ZIP into a standalone PAL C64 PRG. It loads `image.afl`, packs the arbitrary 192 × 200 raster mask into hardware sprite patterns, and uses the selected sprite color. No REU is required. See [the AFLI layer format](CONVERTER-LAYERS.md).

All three supplied exports have passed three actual PAL VICE captures each:

| Export | PRG | Sprite color / pixels | Verification |
| --- | --- | --- | --- |
| `wh40k-layers.zip` | [wh40k-layers.prg](prg/wh40k-layers-20261101/wh40k-layers/wh40k-layers.prg) | White / 1,854 | [Report](runs/wh40k-layers-20261101/layer-verification.json) |
| `wh40k-layers (1).zip` | [wh40k-layers-1.prg](prg/wh40k-layers-20261101/wh40k-layers-1/wh40k-layers-1.prg) | Black / 9,206 | [Report](runs/wh40k-layers-1-20261101/layer-verification.json) |
| `wh40k-layers (2).zip` | [wh40k-layers-2.prg](prg/wh40k-layers-20261101/wh40k-layers-2/wh40k-layers-2.prg) | Black / 7,178 | [Report](runs/wh40k-layers-2-20261101/layer-verification.json) |

Each capture matches all 41,600 pixels in the 208 × 200 valid area, including the eight-sprite field at x112–303. All 15,360 pixels in the full-width area below the image are black. Both visible AFLI RAM halves match, PNGs are identical within each version, and frame counters advance by 26 between captures. [Build receipts](prg/wh40k-layers-20261101/build-receipt.json) retain the exact input and output hashes. This is bounded three-capture evidence.

The player uses two VIC banks within each frame: `$4000` holds the upper image and `$C000` the lower image, alongside phase-specific sprite patterns and pointer tables. The switch at raster 135 makes the AFLI boundary source y87; sprite pointer fetches cross at y88. Overlapping stored rows preserve fetches around the boundary. It retains the 14-cycle row kernel, 21-row sprite reuse, and black cleanup below row 200. This bank switch does not alternate whole display frames.

Build the three ZIPs into a fresh directory:

```sh
rtk proxy python3 afli-sprite-viewer/prg/build-layers.py \
  --output afli-sprite-viewer/prg/wh40k-new-build \
  /Users/rogerjohansson/Downloads/wh40k-layers.zip \
  "/Users/rogerjohansson/Downloads/wh40k-layers (1).zip" \
  "/Users/rogerjohansson/Downloads/wh40k-layers (2).zip"
```

Capture one generated program, then compare it against its exact source ZIP:

```sh
rtk proxy python3 afli-sprite-viewer/capture-layers.py \
  --output afli-sprite-viewer/runs/wh40k-new-capture \
  --symbols afli-sprite-viewer/prg/wh40k-new-build/wh40k-layers/boot-rendered.sym \
  afli-sprite-viewer/prg/wh40k-new-build/wh40k-layers/wh40k-layers.prg \
  /Users/rogerjohansson/Downloads/wh40k-layers.zip

rtk proxy python3 afli-sprite-viewer/validation/verify-layers.py \
  afli-sprite-viewer/runs/wh40k-new-capture \
  /Users/rogerjohansson/Downloads/wh40k-layers.zip \
  --split-y 87
```

The validator defaults to `--split-y 87`, matching this kernel. The builder and capture tool refuse existing output directories. They preserve source ZIPs, rendered assembly, symbols, expected bank data, receipts, and emulator evidence. The pinned GoDot engine remains under the [included MIT license](GoDot-LICENSE.txt).

## Original checker prototype

[Download the cleaned Trial2 PRG](prg/face-afl-trial2-20261101/face-afl.prg). It is a standalone PAL C64 program with BASIC `SYS8192`; no REU is required. The source is `images/face-afl.afl`. The verified player in `afli-viewer` remains separate.

The wider timing strip excludes source x0–111. The valid AFLI area is **208 × 200**, source x112–319. Eight real monochrome, unexpanded hardware sprites cover x112–303 (**192 pixels**). They show white 4 × 3 checker blocks, with transparent holes revealing the original AFLI pixels. The same 24 × 21 pattern repeats when each sprite’s Y coordinate advances by 21.

Trial2 retains the proven image kernel. Immediately after 200 rows, it selects black invalid-bitmap mode (`$D011=$70`), blacks all eight sprite colors, and disables new sprite DMA. Active sprite DMA can finish without drawing white below the image. Sprite Y is reset to 31 while starts are disabled; colors and enable bits return only after raster wrap, preventing an unintended second start at raster 287. The normal bitmap mode and IRQ are then restored for the next frame.

The PRG SHA256 is `d51e83695cc72f69bb0067b58d3f1c558752cafc92d96f762a1be5d4a38ffb67`. A fresh rebuild reproduced the program, bootstrap, and expected bank bytes exactly. The source AFLI is unchanged.

[Three actual PAL VICE captures](runs/face-afl-trial2-20261101/capture.json) have identical PNG hashes while the frame counter advances by 26 between captures. The [independent comparison](validation/face-afl-trial2-20261101-comparison.json) checks all 41,600 valid-area pixels per capture: 19,200 white checker pixels and 22,400 preserved source pixels, with zero mismatches. The entire 384 × 40 pixel region below the image is black in all three captures. These are bounded observations, not a claim of indefinite stability.

Build into a new directory:

```sh
rtk proxy python3 afli-sprite-viewer/prg/build-prgs.py \
  --output afli-sprite-viewer/prg/face-new-build \
  images/face-afl.afl
```

Capture and verify a fresh build:

```sh
rtk proxy python3 afli-sprite-viewer/capture.py \
  --output afli-sprite-viewer/runs/face-new-capture \
  afli-sprite-viewer/prg/face-new-build/face-afl.prg \
  images/face-afl.afl
```

Both commands refuse existing output directories. Each build retains the rendered assembly, symbols, expected bank bytes, hashes, and [receipt](prg/face-afl-trial2-20261101/build-receipt.json). Trial1 and its reports remain historical artifacts.

The first full badline at raster 48 initializes RC; raster 49–247 use fixed 14-CPU-cycle rows. All 64 sprite pointers in each VIC bank are `$FD`, selecting the shared checker at `$7F40` / `$FF40`. The sprites have front priority, hires pixels, and no X/Y expansion (`$D01B/$D01C/$D01D/$D017=0`). VIC X positions are 136,160,184,208,232,256,280,304 (`$D010=$E0`). The idle loop is `$2088`, NMI handler `$208B`, active second-stage IRQ `$0EE5`, and frame counter `$02F0`. Bank A’s full 16KB and bank B’s copied `$C000–$FFA3` payload plus runtime vectors are checked; bank B’s unused RAM tail is unspecified.

The method follows [Roland Toegel, Count Zero, and George Taylor’s eight-sprite FLI article, disC=overy3 (1997), sections 2–3](https://codebase64.net/doku.php?id=magazines%3Adiscovery3). The IRQ wrapper derives from the [pinned MIT GoDot PAL player](https://github.com/godot64/GoDot/blob/90c8c5c05a6683edb76a82efd8d3cff6f4713c3d/extras/iflidiashow.a), with the [license included](GoDot-LICENSE.txt). Its hash and patched instructions are checked before building. [Christian Bauer’s VIC-II description](https://www.cebix.net/VIC-Article.txt), sections 3.7–3.8, explains RC priming, invalid bitmap mode, and sprite DMA behavior.
