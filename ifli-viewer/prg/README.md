# Standalone PAL IFLI programs

`build-prgs.py` combines the converter's uncompressed FunPaint II exports with the original GoDot English PAL viewer and a small startup routine. Each output is a complete C64 PRG with its image embedded.

The program starts through its BASIC `SYS 8192` line. It stages the image below `$d000`, relocates its second phase with RAM visible, and enables the original raster display. It displays the image continuously until the C64 is reset.

Build from the repository root:

```sh
rtk proxy python3 ifli-viewer/prg/build-prgs.py --output /path/to/new-output "/path/to/^^image.fp2"
```

Existing PRG filenames are preserved. KickAssembler and the pinned original `../diashow_eng.prg` are required to build. Running a generated PRG only requires a PAL C64 or PAL emulator.

The GoDot PAL viewer's FLI bug affects the first three character columns. Generated PRGs clear those bitmap columns in both phases, masking the leftmost 24 hires pixels. The converter already reserves 16 pixels, so this hides another 8 pixels of image content and leaves a 296 × 200 visible image area. Source FP2 files remain unchanged. Build receipts record each original source hash, the resulting PRG hash and the display mask.

Display code comes from [GoDot's English PAL IFLI viewer](https://www.godot64.de/iflis/diashow_eng.prg). [Original player source and credits](https://github.com/godot64/GoDot/blob/master/extras/iflidiashow.a). The original raster display and startup routine remain unchanged.
