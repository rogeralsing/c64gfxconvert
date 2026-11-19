# Lillen MCI picture

Standalone PAL C64 player for `images/borders/lillen2.mci` and `lillen2.zip`.
The two MCI fields use the original bitmap and sprite bytes. The player opens
all four borders and uses the export’s individual sprite colors and positions.

## Run

```sh
rtk proxy ./lillen/run.sh
```

Build with `rtk proxy ./lillen/build.sh`. The output is
`lillen/build/lillen2/lillen2.prg`. KickAssembler and PAL VICE (`x64sc`) are
required. Set `VICE` to use a different VICE executable.

## Raster schedule

The player uses Batman’s two VIC banks and side-border raster timing. Each
top and bottom border reuses all eight 24 × 21 multicolor sprites on a
second row. X positions and foreground colors change during the band
handoffs. The second MCI field shifts the bitmap and sprites by one hires
pixel. The handoffs are timed for this export’s positions, colors and
transparent rows.

## Verification

```sh
rtk proxy python3 lillen/tools/verify.py
```

The verifier uses Pillow to compare 16 completed PAL fields against an
independent decode of the source bitmap and sprite bytes. It checks the
19,656-cycle field cadence, VIC registers and the two bitmap and sprite banks.
The report and native screenshots are in `lillen/build/lillen2/proof/`.
