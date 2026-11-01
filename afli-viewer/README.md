# Standalone PAL AFLI player

The builder embeds a standard 16,385-byte `.afl` image in a runnable C64 PRG. Each program has a BASIC `SYS 8192` entry, needs no image files or REU at runtime, and displays one static hires image until reset. Use a PAL C64 or PAL VICE.

Build Darth2 from the repository root into a new directory:

```sh
rtk proxy python3 afli-viewer/prg/build-prgs.py \
  --output afli-viewer/prg/darth2-new-build \
  /Users/rogerjohansson/Downloads/darth2.afl
```

The output directory must not already exist. KickAssembler at `~/.local/bin/kickass` and the pinned `ifli-viewer/diashow_eng.prg` are build dependencies. Source AFLI images and existing IFLI players are never modified. Receipts include source, player, bootstrap, and generated PRG hashes.

The player reuses the [original GoDot English PAL raster engine](https://www.godot64.de/iflis/diashow_eng.prg), with [its source and credits](https://github.com/godot64/GoDot/blob/90c8c5c05a6683edb76a82efd8d3cff6f4713c3d/extras/iflidiashow.a). Its [MIT license](GoDot-LICENSE.txt) accompanies each build. The initial `$D016` immediate at `$0e76` changes from `$19` to `$08` for hires, 40 columns and X-scroll 0. The original VIC-bank alternation remains, with identical AFLI screens and bitmaps in both banks, so the image is static.

The original 23-cycle scanline blocks, 208-block generator, and interrupt stabilization instructions remain intact. The raster triggers move four scanlines earlier; generated and initial `$D011` both start at `$38`. A 20-cycle entry shim at `$2090` consists of seven NOPs, `BIT $02`, and `JMP $8400`. It makes the first phase-zero block start at PAL raster 48, cycle 5, allowing the first badline to reset the VIC row counter before cycle 14. Later blocks settle at cycle 8. The [VIC-II hardware reference](https://www.cebix.net/VIC-Article.txt), section 3.7.2, describes that first-phase cycle-14 row-counter reset.

`$D018` initially selects screen matrix `$08`; its generated sequence starts at `$18`, compensating for the register write occurring after color DMA, so the previous matrix supplies the current scanline. The old X-scroll toggle at `$0efa-$0f01` becomes a `$D011=$30` vertical-border postlude, retaining valid hires bitmap mode. These changes place all 200 fetch rows within raster lines `$30-$f7`, following the [full-height FLI display constraints](https://codebase64.c64.org/doku.php?id=base:fli_displayer). Every patched byte sequence and its checked original value is listed in the build receipt.

At runtime screens occupy `$4000-$5fff` and `$c000-$dfff`; the corresponding 8,000-byte bitmaps occupy `$6000-$7f3f` and `$e000-$ff3f`. The bootstrap relocates the second staged bank before generating the original speedcode at `$8400`. Its idle display loop is `$2088`.

Hires FLI has a hardware artifact in the first three character columns. The generated PRG clears those columns in its stored screens and bitmap, but this does not guarantee a black mask during playback: the hardware strip can appear gray or black as the VIC banks alternate. The leftmost 24 pixels are unreliable and excluded from the valid image area, leaving 296 × 200 visible image pixels, beginning at source x=24. This hides 8 pixels beyond the converter's 16-pixel reserved area. The [FLI display routine reference](https://codebase64.c64.org/doku.php?id=base:fli_displayer) describes this hires-specific artifact and the additional sprite/timing work needed to cover it; this builder preserves the proven timing instead.

The validated [darth2.prg](prg/full200h-20261031/darth2.prg) is 48,013 bytes; a separate rebuild reproduced it byte for byte. SHA-256: `2defa1a7a5d027a7620d63475ec16d295a45c128f8455faa662307ddb27363c5`.

Darth2 ran in PAL VICE at 100% speed with warp disabled. Independent comparison matched all 59,200 valid pixels across all 200 source rows, with no vertical cropping, and its two 16,192-byte display banks matched their expected payloads. The original AFLI file retained its hash. Evidence: [build receipt](prg/full200h-20261031/build-receipt.json) and [Darth2 pixel comparison](validation/darth2-full200h-comparison.json).

To open a generated program in a fresh VICE instance and capture its display and RAM:

```sh
rtk proxy python3 afli-viewer/preview.py \
  --output afli-viewer/runs/darth2-new-preview \
  afli-viewer/prg/full200h-20261031/darth2.prg \
  /Users/rogerjohansson/Downloads/darth2.afl
```
