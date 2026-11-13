# C64 PAL palettes

The converter offers **Colodore (PAL)** and **Pepto (PAL)** in the Image panel,
below the graphics format. Both use the 16 RGB values distributed with VICE,
in standard C64 color-index order:

- [Colodore](https://github.com/VICE-Team/svn-mirror/blob/main/vice/data/C64/colodore.vpl), the existing default.
- [Pepto](https://github.com/VICE-Team/svn-mirror/blob/main/vice/data/C64/pepto-pal.vpl), the darker PAL reference.

**PEPTOette_a** is also available, using the 16 values published by the
[C64GFX palette catalogue](https://c64gfx.com/api/palettes.json). These values
matched the supplied Talent artwork captures. `peptoette-a.vpl` preserves that
reference in standard C64 index order.

The image-wide **Virtual color mode** is separate from the C64 palette choice.
Computed retains the existing generated pairs. Talent uses the 76 two-color
pairs occurring at least 500 times in the deduplicated captures, plus all 16
solid colors. `talent-palette.js` stores pair indices and compact provenance;
it contains no images or local paths. Talent's virtual RGB values are recomputed
as 50/50 mixtures in linear sRGB whenever the selected C64 palette changes.

The [Colodore color model](https://www.pepto.de/projects/colorvic/) documents
the underlying measurements and analog display assumptions. It is a PAL
reference, rather than a universal RGB palette for every physical C64 and TV.

`palettes.js` supplies these values to palette controls, source mapping, and all
graphics modes. Switching palettes recalculates brightness bands and virtual
colors, updates controls, and renders all layers again. Color selections,
virtual-color exclusions, and brightness limits retain their C64 indices.
Project JSON stores `image.paletteId` as `colodore` or `pepto`; older projects
without this field use Colodore. Native C64 exports contain hardware color
indices, so their displayed RGB colors depend on the computer or emulator palette.

Computed's **Darkest level** and **Lightest level** clamp the C64 Palette view
to its 17 brightness rows, numbered 0–16. Row 0 is black, row 1 mixes black with
blue/brown, row 2 uses blue/brown, and row 16 is white. Talent groups its actual
Oklab lightness values into levels spanning at most three percentage points;
PEPTOette_a currently produces 20 levels. Both palettes use the same brightness
selection, ordered dither, and within-level chroma matching. Talent's caps use
actual lightness percentages. Dithering stays inside the selected bounds.
These caps do not change the source image; subsequent format fitting uses the
capped palette image as its target.

NUFLI and PAFLI verification load `colodore.vpl` explicitly into VICE with
neutral saturation, contrast, brightness, and gamma controls. Existing palette
files and screenshots under older validation directories remain historical
records of the previous image-sampled palette.
