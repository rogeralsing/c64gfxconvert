# SID1 envelope regression

The full-song implementation changed an already approved SID1 sound. The fault
was present in both the 333.84-second version and its three-minute selection.
Matching frequency and CONTROL values against the new model did not catch it.

At 0.08 seconds, the new player entered a TEST rest and wrote sustain zero.
At 0.12 seconds it restored the pulse waveform and sustain `$20`, without a
new GATE edge. The SID envelope had reached its zero hold and stayed there.
Actual VICE ENV3 replay measured zero during the later tones. The accepted
player keeps sustain `$20` through the rests, with envelope value 34.

The first note had the correct native amplitude. The second was about 30 dB
too quiet. Large envelope/DC transients made whole-file RMS and peak summaries
misleading. This was a player/model regression, not a reason to alter approved
instruments to meet a memory budget.

## Narrow repair

The descriptor's continuous-envelope flag preserves the approved first
twenty-second SID1 recipe. Sustain remains `$20` during TEST rests. Boundary
prewrites repeat the previous control value, introducing no extra GATE or
TEST edge before the normal control slot. Native note-age bookkeeping remains
unchanged.

SID1 frequency, pulse and musical control rows remain unchanged. SID2's data,
all SID3 sample codes, PCM banks and triangle tables remain byte-identical.
Score fields after the first twenty seconds are unchanged. Listening gain,
sample clock and mixing policy are unchanged. Newly recorded WAVs are not
claimed byte-identical to earlier recordings.

## Independent acceptance gate

`sid1_reference.py` checks 122 audible passages against the immutable accepted
WAV identified by SHA256 in `references/hyperbased-stems/sid1-phrases.json`.
It checks gain-normalized steady tone/noise levels, spectral amplitudes and
excessive transient peaks. It only measures audio; it never changes a WAV.

The broken delivered recording fails 99 of 122 passages. The actual repaired
twenty-second VICE capture passes all 122: minimum steady RMS ratio 0.99940,
median 1.00003 and raw peak ratio 1.00307. These ratios account for the files'
documented constant listening gains.

The same gate runs before the complete build writes new listening WAVs or
delivers the normal PRG. A failed gate must stop delivery. Approved sounds are
constraints; optimizations must preserve them, or report the measured limit
and present a separate audible proposal for the user to assess.
