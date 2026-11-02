# Colodore PAL

The converter uses the 16 Colodore PAL RGB values distributed with VICE, in
standard C64 color-index order. The source palette is
[VICE's colodore.vpl](https://github.com/VICE-Team/svn-mirror/blob/main/vice/data/C64/colodore.vpl).
The [Colodore color model](https://www.pepto.de/projects/colorvic/) documents
the underlying measurements and analog display assumptions. It is a PAL
reference, rather than a universal RGB palette for every physical C64 and TV.

`index.html` uses these values for palette controls, source mapping, and all
graphics modes. Brightness bands and virtual-color mixtures are calculated
from the palette when the page loads.

NUFLI and PAFLI verification load `colodore.vpl` explicitly into VICE with
neutral saturation, contrast, brightness, and gamma controls. Existing palette
files and screenshots under older validation directories remain historical
records of the previous image-sampled palette.
