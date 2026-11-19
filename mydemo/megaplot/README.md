# Megaplot

Megaplot draws a single open chain on the C64. By default, 25 moving joints
connect 24 straight segments. Each joint follows two sine waves in X and two
in Y. Their phases and speeds differ, so joints trade places, the chain
crosses itself, and tight corners open again. Both endpoints roam with the
other joints.

Build from the repository root and open the program in PAL VICE.

```sh
python3 mydemo/megaplot/build_megaplot.py
x64sc -pal -autostart mydemo/megaplot/build/megaplot.prg
```

Use `--segments` to choose between 4 and 48 segments. Fewer segments expose
the straight edges. More segments give the same motion a smoother outline.

```sh
python3 mydemo/megaplot/build_megaplot.py --segments 36
```

The 6510 computes each joint once per frame from four shared 256-byte sine tables.
Adjacent segments share the same endpoint. The line drawer stamps whole
characters onto a 160×100 logical grid and combines glyphs where segments
share a cell. It flips the screen and character set together in the PAL border.

The following command rebuilds the demo and checks one complete motion cycle
against the expected joints and pixels in PAL VICE.

```sh
sh mydemo/megaplot/verify.sh --all-frames
```

The default 24-segment build exhausts its 55 spare glyphs on frames 121, 123,
124, and 251. At that point a stamp overwrites the previous contents of its
cell. Over one 256-frame cycle, VICE showed 44 missing logical pixels,
including two interior joints. The strict pixel check reports those differences
and exits with status 1. Per-frame counts and screenshot names are in
`build/verify.json`.
