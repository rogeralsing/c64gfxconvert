# Moving refractive glass cube

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Optical controls](optics-controls.png)

The shaded ball is now 44 physical pixels across, compared with 24 in the
[earlier alpha-only scene](../glass/README.md). The cube moves cyclically in
three axes. In front of it, the ball remains sharp. Behind it, Three.js's
screen-space transmission pass displaces and splits the image; material
roughness adds softening. Grayscale studio reflections move across the cube.

The optical effects are rendered offline, then converted with screen-fixed
Bayer dithering and the existing immutable 256-glyph font. The literal-delta
C64 player is unchanged. It plays one blank startup image, then repeats the
160-image orbit forever, with no blank inside the loop.

| Content | Bytes |
| --- | ---: |
| Delta movie, including closing patch | 13,973 |
| Fixed font | 2,048 |
| Frame pointers | 322 |
| Playback bytecode | 11 |
| Meaningful loaded code, state and data | 17,392 |
| PRG file, including address gaps | 24,214 |

PAL VICE verifies 25.0623 fps, 481 images in both fields, and two real loop
wraps: 962 exact visible fields. See [native verification](native-verification.json)
and the [summary](summary.json).

Working memory additionally uses a 1,024-byte screen, 1,024-byte color RAM and
nine zero-page bytes. The nominal orbit lasts 6.4 seconds at 25 fps. The GIF is
built from actual VICE screenshots, cropped to the active picture and enlarged
with nearest-neighbor pixels. Its decoded pixels match all 160 screenshot
crops; its 40 ms frame duration approximates PAL timing.

GPU controls compare the full scene with zero-thickness and zero-roughness
variants, plus corresponding ball-hidden controls. This distinguishes optical
distortion from changes to the cube background. Exact loop endpoints and every
Bayer decision are checked independently. The foreground ball has no glass
depth errors.

Independent fixed-font matching reproduces the selected production screens.
Behind the cube, refraction changes 584 pixels in the isolated ball contribution
relative to the zero-thickness control; softening changes 204 relative to sharp
refraction. The ball affects 48 character cells. Thin rim lines can fragment in
the fixed font, and the additional softening is subtler than the refraction in
1-bit output. Active-bounds font error is 2.82%, with no white pixels outside the
GPU object silhouette.

Receipts: [GPU and bitmap calibration](bitmap-verification.json),
[character matching](character-audit.json), [character optical controls](character-visibility.json),
and [assembled decoder](host-proof.json).
Build commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`06da4fe30eea77aa4e4d9e7a911f319fa73ee467f5d8bed9dddb7bfcafe5a136`.
