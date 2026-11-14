# Steamboat Willie silent player

The approved six-second monochrome Mickey GIF, collected from the original
movie-player worktree. All 60 character screens, the locked 256-glyph font and
the silent native player are preserved. Playback uses five PAL fields per
frame, approximately 10 fps.

The source player is
`asm/sphere-polygons/font-v2/ecm-solid-font/mickey-gif/mono/` in the
`c64-fine-pixel-dither-20261112` worktree. Its accepted picture and font inputs
are under `darker/generated/`. This collection uses those frozen inputs
directly. The original source and the separate sampled-whistling work remain
unchanged.

This version uses normal hires text with black foreground and white
background. The font occupies 2,048 bytes. It has SHA-256
`7fa677802cbea962c5530f0596bfe1e60dffccd6d3739ddd4cb0ff36aa06d5e6`.
The 60 character screens have SHA-256
`631fa988e77cf2713fc5ac38e8a4b54a5c69f2a4f89b035b27f4ef89344092aa`.

## Setup, build and run

Requirements: Python 3, the packages in `requirements.txt`, Kick Assembler at
`~/.local/bin/kickass`, and PAL VICE at `/opt/homebrew/bin/x64sc`.

From the repository root:

```sh
rtk proxy python3 -m venv mydemo/steamboatwillie/.venv
rtk proxy mydemo/steamboatwillie/.venv/bin/python -m pip install -r mydemo/steamboatwillie/requirements.txt
rtk proxy ./mydemo/steamboatwillie/build.sh
rtk proxy ./mydemo/steamboatwillie/run.sh
rtk proxy ./mydemo/steamboatwillie/verify.sh
```

The scripts use `PYTHON` when supplied, then the local `.venv`, then `python3`.
They do not install packages during a build. `run.sh` accepts `VICE` to select
another emulator executable. The verifier uses the original Homebrew VICE path.

The runnable program is `build/player.prg`. The builder checks every frozen
frame and executes the assembled 6502 routines over two complete loops with
py65. The native verifier checks every frame and the loop boundary at actual
completed PAL fields, including cadence, front-screen protection and the
absence of per-frame Color RAM writes. Proofs are written to
`build/host-proof.json` and `build/native-check/verification.json`.

The relocated build must reproduce the source PRG SHA-256:
`b655156890b12e10a8074c084adaacec5b7ad6114b7ab4f9d15f8b79d695cfc8`.
Its movie stream occupies 28,010 bytes. Assembly and frozen picture bytes are
unchanged; build paths and the local VICE monitor import are relocated.

`generated/manifest.json` retains the original provenance, including historical
absolute paths and the earlier `webPreviewOnly` field. The later native build
and native proof establish playback. The build reads only this folder's frozen
inputs. It does not regenerate GIF frames or train a font. The VICE verifier
uses the repository palette at `../../palettes/colodore.vpl`.

Source GIF: [Mickey Steamboat Willie](https://media.tenor.com/idROkHXXAjAAAAAM/mickey-steamboat-willie.gif).
