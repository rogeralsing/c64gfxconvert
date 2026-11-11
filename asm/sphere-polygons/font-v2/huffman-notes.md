# Disk streaming and Huffman budget

The measured source is the current 168-glyph, 164-pixel checker sphere with
18 × 9 checks and 64° tilt. At the HTML rotation speed, sampled at 25 FPS, the
491 source frames contain 128,363 bytes of hybrid character deltas. The initial
screen and font are separate. Average demand is 6,536 bytes/s, with a 7,825
bytes/s equivalent for the largest frame.

## Disk

Streaming is possible with a resident IRQ fastloader and prefilled alternating
data buffers. The display can retain its existing single front screen. This
project has not integrated such a loader or verified uninterrupted 25 FPS while
loading.

Commodore specifies 400 bytes/s for the standard 1541 interface. Krill's v194
release notes report approximately 7 kB/s typical and 7.7 kB/s maximum. The
uncompressed stream is therefore close to that loader's nominal throughput;
buffers are needed for frame-size variation and drive delays.

Primary references:

- [Commodore 1540/1541 service manual, specification page 4](https://www.radioedintorni.it/Immagini/RetroComputer/Riparazioni-1541/1540-1541_Service_Manual_Preliminary_314002-01_1985.pdf).
- [Krill v194 author release notes](https://csdb.dk/release/?id=226124&show=notes).
- [Spindle 3.1 official handbook, section 2.12.1](https://www.linusakesson.net/software/spindle/v3manual.pdf): graphics streaming with alternating data buffers. The serial phase uses 18 cycles per bit pair, or 72 per byte. This is not a whole-loader throughput measurement.

## Actual compression

| Representation | Archive bytes | Saving | Average streamed bytes/s at 25 FPS |
| --- | ---: | ---: | ---: |
| Existing hybrid delta | 128,363 | — | 6,536 |
| One byte-Huffman codebook | 125,640 | 2.12% | 6,384 |
| Separate count, glyph and position codebooks | 119,527 | 6.88% | 6,046 |

Archive sizes include code-length headers and two-byte decoded frame lengths.
Stream rates exclude the one-time codebook header. Payload-only savings are
3.09% and 8.25%, respectively. Position bytes have 7.928 bits of entropy per
byte; Huffman has little room to compress them in this representation.
Both host codecs reproduce all 491 frames exactly. The field-aware native
decoder has not been implemented or timed.

## Actual 6510 decoder

The fixed byte decoder uses an 8-bit prefix lookup, a 2-bit secondary lookup
for long codes, and byte-alignment tables. It occupies 897 bytes of code/state
plus 5,120 table bytes. Decoding goes into a hidden RAM buffer; these timings
exclude applying the delta and disk loading.

| Measurement | Minimum | Mean | Maximum |
| --- | ---: | ---: | ---: |
| Huffman CPU instructions, all 491 frames | 21,823 | 28,697 | 35,016 |
| Huffman PAL clocks, 18 cases including extrema | 22,903 | 30,506 | 37,037 |
| Existing delta application CPU instructions, all 491 frames | 3,723 | 4,778 | 5,719 |

PAL verification uses display enabled, 100% speed and warp disabled. Every
decoded byte matches the source. Two PAL fields provide 39,312 clocks, roughly
40 ms. Huffman alone fits that interval in the tested cases; a heavy Huffman
frame plus delta application can exceed it.

The serial-phase estimate for 255.344 framed compressed bytes per image is
18,385 CPU cycles. Adding that estimate to the all-frame CPU means for Huffman
and delta application gives **51,860 cycles per image before VIC stalls and
other loader overhead**. This specific decoder therefore does not support a
25-FPS claim for simultaneous disk streaming and rendering. This is a budget
calculation, not a measured combined player or a lower bound on every possible
Huffman implementation. The uncompressed equivalent is about 23,601 CPU cycles
before stalls and other overhead, making raw-delta streaming the simpler first
integration candidate.

## Reproduce

```sh
rtk proxy node asm/sphere-polygons/font-v2/huffman-study.cjs
rtk proxy node asm/sphere-polygons/font-v2/huffman-study.cjs --field-aware
rtk proxy node asm/sphere-polygons/font-v2/huffman-build.cjs
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 asm/sphere-polygons/font-v2/verify-huffman.py
rtk proxy env PYTHONPATH=/tmp/disco-sid-analysis-py65 python3 asm/sphere-polygons/font-v2/measure-delta-cycles.py
```

Detailed receipts are in `build/huffman-study/current/metadata.json`,
`build/huffman-study/field-aware/metadata.json`,
`build/huffman-study/delta-apply-cycles.json` and
`build/huffman-native/verification.json`. No disk loader was installed or
integrated during this experiment.
