# C64 one-axis span mirrors

This standalone player shows **V only for 501 PAL fields**, then **H only for 501 fields**, and repeats while the original source-image clock continues. V means top/bottom reflection; H means left/right reflection. Each mode changes one axis.

**V mode:** the original top 12 rows across all 40 columns stay unchanged. The bottom 12 rows use `V[c]` at row `23−y`. The 24-row canvas uses YSCROLL 7, four black pixels above/below, and a blank screen row 24.

**H mode:** the original left 20 columns across **all 25 source rows** stay unchanged. The right half uses `H[c]` at column `39−x`. YSCROLL 3 preserves the full 200-pixel image with no vertical shift, including source row 24. The mode, screen and YSCROLL change together in the lower border.

Native PAL VICE passed **1,003 consecutive actual fields**, including the first repeated V image. Each mode lasted exactly **501 fields / 9.9951 seconds**, for **19.9902 seconds** total. Both modes displayed **249 images / 24.91 fps including boundary holds**, approximately **25.06 fps** otherwise. The longest hold was **5 fields / 0.0998 seconds**. Every screenshot, full 1,024-byte hidden clear, source half and timer matched the independent reference. Forced refresh was disabled.

The proof checked 120,000 original V top-half cells and 124,500 original H left-half cells. It exercised 11,890 V top-right and 13,036 H bottom-left cells that differ from simultaneous quadrant mirroring. It also preserved 28 nonzero H row-24 cells. No writes reached the displayed front, font, raw source, frame index or lookups.

The accepted corrected H/V lookup tables are reused byte-for-byte. Exact canonical Bayer tone masks retain their texture; other glyphs keep actual-reflection nearest mappings. The existing independent policy oracle checked all 494 non-template mappings. Font and lookup contents were preserved.

Ordinary main RAM is **28,792 B**, including the unchanged **23,076 B raw film**, **2,048 B font**, **512 B lookup tables** and **two 1,024 B output screens**. Color RAM is a separate 1,024 four-bit cells. The timed sequence is rendered directly from independent X/length/raw source rows.

- `player.prg`, `main.sym`: accepted standalone program and symbols.
- `preview-pal.gif`: actual 20-second sequence, **599 × 400**, with 59/63 PAL pixel aspect. It plays once because native source orientation continues into the next cycle. All 498 encoded GIF frames were decoded and checked.
- `native-mode-contact.png`: actual V/H views at matching source poses.
- `native-v-only-pal.png`, `native-h-only-pal.png`: actual matching-pose examples.
- `native-verification.json`, `native-monitor.log.gz`, `native-scanouts.zip`: complete proof and all 1,003 original screenshots.
- `independent-lookup-policy.json`, `host-proof.json`: lookup policy and assembled-CPU receipts.
- `memory.json`, `timing.json`, `media.json`, `source-hashes.json`, `sha256.json`: accounting and provenance.
- `sources/`: exact source snapshot, generated native inputs, shared proof helpers and the five accepted source/lookup assets needed by them.
- `inputs/raw-film/`: unchanged raw-film builder inputs.

From this archive directory, rebuild and repeat the proof:

```sh
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-axis-player.cjs --input inputs/raw-film --reference reference.frames --output /tmp/c64-span-axis-rebuild
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-axis-player.py --build /tmp/c64-span-axis-rebuild --output /tmp/c64-span-axis-proof
```

KickAss, Python/py65, Pillow and VICE 3.10 are needed for assembly, CPU and native verification. GIF time is cumulatively rounded to 10 ms; the preview lasts 19.99 seconds.

PRG SHA256: `d411301750e67dd407d0946bca8a039115b4fe6c1539ff9b26b1a4a145be23db`.
Font SHA256: `1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.
Raw rows SHA256: `cbd68a6607da7e175f587e58c1d738fe321146d3ca9414d4eba05c46f0c9c719`.
