# Native CRT corner masks

`tv-corners-profile.json` is the readable source for four black hires sprite
masks. The eight-depth profile is `[6, 4, 3, 2, 1, 1, 0, 0]` physical pixels
outside the rounded opening. Interior pixels remain transparent.

| Frame | TV origin | Global baseline Y | Mask rows |
| --- | --- | ---: | --- |
| Top left | `(0, 0)` | 2 | `baseline + depth` |
| Top right | `(56, 0)` | 0 | `baseline + depth` |
| Bottom left | `(0, 43)` | 62 | `baseline - depth` |
| Bottom right | `(56, 43)` | 63 | `baseline - depth` |

Left corners set local columns `0..width-1`; right corners set
`24-width..23`. These offsets preserve the TV's existing perspective edge steps.
Each frame has 17 opaque black pixels and standard 24×21 hires storage: three
bytes per row, left pixel in bit 7, byte 63 zero. The four frames occupy 256
bytes in `tv-corners.bin`; one bits are black masks and zero bits are transparent.

The native 80×64 `tv-corners-preview.png` includes the existing edge steps for
context. The generator verifies all 2,016 frame bits and writes geometry and
hashes to `tv-corners-import.json`.

```sh
python3 giana/tools/prepare-tv-corners.py
```
