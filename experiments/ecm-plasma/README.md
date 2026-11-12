# ECM sine plasma

This is a separate adaptation of the ECM experiment in `../ecm-dither/`.
The original additive metaballs, ten-second clears, sources and built artifacts
remain in that directory. This variant generates a fresh sine-plasma phase
field every frame.

Build and run:

```sh
./build-plasma.sh
./run-plasma.sh
python3 verify-plasma.py
```

The output is `build/ecm-plasma.prg`. The generator requires Python 3 and
Pillow. The build uses the same local KickAssembler installation as the
original experiment; the runner uses PAL VICE.

Color RAM is initialized to blue (`6`) once. The four ECM backgrounds are
purple (`4`), pink/light red (`10`), yellow (`7`) and white (`1`). Each 64-code
interval makes a complete blue/accent/blue pulse. The font contains 64 nested
Bayer masks. Glyph `g` has `abs(64 - 2*g)` foreground pixels: glyph zero is
solid blue, glyph 32 exposes the background completely, and glyphs 16 and 48
are 50% checkerboards. A background-bank change occurs at solid foreground
coverage, hiding the change. `build/phase-ramp.png` shows all 256 codes.

The phase field is separable. With a 256-entry signed table
`S[i] = round(39*sin(2*pi*i/256))`, it is:

```text
X[x] = (S[(5*x + hi(A)) & 255] + S[(13*x + hi(B)) & 255] + hi(E)) & 255
Y[y] = (S[(7*y + hi(C)) & 255] + S[(17*y + hi(D)) & 255]) & 255
screen[x,y] = (X[x] + Y[y]) & 255
```

Each addition discards carry beyond its byte. Five unsigned 16-bit phase
accumulators start at `0000, 4000, 8000, C000, 0000` and advance by
`013D, 00B5, FF6D, 0067, 0071` after each presented frame. Fractional phase
steps give the waves different speeds. The accumulator state repeats after
65,536 updates, about 21.8 minutes at 50 updates/s; that is not a proof of the
complete visible period.

The renderer uses the row-difference technique from Linus Åkesson's
[Spindle ECM plasma example](https://linusakesson.net/software/spindle/v3.php).
It computes 40 column values and 25 row values, then patches row differences
into small screen-specific routines. Each cell uses `SBX #difference`, `TXA`
and `STA screen,Y`, totaling nine CPU cycles before VIC stalls. `SBX` is the
NMOS 6510's undocumented immediate AXS instruction; `A=X` is maintained so
its subtraction advances the phase to the next row. This adaptation uses the
existing experiment's standalone setup, a new full-coverage cyclic font and
four sine components.

Two screen buffers at `$0400` and `$0800` share the fixed font at `$2000`.
Initialization prepares phase zero in the hidden buffer. At the bottom border
the runtime presents that completed buffer, advances the phase accumulators,
then computes the next hidden buffer. Static Color RAM lets the screen swap
change both dither and background selection without a separate color copy.

`build/host-preview.png` is a model preview. Native screen bytes, visible VIC
pixels and actual presentation cadence are checked by `verify-plasma.py`.
Its receipt and animation are written only under this variant's `build/`.

The native PAL proof covers 256 presented frames at **50.12448 updates/s**.
Every frame origin is 19,656 machine clocks apart. Preparing the next frame
takes 14,907–14,912 clocks, leaving at least 4,721 clocks before the next swap.
Six actual VIC screenshots, including a pattern covering all 256 screen codes,
match 384,000 decoded pixels with zero mismatches. The proof also checks fixed
Color RAM, active-screen write protection, screen padding and injected phase
carry/borrow/wrap cases. This is a finite native excerpt, not an execution of
the entire 65,536-update accumulator period.
