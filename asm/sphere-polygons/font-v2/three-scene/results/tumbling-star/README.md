# Full three-axis opaque star

[C64 program](player.prg) · [Actual C64 preview](c64.gif) · [Bitmap versus characters](bitmap-vs-c64.png)

The long-arm star makes full compound rotations around all three axes:
360 degrees around X, 720 around Y and 360 around Z. The 240-frame loop lasts
9.6 seconds at the nominal 25 fps. Position and angular velocity match at the
loop boundary; natural overlaps show the front and rear of the object.

The source retains the closed six-pyramid geometry: 14 vertices, 36 edges and
24 outward-facing triangles. Tips are 40 units from the center and cube
half-extent is 8.5, giving 31.5-unit arms beyond each base. Eighteen fixed
facets are white and six are black. Paint rotates with the geometry.

The initial blank frame plays once. Native playback then repeats frames
1–240 indefinitely through the existing character-delta player. The shared
256-glyph font and decoder are unchanged. No music or IRQ workload is included.

The GIF contains actual verified VICE screenshots cropped to the active
picture. Its decoded pixels are checked against all 240 screenshots; 40 ms
per frame approximates the native PAL timing. The local scene source and its
imported geometry are saved together here. Earlier scene results are retained.

Receipts: [native verification](native-verification.json), [opaque bitmap proof](bitmap-verification.json),
[character matching](character-audit.json), [assembled decoder](host-proof.json), [summary](summary.json).
Build commands are in the [pipeline documentation](../../README.md).
