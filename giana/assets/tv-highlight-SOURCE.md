# Native spherical glass shine

`tv-highlight-mask.json` is the editable art source: 21 rows of 24 native pixels,
with `#` lit and `.` transparent. The approved mask contains 90 lit pixels,
about 18% coverage. Curved half-tone and quarter-tone contours form the top-left
part of a spherical reflection, fading inward, right, and down. Its outer edge
follows the rounded TV corner.

`prepare-tv-highlight.py` packs these rows directly into one 64-byte hires C64
sprite. Each row has three bytes, leftmost pixel in bit 7; byte 63 is zero
padding. Set bits use runtime cyan 3; clear bits are transparent. The native
`tv-highlight-preview.png` contains the same exact cyan/transparent pixels.
The scene keeps the sprite at TV-local `(0, 3)`.

All 504 source pixels are checked against the packed bits. The importer also
checks that no lit pixel covers the top-left black corner mask and records the
source/output hashes in `tv-highlight-import.json`.

The unchanged original user-supplied PNG remains as `tv-highlight-source.png`,
SHA-256 `48361b03d5c4eaf9aab57ed7f21d0695a83359c21a6fc9fb88d52ccc7cd6a946`.
It is a historical reference; the native row mask is the current design input.

```sh
python3 giana/tools/prepare-tv-highlight.py
```
