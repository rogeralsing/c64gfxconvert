# Precomputed inter-frame skip/render streams

This study uses the same 256 exact character frames per model as the independent-frame packing study. It also tests a 64-frame full-period sequence by selecting every fourth frame. There is no motion compensation, approximate glyph selection, or native C64 player.

`delta.cjs` exports `codecs`, `encodePairs`, `decodePairs`, `encodePackets`, `decodePackets`, `serialize`, `play`, `syntheticChecks`, and `study`. Each entry in `codecs` supplies `encode(screen, reference)` and `decode(payload, reference)`, with exact 1,000-byte screens. The decoder leaves its reference unchanged.

## The two patch grammars

**`delta-varint-pairs`:** each packet stores an unsigned LEB128 skip count, an unsigned LEB128 literal count, and that many exact character bytes. Skips retain reference values. A packet may not have both counts zero. A final skip still stores its zero literal count. The offline dynamic program groups changed positions and bridges unchanged gaps when the complete byte cost is lower. It can include the final unchanged tail when that saves another packet.

**`delta-packets64`:** each packet has one header byte. Bits 7–6 select skip (`00`), literal (`01`), or repeat (`10`). Bits 5–0 store length minus one, giving lengths 1–64. Literals carry that many bytes; repeats carry one exact glyph byte; skips carry no payload. Type `11` is invalid. An offline dynamic program considers every legal skip, literal, and repeated-glyph packet. Unchanged cells may be included in a literal if merging saves bytes.

Both formats stop at the known 1,000 output cells. There is no uncounted terminator. Decoders reject truncated payloads, output overruns, and trailing bytes. Ordinary glyph 0 or 15 values are written normally, so edges disappearing into blank or solid cells are preserved.

## Keys, physical buffers, and loops

Keyframes use the actual `baseline-rle.cjs` common-character RLE encoder and decoder. They are not stored raw. These keys are not the smaller two-section hybrid from the separate study; a future combined container can substitute that key decoder if it identifies and accounts for the different format.

The serialized `DC64` container has a 12-byte header identifying version, patch codec, key codec, reference lag, frame count, key policy, and loop policy. Every frame has a one-byte key/delta mode and a two-byte payload length before its payload. The fixed font and any optional seek index are separate.

Lag 1 uses the canonical previous decoded frame as reference. Lag 2 uses the actual contents of the alternating destination/back buffer: frame `t−2`. The first one or two frames are mandatory compressed keys. Keys every 16 or 32 frames seed both parity lanes for lag 2, so each interval begins with two consecutive keys. Adaptive mode selects the smaller compressed key or patch, charging the same mode byte in either case.

Two explicit wrap policies are tested. Reload mode reuses the first one or two key records at every loop. Closing-patch mode stores additional complete patch records for the transitions from the final reference frames to the initial frames. Those extra records are included in the archive size. Initial playback still requires the initial keys.

The decoder parses the actual serialized bytes and reconstructs three complete loops. Lag-2 testing maintains two physical buffer states throughout; it does not supply an ideal reference frame from the corpus. Expected frames are used only for the comparison after decoding.

## Results

All 46,080 reconstructed frames, or 46,080,000 character bytes, matched exactly across both models, both sequence lengths, both reference lags, both codecs, all three key policies, and both wrap policies. Synthetic tests cover unchanged frames, blank/full replacement, edge-to-blank and edge-to-full clearing, arbitrary glyphs, gap merging, final-tail decisions, and malformed streams.

For the 256-frame period, the best tested container uses adaptive keys and 64-cell opcode patches. Sizes below include the global header and all per-frame mode/length fields, but exclude the font, decoder, screen buffers, and optional seek index.

| Model | Lag | Total bytes | Keys | Mean circular patch bytes |
| --- | ---: | ---: | ---: | ---: |
| Checker | 1 | 91,481 | 98 | 358.84 |
| Checker | 2 | 95,091 | 230 | 392.45 |
| Football | 1 | 57,115 | 49 | 221.59 |
| Football | 2 | 61,550 | 186 | 249.12 |

Compared with independently framed common-character RLE, the best lag-1 containers save 3.84% for the checker and 8.19% for the football. Lag 2 saves only 0.04% and 1.07%. A larger change between displayed poses reduces useful equality at fixed character positions. On the 64-frame sequence the adaptive encoder chooses almost entirely keys, and its extra mode bytes make it slightly larger than independent RLE.

The separate best independent hybrid remains a strong comparison: it averages about 307.42 and 225.31 bytes per frame including its framing. The delta results here are therefore not a general compression win, especially for lag 2. Closing patches add storage in this tested container because initial keys must still be retained; their possible advantage would be avoiding a heavier key decode at wrap, which is not timed here.

The report's write/skip counts describe patch operations, not measured 6510 cycles. In particular, lag-1 canonical references do not automatically solve synchronization of two C64 screen buffers. Lag 2 models that destination history directly. No native FPS claim is made.

Run from the repository root:

```sh
rtk proxy node asm/sphere-polygons/precomputed/hybrid/delta.cjs
```

The ignored `build/delta-report.json` contains all 96 container results and input hashes. The smallest actual serialized archive for each model, period, and lag is also written as `build/delta-best-*.dc64`.
