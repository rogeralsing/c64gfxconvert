# C64 GFX Convert

[Open the converter](https://rogeralsing.github.io/c64gfxconvert/)

A browser-based Commodore 64 image converter with FLI, IFLI, MCI, AFLI, HIRES,
Multicolor Bitmap and NUFLI modes, optional virtual colors, sprite
overlays, and native exports. Image processing stays in your browser.

<img src="assets/images/c64-studio-layers.png" alt="C64 Studio showing a layered FLI conversion and per-layer image settings" width="960">

## Run locally

Open `index.html` in a modern browser. No build step or server is required.

## Graphics formats

| Format | Logical pixels | Color allocation |
| --- | --- | --- |
| **FLI** | 160 × 200, double-width pixels | One shared background, one color per 4 × 8 tile, and two additional colors per scanline within each tile. |
| **IFLI** | Two 160 × 200 frames, double-width pixels | Alternates two FLI frames one hires pixel apart. Both frames share the background and tile color; scanline colors may differ. |
| **MCI** | Two 160 × 200 frames, double-width pixels | Alternates two standard multicolor frames one hires pixel apart. Both frames share the background and one tile color; each frame has two additional colors fixed throughout each 4 × 8 tile. The full image width is available. |
| **AFLI** | 320 × 200, square pixels | Two freely chosen colors per 8 × 1 scanline strip, with no shared background color. |
| **HIRES** | 320 × 200, square pixels | Two freely chosen colors per 8 × 8 tile, with no shared background color. |
| **HIRES · 2 colors** | 320 × 200, square pixels | One user-selected shadow/highlight pair for the entire image. Source brightness drives the pattern; no automatic palette matching. |
| **Multicolor Bitmap** | 160 × 200, double-width pixels | Three colors per 4 × 8 tile, plus one background color shared by the whole image. |
| **NUFLI** | 320 × 200, square pixels | A hires bitmap with 8 × 2 color cells and a sprite underlay for additional color choices. |

Virtual colors are a separate layer setting: **Off**, **Lines**, or **Checkers**.

For two-color artwork, select **Hires · 2 colors**, then choose **Shadow color**
and **Highlight color** from the normal C64 palette. Adjust **Brightness**,
**Contrast**, **Levels**, and **Dither** to shape the result. Dither at 0% uses a
hard threshold; 100% uses a 4 × 4 ordered pattern. Palette choices do not change
the pattern, so swapping the colors also works as an inversion. Transparent
layer edges use ordered coverage to keep the final image within the selected
pair. Both colors are preserved in saved projects.

**Save Hires** downloads an Art Studio `.art` image: 320 × 200 pixels with the
selected colors, stored as a native C64 hires bitmap. The 9,009-byte file contains
a `$2000` load address, bitmap, screen colors, border color, and padding. Export
always uses the converted image, even while viewing the unrestricted source.

**Save Multicolor** downloads a Koala Painter `.koa` image in **Multicolor Bitmap**
mode. The 10,003-byte file contains a `$6000` load address, bitmap, screen colors,
color RAM, and the selected background color. Export uses the fitted composition
from all visible layers, regardless of the selected preview tab.

**Save MCI** downloads a native True Paint `.mci` image containing both fitted
bitmaps, their separate screen colors, shared color RAM, and background color.
The 19,434-byte file loads at `$9C00`. Like other exports, it uses the fitted
composition regardless of the selected preview tab. MCI uses standard multicolor
cells without FLI's per-scanline color changes or reserved left columns.

The IFLI and MCI previews alternate the two frames and show them individually below
the simulation:

<img src="assets/images/c64-studio-ifli.png" alt="IFLI simulation with its two constituent frames shown underneath" width="960">

## Layers

Build one image from several source images, with separate conversion settings
for each layer. For example, put scenery on the bottom layer and figures with
a transparent background on a layer above it. Transparent pixels reveal the
layers below. The opening screenshot shows both layers combined; these views
show each layer on its own:

| Background layer only | Foreground layer only |
| --- | --- |
| <img src="assets/images/c64-studio-background-layer.png" alt="Scenery layer visible with the figures layer hidden" width="480"> | <img src="assets/images/c64-studio-foreground-layer.png" alt="Figures layer visible with the scenery layer hidden" width="480"> |

**Image** settings apply to the whole composition: graphics format, background
color where the format supports it, and the hardware sprite color in sprite
modes. All layers use the same graphics format.

Select a layer in **Layers** to edit its source image, position, scale,
brightness, contrast, levels, hue, saturation, noise, interlace, dithering,
virtual colors, palette limits, excluded colors, and sprite matching. Changes
apply only to the selected layer, so you can tune figures and scenery
independently.

- Click **New**, then **Choose image**, to add a source image to a new layer.
- Layers paint from bottom to top. Use the arrows to change their order.
- Click an eye to hide or show a layer without deleting it.
- Use **Duplicate** to start from an existing layer, or **Delete** to remove one.
- Double-click a selected layer name, or press **F2**, to rename it.
- Drag the preview to move the selected layer, or use **Scale**, **Position X**,
  and **Position Y** for precise placement.

Visible layers combine into one image before the final C64 tile restrictions
are applied. The preview and native export use that same fitted result.

## Projects

Use **Save project** to download a JSON file containing all layers, their source
images, and their settings. **Open project** restores that file, including layer
order, visibility, the active layer, shared graphics settings, and preview options.
Images are embedded in the JSON, so the original files are not needed to reopen
it. Larger source images produce larger project files. Projects stay local.

[Open the DutchBreezeRemake demo](https://rogeralsing.github.io/c64gfxconvert/?project=dutchbreeze)
with all layers and settings loaded. The `?project=dutchbreeze` query parameter
opens the bundled demo automatically. Without it, the converter starts empty.
You can also download [the project JSON](examples/DutchBreezeRemake.json) and
choose **Open project**.

## Tests

```sh
node --test tests/*.test.cjs
```

## GitHub Pages

GitHub Pages publishes the repository root from `main`. Pushes to `main`
automatically update the site. The `.nojekyll` file serves the static app
without Jekyll processing.
