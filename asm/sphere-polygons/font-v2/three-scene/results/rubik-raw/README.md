# Verified raw-chunk Rubik film

[Download player.prg](player.prg) or view the actual [PAL VICE capture](c64.gif).
The ten-second film includes the checker sphere entrance, close zoom, morph,
smooth Rubik reveal, upper clockwise turn and left counterclockwise half-turn.

Animation data uses 35,118 bytes. Player, font, frame pointers and movie occupy
38,710 meaningful loaded bytes; the PRG file is 45,359 bytes because it includes
address gaps. Screen RAM, color RAM and nine zero-page bytes are separate.
Playback is 25.0623 fps, with all 250 images verified in both actual PAL fields.

The [native receipt](native-verification.json) records hashes, timing and memory.
The [literal audit](literal-audit.json) independently checks the stream and
assembled 6502 decoder. The [bitmap receipt](bitmap-verification.json) checks
actual GPU export, clipping, morph continuity and Rubik turns. The
[source comparison](source-comparison.png) separates bitmap/font approximation
from native playback correctness. [font.bin](font.bin) is the shared 256-glyph
charset embedded in the PRG.

Build and validation commands are in the [pipeline README](../../README.md).
