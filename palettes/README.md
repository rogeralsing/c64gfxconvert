# C64 PAL palettes

The converter offers **Colodore (PAL)** and **Pepto (PAL)** in the Image panel,
below the graphics format. Both use the 16 RGB values distributed with VICE,
in standard C64 color-index order:

- [Colodore](https://github.com/VICE-Team/svn-mirror/blob/main/vice/data/C64/colodore.vpl), the existing default.
- [Pepto](https://github.com/VICE-Team/svn-mirror/blob/main/vice/data/C64/pepto-pal.vpl), the darker PAL reference.

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

In virtual modes, **Darkest level** and **Lightest level** clamp the C64 Palette
view to the existing 17 virtual brightness rows, numbered 0–16. Row 0 is black,
row 1 mixes black with blue/brown, row 2 uses blue/brown, and row 16 is white.
Dithering stays inside the selected bounds. These caps do not change the source
image; subsequent format fitting uses the capped palette image as its target.

NUFLI and PAFLI verification load `colodore.vpl` explicitly into VICE with
neutral saturation, contrast, brightness, and gamma controls. Existing palette
files and screenshots under older validation directories remain historical
records of the previous image-sampled palette.
