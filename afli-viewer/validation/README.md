# Expected AFLI references

These images are source-file decodes, **not emulator captures**. The native
320×200 PNGs and 64,000-byte color-index buffers include every source column.
The labeled PNGs use nearest-neighbor 2× display scaling for visual QA.

The script reads the current `C64_PALETTE` declaration in `index.html`.
For scanline y and character column c: tile=(y>>3)*40+c, row=y&7;
screen=file[2+row*1024+tile], bitmap=file[0x2002+tile*8+row].
Bitmap bit 7 is the leftmost pixel; bit 1 selects the screen byte's high nibble,
bit 0 its low nibble. No palette snapping, temporal mixing, or source cropping
is applied. Source hashes, palette values and decoded hashes are recorded in
`reference-metadata.json`.

Regenerate with `rtk proxy python3 afli-viewer/validation/decode-references.py`.
The default reference and actual-capture preview is Darth2.
Pass exact source basenames to add or refresh individual references.
