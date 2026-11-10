# Initial two-voice snare experiment

This run uses real acoustic `assets/snare.wav`, the same target preparation and
AudioLoss as the main matrix, and the initial renderer snapshot retained in
`source-snapshot/`. The SID renderer source SHA-256 is
`be570bfaa042a8d44cb9ad2ffc03ead02fedca7b071233b9c608065ccb278d71`.

The program combines filtered noise on SID voice 1 with an unfiltered triangle
body on voice 2. It searches 15 macro parameters and three filter families.
Every secondary global-register write is discarded; only voice 1 controls the
shared filter and master volume. Event traces were checked for the voice-1-only
filter mask and at least eight cycles between writes. No voice 3 or PCM sample
data is used. These traces were not assembled into, or verified as, a C64 PRG.

Both CMA-ES and uniform random search used seed 1 and exactly 600 candidate
renders. Their first 150 program parameters match exactly. Each winner then
received five extra score-only rerenders, separate from the search budget.

| Method | Best single search score | Five fresh scores: mean ± population SD | Search time | Patch writes |
| --- | ---: | ---: | ---: | ---: |
| CMA-ES | 1.465684 | 1.576650 ± 0.049719 | 127.56 s | 59 |
| Random | 1.448381 | 1.589022 ± 0.084148 | 63.83 s | 165 |

The apparent single-render improvement does not survive repeated evaluation.
The two-voice program consumes an additional physical voice and different
parameter space. This one-seed result does not establish either improved
imitation or optimizer superiority over the main one-voice experiment.

## Variability diagnostic

`stability_check.py` imports the frozen old sources, independently rerenders
each winner five times, saves every raw and normalized waveform, and records
pairwise differences in `stability.json`. This later batch gave:

| Method | Mean raw signal RMS | Median pairwise raw PCM difference RMS | Median raw correlation | Median raw envelope difference RMS | Median normalized envelope relative difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| CMA-ES | about 0.0297 | 0.02639 | 0.473 | 0.002225 | 9.0% |
| Random | about 0.02927 | 0.01894 | 0.707 | 0.002662 | 14.3% |

The later five-render spectral means were 1.631083 ± 0.061812 and
1.587233 ± 0.102371 respectively. The 150 identical prefix programs differed
in spectral score by a median 0.047054 and maximum 0.347421 between searches.
These measurements show material waveform, envelope, peak, and score variation;
they do not identify the underlying cause. Random/noise phase and peak
normalization can affect these quantities, so PCM differences alone are not a
hardware-fidelity verdict. Investigate reset and initialization semantics before
using this initial configuration for stronger conclusions.

The preserved artifacts remain evidence of the initial configuration. Do not
overwrite them with a repaired-core rerun. Use a separate output directory.

Reproduce the old-core variability measurement from the repository root:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python \
  experiments/sid-inverse/results/layered-snare/stability_check.py
```

This command intentionally rewrites only the diagnostic outputs. The original
search histories, best waveforms, parameters, and source snapshot remain intact.
