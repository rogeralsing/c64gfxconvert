# Opaque long-arm star

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

This scene contains one opaque star. There is no ball, glass, wireframe, texture
or intermediate gray. Entire triangular facets are black or white. One fixed
broad visible white facet per arm keeps all six rays readable without lighting
flashes. Black faces write depth and occlude farther white faces.

The six pyramid tips lie 40 logical units from the center, compared with 30
previously. Cube half-extent decreases from 10 to 8.5, so each arm extends
31.5 units beyond its base instead of 20. The closed nonconvex geometry still
has 14 vertices, 36 edges and 24 outward-facing triangles.

| Measured item | Result |
| --- | ---: |
| PAL playback, including waits | 25.0623 fps |
| Actual images verified in both fields | 481 |
| Exact visible fields | 962 |
| Real loop wraps verified | 2 |
| Delta movie, including closure | 12,971 bytes |
| Meaningful loaded code, state and data | 16,390 bytes |
| PRG including address gaps | 23,212 bytes |

All 3,014 full tiles and 146,660 empty tiles across the film are preserved
exactly by the fixed font, with no interior stipple. Mixed edge tiles use font
approximation, with 0.617% active-bounds error and no silhouette spill. The six
long rays survive visual review, though a few endpoint pixels simplify.

The 160-image loop repeats after one blank startup frame. Working memory
additionally uses a 1,024-byte screen, 1,024-byte color RAM and nine zero-page
bytes. No music or IRQ workload is included in the timing. The native player
and shared 256-glyph font are unchanged.

The GIF uses actual verified VICE screenshots cropped to the active picture.
Decoded pixels match all 160 crops; its 40 ms frame duration approximates PAL
timing. The standalone [scene source](demo-solid-star.mjs) is saved here too.
Earlier glass scenes and the saved diamond remain untouched.

Receipts: [native verification](native-verification.json), [opaque bitmap proof](bitmap-verification.json),
[character matching](character-audit.json), [assembled decoder](host-proof.json), [summary](summary.json).
Build commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`7c12aeb9288eeb0771582788eba5834198e2686650951e2082d704105ccc022c`.
