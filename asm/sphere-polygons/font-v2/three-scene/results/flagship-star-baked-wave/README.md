# Baked history wave, fixed font, native PAL playback

Both PRGs play an ordinary character-delta movie through the existing unchanged
single-screen `literal-front` player. The ten-frame age wave is composed offline.
The locked 256-character font remains byte-identical:
`1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.

| Variant | Delta payload | Payload + pointers + font | Mean / maximum bytes per patch | Native PAL FPS | Ordinary main RAM |
|---|---:|---:|---:|---:|---:|
| Original movie baseline | 15,272 B | 17,514 B | 157.44 / 226 | Existing baseline | Existing baseline |
| Baked 8-pixel character rows | 15,048 B | 17,308 B | 141.96 / 194 | 25.062283 | 19,389 B |
| Baked 2-pixel raster bands | 15,899 B | 18,159 B | 149.99 / 205 | 25.062265 | 20,240 B |

The 8-pixel version saves 224 payload bytes and 206 bytes including pointers.
The 2-pixel version adds 627 payload bytes and 645 bytes including pointers.
Both use one 1,024-byte working screen and the original skip/length/literal codec.
Each also uses the separate shared Color RAM, filled white.

## Wave and startup

For the 8-pixel version, a complete character row selects this age:

```text
age(row, phase) = round(4.5 + 4.5 * sin(2*pi*(row/24 + phase/96)))
```

Age 0 is the latest image; age 9 is nine images older. Phase starts at zero on
the initial blank screen and advances on every committed film image. The
2-pixel version samples the same full-height sine across 100 two-raster bands,
using `band/99` in place of `row/24`.

All initial history slots are blank. Stored composites 0–9 contain the real
startup while that history fills; only composite 0 is entirely blank. The
96-frame repeating suffix is composites 10–105, with latest source poses
10–96, 1–9. Composite 106 exactly reproduces composite 10, including its history
and phase. Thus each baked film stores **106 screens and 106 outgoing patches**,
including the closing delta. The source baseline stores 97 of each. The initial
blank requires no stored seed screen. The pointer-table increase is 18 bytes.

## Approximation and native proof

The 8-pixel composition has zero additional pixel error: complete source
character rows are copied exactly.

For the 2-pixel composition, the existing matcher selects the closest locked
font glyph for each 8 × 8 cell, with minimum Hamming error and lowest-code ties.
No glyph is added or changed. Compared with the ideal two-raster-band mix of
the source glyph bitmaps, this adds **8,464 wrong pixels across 106 screens**:
**79.85 pixels per screen on average, 142 maximum, or 0.1248% of the whole
320 × 200 screen**. This percentage is a whole-screen measure; an object-only
error percentage was not measured. It is additional to the original source
movie's conversion to characters. Delta playback itself reproduces the baked
character screens exactly.

The unchanged native verifier proved each PRG in PAL VICE at normal speed:

- All 106 stored frames and two real loop wraps.
- 298 displayed images, with all 596 PAL field screenshots matching exactly.
- Every playback counter and immutable font/movie check passed.
- Two PAL fields per image, about 25.062 FPS, with no music or IRQ workload.
- Maximum render cost: 5,934 cycles for 8-pixel rows and 5,976 for 2-pixel bands.

The measured suffix duration is about 3.83046 seconds, and startup is about
0.39900 seconds. Host GIFs use 40 ms delays because GIF timing has 10 ms
granularity; their 96-frame loop lasts nominally 3.84 seconds. Their 599 × 400
display approximates PAL pixel aspect 59/63.

Ordinary RAM accounting includes the actual 12-byte BASIC stub, code and its
tables/alignment, font, payload, one screen, and nine zero-page bytes. The
unchanged builder's raw manifests retain an inherited 13-byte BASIC estimate;
`native-summary.json` accounts for the actual 12 bytes. PRG address-gap padding
is reclaimable and excluded. Color RAM remains separate.

## Files

- [8-pixel PRG](wave-rows-8/native/player.prg), [PAL loop preview](wave-rows-8/loop-pal.gif).
- [2-pixel PRG](wave-raster-2/native/player.prg), [PAL loop preview](wave-raster-2/loop-pal.gif).
- [Compression comparison](comparison.json), [native measurements](native-summary.json).
- Each variant contains the frozen font, reference screens, exact payload,
  index, playback script, storage study and native build receipt.
- Native `pal-proof.zip` and `pal-held-proof.zip` retain all screenshots,
  monitor transcripts, final dumps and verification JSON. The verification JSON
  is also available separately alongside each PRG.
- `source/` freezes the small generator, matcher/encoder dependencies, unchanged
  native builder/player and verifier. `inputs/pal-source/` freezes the 97 source
  screens, locked font and original payload. [Source reproduction proof](frozen-reproduction-proof.json)
  confirms 15 generated binary/index/script files are byte-identical.
- `sha256.json` records every archived file except itself.

## Reproduce

Run from the repository root with Node.js, RTK, KickAssembler 5.25, Python/Pillow
and VICE 3.10 installed. `KICKASS` can select another assembler executable; the
verifier accepts `--vice=/absolute/path/to/x64sc`.

```sh
BAKED_ARCHIVE="$PWD/asm/sphere-polygons/font-v2/three-scene/results/flagship-star-baked-wave"
BAKED_SOURCE="$BAKED_ARCHIVE/source/asm/sphere-polygons/font-v2"
BAKED_OUTPUT="$PWD/asm/sphere-polygons/font-v2/build/raster-wave-study/reproduced"

rtk proxy node "$BAKED_SOURCE/study-raster-wave.cjs" \
  --input="$BAKED_ARCHIVE/inputs/pal-source" --output="$BAKED_OUTPUT" --preview

rtk proxy node "$BAKED_SOURCE/build-scene-player.cjs" --codec=literal \
  --input="$BAKED_OUTPUT/wave-rows-8" \
  --script="$BAKED_OUTPUT/wave-rows-8/playback.json" \
  --output="$BAKED_OUTPUT/native/wave-rows-8"
rtk proxy python3 "$BAKED_SOURCE/verify-scene.py" --variant=literal-front \
  --root="$BAKED_OUTPUT/native/wave-rows-8"

rtk proxy node "$BAKED_SOURCE/build-scene-player.cjs" --codec=literal \
  --input="$BAKED_OUTPUT/wave-raster-2" \
  --script="$BAKED_OUTPUT/wave-raster-2/playback.json" \
  --output="$BAKED_OUTPUT/native/wave-raster-2"
rtk proxy python3 "$BAKED_SOURCE/verify-scene.py" --variant=literal-front \
  --root="$BAKED_OUTPUT/native/wave-raster-2"
```
