# ECM dither font

A standalone C64 extended color mode experiment. The font starts with an empty
8×8 tile and adds one pixel per glyph until it reaches a 50% checkerboard.
An 8×8 Bayer threshold matrix determines the order. Glyphs 0–32 are active;
slots 33–63 are empty and available for other shapes or dither phases.

## Build and run

Requires Python 3 with Pillow, KickAssembler and VICE. Uses the same local
toolchain as the repository's assembly experiments.

```sh
./build.sh
./run.sh
python3 verify.py
```

`build/ecm-dither.prg` is the runnable C64 program. `build/font.bin` contains
all 64 ECM slots (512 bytes); `build/font-33.bin` contains only the 33 active
glyphs (264 bytes). Both files contain raw character bytes without a load address.
`build/font-sheet.png` shows every active glyph and all 65 coverage levels.
`build/screen.png` is a digital preview of the native screen, using Colodore RGB
colors; it does not simulate the PAL signal or physical pixel aspect ratio.

The C64 screen shows four bands, from top to bottom:

1. Every glyph from empty to 50%, white foreground on black.
2. The same glyphs in reverse order, black foreground on white: 50–100% white.
3. A complete black-to-white ramp sampled across 40 columns.
4. The same ramp from blue to light blue, using the other two background registers.

The program is static. Reset the emulator to return to BASIC. `verify.py`
starts and closes its own emulator and saves an actual VIC screenshot.

## How many characters?

An 8×8 tile contains 64 pixels. Densities from 0/64 through 32/64 need **33
glyphs**, including both endpoints. Each step changes coverage by 1/64, or
1.5625 percentage points. Reusing those glyphs with swapped colors reaches
64/64, giving **65 distinct coverage levels**. These are spatial coverage
levels, not equally spaced perceived brightness levels.

A repeated 4×4 matrix would need only nine glyphs from 0–50%, yielding 17
coverage levels after swapping colors. The 33-glyph version keeps finer steps
and leaves 31 ECM character slots free.

Swapping foreground and background complements the pixel pattern. It does not
reverse the Bayer threshold order: the dither phase changes around the 50%
transition. The two possible 50% checkerboards have equal coverage and opposite
phase. For an animated fade, evaluate that pattern change before choosing a
font layout; extra glyph slots can hold alternate patterns.

Using all 64 slots can remove that phase change: keep the 33 existing masks
and add the 31 masks containing the highest-ranked 1–31 pixels. Above 50%,
swap colors and select the appropriate high-ranked mask. The resulting full
0–100% ramp is nested, changing exactly one pixel per step. This prototype
uses the smaller 33-glyph design to expose the tradeoff.

## ECM encoding

ECM uses 40×25 cells with 8×8 hires pixels. The low six screen-code bits select
one of 64 glyphs; the high two bits select `$D021`, `$D022`, `$D023` or `$D024`.
Color RAM selects one of all 16 foreground colors per cell. See the
[Commodore Programmer's Reference Guide](https://www.devili.iki.fi/Computers/Commodore/C64/Programmers_Reference/Chapter_3/page_120.html).

To swap a color pair, both colors must be present in the four global background
registers. The demo sets them to black, white, blue and light blue. For black to
white coverage `n` from 0 to 64:

```text
n <= 32: glyph = n;      background = black; foreground = white
n >  32: glyph = 64 - n; background = white; foreground = black
screen_code = glyph | (background_slot << 6)
```

Changing only a screen code's high bits changes its background. A full color
swap also changes its Color RAM nibble. ECM has no automatic inverse-glyph bit.
The demo enables ECM and disables bitmap and multicolor modes.

## Memory

The screen lives at `$0400`, the font at `$2000`, and Color RAM at `$D800`.
Although the active font contains only 264 bytes, VIC-II still selects its
character base on a 2 KB boundary. Unused bytes after the first 512 bytes need
not be allocated to ECM characters.

## Additive balls with an offscreen brightness buffer

```sh
./build-metaballs.sh
./run-metaballs.sh
python3 verify-metaballs.py
```

`build/metaballs/metaballs.prg` animates three additive balls with retained
brightness trails. Startup clears a **40×25-byte offscreen buffer**.
Every ten seconds, a hardware-timer deadline clears that buffer again.
Other updates decrease every value by one, clamped at zero, then add the balls.
Every cell holds a numerical brightness value from 0 to 255. Character and
color selection happens after accumulation:

```text
brightness[cell] = 0 if reset_due else max(0, brightness[cell] - 1)
brightness[cell] = min(255, brightness[cell] + ball_lookup[dy][dx])
screen[cell]     = brightness[cell]
color_ram[cell]  = color_lookup[brightness[cell]]
```

The 25×25 ball lookup contains only integers from 0 to 4. Its radius is 12
cells (96 pixels), 50% larger than the original radius of eight cells. For
`u = max(0, 1 - (dx² + dy²)/144)`, its slower brightness buildup is
`round(4 * (0.4*u² + 0.6*u⁴))`. The blend delays middle brightness values
while its small integer weights let repeated passes build the trails. It contains no
character codes or colors. `build/metaballs/kernel.json` and `kernel.txt`
expose the numbers; `kernel.bin` contains the same 625 bytes for the C64.

The left half of kernel row nine is
`0 0 0 0 1 1 1 2 2 3 3 3 3`. The full kernel contributes 452 brightness
units, about 38% more than the preceding peak-three kernel's 327 units.
Quantization leaves 241 nonzero cells in the same 25×25
lookup. The geometry and movement tables are unchanged.

All additions saturate to 255, rather than wrapping to zero. Three coincident
centers add twelve to the existing field in one update. The previous field survives into
the next frame, producing trails. Repeated additions replenish old light and
can still reach white. Between timed resets, fading remains an exact decrement
of one per update.

Two chained CIA2 timers generate a deadline every 9,852,480 PAL machine clocks,
or ten seconds. Timer A divides the clock by 30,789; timer B counts 320 of
those ticks. Coherent counter reads detect timer B's reload without interrupts.
The runtime consumes the deadline at the next update, clears
the field, then adds the balls at their current positions. Movement counters
continue through the clear. Timer deadlines remain periodic rather than
restarting after each clear, so polling delays do not accumulate.
Ball origins are signed cell coordinates. The accumulator intersects each
25×25 kernel with the 40×25 field before adding it, so balls can cross any
edge or corner. Fully offscreen kernels contribute nothing. Clipping preserves
the source kernel's original row and column; it does not move a ball back inside.

Each axis adds two sine components with independent periods. A 128-step
primary phase advances by three entries per update. Separate secondary phases
advance by one entry and wrap at 251 for X and 239 for Y. Each ball combines
its primary path with a slower per-ball drift. The primary paths use different
signs and harmonics while preserving the initial three-ball overlap.

The three motion counters repeat after `lcm(128, 251, 239) = 7,678,592`
updates, approximately 5.55 days at 16 updates/s. This is a long deterministic
trajectory cycle. The retained brightness buffer adds history, so that counter
period does not by itself establish the period of the complete visible state.

Each ball's **center reaches the screen edges**: x = 0…39 and y = 0…24 in
character-cell coordinates. Horizontal primary centers use
`round(19.5 + 16.5*sin(phase))`; vertical primary centers use
`12 + round(11*sin(phase))`, with the per-ball harmonics and signs described
in `manifest.json`. Secondary amplitudes are three horizontally and one
vertically. These component ranges keep the final center inside the screen
while reaching both ends of each axis, without a movement clamp.

Top-left kernel origins span x = −12…27 and y = −12…12. When the center is
on an edge, roughly half the ball extends beyond the screen and is clipped.

`positions.bin` contains six 128-byte primary-component planes. Each of
`drift-x.bin` and `drift-y.bin` contains three 256-byte signed planes, with
unused entries after the logical period padded to zero. The native program
adds the signed components before clipping. Each ball's center is 12 cells
below and to the right of its top-left origin.

Projection stores the completed brightness values directly as ECM screen codes
and uses a 256-entry lookup for foreground colors. An identity screen-code
lookup is also exported for inspection. Each group of 64 input values traverses
a complete color interval, without scaling the buffer down:

| Buffer values | Complete color interval |
| --- | --- |
| 0–63 | Blue to purple |
| 64–127 | Purple to pink |
| 128–191 | Pink to yellow |
| 192–255 | Yellow to white |

Each color interval passes through the entire 0–100% dither coverage ramp.
Values 63, 127, 191 and 255 are the solid destination colors; values 64, 128
and 192 repeat the shared endpoint before continuing. The value 256 cannot
be stored in a byte, so 255 is already completely white. These palette
intervals are not equal steps of perceived brightness.

ECM has only four global backgrounds. They hold blue (6), purple (4),
pink/light red (10) and yellow (7). Each interval selects its next color as the
per-cell foreground: purple (4), pink (10), yellow (7) or white (1). White
needs no global background slot. Zero brightness and the border are blue.
The projection is therefore:

```text
segment         = brightness >> 6
glyph           = brightness & 63
screen_code     = brightness
foreground      = [4, 10, 7, 1][segment]
```

The numeric buffer remains separate from the visible screen and is completed
before projection. Its byte values happen to encode the required ECM screen
codes directly with this ramp layout.

Presentation uses one fully unrolled pass for all 1,000 cells. It loads each
brightness byte, stores the screen code, looks up the foreground color and
writes Color RAM directly. There is no intermediate color buffer or separate
color-copy pass. The renderer starts at raster line 55 and writes behind the
VIC's current row fetches, completing before the next frame's visible fetch.

### Compiled additive rows

The build compiles the fixed numerical kernel into row blitters, omitting zero
weights and sharing identical mirrored rows. Each nonzero operation loads the
existing field byte and uses a constant-weight address into a 260-byte
saturation table. The table contains `min(255, i)` for indices 0 through 259,
covering every possible byte value plus a kernel weight up to four.

Clipping selects the first and last generated operations for each visible row.
The dispatcher temporarily inserts a return at the end entry, calls the start
entry, then restores the original opcode. Source-column offsets are included
in the field pointer so partially visible rows retain their correct shape.
The generated rows, entry tables and saturation table are rebuilt from the kernel.
Rebuild to change kernel weights; the native rows contain compiled constants.

The startup and timed clear use the same unrolled pass. Per-frame fading uses a compact partially
unrolled pass and a 256-byte lookup containing `max(0, i-1)`. It updates
exactly 1,000 logical cells and preserves the 24 padding bytes. The fade loop
uses aligned field blocks and lookup data to avoid indexed-read page crosses.

This animation uses all 64 font slots. Glyphs 0–32 preserve the original font;
glyphs 33–62 continue the nested Bayer masks, and glyph 63 is completely filled.
Coverage is 0/64 through 62/64, then 64/64. The last step adds two pixels:
64 glyphs cannot represent all 65 possible coverage counts. This keeps the
empty tile, exact 50% checkerboard and solid endpoint, with no phase inversion.
This full-coverage font supports all five colors with four backgrounds, without
swapping foreground and background at 50%.
The animation's font and assets live under `build/metaballs/`; the original
33-glyph demonstration remains available separately.

`build/metaballs/preview.gif` is a finite 256-frame host-model excerpt at
nominal three-PAL-frame cadence, encoded as 60 ms per update. Its ten-second
reset uses that nominal clock; the native verifier checks actual timer timing.
Its GIF loop is not the motion period.
`additive-study.png` compares one, two and three coincident balls.
`color-ramp.png` displays all four complete 64-value color intervals.
The native verifier exercises the real C64 program, checks its numerical
buffer and projection, and records native timing separately.

### Native PAL verification

`build/metaballs/native.gif` reconstructs a verified finite native excerpt
of 384 updates through the actual fixed font, at its measured cadence. The verifier
also compares five actual VIC screenshots, totaling 320,000 pixels, with zero
mismatches. `build/metaballs/verification.json` contains the receipt.

The excerpt matches an independent stateful numerical model: clear at a due
timer deadline, otherwise fade the previous field, then add the current balls.
The timer check covers two natural ten-second deadlines, including the cleared
field before ball addition and uninterrupted motion across each reset. The
observed clears begin at 10.033 and 20.048 seconds from timer arming, at the
first poll after each deadline. The entire excerpt averages 16.68 updates/s.
For each ball, the
verifier records actual native centers and requires all four screen edges
to be reached during the excerpt. Additional injected
counter states exercise each component's wrap, simultaneous wrap and states
from far beyond the excerpt. The trajectory-counter period is proved from the
counter periods; the verifier does not execute 7,678,592 native updates.
An injected field exercises all 256 native fade inputs, including `0→0`,
`1→0` and `255→254`, with lookup and padding guards. Another injected field
exercises all 256 byte values through native
projection. A second case starts every cell at 254 before adding the balls;
overflowing sums reach 255 without wrapping. Additional native cases exercise
each edge and corner, fully offscreen balls and signed-coordinate extremes.
They compare all 1,000 field cells and check guards before the field, in its
trailing padding and across the following RAM before projection.

For a matching scene, the verifier also compares the optimized program's
field, screen and color hashes against a saved pre-optimization proof for
matching checkpoints. It first checks scene
compatibility using the independent numerical oracle. A deliberately changed
motion path, palette or history rule uses the independent native proof and reports that
the saved scene comparison does not apply.

The verifier measures all 25 row-write windows in five representative frames.
All 125 intervals follow the old row's badline fetch and precede its next
fetch. Every render finishes before the next visible top fetch, with at least
337 machine clocks of margin in this run.

The optimization comparison below uses the preserved wide-path scene with
22×14-cell motion amplitudes and the original `85*u²` kernel. Both versions
use exactly that same input.
Measurements cover all 64 steady motion phases in normal PAL VICE, with
warp disabled. Cycle counts include VIC bus stalls:

| Work per frame | Original loop | Optimized |
| --- | ---: | ---: |
| Clear brightness field | 6,800 | 4,356 |
| Add three clipped balls | 26,729 | 19,737 |
| Project screen and update Color RAM | 45,291 | 19,042 |
| All work excluding raster wait | 78,840 | 43,153 |
| Average displayed frames/s | 11.22 | 18.87 |

The fused renderer alone reaches 15.80 frames/s. Compiled additive rows raise
this to **18.87 frames/s**, **68.2% faster** than the original loop. For that
wide-path scene, cadence is two PAL frames in 24 phases, three in 38 phases
and four in two phases: approximately **12.53–25.07 frames/s**. The verifier's `measured_fps`
field reports median cadence (about 16.71 frames/s); the stage profiler's
`average_fps` reports the full-loop rate.

The current motion takes the ball centers to the screen edges. The peak-four
version with timed clears measures **16.71 frames/s on average** in its
64-update stage profile before the first reset, at three PAL frames per update.
The preceding peak-three version without timed clears also averaged 16.71
frames/s; the peak-85 trail prototype averaged 14.92 frames/s across its
256-update excerpt. The current stage profile measures about 14,700 machine
clocks for the timer check and fading, 18,743 for addition, and 19,042 for
rendering, including VIC stalls.
The previous unrolled clear averaged about 4,356 clocks. This is a finite-window measurement, not
an average over the full multi-day state cycle. The scene is verified against
the current numerical oracle rather than the archived wide-path hashes.

For that archived benchmark, the tradeoff is code space: the renderer uses
13,001 bytes, the unrolled clear 3,003 bytes, and compiled rows plus tables
3,300 bytes. The single-load PRG grows from 16,385 to 42,213 bytes, including
load gaps. The slower brightness curve previously compiled to 3,200 bytes of
rows and tables at peak 85. Reducing the kernel peak to three compiles to
1,766 bytes of rows and tables, yielding a 40,679-byte PRG for that version.
The current peak-four kernel compiles to 1,907 bytes, with a 40,820-byte PRG.

With the old peak of 85, exact decrement-by-one retention accumulated rapidly: native mean field
brightness was 229.14 at update 16, 249.75 at update 32 and 252.69 at update 64,
out of 255. By update 64 the canvas was nearly white. The preceding peak-three kernel
had native mean brightness 3.94 at update 16, 6.12 at update 32 and 6.33 at
update 64. The 256-update excerpt ends at mean 7.58, with no saturated cells.

The longer host simulation in `build/metaballs/intensity-study.json` compares
peaks one through ten over 16,384 updates. Peak three adds about 773 brightness
units per update across the screen. At update 16,384 its mean is 28.62, with
9.2% of cells in the yellow-to-white interval. Colors build slowly at recurring
crossings while most of the screen remains in the blue-to-purple interval.
Without timed clears, peak four instead deposits about 1,063 units per update
and produces a broad bright central region. The current ten-second resets
discard that long-term buildup. These are finite simulation results, not a proof over
the complete trajectory cycle.

`build/metaballs/trails-review/before/` preserves the verified version without
retained trails. `trails-review/peak85-input/` preserves the excessive-input
trail prototype. `trails-review/peak3-before-timed-clear/` preserves the
preceding weaker kernel without periodic clears.

To repeat stage profiling after a build:

```sh
python3 profile-metaballs.py
```

The profiler measures machine clocks in an owned emulator and closes it after
a 64-update window. For the compound-sine motion this is a finite excerpt,
not a complete period. `build/metaballs/optimization/baseline/` preserves
the original PRG, symbols and measurements. `optimization/direct-render/`
and `optimization/compiled-add/` preserve the measured candidates; the latter
contains `comparison.json` and `profile/profile.json` for the selected version.

The fixed screen is at `$0400`, the font at `$2000`, and the numeric field at
`$4000`. The field reserves 1,024 bytes for alignment; 1,000 cells are used.
The unrolled renderer starts at `$5000`, the unrolled clear at `$9000`, and
compiled additive rows and tables at `$a000`. The compact fade pass is at
`$8300` and its 256-byte lookup at `$3f00`.
Geometry, addition and projection execute on the C64. The program does not
play pre-rendered screen frames.
