# Four-line FLI scroller

The PAL demo in `demo/wave-four-line-scroll.prg` advances 1.5 wave columns every three PAL fields (16.71 updates/s).

Rebuild it from this directory with Node.js and Kick Assembler. The VICE check also needs `x64sc` and Python with Pillow.

```sh
bash build-four-line-scroll.sh /tmp/wavy-fli-scroll 64 16 ribbon none demo/font-scroll-colors.bin 1.5 3 demo/split-plan.json
python3 verify-four-line-scroll-vice.py /tmp/wavy-fli-scroll --fields 18 --start-offset 932
```

The cadence argument sets the number of PAL fields per update and defaults to four. The optional split plan chooses the number of upper raster lines for each VIC row in each phase. Zero uses a single screen matrix for that row.

The 24-row ribbon uses the same 16 color streams at nine vertical starts. This build advances 1.5 wave columns every two PAL fields (25.06 updates/s).

```sh
bash build-four-line-scroll.sh /tmp/wavy-active-window 64 24 ribbon none demo/font-scroll-colors.bin 1.5 2 '' 16
python3 verify-four-line-scroll-vice.py /tmp/wavy-active-window --fields 260 --start-offset 932
```

One raster pass per phase writes the common Screen RAM destinations and a few bordering groups. The foreground mapper handles the remaining active destinations and clears those that leave the window. Phase B saves staged colors in Screen RAM nibbles unused by the bitmap.

[The Y-sine demo](demo/wave-four-line-y-sine.prg) advances half a wave column every two PAL fields (25.06 updates/s). It moves the active window through all nine starts over 96 A/B pairs. The sine is sampled in quarter rows. The upper bits select the window start and the low two bits set the fine-scroll offset. Both changes take effect together in VBlank.

The color tape starts with `*** COMMODORE 64 ***` in doubled C64 ROM letters and fades from blue to black. The original game graphics are followed by an eight-row palette dither. The closing caption uses Shiru's CC0 Jelly 16×16 font at its original size, in white with corner antialiasing in the three C64 grays. [Jelly 16×16 source](https://opengameart.org/content/jelly-16x16-font)

```sh
bash build-four-line-scroll.sh /tmp/wavy-y-sine 64 24 ribbon none demo/y-sine-colors.bin 0.5 2 '' 16 --y-sine
python3 verify-four-line-scroll-vice.py /tmp/wavy-y-sine --fields 388 --start-offset 932
```

Regenerate the color tape with Node.js and a C64 `chargen` ROM, available in a VICE installation.

```sh
node generate-demo-colors.cjs /path/to/chargen-901225-01.bin demo/jelly-16x16.json demo/y-sine-colors.bin
```
