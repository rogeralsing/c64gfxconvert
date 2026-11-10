# Cut-glass diamond

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

The diamond is saved independently of later experiments. Its [scene entry](scene/demo-diamond.mjs)
and imported [glass scene](scene/demo-glass.mjs) are copied alongside a
[hash manifest](scene/manifest.json). The PRG, font, preview and receipts remain
in this directory. Rebuild the snapshot by passing this saved entry to
`build-glass.cjs --scene`, with a fresh output directory.

The eight-sector glass gem has a small flat table, sloping crown, broad girdle
and pointed pavilion. Its closed convex mesh contains 48 outward-facing
triangles and 26 welded vertices. Broad per-facet grayscale tones complement
physical transmission and studio reflections, keeping the diamond readable in
the coarse font. Wire edges are secondary.

The 44-pixel ball, two-pixel black foreground contour and cyclic motion are
preserved. Polished roughness 0.10 replaces the cube's stronger frosted look.
The rear image remains spatially refracted. Additional roughness softening
changes only one bitmap pixel in the rear control and no final character pixels;
the preview is therefore described as polished refraction rather than blur.

| Measured item | Result |
| --- | ---: |
| PAL playback, including waits | 25.0623 fps |
| Actual images verified in both fields | 481 |
| Exact visible fields | 962 |
| Real loop wraps verified | 2 |
| Delta movie, including closure | 12,196 bytes |
| Fixed font | 2,048 bytes |
| Meaningful loaded code, state and data | 15,615 bytes |
| PRG including address gaps | 22,437 bytes |

The 160-image orbit repeats after one blank startup image. Working memory
additionally uses a 1,024-byte screen, 1,024-byte color RAM and nine zero-page
bytes. Music and IRQ work are absent from the timing. The native player and
shared font are unchanged.

GPU and independent character controls verify the shape, source dependencies,
refraction, depth and black outline. Spatial refraction changes 236 pixels in
the isolated rear character contribution relative to zero thickness. The black
annulus has no white leaks in any frame. Active-bounds character error is 2.06%,
with no white pixels outside the allowed object mask. Both bitmap and character
previews passed visual review for diamond recognition before native verification.

The GIF is made from actual verified VICE screenshots, cropped to the active
picture and enlarged with nearest-neighbor pixels. Its decoded pixels match
all 160 crops; its 40 ms frame duration approximates PAL timing.

Receipts: [native verification](native-verification.json), [GPU and bitmap](bitmap-verification.json),
[character matching](character-audit.json), [character controls](character-visibility.json),
[assembled decoder](host-proof.json), [summary](summary.json).
Build commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`2a44385aeea92e945b1267d66ed000d2b343d043eea00196263852715f3b57d8`.
