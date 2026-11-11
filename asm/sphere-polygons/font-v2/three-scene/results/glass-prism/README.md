# Triangular glass prism

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

The closed triangular prism has two parallel triangular ends and three
rectangular sides. It reuses the cube scene's physical glass, cyclic motion,
44-pixel orbiting ball and black foreground contour. Sloping facets split and
refract the rear image. The C64 receives the resulting character deltas, with
the same fixed 256-glyph font and unchanged native player.

| Content | Bytes |
| --- | ---: |
| Delta movie, including closing patch | 12,992 |
| Saving versus outlined cube movie | 1,066 |
| Fixed font | 2,048 |
| Frame pointers | 322 |
| Playback bytecode | 11 |
| Meaningful loaded code, state and data | 16,411 |
| PRG including address gaps | 23,233 |

PAL VICE verifies 25.0623 fps, 481 images in both fields, and two real loop
wraps: 962 exact visible fields. See [native verification](native-verification.json)
and the [summary](summary.json).

The 160-frame orbit repeats after one blank startup image. Working memory
additionally uses a 1,024-byte screen, 1,024-byte color RAM and nine zero-page
bytes. The GIF uses actual VICE screenshots cropped to the active picture;
its decoded pixels match all 160 crops, and its 40 ms frame duration
approximates PAL timing.

The bitmap proof checks the scene entry and imported glass source hashes,
GPU loop endpoints, every Bayer decision, actual prism ray intersections and
optical controls. Rear refraction changes 684 final-character contribution
pixels versus zero thickness; softening changes 300 versus sharp refraction.
The foreground black annulus contains no white pixels in any frame. Controls
compare the prism with the same prism without its outline, not with the old
cube. Opposing refracted lobes can partly cancel in their centroid, so shape
and footprint changes are measured alongside displacement.

The current font loses fragments of thin prism edges. This remains visible in
the [bitmap comparison](bitmap-vs-c64.png); neither the font nor the native
decoder was changed to hide that limitation.

Receipts: [bitmap and optics](bitmap-verification.json), [character matching](character-audit.json),
[character optical controls](character-visibility.json), [assembled decoder](host-proof.json).
Build commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`e98da84073a2458fc92ddbc8e5f43641adf8004136c156eb707dd4b034e0ee3b`.
