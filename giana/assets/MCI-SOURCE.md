# Giana-man MCI part

`giana-man.mci` is an exact copy of the user-supplied
`images/giana-man.mci`. Its SHA-256 is
`fdcd1028fdbbd71f7c2c86e70d6291d8c7c4828213cb24c8e9a0cc5a3e1a0b55`.
The companion project identity is retained in `mci-import.json`; its embedded
authoring images are not part of the native player.

The uncompressed True Paint file has 19,434 bytes and a `$9C00` file load
address. That address describes the interchange format, not an instruction to
load the file over running demo memory. `tools/prepare-mci.py` preserves both
complete bitmap fields, their separate screen matrices and the shared Color
RAM without palette conversion or pixel changes.

| Component | File offset | Bytes | Runtime destination |
| --- | ---: | ---: | --- |
| Screen A | 2 | 1,000 | `$0400` |
| Background | 1002 | 1 | `$D020/$D021`, color 9 |
| Bitmap A | 1026 | 8,000 | `$2000` |
| Bitmap B | 9218 | 8,000 | `$A000` |
| Screen B | 17410 | 1,000 | `$8400` |
| Shared colors | 18434 | 1,000 | Staged at `$C000`, copied to `$D800` |

The resident control code uses the static PAL phase-switching algorithm from
`mci-viewer/player.asm`, with a music-safe memory layout. `$D018` remains `$18`.
Phase A selects CIA2 direction `$3C` and horizontal scroll `$18`; phase B uses
`$3E` and `$19`. The direction-register values preserve the Spindle loader's
port convention. The viewer never writes `$DD00`.

One complete field is displayed per PAL frame. Phase B moves one hires pixel
right, exposing background at the left edge and clipping its last physical
pixel. The switch occurs at raster 256, below all 200 picture lines. The first
`mciFrameComplete` checkpoint occurs only after a complete phase-A field.
`mciPhase` identifies the field just displayed.

At the handoff, the first disk job loads bitmap B, screen B and shared colors
while the last room remains frozen. The formerly unused enemy sprite slot 6
holds its lower-left corner mask, replacing the old raster multiplex without
changing the frozen picture. The second disk job loads bitmap A and screen A
while the display is blank. No sprites remain enabled in the MCI picture.

The existing native Giana music remains unchanged at `$41C0..$5FDC`. A raster-64
IRQ continues it through both disk jobs and the MCI display, preserving CPU
registers and mapping. `mciMusicFrame` continues the old frame counter and
advances before each call. IRQ/NMI handlers and all live MCI state reside with
the protected viewer code, away from the graphics destinations.

Rebuild the byte-preserving input assets with:

```sh
python3 giana/tools/prepare-mci.py
```

`mci-phase-0.png` and `mci-phase-1.png` are individual source-field previews.
`mci-preview.png` is their static 50/50 blend for review; it does not establish
native interlace cadence. The complete demo's native verifier must inspect
consecutive actual VIC-II fields and the continuing SID calls.
