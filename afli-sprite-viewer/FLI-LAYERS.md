# FLI Virtual + Sprites layers, version 1

`encodeFliSpriteLayers(result, palette, backgroundColorIndex)` exports a stored ZIP with format `c64-fli-sprite-layers`, version `1`. Load `afli-sprite-export.js` first for the shared ZIP and sprite-mask helpers. The existing AFLI export remains byte-for-byte unchanged.

| File | Bytes | Layout |
| --- | ---: | --- |
| `bitmap.bin` | 8,000 | Multicolor bitmap: four logical pixels per byte, most significant pair first. |
| `screen.bin` | 8,192 | Eight 1,024-byte screen banks; 1,000 used bytes and 24 zero padding bytes per bank. |
| `color-ram.bin` | 1,000 | One C64 color index per tile, in row-major order. |
| `sprites.bin` | 4,800 | The 192 × 200 hires sprite raster mask, 24 bytes per row, most significant bit first. |
| `manifest.json` | Variable | UTF-8 dimensions, file names, global background and sprite colors, crop, and packing rules. |

These are raw RAM planes without load-address prefixes; the archive makes no standard `.fli` file-format claim. `backgroundColor` and `spriteColor` each contain the palette index, name, and RGB triplet. The background applies to the entire underlay.

The underlay is **160 × 200 logical pixels**, displayed with 2:1 wide pixels on a 320 × 200 canvas. Each 4 × 8 logical tile permits the global background, one tile color, and two independently chosen colors per scanline. For logical `(x, y)`:

```text
tile = floor(y / 8) * 40 + floor(x / 4)
row  = y % 8
bitmap byte = bitmap.bin[tile * 8 + row]
screen byte = screen.bin[row * 1024 + tile]

00 = manifest.backgroundColor.index
01 = screen byte's high nibble
10 = screen byte's low nibble
11 = color-ram.bin[tile]
```

When allocation colors coincide, the first matching code in that order is used. Every underlay pixel must be an opaque palette color allowed by its fitted tile and row.

The physical valid area is canvas x112–319: **208 pixels, or 104 wide logical columns**, by 200 rows. The sprites cover canvas x112–303, a **192-pixel hires overlay**. They can cover either half of a wide underlay pixel independently. A mask coordinate uses `column = canvasX - 112`, byte `y * 24 + floor(column / 8)`, and bit `0x80 >> (column % 8)`. Set bits draw the selected sprite color; clear bits reveal FLI. The mask is raster data, not prepacked 64-byte hardware sprite frames.

The [shared native builder](prg/build-layers.py) now accepts this ZIP alongside AFLI layer ZIPs. It packs the arbitrary mask into hardware sprite patterns, loads ColorRAM, selects multicolor bitmap mode and the global background, and emits a standalone PAL PRG without an REU. The two VIC banks switch at raster 135, with overlapping stored rows around the source y87 boundary. It retains the 21-row sprite reuse and black cleanup below the 200-row image.

Build and verify the included converter fixture in fresh directories:

```sh
rtk proxy python3 afli-sprite-viewer/prg/build-layers.py \
  --output afli-sprite-viewer/prg/fli-new-build \
  afli-sprite-viewer/validation/fli-sprites-native-fixture.zip

rtk proxy python3 afli-sprite-viewer/capture-layers.py \
  --output afli-sprite-viewer/runs/fli-new-capture \
  --symbols afli-sprite-viewer/prg/fli-new-build/fli-sprites-native-fixture/boot-rendered.sym \
  afli-sprite-viewer/prg/fli-new-build/fli-sprites-native-fixture/fli-sprites-native-fixture.prg \
  afli-sprite-viewer/validation/fli-sprites-native-fixture.zip

rtk proxy python3 afli-sprite-viewer/validation/verify-layers.py \
  afli-sprite-viewer/runs/fli-new-capture \
  afli-sprite-viewer/validation/fli-sprites-native-fixture.zip \
  --split-y 87
```

The [verified fixture PRG](prg/fli-sprites-native-20261101/fli-sprites-native-fixture/fli-sprites-native-fixture.prg) uses cyan background index 3 and 4,714 white hires sprite pixels. Its [actual PAL capture report](runs/fli-sprites-native-20261101/layer-verification.json) passes three comparisons of all 41,600 active pixels and 15,360 black pixels below the image, plus visible RAM and ColorRAM checks. Frame counters advance by 26, with identical captures. These are bounded three-capture observations. Source and program hashes are retained in the [build receipt](prg/fli-sprites-native-20261101/fli-sprites-native-fixture/build-receipt.json); the pinned GoDot engine retains its [MIT license](GoDot-LICENSE.txt).
