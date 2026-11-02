# NUFLI

Select **NUFLI**, upload an image, then open the **NUFLI** preview tab.
**Save NUF** writes a standard uncompressed `.nuf`. **Save PRG** adds a BASIC
launcher for `RUN`, including VICE autostart. Both embed the standard player.
An unpacked NUF loads at `$2000` and starts with `SYS 12288` (`$3000`).

The source and C64 palette views use 320 × 200 square pixels. Existing source
adjustments and palette dithering apply before the hardware fit. This is a
single-frame mode with real C64 colors. It does not use the virtual palette.
The base palette is [Colodore PAL](../palettes/README.md), shared with the other
converter modes. Older validation captures below used the previous palette.

The hardware fit includes:

- Two bitmap colors per 8 × 2 attribute block.
- Six expanded hires underlays covering x=24..311; each sprite pixel is two
  hires pixels wide, with ink independently covering either half.
- Underlay colors shared across 48-pixel columns, changing on odd scanlines.
- Two left-edge sprites, one hires and one multicolor. Outside the first two
  lines of each character row, the bitmap supplies fixed light gray.
- The rightmost eight pixels use only the bitmap.
- Six register-update slots per two scanlines. Eight slots in the standard
  split window are reserved for sprite Y updates. Remaining slots can change
  left-edge sprite colors.

Bitmap and main underlay colors are searched jointly for every 48 × 2 section.
Dynamic programming joins the sections through their shared sprite colors and
finds the minimum main-area error, while leaving at least eight unchanged-color
slots in the standard sprite-Y window. Those writes are allocated to actual spare
slots, preferring the first slot (which cannot update the left edge).

Brightness error takes priority over chroma. The left edge then searches all
color sets reachable with its remaining writes, including simultaneous changes
to multiple sprite colors. It scores both bitmap colors freely on the first two
scanlines of each character row and fixed light gray elsewhere. Main-area and
left-edge allocation remain separate priorities; this is not a globally optimal
search over both regions together.

`nufli-data.js` contains the unchanged player bytes and address tables extracted
from Mufflon v2.0, SVN revision 1440. `nufli-export.js` ports its binary packing;
`nufli.js` is this project's fitter. Original authors: Bitbreaker/Metalvotze,
Crossbow/Crest, and DeeKay/Crest. The original permission notice is preserved in
[MUFFLON-LICENSE.txt](MUFFLON-LICENSE.txt); source URLs and hashes are in
[source.json](source.json).

References:

- [Mufflon source](https://svn.sngs.de/metalvotze/svn/repo/mufflon/)
- [NUFLI hardware and timing](https://cobbpg.github.io/articles/nuflix.html)
- [RECOIL independent decoder](https://github.com/pfusik/recoil/blob/master/recoil.fu)

Run the file-contract and independent full-frame decoding checks with
`node --test tests/nufli.test.cjs`. Emulator evidence belongs in `validation/`.
The quality regression also refits already legal images: staggered underlays,
a changing rightmost underlay with Y writes elsewhere, and both left-edge sprite
layers. All source colors must survive, not merely match the exported preview.

PAL VICE 3.10 verification passed for both `validation/wh40k.prg` (saved through
the browser export buttons) and `validation/stress.prg` (all colors, full width,
left-edge color changes, and sprite split boundaries). Each matched all 64,000
preview pixels in three identical captures at 100% speed with warp disabled.
Reports and screenshots are in `validation/pal-wh40k-verified/` and
`validation/pal-stress-verified/`. NTSC has not been tested.

The joint-search fitter was verified again using WH40K and the full-frame
random stress target. Both PRGs matched all 64,000 preview pixels in three PAL
captures, including Y updates near the end of the legal split window. Current
reports are in `validation/joint-search/pal-wh40k/` and
`validation/joint-search/pal-stress/`. The browser's NUF and PRG buttons were
also checked against the independent decoder and the displayed canvas.

On the same palette-mapped `validation/wh40k-source.png` target, the joint search
reduced summed squared brightness error from 38.4835 to 24.7252 (36%) and changed
5,017 source pixels instead of 6,015. Brightness weighting and source adjustments
were unchanged. Raw measurements are in `validation/joint-search/quality.json`.

To repeat a capture in a new output directory:

```sh
python3 nufli/verify-vice.py nufli/validation/wh40k.prg \
  nufli/validation/wh40k-indices.bin --output /tmp/nufli-pal-check
```

The capture tool needs macOS Homebrew VICE and Pillow. It selects the external
`palettes/colodore.vpl` palette by default, with neutral color controls, so
comparison uses exact RGB values without inferring a palette mapping from the
displayed image. It closes only the VICE process it started.

The Colodore stress export matched all 64,000 preview pixels in three PAL VICE
captures. See `validation/colodore/pal-stress/verification.json`.
