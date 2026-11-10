# Current Madness: pitch and masking audit

This audit uses the revised score-scoped sample banks and output gain 3, not the rejected earlier bank/gain settings. No shared code was changed. All generated WAVs in this directory are offline arithmetic ablations, not new C64 recordings.

## Notes do not collapse to one constant pitch

From 30.72 s, original MOD track 1 carries sample 8 through periods 339, 381, 404, 381, 453, 508, 453, 678 and 339. The current arrangement follows those changes with fractional steps 232, 206, 195, 206, 174, 155, 174, 116 and 232. Its varying melodic carriers remain measurable around 742–1484 Hz.

Tracks 2, 3 and 4 deliberately sustain fixed periods 480, 240 and 480 through most of 30.72–39.68 s. Thus a dominant stationary backing tone is plausible when the melody's timbre or contrast is lost; it is not evidence that all note cursors stopped changing.

The strong 657 Hz peak belongs mainly to backing track 3 / sample 2, with contributions from other backing voices. It is not the main changing melody on track 1.

## Current per-channel levels, 30–40 s

| Track | Original independent RMS | Current fine mixer RMS | Current quantized marginal RMS |
| --- | ---: | ---: | ---: |
| 1 | 0.02610 | 0.01811 | 0.02160 |
| 2 | 0.03598 | 0.02732 | 0.03115 |
| 3 | 0.07013 | 0.06132 | 0.06502 |
| 4 | 0.04933 | 0.04241 | 0.04496 |

The marginal contribution is the quantized full mix minus a mix with the selected voice removed. It includes nonlinear threshold interactions and is not a separately playable physical stem. `channels.json` contains the strongest original/fine/solo/marginal peaks. The reconstructed current full DAC stream was asserted byte-identical to `expected_dac()`.

## Falsified explanations for the changed tonal ratio

Using 32–38 s, power near 164 Hz divided by power near 657 Hz is 0.617 in the independent original. Current fine mixer input is 1.424; final gain-3 quantization gives 1.406. The tonal change therefore already exists before final four-bit rounding.

| Offline ablation | Fine input ratio | Quantized ratio | Quantized RMS-matched STFT error |
| --- | ---: | ---: | ---: |
| Current | 1.424 | 1.406 | 0.552 |
| Simultaneous tick changes instead of stagger | 1.458 | 1.469 | 0.515 |
| Floating-point fractional steps | 1.371 | 1.369 | 0.543 |
| Both | 1.438 | 1.420 | 0.501 |

Removing the stagger or increasing cursor precision changes details but does not restore the original harmonic balance. This does not support rewriting the scheduler or cursors as a demonstrated fix for this complaint.

## Backing attenuation is a remix, not a fidelity fix

Weights 0.7, 0.5, 0.35 and 0.25 were applied to tracks 2–4 before quantization, with output gains 3/4/6. The 164/657 ratio stays near 1.8 over 30–40 s because both peaks largely belong to the backing itself. The changing upper melody becomes more prominent, but full-mix spectral error increases.

A moderate exploratory candidate is `candidate-backing-0.7-gain4.json`: 107 clipped samples out of 192,431 (0.0556%) over the first 50 s, full-passage spectral error 0.538 versus 0.529 for the current mix. `candidate-backing-0.5-gain4.json` raises relative lead contrast further, with only 13 clipped samples, but worsens spectral error to 0.566. Neither is presented as an established fix or a faithful mix.

`backing-ablation.json`, `phase-ablation.json` and `stagger-ablation.json` preserve the exact measurements. No listening judgment is claimed. Separate actual original/C64 lead clips are the appropriate next check; numeric agreement alone has already failed to predict the user's evaluation.
