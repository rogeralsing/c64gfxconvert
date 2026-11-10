# Multicolor pixel extractor

`extract-multicolor.py` recovers the pixel grid from enlarged C64 multicolor
screenshots. Each detected source cell becomes exactly **2 × 1 PNG pixels**.
The script copies the decoded source pixel at the center of each cell. It does
not average, interpolate, quantize, match a C64 palette, or adjust colors.
Alpha is retained. Original files are never modified and existing outputs are
never overwritten.

```sh
python3 -m pip install -r tools/requirements.txt
python3 tools/extract-multicolor.py picture.png -o extracted
python3 tools/extract-multicolor.py screenshots/*.png -o extracted-batch
```

Automatic detection measures where neighboring source pixels change along each
axis, then finds the integer cell spacing and grid origin. It supports separate
horizontal and vertical scales. Flat images, very sparse images, native-size
images with one-pixel-high cells, and blurred/fractionally scaled images may
need explicit geometry. Unclear detection fails instead of resizing arbitrarily.
Lossless input requires every color transition to align with the detected grid,
including differences of one channel unit. Repeated identical cells can hide
the original spacing; use `--cell` when no visible transitions reveal it.

Set source cell dimensions manually when needed:

```sh
python3 tools/extract-multicolor.py picture.jpg -o extracted --cell 10x5
```

The complete canvas is retained by default. Complete cells become output pixels;
partial cells at the edges are omitted and recorded in `manifest.json`.
`--origin X,Y` selects the first complete cell relative to the chosen region.
The manifest also records source dimensions, actual encoding, cell dimensions,
the sampled source rectangle, detection confidence, and output dimensions.

Crop only when the intended picture rectangle is known. Coordinates and sizes
are in **source pixels**, before shrinking:

```sh
python3 tools/extract-multicolor.py picture.jpg -o extracted-screen \
  --crop 160,175,1600,1000 --cell 10x5
```

This example produces **320 × 200**, representing 160 × 200 multicolor cells.
Without the crop, a 1920 × 1360 screenshot with 10 × 5 source cells produces
**384 × 272**. Empty margins and raster effects can be intentional, so the script
does not infer a 320 × 200 crop from the drawing's bounds.

JPEG compression has already altered colors and edges. For JPEG input, the
detector ignores small changes caused by compression, but the output still
copies exact decoded center-pixel RGB values. It cannot reconstruct the original
pre-compression colors. Use lossless source PNGs when available.

## Optional C64 palette snapping

Add `--palette` to replace each sampled color with its nearest RGB color from a
16-color VICE `.vpl` file. This is an explicit color-changing step. It does not
add dithering or change the pixel grid. Without this flag, extraction still
copies source colors unchanged.

```sh
python3 tools/extract-multicolor.py picture.jpg -o extracted-16-colors \
  --palette palettes/peptoette-a.vpl
```

To process PNGs already extracted to 2 × 1 multicolor cells, specify that grid:

```sh
python3 tools/extract-multicolor.py extracted/*.png -o snapped \
  --cell 2x1 --palette palettes/peptoette-a.vpl
```

Pass only artwork PNGs, not the combined preview sheet. Output keeps its source
dimensions in this second example. The manifest records exact RGB counts before
and after snapping, usage of all 16 palette entries, and RGB-distance statistics.
Images may use fewer than 16 palette colors. Alpha is retained separately.

`palettes/peptoette-a.vpl` contains **PEPTOette_a** from the
[C64GFX palette catalogue](https://c64gfx.com/api/palettes.json). It was the closest
of the 117 catalogue entries to all 11 supplied screenshots in the 2026-11-10
analysis. Identification is inferred from RGB matches; JPEG compression prevents
proving the exact original source values. The original extracted images remain
available separately.

Run the extractor's focused checks:

```sh
python3 -m unittest discover -s tests -p 'test_*palette.py'
python3 -m unittest discover -s tests -p 'test_multicolor_extractor.py'
```
