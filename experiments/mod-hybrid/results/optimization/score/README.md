# Lossless score compression experiments

The sampled instruments are already reused across notes. Much of the remaining
RAM stores the precomputed 50 Hz note/effect timeline. This experiment compresses
that packed timeline without changing any sample waveform, note, volume,
retrigger, playback step or musical tick.

## Methods compared

| Complete song | Existing block codec | Byte-run RLE, before decoder | Initial two-byte phrase dictionary | Selected one-byte phrase dictionary |
| --- | ---: | ---: | ---: | ---: |
| Stardust Memories, 240 s | 21,784 B | 21,696 B | 14,425 B | 13,338 B |
| 4-Mat's Madness, 407.04 s | 38,601 B | 38,422 B | 25,424 B | 22,187 B |
| Hyperbased, 333.84 s | 49,666 B | 49,664 B | 29,351 B | 24,124 B |

The phrase-dictionary columns include encoded blocks, raw dictionary phrases,
pointer/length tables and playlist entries. The initial two-byte experiment
used a coarser phrase-length search; subsequent experiments also considered
short odd-length phrases. These are measured experimental results rather than
claims of globally optimal compression.

RLE saved only 88/179/2 bytes before adding its decoder, so it was not integrated.
For comparison, zlib payloads are 5,928/8,762/9,829 bytes and LZMA payloads are
5,144/7,528/8,176 bytes. Those numbers omit decoder code, workspace, block access
and 6502 CPU cost. They are offline bounds, not playable C64 formats.

## Selected codec

`dictionary8` uses literals `$00..$BF`, escape `$C0` followed by a literal byte,
and `$C1..$FF` to select one of at most 63 raw phrases. Phrases never contain
recursive references. Greedy offline selection accounts for token savings,
dictionary storage and pointer/length metadata. Matching never crosses score
block boundaries. The complete restored packed stream and every normalized
four-voice tick are verified before assembly.

Only foreground `get_byte` decoding changes. The sample IRQ, sample DAC clock,
mixing arithmetic and score scheduler remain unchanged. The decoder adds 59
code bytes and a three-byte initialization, plus three zero-page bytes. For
these builds the extra code fits existing alignment padding, so the measured
program-size saving equals the score-data saving. Dictionary storage is
already included in the table above. No decompression buffer is allocated.

## Resident program results

| Song | Previous PRG | Dictionary8 PRG | Net saving | End address |
| --- | ---: | ---: | ---: | ---: |
| Stardust | 45,616 B | 37,170 B | 8,446 B | `$9931` |
| Madness, original full-song banks | 56,143 B, did not fit | 39,729 B | 16,414 B | `$A330` |
| Hyperbased, gain 3 | 75,971 B, did not fit | 50,429 B | 25,542 B | `$CCFC` |

The resident limit is `$D000`. Hyperbased now fits with 772 bytes remaining.
Its gain-3 setting matches the accepted short rendering and does not affect
the compressed-score size. Every bank file is byte-identical to its full-song
baseline. Gain 3 clips 1,863 of 1,284,825 calculated DAC values over Hyperbased's
full song, approximately 0.145%; that tradeoff predates this lossless codec.

The separate root-prepared contextual Madness arrangement preserves the
accepted short bank choices wherever each entire note's playback range allows
them. Its dictionary8 program is 45,039 bytes, ending at `$B7EE`; it is under
`madness-contextual-dictionary8/`. Its changed bank strategy is separate from
the compression comparison above.

## Actual execution evidence

- `stardust-dictionary8/`: all 12,000 ticks execute with zero underruns.
  Every one of 923,670 actual music DAC bytes matches the independent model.
  Clock-phase range is 186 CPU cycles, below one 256-cycle sample interval.
- `hyperbased-full-gain3/`: all 16,692 ticks execute with zero underruns.
  Every one of 1,284,825 actual music DAC bytes matches the independent model.
  Clock-phase range is 171 cycles; endpoint drift is zero cycles.
  The first 192,427 DAC bytes also match the previously accepted 50-second
  reference. Four EOF-adjacent samples are excluded because a short score
  suppresses commits for the following tick while the full song continues.
- The earlier two-byte decoder also completed the entire original-bank
  Madness, 20,352 ticks and 1,566,544 exact DAC bytes, without underruns.
  Its evidence is under `madness-full/`.
- `regression-final/default-programs.json` verifies unchanged default PRGs:
  Stardust SHA256 `e55dcb2c66492576deae4ae23eed3746ba3081be894cbdc733bbd9dfc7fec8d2`
  and short Madness `bc14b667b4a9e5a7b0a970043a715ba27aeaf7d68d89c108a3141ca16654070e`.
- `regression/codec-boundaries.json` exercises all 256 literal byte values,
  escapes, repeated data and block boundaries for both dictionary variants.

Exact DAC agreement establishes losslessness against the prepared music.
Foreground work can change sub-sample IRQ-entry jitter slightly, so these
checks do not claim bit-identical analog WAVs or a new perceptual evaluation.
These captures use register output only; the parent task owns listening files.

## Build

The existing builder defaults to `legacy`, preserving previous binaries.
Use the selected codec explicitly:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/pcm4_build.py --input experiments/mod-hybrid/results/optimization/score/hyperbased-full-gain3/arrangement.json --out experiments/mod-hybrid/results/optimization/score/hyperbased-full-gain3/c64 --score-codec dictionary8
```

`dictionary` retains the first two-byte wire format for experimental comparison.
The source is `score_dictionary.py`; shared integration is in `pcm4_build.py`
and conditional foreground code in `pcm4_player.asm`.

`method-comparison.json` contains program sizes, source identities, bank-file
identity checks and available runtime/DAC receipts. Individual `c64/build.json`,
`vice/capture.json` and `reference/trace-check.json` files identify each result.
