# Melody-loss diagnosis and revised C64 tests

The original Madness and Hyperbased comparisons failed the user's listening
evaluation. Exact C64/model agreement had established that the program ran
as modeled; the model itself lost essential musical content.

## Causes

1. The final four-bit quantizer discarded weak tonal material. With the
   original four-voice gain, isolated Madness tracks 1/2 produced the silence
   DAC code in 99.1%/99.6% of frames. Hyperbased tracks 1/2 produced silence
   in 98.5%/97.0%. Mixing louder channels into these signals caused intermittent
   threshold crossings rather than preserving their continuous waveforms.
2. A sample bank's divisor was selected from the highest pitch in the entire
   source song, even for a short preview. Madness sample 8 used divisor 5
   because of later notes, but the first 50 seconds only need divisor 3.
   The stronger decimation removed its dominant carrier at 742–1484 Hz in the
   test passage, despite the output DAC's 1924 Hz Nyquist limit.

Full-fidelity replay before these conversions agreed much better with the
independent original decoder. No large note-order or effect-replay error was
found in the 30–50 second passages. The signal measurements and offline
ablation files are in `../4mats-madness/diagnosis/signal/`.

## Revised actual C64 recordings

Every comparison plays the same 30–40 second passage in this order:
**10 seconds original, 0.5 seconds silence, 10 seconds old C64,
0.5 seconds silence, 10 seconds revised C64**. All three segments have matched
RMS through separate constant gains. The C64 segments come from actual VICE
captures, verified against the raw device WAVs. There is no EQ, limiter,
resampling or pitch/timing adjustment in these comparisons.

- [Madness comparison](madness-original-old-new.wav).
  The revision uses `--bank-scope score`, preserves short source-loop periods,
  and sets `mixing.output_gain=3` before final quantization.
  [50-second PRG](../players/4mats-madness-v2-50s.prg), 25,783 bytes.
- [Hyperbased comparison](../hyperbased/diagnosis/gain3/hyperbased-original-old-gain3.wav).
  This controlled revision changes only final pre-quantization gain to 3.
  Its notes, bank bytes and all other program bytes are unchanged.
  [50-second PRG](../players/hyperbased-v2-50s.prg), 31,051 bytes.

Both revised programs complete 2,500 ticks in register and audio runs with
zero prefetch underruns. Every one of their 192,431 music DAC bytes matches
the independent arithmetic reference. The higher pre-quantization gain clips
96 output values for the revised Madness score (0.0499%) and 162 values for
Hyperbased (0.0842%) over the first 50 seconds. Increasing gain trades a small
amount of peak clipping for lower quantization loss; it is not a global change
to the original Stardust player.

The revised files are candidates awaiting listening evaluation. Execution and
signal measurements do not establish that the instruments now sound faithful.

The score-scoped banks are valid only for the selected notes. Prepare them
again before extending or changing the sequence. This is still a 50-second
test, not a complete resident conversion of either song.

## Evidence

- `madness-original-old-new.json`: actual source/capture hashes, segment audit,
  clipping count and exact DAC verification.
- `../hyperbased/diagnosis/gain3/hyperbased-original-old-gain3.json`: matching
  Hyperbased comparison receipt.
- `../note-banks-development/score-scope/4mats-madness/{c64,vice,reference}/`:
  assembled program, actual execution/capture and independent DAC reference.
- `../note-banks-development/regression.json`: unchanged default banks,
  note/effect/volume/trigger data and valid fractional steps.
- `../../diagnosis/outputgain-regression/regression.json`: byte-identical
  default Stardust and Madness PRGs and unchanged default DAC streams.

The copies under `../players/` match the hashes of the actual captured PRGs.
