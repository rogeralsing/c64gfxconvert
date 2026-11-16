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

## Assets

`assets/` contains unchanged copies of `images/borders/batman.mci`,
`batman-sprites.zip` and `batman.json`, plus the PEPTOette_a display palette.
The ZIP supplies 52 native sprite frames per MCI field: two rows of eight above,
two rows of eight below, and ten bands on each side. Bitmap and sprite data are
embedded directly from these exports.

## Native verification

The verifier decodes the original exports independently and compares completed
PAL fields from VICE, including sprite data in RAM, bitmap pixels, border pixels
and field timing. Python verification requires Pillow.

```sh
rtk proxy python3 batman/tools/verify.py
```
