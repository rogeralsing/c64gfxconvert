# SID inverse-synthesis laboratory

Explore whether a short, playable SID instrument program can approximate recorded percussion and guitar sounds. All work stays inside this directory; existing graphics experiments remain untouched.

## Questions and evidence

1. Can a SID core render PCM directly, repeatably, fast enough for automated search? Measure runtime, reset behavior, and output determinism.
2. Does evolutionary fitting improve over a fixed starting patch and an equal-budget random search on real recorded kick, snare, and guitar references? Retain the original audio, fitted audio, seeds, evaluation counts, and scores.
3. Does a spectral/envelope objective produce different results from samplewise waveform error? Compare equal budgets and listen to the final candidates; numerical scores alone do not establish perceived quality.
4. Do the resulting register programs survive export and execution on an emulated C64? Build a PAL PRG, record its VICE output, compare against the direct SID rendering, and measure the event budget.
5. Which apparent successes fail when the chip model, note pitch, or preceding SID state changes? Evaluate those conditions explicitly rather than assuming a fresh emulator is an instrument retrigger.

## Working scope

Begin with one physical SID voice per fitted instrument, fixed master volume, and 200 Hz curve updates plus explicit gate/noise transition events. Treat the shared SID filter as a resource, not an independent filter per instrument. Preserve short waveform and pitch sequences; avoid a PCM-like stream of unrestricted register writes.

Use independent real recorded targets with documented provenance. A synthetic recovery case can check the search loop, but cannot prove acoustic imitation. Keep a random-search baseline and compare multiple seeds before declaring an optimizer superior.

## Deliverables

- Reproducible renderer, optimizer, and experiment commands.
- Source/license records for reference audio.
- Target, initial, and fitted WAV files plus an A/B listening artifact.
- Machine-readable experiment receipts and a concise report of useful approaches, failures, and remaining limits.
- At least one register program verified through an actual C64 PRG in VICE.

Repeated evaluation uses mean loss and its spread, never samplewise averaging of noise or phase-varying waveforms. Fitting budgets and finalist validation budgets are recorded separately. A pooled best-of-two-CMA-objectives finalist is a listening candidate, not evidence that CMA outperforms one random-search run.

This is a research experiment, not a MOD importer or a finished music editor. Do not claim listening quality, real-chip fidelity, or arbitrary MOD compatibility from fitting scores.
