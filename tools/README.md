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

## Dither pairs and neighboring tones

Analyze the palette-snapped PNGs to count vertical color pairs and their spatial
neighbors. Use the extractor manifest to select artwork only, excluding preview
sheets and palette illustrations:

```sh
python3 tools/analyze-dither-pairs.py \
  --manifest /path/to/snapped/manifest.json -o pair-analysis
```

The script also accepts individual PNG paths. It requires opaque images with
identical horizontal pixel pairs and exact colors from the specified palette.
`--palette` defaults to `palettes/peptoette-a.vpl`. It does not resize or recolor
the inputs. Identical decoded images are counted once, with aliases recorded.

Each 2 × 1 multicolor pixel is counted once. Every vertical neighbor is sampled:
rows 0–1, 1–2, 2–3, and so on. Both row phases contribute, with separate phase
counts in the JSON output. Reversed pairs share one identity and their counts
are added together. The darker color goes first, using CIE L* derived from
linear sRGB luminance. Colors within 1 L* are ordered by C64 index instead.
Original orientation counts are retained.

Horizontal neighbors are one logical pixel apart. Vertical neighbors start two
rows apart, so the two pairs do not share a pixel. Each right/down contact is
counted once, separately by direction. Same-pair contacts describe continued
texture and are stored separately from transitions between different pairs.
Filtering never creates a new edge across a removed rare pair.

The default graph keeps pairs with at least **500 occurrences**, then links
with at least **50 contacts** between retained pairs. Override those values with
`--min-count` and `--min-edge-count`. Full counts remain available regardless of
these display thresholds. Solid same-color pairs are included in the data so
they can serve as endpoints in tone ramps. These same-color pairs are shown by
default in the same list, matrix, and neighbor view as two-color pairs. They use
the same frequency threshold; the report can hide them with a checkbox.

Each pair also includes its virtual 50/50 color. The RGB channels are decoded to
linear sRGB, averaged, then encoded back to 8-bit sRGB for display. The report
shows this solid color beside the original pair, together with relative
luminance Y as a percentage. Perceptual lightness L* remains a separate measure.
JSON includes `virtual_rgb`, `virtual_hex`, and `luminance`; CSV includes the hex
color and luminance. Exported Y uses the 0–1 scale and is calculated before RGB
byte rounding. For example, black plus white gives `#BCBCBC`, Y = 0.5.

Outputs:

- `analysis.json`: full per-image and aggregate counts, orientations, phases,
  contacts, source indices, thresholds, and duplicate-image aliases.
- `pairs.csv`: all observed pair frequencies and their retention flags.
- `neighbors.csv`: all different-pair contacts and their retention flags.
- `report.html`: a self-contained interactive report with frequency filters,
  pair previews, neighbor counts, a contact matrix, source-position highlights,
  and candidate tone chains. The sibling `dither-pairs-report.html` template is
  required to generate this report. Fonts are optional network resources.

The supplied dataset contains ten unique images and 120 observed two-color
pair types. At the default threshold, 76 remain and cover 97.32% of two-color
occurrences. Image borders and raster stripes contribute to the statistics;
use the image filter to inspect their influence. Contacts also occur at object
boundaries. A chain of observed links is a candidate ramp, not proof that one
continuous or intentional gradient appears in the artwork.

```sh
python3 -m unittest discover -s tests -p 'test_dither_pairs.py'
```

## Talent converter neighbor data

Export the artwork analysis into the converter's compact neighbor catalogue:

```sh
python3 tools/build-talent-neighbors.py \
  --analysis /path/to/pair-analysis/analysis.json \
  --output talent-neighbors.js
```

The exporter reads allowed pairs and the analysis date from `talent-palette.js`;
`--catalog` selects another catalogue. It preserves each deduplicated image's
ID and only exports contacts with at least 50 observations whose endpoints are
both allowed pairs. Pair IDs use numerically sorted C64 indices, independently
of the analysis palette's dark-first ordering. `count` combines horizontal and
vertical contacts; directional counts, source images, pixels, and private paths
are omitted. Images with no qualifying edges remain in the catalogue.

Each exported edge therefore has evidence within one image. Joining edges into
a black-to-white candidate scale does not establish that one continuous gradient
appeared in the source artwork. Re-run the exporter when the source analysis or
allowed Talent pairs change.
