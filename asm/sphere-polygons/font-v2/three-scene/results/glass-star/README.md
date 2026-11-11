# Six-tip 3D glass star

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

The eight cube corners are retained. Each square cube face becomes four
triangles meeting at an outward pyramid tip, giving six tips on the positive
and negative X, Y and Z axes. Cube half-extent is 10 logical units and tip
distance is 30. The concave valleys remain visible from a near-diagonal view.

The closed nonconvex surface has 14 vertices, 36 edges and 24 outward-facing
triangles. Pyramid interiors occupy separate face-exterior regions; no internal
cube quads remain. Nearest-surface depth writes prevent farther front-facing
facets from overwriting nearer ones. Broad polished-glass tones carry the shape
through the fixed font. The 44-pixel orbiting ball and black foreground outline
are preserved.

| Measured item | Result |
| --- | ---: |
| PAL playback, including waits | 25.0623 fps |
| Actual images verified in both fields | 481 |
| Exact visible fields | 962 |
| Real loop wraps verified | 2 |
| Delta movie, including closure | 11,181 bytes |
| Meaningful loaded code, state and data | 14,600 bytes |
| PRG including address gaps | 21,422 bytes |

Working memory additionally uses a 1,024-byte screen, 1,024-byte color RAM and
nine zero-page bytes. Music and IRQ work are absent from the timing. The native
player and shared 256-glyph font are unchanged. The 160-image orbit repeats
forever after one blank startup image.

Independent controls verify the source dependency graph, closed mesh, winding,
nonconvexity, actual GPU masks, refraction and black outline. Rear refraction
changes 512 final-character contribution pixels relative to zero thickness;
roughness changes 20 relative to sharp refraction. All outline pixels remain
black. Active-bounds font error is 1.56%; a few outer tip pixels simplify, but
the six-ray silhouette passes visual review.

The GIF uses actual verified VICE screenshots cropped to the active picture.
Decoded pixels match all 160 crops; its 40 ms frame duration approximates PAL
timing. The [diamond and its self-contained source snapshot](../glass-diamond/README.md)
remain saved separately.

Receipts: [native verification](native-verification.json), [GPU and bitmap](bitmap-verification.json),
[character matching](character-audit.json), [character controls](character-visibility.json),
[assembled decoder](host-proof.json), [summary](summary.json).
Build commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`92f67883d15d0df98a16fce6c77054b3e8fee6a4fbbe4ae6267a481a1a0988ca`.
