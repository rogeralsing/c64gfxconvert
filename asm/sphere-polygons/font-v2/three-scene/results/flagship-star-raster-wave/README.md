# Native raster-wave spike star

This variant draws the unchanged locked-font movie while VIC selects a different historical screen before each selected character row. It uses ten frozen history screens and one hidden work screen. The hidden screen receives a complete 1024-byte copy of newest, then the exact movie delta. Newest, wave phase and the complete row map are published together in the lower border.

The full wave changes at natural **8-pixel character-row boundaries** across all 25 rows. It is not one-pixel FLI. Age is the rounded sinusoid `4.5 + 4.5*sin(2*pi*(row/24 + phase/96))`, ranging from newest to nine images old. One phase advances per published movie image. `limited/` applies the wave to rows 6–17, restoring newest from row 18; it uses 14 row IRQs instead of 25.

Both variants hold each image for **two PAL fields**, about **25.06 fps**. The full proof passed **289 images, 578 actual composite scanouts, 26 ring wraps and 2 real movie wraps**. All **14,450 D018 stores** completed before the following badline, with at least **27 clocks** to spare. The limited proof passed **97 images, 194 actual scanouts and 2,716 row deadlines**, with at least **29 clocks** to spare. Every full 1024-byte copy and outgoing decoder cursor matched. Native write checkpoints detected zero writes into the ten frozen histories or immutable font/movie. All 11 startup screens were blank. There is no music or other interrupt workload in this result.

Expected images were independently composed from the actual reference-film history in each screen slot. They were not compared with the newest frame alone. The sinusoidal age LUT was independently checked mathematically, permitting floating-point ambiguity only at exact half-integer rounding ties. Every completed field was captured, including any held fields; the verifier does not assume a fixed frame rate. Actual row deadlines use non-stopping [VICE execution tracepoints](https://vice-emu.sourceforge.io/vice_12.html), with forced refresh disabled.

The full player uses **33,469 B of ordinary main RAM**; the limited version uses **33,370 B**. Each uses **11,264 B of screen RAM**, a **2,048 B font**, and **15,272 B of movie data**. The movie arena has **5,208 B free**. Color RAM is a separate 1,024 four-bit cells. PRG file size includes zero-filled address gaps and is not live memory use.

- `player.prg`, `main.sym`: verified full-wave native player and symbols.
- `native-verification.json`, `native-monitor.log.gz`, `native-scanouts.zip`: full proof and all 578 actual screenshots.
- `preview-pal.gif`: 96 actual composite frames from the second movie loop, after startup history fills; every frame was also compared exactly against the third native loop. The output is **599 × 400** with **59/63 PAL pixel aspect**.
- `preview-square.gif`: the same frames at 640 × 400 square pixels.
- `native-contact.png`, `native-composite-pal.png`: actual full-wave composite examples.
- `limited/`: complete limited-row player, proof, accounting and actual GIFs. Its 96-frame preview plays once and shows the first loop including blank-history startup; it is a startup demonstration rather than a seamless steady loop.
- `host-proof.json`: independent assembled 6502 behavior and live IRQ register/status preservation; native VIC timing is separate in `timing.json`.
- `memory.json`, `timing.json`, `summary.json`, `source-hashes.json`, `sha256.json`: exact accounting, measured cadence and hashes.
- `sources/`: exact source snapshot and complete generated assembly inputs, preserving relative imports. Reassembly needs KickAss; native verification needs Python 3, Pillow and VICE 3.10.

The locked font remains `1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`. Movie SHA256 remains `6f0bf83e2c289d5113fbe8377b77a92971c159e8428f77d00b65321c64fbc821`.

Full PRG SHA256: `8f8d516b9ce17108dffaaaefe6efe6ecb81ce07195cc38868db38889c01157c7`.
Limited PRG SHA256: `16f28ea11cf61bd7b0e0833c737c531b08ee0ead5f026f3b2a393be765f6ade3`.

Native commands from the repository root:

```sh
rtk proxy python3 asm/sphere-polygons/font-v2/verify-raster-wave-player.py
rtk proxy python3 asm/sphere-polygons/font-v2/verify-raster-wave-player.py --build asm/sphere-polygons/font-v2/build/three-scene-flagship-star-raster-wave-limited/raster-wave --repetitions 1
```

GIF delay precision is 10 ms, so both previews use 40 ms per image rather than the native mean of about 39.900 ms. All 384 decoded GIF frames were compared exactly with their resampled actual native screenshots.
