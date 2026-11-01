# Original C64 IFLI viewer

Run `./run-ifli.sh` to display GoDot's `butterfly.fp2` with its original English PAL slideshow player in VICE x64sc. Press Space to advance. Run `./run-ifli.sh iflishow.d64` for GoDot's original seven-image slideshow disk.

`butterfly.d64` contains `ifli player` and `^^butterfly`. The two leading PETSCII up-arrow characters are how the player recognizes FunPaint II images. The PAL player streams and decompresses FP2 files itself; it does not require a REU. The script selects PAL, normal speed, fast disk traps, and a dummy sound driver because these images are silent. It disables the monitor’s synthetic display refresh, which otherwise produces misleading captures of this raster-driven display after inspection commands.

## Export from the converter

Select IFLI graphics mode, load an image, and adjust its controls. Click **Save IFLI** above the preview to download both fitted frames and their color allocations as a FunPaint II `.fp2` file. Save works from every preview tab and uses the current settings. The filename begins with `^^` and fits the C64's 16-character filename limit.

To view an export, run these commands from this `ifli-viewer` folder, replacing the image path and filename:

```sh
c1541 -format "ifli export,64" d64 exported.d64 \
  -write diashow_eng.prg "ifli player" \
  -write "/path/to/^^image.fp2" "^^image"
./run-ifli.sh exported.d64
```

## Renderer findings

Standard IFLI retains two 160×200 logical frames on a 40×25 character grid. The leftmost 24 hires pixels (12 multicolor pixels, or three character columns) have the FLI bug. The useful arbitrary-color area is 148×200 logical pixels, or 296×200 on the hires grid. Keep the 160-wide storage and reserve or crop the affected strip in a hardware preview.

The current renderer's tile allocation matches the original player: one Color RAM color per 4×8 logical tile shared across both frames, plus two Screen RAM colors per 4×1 logical row in each frame. Its global background color is a valid restricted choice; the player can change the shared background by scanline. The phases alternate with a one-hires-pixel horizontal shift.

The converter reserves the requested two character columns on the left in FLI, IFLI, FLI Virtual, and AFLI. It fits the source into the remaining 304×200 display area, equivalent to 152×200 multicolor pixels, and keeps the reserved strip transparent through image effects. Fitted multicolor data uses the selected background there; AFLI uses black. Bitmap and hires modes retain their full width.

FP2 export preserves the full 160×200 backing and includes the reserved strip. The configured two-column margin is 16 hires pixels; the standard player's documented 24-pixel affected region extends one character column further. Browser animation still follows the browser's refresh cadence rather than a PAL frame cadence.

## Sources

- [GoDot IFLI gallery](https://www.godot64.de/iflis/index.htm)
- [Viewer instructions](https://www.godot64.de/iflis/instruct.txt)
- [GoDot format documentation](https://www.godot64.de/german/l_ifli.htm)
- [Original player source](https://github.com/godot64/GoDot/blob/master/extras/iflidiashow.a)
- [VIC-II reference, section 3.14.3](https://www.cebix.net/VIC-Article.txt)

Downloaded viewer, images, instructions, and original slideshow disk remain third-party material. `butterfly-vice.png` is a single captured emulator frame; a static capture does not reproduce temporal IFLI color blending.
