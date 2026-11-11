# Direct raw-span C64 effects

The same 97 original source frames and locked font, played as three timed modes: normal, a row wave selecting ages 0–9, then a checkerboard mixing source `t` with `t−48` in 4 × 4-character blocks (32 × 32 native pixels). The source image clock continues across mode changes and into the next cycle.

Each stored row is **X, length, raw characters**. The frame table locates a source frame; header scans fill a reusable **500 B row-pointer cache**. Each new output buffer is cleared in full and painted from those independent spans. This is the direct raw-row format, with **23,076 B** of stored film: **22,882 B of rows + 194 B of frame pointers**. The 30-second sequence is generated at runtime from those source frames.

Native PAL VICE passed **1,504 consecutive actual scanouts**, including the first new normal image after the repeat boundary. All three modes occupied exactly **501 PAL fields**, **9.9951 s each**, for **29.9853 s** total. Forced refresh was disabled. Every pixel was checked against an independent composite of the original full-screen references; every cleared output buffer and all **56,350 cached row pointers** matched. Real stale-prefix/tail cases cleared **6,820 nonzero cells outside new images**. All **167 checker images** exercised cases where incorrectly unclipped A and B would each visibly corrupt the result. Native write checkpoints found zero front/font/raw-source/index writes.

| Mode | Actual images in cycle | Mean FPS, including boundary hold |
| --- | ---: | ---: |
| Normal | 249 | 24.91 |
| Wave | 167 | 16.71 |
| Checkerboard | 167 | 16.71 |

The longest displayed-image hold was **5 fields, 0.0998 s**. Ordinary main RAM use is **31,325 B**, including the **2,048 B font**, **two 1,024 B output buffers**, and the pointer pool. Color RAM is a separate 1,024 four-bit cells. File-size padding is not live RAM use. No music or other interrupt workload is included.

- `player.prg`, `main.sym`: accepted native program and symbols.
- `preview-pal.gif`: the full timed sequence from actual scanouts, **599 × 400** with **59/63 PAL pixel aspect**. It **plays once**: the native source clock does not reset to the initial blank image after 30 seconds. GIF time is cumulatively quantized to 10 ms; its length is **29.99 s**.
- `native-contact.png` and `native-mode-0/1/2-pal.png`: actual normal, wave and checker examples.
- `native-verification.json`, `native-monitor.log.gz`, `native-scanouts.zip`: complete native proof and all 1,504 screenshots.
- `rows.bin`, `frame-offsets16.bin`, `font.bin`, `reference.frames`: exact independent source data.
- `host-proof.json`, `preparation-proof.json`, `lookahead-change-proof.json`: separate assembled-CPU behavior/preparation receipts. Actual FPS comes from native fields in `timing.json`.
- `memory.json`, `media.json`, `source-hashes.json`, `sha256.json`: accounting, GIF provenance and hashes.
- `sources/`: exact source snapshot and all generated assembly inputs, with relative imports preserved. Python 3, Pillow and VICE 3.10 reproduce the native proof; KickAss reassembles the program.

Native proof from the repository root:

```sh
rtk proxy python3 asm/sphere-polygons/font-v2/verify-span-effects-player.py
```

PRG SHA256: `67dd338cc66dd4e006a57a7ad8471a787dcac94d2d6cc31add613c271378208b`.
Rows SHA256: `cbd68a6607da7e175f587e58c1d738fe321146d3ca9414d4eba05c46f0c9c719`.
Original frame-table SHA256: `9c9a213dd0baee1092c80bb6dbe5c41eaa3db391016bee1a1c4c5abc64306932`.
Locked font SHA256: `1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.
