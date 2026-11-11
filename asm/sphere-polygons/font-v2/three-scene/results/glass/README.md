# Glass cube and orbiting ball

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

The ball orbits a stationary tilted glass cube. It passes in front of the cube
and remains visible through it on the rear pass. Continuous grayscale shading
and reflections become screen-fixed ordered dithering during bitmap export.
The original 256-glyph font and fast literal-delta player are unchanged.

The C64 plays one blank startup image, then repeats 160 orbit images forever.
The orbit lasts 6.4 seconds at nominal 25 fps, or 6.3841 seconds at measured PAL
speed. There is no blank frame or reset inside the loop.

| Measured item | Result |
| --- | ---: |
| PAL playback, including waits | 25.0623 fps |
| Actual images verified in both PAL fields | 481 |
| Exact visible fields | 962 |
| Real loop wraps verified | 2 |
| Delta payload, including closing patch | 3,316 bytes |
| Fixed font | 2,048 bytes |
| Frame pointers | 322 bytes |
| Playback bytecode | 11 bytes |
| Meaningful loaded code, state and data | 6,735 bytes |
| PRG file, including address gaps | 13,557 bytes |

Working memory additionally uses a 1,024-byte screen, 1,024-byte color RAM, and
nine zero-page bytes. No music or interrupt workload is included in the timing.
The GIF uses actual verified VICE screenshots cropped to the active picture,
scaled with nearest-neighbor pixels. Its 40 ms frame duration approximates PAL
timing, and its decoded pixels were checked against all 160 screenshot crops.

The bitmap verifier independently checks every Bayer decision, exact GPU loop
endpoints, and ball-visible/hidden controls with actual ray-tested depth. The
character verifier reproduces the selected production screens independently:
behind the cube the ball still changes nine characters and 104 pixels inside
its silhouette. Font approximation has 2.42% error inside the active bounds,
with no white pixels outside the object silhouette.

Receipts: [native scanout](native-verification.json), [assembled decoder](host-proof.json),
[bitmap calibration](bitmap-verification.json), [character matching](character-audit.json),
[ball visibility after matching](character-visibility.json), [summary](summary.json).
Rebuild commands and scene sources are linked from the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`e52d1590d481e2ac57829eb7ede9441fdcb63fc1bb3627712a14caee5e8205cb`.
