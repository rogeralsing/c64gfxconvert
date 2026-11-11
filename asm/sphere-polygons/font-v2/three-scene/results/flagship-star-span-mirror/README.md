# Standalone C64 raw-span mirror

The original raw-span movie supplies the top-left 20 × 12 character cells. Top-right reverses columns and applies the nearest horizontal glyph lookup. Bottom-left reverses rows and applies the nearest vertical lookup. Bottom-right applies **V[H[c]]**, vertically mirroring the actual top-right glyph. Both lookup tables contain 256 bytes; the locked font remains unchanged.

The result occupies **24 character rows / 192 pixels**, centered with **four black pixels above and below**. YSCROLL is 7 (`D011` control `$1f`), the first character fetch is raster 55, rows 0–23 occupy active Y 4–195, and screen row 24 is blank. The axes are at **X 160 / Y 100**. Actual native screenshots checked this entire 200-line geometry, including both black margins; no idle-byte overwrite was needed. The [VIC article](https://www.cebix.net/VIC-Article.txt), sections 3.5 and 3.7.3.9, describes the display window and idle mode.

Native PAL VICE passed **289 displayed images and 578 consecutive actual scanouts**, including every original source pose and two real movie wraps. Actual cadence is **two fields per image / 25.0623 fps**. Every front/hidden character cell, full 1024-byte clear, blank row 24, spare byte, lookup result and 200-line bitmap matched. Forced refresh was disabled. Font, source rows, frame table and both H/V tables remained unchanged; no writes reached the displayed front buffer.

Nearest glyphs approximate ideal pixel mirrors. An independent exhaustive Hamming search verified every lookup entry, including the lowest-code tie rule. Across the 97-frame source corpus, the output differs from ideal mirrors by **1.1864% of full-screen pixels** on average; maximum error is **1,336 pixels /2.0875%** in one frame. This is the accepted fixed-font approximation. `native-vs-ideal.png` shows an actual worst-case native screenshot, the ideal bitmap mirror, and its error map.

Ordinary main RAM use is **28,540 B**. The source movie is still **23,076 B** (22,882 raw-row bytes + 194 frame-pointer bytes); font is **2,048 B**; H/V tables add **512 B**; two output buffers use **2,048 B**. Color RAM is a separate 1,024 four-bit cells. Source format, original frame data and font were preserved. The timed normal/wave/checker player is a separate unchanged experiment.

- `player.prg`, `main.sym`: accepted standalone native program and symbols.
- `preview-pal.gif`: actual steady 96-state loop at 599 × 400 with 59/63 PAL pixel aspect. Every state from the second native loop was compared against the third; all decoded GIF frames were checked. GIF timing uses 40 ms precision steps rather than the native 39.900 ms interval.
- `native-contact.png`, `native-mirror-pal.png`, `native-vs-ideal.png`: actual native views and ideal-error comparison.
- `native-verification.json`, `native-monitor.log.gz`, `native-scanouts.zip`: complete proof and all 578 original screenshots.
- `independent-lut-proof.json`: all 256 glyph H/V errors, weighted source usage and per-frame ideal-mirror errors.
- `rows.bin`, `frame-offsets16.bin`, `font.bin`, `h-lut.bin`, `v-lut.bin`, `reference.frames`: exact source assets.
- `memory.json`, `timing.json`, `media.json`, `source-hashes.json`, `sha256.json`: accounting and artifact provenance.
- `sources/`: exact native sources and generated assembly inputs with relative imports preserved. The mirror verifier reuses the independent raw-span parser and generic native monitor helpers read-only.

Reproduce the native proof from the repository root:

```sh
rtk proxy python3 asm/sphere-polygons/font-v2/verify-span-mirror-player.py
```

PRG SHA256: `add6e800968b3520b4eb3ff1b098b350ddd1e09dee6af4115615c67fe1a79b5a`.
Font SHA256: `1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.
Raw rows SHA256: `cbd68a6607da7e175f587e58c1d738fe321146d3ca9414d4eba05c46f0c9c719`.
H lookup SHA256: `f172251c6f9f53fc97fca07c104228e19891e051745336023a5643371513dfaa`.
V lookup SHA256: `f61d85daa6c97d926bd9d2f81425d925460412142112d8e2c14430288646b502`.
