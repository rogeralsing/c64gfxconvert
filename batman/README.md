# Batman MCI picture

A separate PAL C64 picture player, copied from the MCI border experiment and
adapted to the supplied Batman artwork. The central bitmap and all four borders
alternate their original two MCI fields, with the second field one hires pixel
to the right. Top and bottom each use two normal-height sprite rows.

## Build and run

KickAssembler, Python 3 and PAL VICE (`x64sc`) are required.

```sh
rtk proxy ./batman/build.sh
rtk proxy ./batman/run.sh
```

The program is written to `batman/build/batman.prg`. This is a silent picture
player for an unexpanded 64 KiB C64. The launcher runs at 100% speed with warp
disabled. Build symbols, receipts and emulator captures stay in `build/`.
The default build uses the optimized sprite export. To rebuild the original
manual-color version, pass `--sprites assets/batman-sprites.zip` to `build.sh`.
The converter's normal-width, optimized top/bottom placements require a dedicated
raster schedule. This player accepts the fixed X-expanded layout.

## Assets

`assets/` contains unchanged copies of `images/borders/batman.mci`,
`batman-sprites.zip` and `batman.json`, plus the PEPTOette_a display palette.
The ZIP supplies 52 native sprite frames per MCI field: two rows of eight above,
two rows of eight below, and ten bands on each side. Bitmap and sprite data are
embedded directly from these exports.

`batman-optimized.json` enables **Automatic sprite colors** in the converter.
The bundled `batman-optimized-sprites.zip` preserves the native-verified export
made before the converter's unified full-resolution mapping. It keeps one global cyan/light-blue
multicolor pair and selects a foreground for each of the 52 logical sprites.
The plan is identical between MCI fields and reduced the virtual-color Oklab
error by 19.9% under that earlier mapping. Reopening the JSON in the current
converter recomputes colors and can produce a different sprite ZIP. The central MCI bitmap stays
unchanged. The player writes individual foreground registers at each sprite
handoff; the shared multicolors stay fixed during the picture.

## Native verification

The verifier decodes the original exports independently and compares completed
PAL fields from VICE, including sprite data in RAM, bitmap pixels, border pixels
and field timing. Python verification requires Pillow.

```sh
rtk proxy python3 batman/tools/verify.py
```

The verifier defaults to the optimized sprite ZIP. Pass
`--border-sprites batman/assets/batman-sprites.zip` when checking a manual-color
build. The optimized export, manual control and a dense 16-color test pattern
have separate native proof artifacts under `build/`.
