# Verified flagship star

[Download player.prg](player.prg) or view the actual [PAL VICE capture](c64.gif).
One large, lit six-tip star rotates forever, using the fixed 256-glyph
universal drawing font. The 96-image symmetry loop lasts 3.84 seconds at
nominal 25 fps; a full visible revolution takes three loops.

The [native receipt](native-verification.json) verifies all 97 stored images,
289 displayed images, both PAL fields and two real loop wraps. Measured
playback is 25.06224 fps, with 578 visible fields checked. The PRG is 23,578
bytes; meaningful loaded bytes are 16,628, including the 2,048-byte font and
13,337-byte animation payload.

The [bitmap receipt](bitmap-verification.json) checks actual GPU export,
lighting, ordered Bayer quantization, screen bounds and seamless rotation.
The [literal audit](literal-audit.json) independently checks every assembled
6502 transition, including the closing transition and immutable font/movie
bytes. The [source comparison](source-comparison.png) shows the approximation
made by the static charset; native playback reproduces those character
screens exactly.

[content-rows-stride3.json](content-rows-stride3.json) preserves the selected
65 content glyphs. Together with `../../universal-font.bin` and
`../../../universal/font.cjs`, it pins the universal font without requiring
the full training corpora.

Build and validation commands are in the [pipeline README](../../README.md#flagship-star-very-large-lit-endless-rotation).
