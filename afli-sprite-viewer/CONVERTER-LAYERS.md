# Converter layer export, version 1

`encodeAfliSpriteLayers(result, palette)` returns a `Uint8Array` containing a standard, uncompressed ZIP. Load `afli-export.js` before `afli-sprite-export.js`. The encoder accepts the fitted converter result and leaves its images, row colors, sprite mask, and palette unchanged.

The archive contains three files:

| File | Content |
| --- | --- |
| `image.afl` | The real 320 × 200 AFLI underlay, encoded by the existing AFLI exporter. It has load address `$4000`, eight screen banks, a hires bitmap, and the recognized 16,385-byte AFLI-editor length. Each eight-pixel scanline segment has its fitted two C64 colors. |
| `sprites.bin` | A 4,800-byte monochrome **raster mask** for source x112–303 and y0–199. It stores 192 × 200 bits, 24 bytes per row. |
| `manifest.json` | UTF-8 metadata with format `c64-afli-sprite-layers`, version `1`, selected sprite color, dimensions, crop, and packing rules. |

The full source coordinate system is 320 × 200 square pixels. The declared valid AFLI area is x112–319, 208 × 200. The sprite field is x112–303, 192 × 200, corresponding to eight adjacent 24-pixel sprites. The underlay retains all 320 columns; the manifest records the narrower display area.

For a source coordinate `(x, y)` inside the sprite field, let `column = x - 112`. Its mask bit is:

```text
byte offset = y * 24 + floor(column / 8)
bit mask    = 0x80 >> (column % 8)
```

Rows run from top to bottom; columns run from left to right. A set bit draws `manifest.spriteColor`; a clear bit reveals the AFLI underlay. The selected color includes its C64 index, palette name, and RGB triplet. Sprite pixels outside x112–303 are rejected, and mask values must be exactly 0 or 1.

The result fields used by the encoder are `pixels`, `afli`, `spriteMask`, and `spriteColorIndex`. Both images must be 320 × 200; the mask must contain 64,000 entries in the full image coordinate system. The existing AFLI encoder validates the palette, opaque underlay pixels, and fitted row colors. `spritePixels` is a derived preview and is not stored in the archive.

The ZIP itself contains layers rather than an embedded program. **`sprites.bin` is a raster mask, not a sequence of 64-byte hardware sprite frames.** The new [native layer builder](prg/build-layers.py) now performs that conversion: it packs arbitrary mask rows into VIC sprite patterns and pointers, combines them with the AFLI underlay, and emits a standalone PAL PRG. The [README](README.md#native-player-for-converter-layers) gives the build, capture, and verification commands, including `--split-y 87` for its mid-image bank switch. No REU is required.

The original checker prototype uses 24 × 21 hardware sprites, starts its first visible sprite row at raster 32, starts the AFLI image at raster 48, and reuses sprites every 21 rows. The manifest’s `referencePlayer.programIncluded=false` and `referencePlayer.acceptsThisMask=false` refer to that original checker prototype and the ZIP’s contents; they do not describe the new native builder’s capabilities. The version 1 file format and straightforward 200-row raster packing remain unchanged.

ZIP entries use stored method 0, CRC32, UTF-8 flags, and a deterministic 1980-01-01 timestamp. Local headers, the central directory, and the end record follow the [PKWARE ZIP specification](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT). No compression library or build step is required.
