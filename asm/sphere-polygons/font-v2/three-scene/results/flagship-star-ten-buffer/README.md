# Ten-buffer native spike star

The same PAL-corrected large spike-star movie and locked 256-character font now play through ten full 1024-byte screen buffers. The displayed buffer is copied in full to the next slot, the exact previous-frame delta is applied there, then VIC selects that slot in the lower border. The 96-frame movie loop and 10-slot screen ring advance independently.

Native PAL VICE passed 289 displayed images and 578 actual completed scanouts, covering 28 screen-ring wraps and 2 real movie wraps. All 97 source images, each full 1024-byte copy, all 10 screen slots, script counters, codec cursors, font/movie immutability, and zero writes to the current front were checked. Forced refresh was disabled. Cadence remains two PAL fields per image: **25.0622135 fps**. This is a silent player with no music or interrupt workload.

Memory: **10,240 B** of screen RAM, an increase of **9,216 B**. Ordinary main RAM use is **29,092 B** (18,843 meaningful loaded + 10,240 screens + 9 zero-page). Color RAM is a separate 1,024 four-bit cells. Movie payload remains 15,272 B and the font remains 2,048 B; the movie arena has 5,208 B free. PRG file size includes zero-filled address gaps and is not the live memory total.

The font is unchanged: `1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.

PRG SHA256: `3d4b654cd8e54058a8d8c8e42b3c513ad946fcb8083df38da3d40404105144ac`.

- `preview-pal.gif`: all 96 loop frames from actual native scanouts, 599 × 400 with 59/63 PAL pixel aspect.
- `preview-square.gif`: the same scanouts at 640 × 400 with square pixels.
- `native-contact.png`: 12 actual native frames.
- `native-scanouts.zip`: every one of the 578 screenshots used by the proof.
- `native-verification.json` and `native-monitor.log.gz`: complete native evidence. The JSON reports `displayedImagesVerified`, `actualVisibleFieldsVerified`, `filmWrapsVerified`, `ringWrapsVerified`, and `meanFps`.
- `host-proof.json`: assembled 6502 CPU timing and full-ring behavioral proof. Native VIC timing is reported separately in `timing.json`.
- `memory.json`, `source-hashes.json`, and `sha256.json`: accounting and exact inputs.

The source snapshot under `sources/` keeps the original relative import layout. It contains the generated native program and all binary inputs; no Three.js export or font regeneration is needed to reassemble it. Install Pillow and VICE 3.10, then run the included `sources/asm/sphere-polygons/font-v2/verify-ring-player.py` with Python 3 to repeat the native proof. Its default build path points into the snapshot. To reassemble, enter that snapshot's `build/three-scene-flagship-star-ring/ring-10` directory and run `kickass main.asm -o player.prg -symbolfile -vicesymbols`.

GIF timing uses 40 ms per frame because the format has 10 ms precision. The native mean is about 39.900 ms per frame. Both GIFs were decoded again and all 192 frames compared exactly to the corresponding resampled native screenshots.
