# ECM plasma: two additive strength viewports

This demo copy contains the latest ECM plasma from
`../../experiments/ecm-viewports/`, captured on 12 November 2026. Two fixed
**80×50 numeric strength maps**, each with its own moving **40×25 viewport**,
produce one common 1,000-byte strength buffer. The accepted metaball font and
ECM projection are retained. The original experiments in `../../experiments/`
remain in place. The local `vice_transport.py` supplies the read-only monitor
and screenshot helpers; `accepted-metaball-font.bin` preserves the verifier's
independent 512-byte font reference from the original metaball experiment.
The shared Colodore palette remains in `../../palettes/`.

The source reads now bend in perpendicular directions. Map A uses a different
horizontal sine offset for each of the 25 output rows. Map B uses a different
vertical sine offset for each of the 40 output columns:

```text
row_x[y]     = clamp(ax + wave_x[(wave_phase_a + 8*y) & 255], 0, 40)
column_y[x]  = clamp(by + wave_y[(wave_phase_b + 6*x) & 255], 0, 25)
strength[x,y] = A[row_x[y]+x, ay+y] + B[bx+x, column_y[x]+y]
screen[x,y]   = strength[x,y]
color[x,y]    = foreground[strength[x,y] >> 6]
```

The signed sine tables have amplitudes of four cells horizontally and three
cells vertically. Their byte phases start at 0 and 64 and advance by +4 and
−6 per update, twice the previous temporal frequency. Spatial frequency and
amplitude are unchanged. The two wave counters repeat together after 128
updates. Each row or column origin is clamped before reading, so all
samples stay within the logical 80×50 maps. The existing camera paths still
cover the full origin ranges; near an edge, the wave flattens where clamped.
The source maps themselves remain unchanged.

Every frame fully overwrites the strength buffer. There is no previous-frame
accumulation, fade or periodic clear in this variant. The native composition
reads both source cells together and writes their sum once; this gives the
same result as copying viewport A into the buffer and then adding viewport B.

Run from `mydemo/plasma/`:

```sh
./build-viewports.sh
./run-viewports.sh
python3 verify-viewports.py
```

The program is `build/ecm-viewports.prg`. Python 3 and Pillow generate the
assets. KickAssembler and PAL VICE use the same installed tools as the other
ECM experiments. The verifier uses the bundled accepted metaball font, so it
does not need another experiment's build output.

Press **SPACE** to advance through these palettes, then return to the first:

| Palette | Five colors | C64 indices |
| --- | --- | --- |
| 1 | Blue, dark gray, purple, medium gray, pink | `6,11,4,12,10` |
| 2 | Blue, dark gray, purple, light blue, green | `6,11,4,14,5` |
| 3 | Brown, dark gray, orange, medium gray, green | `9,11,8,12,5` |
| 4 | Green, medium gray, orange, dark gray, brown | `5,12,8,11,9` |
| 5 | Green, medium gray, orange, purple, red | `5,12,8,4,2` |

Holding SPACE does not repeat: release it before selecting the next palette.
The native program reads SPACE directly from the CIA keyboard matrix. A press
refills the four foreground lookup bands. The background registers change
after screen projection finishes in the vertical border, before the next
visible scan. A palette change can add one PAL frame to that update; normal
animation retains its regular cadence. Numeric maps, wave amplitudes and
movement continue without a reset.

Each source map contains nine soft Gaussian light spots, with a mixture of
small, medium and broad shapes. Their radii and brightness weights vary, and
the two arrangements differ. Each complete map is normalized once over its
entire 80×50 extent. Moving a
viewport does not renormalize its values. Map A holds values from 0 through
127, and map B from 0 through 128. Their sum cannot exceed 255, so additive
brightness never wraps. `build/map-a.json` and `map-b.json` expose all numeric
values. `build/maps.png` shows both complete fields and the initial base
viewports before wave distortion.

Native map A uses a 128-byte row pitch: 80 logical values and 48 padding bytes
per row, occupying 6,400 bytes. Native map B is transposed for vertical reads:
each of its 80 columns holds 50 logical values and 14 padding bytes, occupying
5,120 bytes at a 64-byte column pitch. Both logical binary copies remain
4,000 bytes. The padding byte is `$CD`.

The native composer prepares 25 A row pointers and 40 B column pointers.
It visits two-column strips, alternating direction and addition order between
rows. Each cell reuses the previous Y index and needs only one new `LDY`.
The source-map reads avoid page-cross penalties. The fixed sum bound allows
carry to be cleared once at composition entry: every valid `ADC` leaves carry
clear for the next cell. Each sine table is stored twice consecutively, so unrolled
row/column offsets wrap without updating the phase index between samples.
The complete field exists before the sequential screen projection begins.

Four independent unsigned 16-bit phase accumulators move the cameras. Their
initial values are `0000,4000,8000,C000`; their per-update increments are
`013D,00B5,FF6D,0067`. The high bytes index X and Y lookup tables:

```text
x = round(20 + 20*sin(2*pi*index/256))
y = round(12.5 + 12.5*sin(2*pi*index/256))
```

The first two accumulators move viewport A; the next two move B. The viewport
origins remain inside their source maps. The accumulator state repeats after
65,536 updates; that does not establish the period of every visible image.

Screen codes and the font match the metaball experiment exactly. Screen codes
equal the strength bytes. In the default palette, backgrounds are blue,
dark gray, purple and medium gray (`6,11,4,12`); the corresponding foregrounds
are dark gray, purple, medium gray and pink (`11,4,12,10`). Other palettes use their first four colors
as backgrounds and their last four as foregrounds.
The 64 glyphs have foreground coverage 0–62 pixels, then 64 pixels. Glyph zero
is empty and glyph 32 is the original one-pixel checkerboard. All four
64-value intervals retain their complete color transition.

`build/host-preview.png` is a model image. The native verifier independently
checks sampled viewports, the composed strength buffer, projection, map and
buffer guards, visible VIC pixels and actual presentation timing. Its outputs
are isolated under this experiment's `build/`.

The verifier covers natural updates, viewport corners, signed wave extrema,
wave phase wraps, accumulator boundaries and field overwrites from dirty
initial contents. A legal maximum-strength sum followed by zero checks that
carry cannot leak into the next result. It checks map padding, field, screen
and source guards. The native animation is a finite 256-update excerpt; it
does not show the full accumulator-state period.

The native PAL proof measures **25.06 updates/s** during normal animation:
all 256 measured intervals span two PAL frames. Composition takes
19,536–19,690 machine clocks. Projection and its idle palette check take
19,048–19,050 clocks, with at least 330 clocks before the next top fetch.
All 250 sampled row-fetch windows are safe. Five palette commits finish in
raster lines 45–46, at least 276 clocks before the next top fetch. Sixteen
actual VIC screenshots match 1,024,000 decoded pixels with zero mismatches.

The proof checks 257 natural updates, 24 injected clamp/counter/boundary
cases, and five SPACE press/hold/release sequences through the real emulated
CIA keyboard matrix. Selection follows `0,1,2,3,4,0`; each held key remains on
the same palette for two checked updates. Every palette passes all 256
strength codes and a normal-field VIC capture. Each press takes three PAL
frames; held and released updates take two. Both logical source maps, the
font and camera tables remain identical to the straight
viewport version saved in the original experiment under
`../../experiments/ecm-viewports/build/wave-review/before/`.

The full native proof above used the five-palette version `b4aa1777f1`,
including palette 2's green endpoint and palette 5's red endpoint.
