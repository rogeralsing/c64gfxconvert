# PAFLI — Phase-Alternating FLI

PAFLI is this converter's name for two alternating, full-resolution AFLI frames
whose color-cell grids are four hires pixels apart. Each frame still permits
two arbitrary C64 colors per 8 × 1 scanline cell. The artwork stays aligned.

Select **PAFLI**, upload an image, and open its preview tab. The converter shows
alternating frames, both aligned phases side by side, and a static 50/50 blend.
**Save PRG** includes both frames and a PAL player; autostart it in VICE or load
and `RUN`. Downloads use the suffix `-pafli.prg`. No external image files or REU
are required.

The source, virtual palette, source adjustments, dithering, and even/odd-row
component selection follow AFLI Virtual. Both frames use the first virtual
component on even rows and the second on odd rows. The two fits are independent:

1. Fit frame A with the existing AFLI mapper.
2. Move the same resolved source left four pixels, then fit frame B.
3. Display frame A with X-scroll 0 and frame B with X-scroll 4. The second
   bitmap's rightward display shift cancels its leftward source shift.

No source resampling, column splitting, or new virtual-color selection occurs
between the two fits. Their different 8 × 1 groupings permit different legal
approximations. The shared visible area is x=28..319 and y=0..191, 292 × 192 pixels, accounting
for the three-column AFLI hardware artifact plus the four-pixel scroll phase.
Pixels outside that common area do not influence the color fitting. The four
padded columns of frame B are clipped rather than wrapped.

The final eight rows are cleared in both raw bitmap planes and all eight color
banks. Both ink and paper are black, so idle bitmap reads cannot expose the
unused color beneath the image. The preview and blend show the same black rows.
This is a data-only mask; the original raster player and timing stay unchanged.

The browser simulation targets 50 frame changes per second. A display's refresh
rate can make the simulation look different from a PAL C64. The static blend
shows the arithmetic mean of the two aligned frames.

The player reuses the pinned GoDot PAL engine and this project's validated
AFLI startup and timing shim. It changes the scroll phase by four after each
image, then uses the engine's original VIC-bank toggle. The lower-border
postlude remains in place. BASIC `SYS 8384` starts it; `$20a0` marks the end of
the active frame and `$02f0` counts completed frames. See
[GoDot-LICENSE.txt](GoDot-LICENSE.txt).

Regenerate the browser's embedded player with:

```sh
python3 pafli/prg/build-player.py
```

This needs the installed Kick Assembler toolchain. It verifies the upstream
binary hash and original bytes before every patch. `prg/player.json` records
the source, hashes, memory layout, and patch purposes.

Run conversion and file-contract tests with:

```sh
node --test tests/pafli.test.cjs tests/image-layout.test.cjs
```

`verify-vice.py` checks six consecutive PAL frames against the two aligned
preview references, compares both active RAM banks to the exported PRG, checks
the 0/4 scroll phases, and confirms one phase change per frame. It uses an
external [Colodore PAL palette](../palettes/README.md) with neutral color controls
for exact RGB comparisons. Existing screenshots below used the previous palette.

```sh
python3 pafli/verify-vice.py pafli/validation/data-only-bottom/tentacles-pafli-fixed.prg \
  pafli/validation/data-only-bottom/tentacles-0.bin \
  pafli/validation/data-only-bottom/tentacles-1.bin \
  --output /tmp/pafli-pal-check
```

References:

- [Pinned GoDot PAL engine source](https://github.com/godot64/GoDot/blob/90c8c5c05a6683edb76a82efd8d3cff6f4713c3d/extras/iflidiashow.a)
- [VIC-II horizontal fine scrolling](https://www.cebix.net/VIC-Article.txt)

## Verification

The data-masked `validation/data-only-bottom/tentacles-pafli-fixed.prg` passed PAL VICE 3.10 at normal
speed with warp disabled. Six consecutive frames alternate A/B with X-scroll
0/4. Each phase's three screenshots are identical, both 16,192-byte active banks
match the export, and all 58,400 checked pixels, including the cleared rows, match their aligned preview in
every capture. The usable image and the area below it are black from row 192
downwards; the existing 28-pixel left artifact remains excluded. See
`validation/data-only-bottom/pal-verified/verification.json`.

The full Node suite passed 52 tests, including fixed-position hires landmarks,
different 8 × 1 source groupings, and independent decoding of both exported
banks. NTSC and physical C64 hardware have not been tested.

The Colodore verification rerun also passed: both RAM banks matched, all six
frames matched their phase references, and alternating phases remained stable.
See `validation/colodore-pal/verification.json`.
