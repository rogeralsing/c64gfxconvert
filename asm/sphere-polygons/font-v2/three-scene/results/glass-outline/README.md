# Black foreground outline

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Outline comparison](outline-control.png)

A black two-pixel contour separates the foreground ball from the glass. It is
an opaque inverted hull with depth writes, growing smoothly with foreground
depth. The 44-pixel shaded ball core is unchanged in the source bitmap. The
outline is disabled behind the cube; all 80 rear-half source and character
images remain identical to the [previous refractive version](../glass-refraction/README.md).

The initial fixed-font match placed 584 white pixels in the measured annulus
over the film. Excluding the actual GPU ring matte from the allowed-white
matching mask reduces that to zero in all 161 stored images. No font or native
player changes were required. In the foreground control, 52 previously white
ring pixels become black. Edge glyph approximation changes 32 of the ball's
1,536 core pixels, including 16 fewer white pixels.

| Measured item | Result |
| --- | ---: |
| PAL playback, including waits | 25.0623 fps |
| Actual images verified in both fields | 481 |
| Exact visible fields | 962 |
| Real loop wraps verified | 2 |
| Delta movie, including closure | 14,058 bytes |
| Additional movie data for the outline | 85 bytes |
| Meaningful loaded code, state and data | 17,477 bytes |
| PRG including address gaps | 24,299 bytes |

Working memory additionally uses a 1,024-byte screen, 1,024-byte color RAM and
nine zero-page bytes. Music and IRQ work are absent from the timing. The
160-frame orbit repeats forever after one blank startup image. The GIF uses
actual verified VICE screenshots cropped to the active picture; decoded pixels
match all 160 crops. Its 40 ms frame duration approximates PAL timing.

Receipts: [native verification](native-verification.json), [assembled decoder](host-proof.json),
[bitmap controls](bitmap-verification.json), [character matching](character-audit.json),
[character outline/optics controls](character-visibility.json), [summary](summary.json).
Build commands are in the [pipeline documentation](../../README.md).

Frozen PRG SHA-256:
`17d82fec8e3df2153ac69b964ec45fb3fdb49d6237b014dfffec00ff662f3706`.
