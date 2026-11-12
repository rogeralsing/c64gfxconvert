# My demo

Four independent C64 parts collected on 2026-11-12. Each directory contains
its sources, required assets and build scripts. The original projects remain
in place.

| Directory | Part | Source |
| --- | --- | --- |
| `plasma/` | Two additive light maps with moving wave-distorted viewports and five SPACE-selectable palettes | `experiments/ecm-viewports/` in this repository |
| `discoball/` | Live sprite sphere over the disco background, including its intro, outro and original music | `c64demo/experiments/sprite-ball/` in the sibling repository |
| `movieplayer/` | ECM movie player with the lit cube, spike star and checker ball | `asm/sphere-polygons/font-v2/ecm-solid-font/` in the `c64-fine-pixel-dither-20261112` worktree |
| `rimrunner/` | MCI parallax scenery with the mounted rider, three scrolling bands and SPACE pause | `asm/src/parallax.asm` and `asm/tools/` in this repository |

Build from the repository root:

```sh
sh mydemo/plasma/build-viewports.sh
sh mydemo/discoball/build.sh
sh mydemo/movieplayer/build.sh
sh mydemo/rimrunner/build.sh
```

Run each part in PAL VICE:

```sh
sh mydemo/plasma/run-viewports.sh
sh mydemo/discoball/run.sh
sh mydemo/movieplayer/run.sh
sh mydemo/rimrunner/run.sh
```

Python 3, Pillow, NumPy, KickAssembler and VICE are required across these
parts. The scripts retain the original local tool conventions. Pixel
verification uses this repository's `palettes/colodore.vpl`. Generated programs
and verification outputs stay in each part's ignored `build/` directory.

See each directory's README for native verification and runtime details.
