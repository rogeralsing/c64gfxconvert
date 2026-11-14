# Cube font and illusion borders

Uses the supplied `Skarmavbild-.zip`, preserved byte-for-byte as `source.zip`.
No other graphics or music assets are modified.

The source contains a cube made from 82 used glyphs, mixing hires and
multicolor cells. The builder resolves each cell's actual displayed colors
before normalization. This matters because some glyphs are used in both modes,
and some nonzero multicolor bit pairs resolve to the black background.

## Build and view

```sh
python3 build.py
open build/preview.html
/opt/homebrew/bin/x64sc -pal -autostart build/cube-illusion.prg
```

Requires Python 3 with Pillow and Kick Assembler on `PATH`. The builder also
recognizes the local installation at `/Users/rogerjohansson/.local/bin/kickass`.
Use `python3 build.py --assets-only` to skip assembly.

## Assets

Each asset directory contains `charset.bin` (2048 bytes), `screen.bin` (1000
bytes), `color-ram.bin` (1000 bytes), a manifest, and a PNG preview.

| Directory under `build/` | Glyphs | Contents |
| --- | ---: | --- |
| `clean/` | 77 | One foreground, black background; every ink pixel uses `%01`. |
| `bordered-vertical/` | 95 | Unchanged core plus separate strips above and below its strokes. |
| `bordered-horizontal/` | 103 | Unchanged core plus separate strips left and right of its strokes. |
| `demo/` | 182 | Two cubes with opposite border polarity in one charset. |

`build/cube-fonts.zip` packages all four directories. `build/comparison.png`
shows the source, cleaned font, and bordered copy. `build/verification.json`
records character counts, mask counts, source hash, and conversion checks.
Each directory also has a matching ZIP, such as `build/clean.zip`, with the
manifest and binaries at the archive root, matching the input export format.

Normalization retains every visible source foreground pixel. Converting hires
details to multicolor requires aligning horizontal pairs: a pair becomes ink
if either source pixel was ink. This adds 143 physical pixels to the original
silhouette; it removes none. Colored and gray conversion speckles become the
same foreground as the white strokes. There is no smoothing or redraw of the
cube's existing geometry.

## Border encoding

| Bit pair | Role | C64 source |
| --- | --- | --- |
| `%00` | Background | `$D021`, gray 12 in bordered variants |
| `%01` | Clean cube core | `$D022` |
| `%10` | Leading flank | `$D023` |
| `%11` | Trailing flank | Color RAM low three bits |

Vertical strips are one raster row thick. Horizontal strips are one
multicolor pixel, or two screen pixels, thick. The strips are derived from
offset copies of the whole foreground mask; they are not limited to the
cube's outermost bottom or side. The core takes precedence. A background
pixel claimed by both opposing strips remains background to avoid assigning
contradictory border roles.

The native preview advances one counter through six stages, then wraps
directly to stage zero. It never traverses the stages backward. Each stage
lasts four PAL frames. All three masks cycle between black and white, with
different phases:

| Stage | Trailing border | Core | Leading border |
| --- | --- | --- | --- |
| 0 | White | Black | Black |
| 1 | White | White | Black |
| 2 | Black | White | Black |
| 3 | Black | White | White |
| 4 | Black | Black | White |
| 5 | White | Black | White |

`$D022` supplies the core, `$D023` supplies the leading border, and Color RAM
supplies the trailing border as 8 or 9 (multicolor black or white). The
generated `build/demo/tail-stores.asm` changes only the 153 cells containing
`%11` pixels. Its stores cost 612 CPU cycles and finish before the display
area starts. The screen map and font remain fixed.

Both cubes have the same core color at every instant. The second cube swaps
`%10` and `%11` in the font, rather than using a separate timer.

The browser preview starts paused with the forward contrast wave selected.
It also provides the earlier bouncing ramp and two phase-shifted cycles for
comparison. It does not attempt to put gray palette indices 11, 12, or 15
into the three-bit per-cell foreground.

The earlier native preview used a symmetric grayscale ramp with fixed
borders. Its brightness progression reversed halfway through, causing the
reported bouncing. The forward contrast wave replaces that programmed
reversal. It remains an experiment rather than a frame-by-frame
reconstruction of the original video; perceived motion still requires
visual assessment.

Relevant primary explanation: Shapiro and Charles,
[Motion-illusion building blocks](https://illusionoftheyear.com/files/Shapiro_Charles_Motion_Building_Blocks.pdf).

## Verification

`build/native-verification.json` records the native phase-sequence check and
pixel comparisons. The phase check reads all three color sources over a
complete loop in PAL VICE, rather than checking isolated still frames.
This verifies the forward sequence and rendering, not the subjective
strength of the motion illusion.
