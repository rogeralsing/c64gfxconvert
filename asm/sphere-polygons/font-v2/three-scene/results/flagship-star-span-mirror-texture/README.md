# C64 mirror: preserve uniform dither tones

The old lookup objective could replace uniform Bayer dithering with solid geometric glyphs. For example, source 216 contains 52 white pixels but mapped to 61; source 200 contains 36 but mapped to 21 horizontally and 43 vertically. The fix recognizes exact canonical 4×4 Bayer threshold masks expanded to 2×2 physical pixels and keeps those uniform-tone glyphs unchanged under H/V. All other glyphs keep actual geometric reflection with nearest Hamming distance and lowest-code ties.

This is a narrow lookup fix: **seven H entries and seven V entries**, exactly **14 PRG bytes**, changed. The other **249 source-glyph mappings per axis** remain unchanged. Font, renderer, raw movie, frame table, geometry, 512-byte lookup allocation and memory use are identical. The previous accepted archive remains untouched.

Independent regression proves **old 14 tone entries fail / new 0 fail**, including actual culprits 200, 206, 216. All **494 non-template reflection mappings** still pass exhaustive nearest checks. Genuine edges/diagonals 10, 42, 45, 156 keep their previous reflected targets. `independent-texture-regression.json` records the exact old failure reason, density changes, unchanged inputs, and every changed PRG address.

Native PAL VICE passed **289 images and 578 consecutive actual scanouts**, including two source-loop wraps, at **25.0623 fps**. Full-screen pixels match the new lookup policy; the 24-row canvas remains centered at Y 4–195 with four black pixels above/below. Source/font/index/lookups remained immutable; no writes reached the displayed front.

`before-after-pose-006.png` compares actual native screenshots at the same source pose, including enlarged 216 and 200 examples. `preview-pal.gif` is the corrected actual 96-state steady loop, 599 × 400 with 59/63 PAL pixel aspect. Every state was compared to the next native loop; all encoded GIF frames were decoded and checked.

Raw geometric bitmap error is recorded separately: **1.1864% before / 2.3605% after** across the 97-frame corpus. That metric penalizes dither-phase differences and favored the incorrect triangles; it is not the quality score for this tone-preservation fix. Uniform texture bitmap and ink density are now preserved exactly.

- `player.prg`, `main.sym`: accepted native texture-fix player.
- `native-verification.json`, `native-monitor.log.gz`, `native-scanouts.zip`: proof and all 578 screenshots.
- `independent-texture-regression.json`, `independent-lut-proof.json`: independent structural regression and separate geometric-error measurements.
- `lut-regression.json`, `host-proof.json`: builder byte-difference and assembled-CPU receipts.
- `inputs/baseline-player.prg`: frozen old executable, so reproduction never depends on an overwritten working build.
- `inputs/baseline/`: original source/LUT/program bundle for the independent verifier.
- `inputs/raw-film/`: unchanged raw-row builder inputs.
- `sources/`: exact source snapshot and generated assembly inputs.
- `comparison.json`, `timing.json`, `media.json`, `source-hashes.json`, `sha256.json`: provenance and hashes.

From this archive directory, rebuild using the frozen baseline explicitly:

```sh
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-mirror-player.cjs --input inputs/raw-film --reference reference.frames --baseline inputs/baseline-player.prg --output /tmp/c64-mirror-texture-rebuild
```

Then repeat the independent native proof with its baseline bundle:

```sh
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-mirror-player.py --build /tmp/c64-mirror-texture-rebuild --baseline inputs/baseline --output /tmp/c64-mirror-texture-proof
```

Reassembly needs KickAss; CPU proof needs Python/py65; native proof needs Pillow and VICE 3.10. The working verifier defaults to the new texture build and the old accepted archive as baseline.

New PRG SHA256: `62ed4edff6a8e6c12a5b3de61e59a1cf09586e6f55fecc3387e62ba4614587f3`.
Frozen baseline SHA256: `add6e800968b3520b4eb3ff1b098b350ddd1e09dee6af4115615c67fe1a79b5a`.
Font SHA256: `1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.
Raw rows SHA256: `cbd68a6607da7e175f587e58c1d738fe321146d3ca9414d4eba05c46f0c9c719`.
