# Megaplot

Megaplot draws a single open chain on the C64. By default, 57 moving joints
connect 56 short segments. Each joint follows two sine waves in X and two
in Y. Their phases and speeds differ, so joints trade places, the chain
crosses itself, and tight corners open again. Both endpoints roam with the
other joints.

Build from the repository root and open the program in PAL VICE.

```sh
python3 mydemo/megaplot/build_megaplot.py
x64sc -pal -autostart mydemo/megaplot/build/megaplot.prg
```

Use `--segments` to choose between 4 and 56 segments. The default extends
the original 48-segment curve by eight segments, with separate sine phase
steps for the added tail.

```sh
python3 mydemo/megaplot/build_megaplot.py --segments 24
```

The 6510 computes each joint once per frame from four shared 256-byte sine tables.
Adjacent segments share the same endpoint. The line drawer stamps whole
characters onto a 160×100 logical grid and combines glyphs where segments
share a cell. It flips the screen and character set together in the PAL border.

Build the NOICE variant to draw the wave over a fixed 40×25 line-art
template. Its restore routines set every cell in the back buffer before
the wave is drawn. At a full patch bank, existing pixels take priority.

```sh
python3 mydemo/megaplot/build_megaplot.py --background noice
x64sc -pal -autostart mydemo/megaplot/build/noice/megaplot.prg
sh mydemo/megaplot/verify.sh --background noice --all-frames
```

The following command rebuilds the demo and checks one complete motion cycle
against the expected joints and pixels in PAL VICE.

```sh
sh mydemo/megaplot/verify.sh --all-frames
```

The default 56-segment build exhausts its 55 spare glyphs on frames 120–124
and 249–252. At that point a stamp overwrites the previous contents of its
cell. The strict pixel check reports those differences and exits with
status 1. Per-frame counts and screenshot names are in `build/verify.json`.
