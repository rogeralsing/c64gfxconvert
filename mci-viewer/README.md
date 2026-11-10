# Standalone PAL MCI example

`build-prg.py` embeds an uncompressed True Paint `.mci` export in a standalone C64
program. Its BASIC startup displays the image continuously on a PAL C64 or PAL
VICE. KickAssembler is required only when building.

```sh
rtk proxy python3 mci-viewer/build-prg.py image.mci --output /path/to/image.prg
rtk proxy x64sc -pal -autostart /path/to/image.prg
```

The program alternates standard multicolor bitmaps every PAL video frame. Phase
B uses one hires pixel of horizontal scroll. The leftmost column in that phase
shows the background; the extra rightmost half-pixel is clipped. All 320 display
columns and 200 rows are available, without a FLI left-column mask.

| Data | Address |
| --- | --- |
| BASIC startup and player | `$0801` |
| Shared colors staged for initialization | `$2000` |
| Phase A screen / bitmap | `$4000` / `$6000` |
| Phase B screen / bitmap | `$8000` / `$a000` |
| Shared color RAM | `$d800` |

`$d018` remains `$08`. The player changes VIC bank and `$d016` below the picture
at raster line 256. CIA and VIC interrupts are disabled. The `frameComplete`
label provides a breakpoint after a complete picture; `phase` identifies that
picture as 0 or 1.

Each build also writes KickAssembler `.sym`, VICE `.vs`, and a JSON build receipt.
Existing artifacts are preserved unless `--force` is supplied. The source MCI
file remains unchanged.

## Smooth sine wave on a stock C64

The sine player samples every picture row from a continuous vertical warp. Its
240 geometry frames include a moving sine, a smooth amplitude envelope, fixed
edges, and mean compensation. Both MCI phases use identical geometry. The
picture updates once per PAL phase pair, approximately 25 times per second.

Prepare the source strips and geometry, then build a separate program:

```sh
rtk proxy python3 mci-viewer/sine-data.py image.mci --output-dir /path/to/sine-data
rtk proxy python3 mci-viewer/sine-geometry.py --output /path/to/sine-geometry
rtk proxy python3 mci-viewer/build-sine.py --data-dir /path/to/sine-data --geometry-dir /path/to/sine-geometry --output /path/to/image-sine.prg
```

The source preparation fits palettes across 24 source rows for each 16-row
display band. This permits a four-pixel displacement while preserving valid
bitmap, screen and Color RAM combinations. The wider palette fit can change
some colors compared with the original static MCI conversion; preparation also
writes comparison images for review.

The program needs no REU. Its payload loads below `$d000`; startup relocates the
source data, generates copy routines, and creates the initial bitmaps. During
display, it copies only rows whose sampled source row changed. One bitmap is
updated while the other MCI phase is displayed. RAM under I/O is visible only
during those copy bursts, and I/O is restored before raster polling and phase
changes.

| Data | Address |
| --- | --- |
| Current/next row maps | `$0200` / `$0300` |
| Phase A screen / bitmap | `$0400` / `$2000` |
| Phase B screen / bitmap | `$4400` / `$6000` |
| Generated copy routines | `$0800` / `$4800` |
| Phase A/B source strips | `$8000` / `$b0c0` |
| Geometry offsets and runs | `$e180` |
| Runtime | `$f500` |

At `frameComplete`, `phase`, `displayFrame` and `mapPage` identify the completed
picture. `mapPage` selects the 200-byte row map at `$0200` or `$0300`. A map entry
is the row within the current 24-row strip, rather than an absolute source Y.
Startup overwrites the staged payload, so restart this program by reloading it.

## Earlier coarse rubber-wave experiment

Build a separate animated example with `--wave`:

```sh
rtk proxy python3 mci-viewer/build-prg.py image.mci --wave --output /path/to/image-wave.prg
```

Extra early badlines repeat the first scanline of each eight-line bitmap cell.
The remaining seven scanlines run normally, retaining that cell's bitmap and
screen/Color RAM pairing. A sine table moves the stretched bands. The amplitude
rises from zero to four extra lines per cell over 256 MCI phase pairs, then falls
and repeats. The two MCI phases share the same deformation; motion changes once
per pair. The normal 200-line viewport crops the stretched image at the bottom.
The final cells adjust their repetition counts to keep all badlines at or before
raster 247 and cover the picture through line 250 without a blank bottom band.

`repeatCounts` at `$2500` contains the current pair's 25 repetition counts.
`cellRasters` at `$2520` identifies each cell's first badline. `phase`, `motion`,
`amplitude` and `pairTick` are exported symbols, and `frameComplete` retains its
meaning as the completed-picture checkpoint.
