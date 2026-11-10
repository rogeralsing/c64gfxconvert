# Madness and Hyperbased signal-loss diagnosis

These are offline arithmetic measurements and ablations. They are not new
C64 recordings, and no listening judgment is claimed. Shared player and
preparation source files were not changed.

## Two demonstrated mechanisms

1. **The final four-bit mix suppresses quiet instruments.** In seconds 30–50
   of Madness, channel 1's fine-precision RMS is 0.01875 and channel 2's is
   0.02345. Quantizing either channel with its unchanged four-voice allocation
   produces the center/silent DAC code in 99.1% and 99.6% of samples.
   Sample 8, which occupies 17.92 seconds of channel 1, is completely silent
   when quantized alone. Sample 3, occupying 19.28 seconds of channel 2, is
   silent in 99.8% of its isolated DAC frames. Other voices move the combined
   value across thresholds, so the quiet contribution becomes intermittent.
   This explains why preserving every sequencer tick and DAC byte did not
   preserve the audible melody.

2. **Madness sample 8 was filtered for a later, faster note.** Its divisor 5
   came from the minimum period 202 in the complete 407-second song. The
   complete first 50 seconds only reach period 339, so divisor 3 is sufficient
   there. The strongest source carrier is approximately 0.14185 cycles per
   original sample. It plays near 742–1484 Hz in the comparison passage,
   within the 1924 Hz output Nyquist limit. A divisor-5 low-pass removes that
   carrier before playback; divisor 3 retains it. About 66.3% of the complete
   source sample's Hann-windowed energy lies above 0.1 cycles/source sample.
   This is an instrument preparation error for this preview's pitch range.

Changing only sample 8 from divisor 5 to 3 adds 705 bank bytes. Every first-50s
fractional step still fits 0–255. Channel 1's RMS-matched STFT magnitude error
against its independent original solo falls from 0.967 to 0.794 before bank
quantization, and from 0.963 to 0.798 at the fine mixer input. These metrics
still include resampling, phase and output bandwidth differences.

The candidate arrangement is
`4mats-madness-sample8/candidate-arrangement.json`. It retains baseline output
gain; a gain change must be selected separately. Its banks are offline
candidate data, not an already verified C64 build.

## Global output gain ablation

The test changes only final quantization:

`DAC = clamp(round(8 + (fine_sum - 128) * gain / 16), 0, 15)`

All banks, channel volumes, note states and sample cursors otherwise stay
unchanged. SNR compares the reconstructed, gain-corrected digital output with
the fine mixer input over seconds 30–50; it is not SNR against the original MOD.
Clipping counts rounded values outside 0–15 before clamping.

| Song | Gain | Quantization SNR | Clipped frames, first 50s | Center code, 30–50s |
| --- | ---: | ---: | ---: | ---: |
| Madness | 1 | 6.88 dB | 0% | 69.2% |
| Madness | 1.5 | 10.52 dB | 0% | 50.6% |
| Madness | 2 | 12.32 dB | 0.001% | 47.0% |
| Madness | 3 | 16.21 dB | 0.045% | 26.6% |
| Madness | 4 | 17.45 dB | 0.616% | 26.6% |
| Hyperbased | 1 | 6.44 dB | 0% | 73.5% |
| Hyperbased | 1.5 | 9.66 dB | 0% | 57.3% |
| Hyperbased | 2 | 11.71 dB | 0.001% | 51.6% |
| Hyperbased | 3 | 15.37 dB | 0.084% | 33.0% |
| Hyperbased | 4 | 16.52 dB | 0.667% | 33.0% |

Gain 3 is a bounded candidate: about 9 dB less digital quantization error,
with rare clipping. It does not make the four-bit output lossless. At gain 3,
isolated Madness channels 1/2 still have 76.2%/63.4% silent frames; Hyperbased
channels 1/2 have 72.0%/84.2%. The main concern therefore remains the actual
musical phrase, not a passing numeric threshold.

For Hyperbased, using divisors derived only from its first 50 seconds adds
2510 bank bytes and makes a small further change. Channel 2's fine-input STFT
error falls only from 0.505 to 0.497. Its primary demonstrated loss is final
mix quantization, rather than the severe missing carrier found in Madness
sample 8. See `hyperbased-preview/changes.json` and candidate arrangement.

## Secondary pitch issue

Madness sample 5's 32-byte original loop becomes 5 bytes at divisor 7. The
resulting sustain pitch is approximately 155 cents flat. That instrument
occupies 1.36 seconds of channel 1 in the comparison passage, so it cannot
explain the complete failure by itself. Long loops for other samples have
less than 1.3 cents of loop-length rounding error.

Fractional step quantization alone is also too small to explain the chaos.
Madness channels 1/2 have median absolute step errors of 2.72/1.69 cents;
Hyperbased channels 1/2 have 1.69/3.89 cents. Details are in
`pitch-step-errors.json`.

## Evidence files

`analyze.py` generates the diagnosis. Each variant folder contains:

- `analysis.json`: per-instrument, per-channel and gain-ablation measurements.
- `layers.npz`: floating banks, four-bit banks, fine mixer inputs and final DAC.
- `offline-track-*.wav`: isolated arithmetic layers, not actual C64 captures.
- `offline-fullmix-outputgain-*.wav`: constant-level listening candidates.

The baseline DAC reconstruction is asserted byte-for-byte equal to the
independent existing `expected_dac()` result. Original comparisons use the
independent libopenmpt solos from each song's `diagnosis/original-solos/`.
