# Controlled SID instrument fitting

`fit.py` searches compact one-voice instrument macros against an actual SID renderer. It uses the renderer contract in `sid_render.py`. It does not train a neural network or invent a replacement SID model.

## Scope

The reference must be one isolated sound, not a complete song or polyphonic recording. `prepare_target` downmixes stereo, resamples, removes DC, trims leading silence while retaining one millisecond before onset, and peak-normalizes to 0.8. Trailing audio remains part of the objective. `fit_target` accepts an already prepared mono target; it does not resample or trim it again.

Every render receives the same length, note, chip model and control rate. The optimizer normalizes each non-silent candidate to the same peak. This compares timbre and relative amplitude envelopes, not absolute SID loudness. A render below a raw peak of `1e-6` receives a silence penalty. Normalization gains and raw peaks are recorded so quiet-render amplification remains visible. Render starts are not independently shifted to improve the score.

## Search and budget

Each instrument has three fixed waveform/filter families. A small, bounded parameter space controls ADSR, pitch curve, filter curve, pulse width where relevant, gate duration and a short noise attack. Discrete values are rounded after decoding normalized parameters. Time constants use logarithmic scales. Master volume and oscillator count are not optimizer parameters.

The first quarter of the evaluation budget contains a midpoint candidate for each family, followed by seeded uniform random vectors. These candidates form a reproducible initialization baseline. The remaining evaluations are divided equally between families. A separate bounded CMA-ES run starts from each family's best baseline candidate. CMA-ES uses independent seeded random generators. Every rendered candidate counts toward the requested budget, including the final incomplete population. A partial population is scored but not passed to `tell`. Parameters that cannot affect a family's output, such as cutoff with filtering off, are omitted from that family's search vector.

`--search-mode random` provides the equal-total-budget control experiment. It uses the same initial quarter, then continues seeded uniform random search until the complete budget is spent. Families receive candidates in round-robin order. Comparing CMA-ES only against its initial quarter would give the optimizer more evaluations than the random control, so it is not a valid equal-budget method comparison.

The `mse` and `spectral` runs use the same baseline candidates and total budget. Their CMA-ES paths then differ because fitness differs. The best candidate is selected using the requested training objective only. Every candidate also receives both MSE and spectral scores; this allows cross-metric comparisons. The spectral audit of an MSE run is a second metric on the same target, not unseen validation data. A fair scientific claim additionally needs multiple random seeds, other references and listening tests.

## Audio objectives

MSE compares the normalized PCM values directly. The spectral objective combines:

- 0.60 times relative STFT magnitude L1 error;
- 0.20 times log-magnitude L1 error;
- 0.15 times relative amplitude-envelope L1 error;
- 0.05 times relative envelope-derivative L1 error, emphasizing transients.

STFT windows contain 128, 512 and 2048 samples, with 75% overlap. At 22,050 Hz they span approximately 5.8, 23.2 and 92.9 milliseconds. RMS envelopes use a four-millisecond window and two-millisecond spacing. Relative-error denominators and the logarithm have explicit floors. These weights are experimental choices, not calibrated perceptual units. Scores have no universal audible-quality threshold.

Multi-resolution magnitude losses reduce phase sensitivity. They do not make the comparison fully invariant to onset errors or noise realizations. A one-voice SID cannot reproduce arbitrary independent partial decays, complex body resonances or polyphony. A good score on one note does not prove successful transposition.

## Timing and portability

The control rate describes register updates, not audio sample rate. The renderer runs the SID between those updates. The result records the number of control ticks and a conservative upper bound on register writes from this schema. These are not measured 6510 cycle costs. The final player must verify actual changed-register writes, interrupt/parser cost, shared-filter ownership and interactions with graphics.

The optimizer does not add an event-count term to the audio loss because all runs share the same fixed control-rate constraint. Any source of hidden per-sample volume modulation must remain excluded by the renderer. Changing the control rate changes the feasible search space and must be reported separately.

Resetting an emulator for a deterministic candidate is useful during optimization. It does not establish that the result retriggers correctly on a live SID with previous envelope/filter state. Test repeated notes, other pitches, both chip models as applicable, and real hardware before treating a patch as a reusable instrument.

## Usage

```sh
experiments/sid-inverse/.venv/bin/python experiments/sid-inverse/fit.py reference.wav \
  --kind kick --seed 1 --budget 240 --loss spectral \
  --output /tmp/sid-fit-kick
```

The output contains target, initial, random-baseline and best WAVs; the best patch; candidate history; and settings, component scores and timing in JSON. `fit_target` returns audio arrays for in-process work. `save_result` writes the same artifacts for orchestrators.

## Method references

- [DDSP: Differentiable Digital Signal Processing](https://arxiv.org/abs/2001.04643), including the phase-alignment problem and multi-scale spectral comparison.
- [DDSP loss implementation](https://github.com/magenta/ddsp/blob/main/ddsp/losses.py), including magnitude, log-magnitude, loudness and time-difference terms.
- [Quality-diversity for Synthesizer Sound Matching](https://doi.org/10.2197/ipsjjip.31.220), a primary example of evolutionary sound matching.
- [Evaluating Sound Similarity Metrics for Differentiable, Iterative Sound-Matching](https://arxiv.org/abs/2506.22628), showing why metric rankings need listening validation.
