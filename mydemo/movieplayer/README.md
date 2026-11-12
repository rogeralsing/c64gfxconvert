# ECM movie player

Native C64 ECM playback of the lit spike star, cube and checker ball, collected
from the 2026-11-12 `ecm-solid-font` effects player. The original source remains
in the `c64-fine-pixel-dither-20261112` worktree under
`asm/sphere-polygons/font-v2/ecm-solid-font/`.

Each object has 48 animation poses and one blank frame. The sequence includes
normal playback, temporal waves, temporal checkerboards, H/V/HV mirrors and
fixed-position 2× zoom flashes. The final phases combine the star and cube.
WASD moves the crop center used by later flashes; each flash keeps its crop
fixed.

The native assembly and frozen movie bytes are unchanged. The player uses a
512-byte mirror-complete font with SHA-256
`180223a47f20c13a5ca203d00d80cc49db6d3d5504589c02c0ed59d01870043f`.
Background colors are fixed at C64 indices 0, 12, 15 and 1. Foreground colors
vary per cell and frame. Row spans preserve the frozen movies exactly; 2× zoom
uses an approximate glyph-quadrant lookup.

## Build and run

Requirements: Python 3 with NumPy and Pillow, Kick Assembler at
`~/.local/bin/kickass`, and PAL VICE at `/opt/homebrew/bin/x64sc`.

From the repository root:

```sh
rtk proxy ./mydemo/movieplayer/build.sh
rtk proxy ./mydemo/movieplayer/run.sh
rtk proxy ./mydemo/movieplayer/verify.sh
```

Set `PYTHON` to select Python. `run.sh` accepts `VICE` to select VICE.
The verifier accepts `--vice PATH` and its original verification options.
Output is written to ignored `build/`; the runnable program is
`build/player.prg`.

`generated-symmetric/` contains the exact frozen inputs needed by the three
native movies: font, palette, mirror tables, character screens and Color RAM
frames. Its original manifest retains provenance for the broader font study;
this folder includes only the three datasets used by this player. Regenerating
3D scenes or training the font is outside this build.

The verifier uses a local copy of the existing VICE monitor transport and the
repository palette at `../../palettes/colodore.vpl`. It checks actual completed
PAL fields against an independent ECM decoder, including Color RAM commits,
mirrors, history, flash crops and playback timing. Proofs appear under
`build/native-check/`.

The source build's PRG SHA-256 is
`0f5b2b2958ff248971cf2be4ba024bc27b894822cb2c57c4eb507eaf410bd5fd`.
The relocated build must reproduce those program bytes.
