# SID inverse-synthesis laboratory

This directory contains a measured exploration of instrument matching with the C64 SID. The reference recordings are a real acoustic bass drum, snare, and nylon-string guitar. The output instruments contain SID register programs, not PCM sample streams.

Open `listen.html` for the listening comparisons after generating the results. `REPORT.md` records the conclusions and their limits. The detailed experiment scope is in `PLAN.md`.

## Reproduce

Run from this directory. Python 3.14 was used for the recorded run; exact direct dependencies are pinned in `requirements.txt`.

```sh
rtk proxy python3 -m venv .venv
rtk proxy .venv/bin/python -m pip install -r requirements.txt
rtk proxy .venv/bin/python assets/prepare.py
rtk proxy .venv/bin/python render_contract.py
rtk proxy .venv/bin/python search_checks.py
rtk proxy .venv/bin/python reset_diagnosis.py
rtk proxy .venv/bin/python reference_baselines.py
rtk proxy .venv/bin/python run_matrix.py --out results/fresh-sweep --budget 600 --workers 3
rtk proxy .venv/bin/python layered_check.py --out results/fresh-layered-snare --budget 600 --seed 1
rtk proxy .venv/bin/python hybrid_checks.py
rtk proxy .venv/bin/python finalists.py --results-dir results/fresh-sweep --out results/finalists --repeats 5 --top 6
rtk proxy .venv/bin/python robustness.py --results-dir results/finalists --out results/robustness --repeats 10
rtk proxy .venv/bin/python waveform_checks.py --results-dir results/finalists/guitar --out results/waveform-checks
rtk proxy .venv/bin/python vice_probe.py results/finalists/kick/patch.json --out results/vice-kick --duration 0.8 --note-hz 110
rtk proxy .venv/bin/python vice_probe.py results/finalists/snare/patch.json --out results/vice-snare --duration 0.7999546485260771 --note-hz 110
rtk proxy .venv/bin/python vice_probe.py results/finalists/guitar/patch.json --out results/vice-guitar --duration 0.8 --note-hz 221.47644388774796
rtk proxy .venv/bin/python make_report.py
rtk proxy .venv/bin/python write_findings.py
rtk proxy .venv/bin/python provenance.py
rtk proxy .venv/bin/python verify_lab.py
```

The reset-lifecycle diagnosis is preserved in `results/reset-diagnosis/diagnosis.json`; `reset_diagnosis.py` reproduces both lifecycles with its explicit legacy factory. That diagnostic is a required input to `write_findings.py`. The independent two-voice snare experiment has its own budget and seed, separate from the main matrix.

The three VICE commands use the exact durations and root frequencies of the preserved prepared recordings. For other assets, use the corresponding values from each selected `results.json`.

Each matrix run receives exactly 600 candidate renderings, including the common initial random candidates. The main comparison uses three seeds for each of spectral CMA-ES, spectral random search, and waveform-MSE CMA-ES. Finalist re-evaluation is an additional validation budget. Selecting a favorite across both CMA objectives does not give CMA a fair method-comparison advantage; use the separate equal-budget rows for that claim.

The final renderer constructs a new native SID for every independent candidate. The initial experiment reused one instance after reset, which left oscillator/envelope/analog state behind. That experiment is preserved in `results/sweep`; it is excluded from the final method comparison. Continuous-note history checks intentionally keep state inside one rendering.

The renderer's native dithering is still not exactly repeatable. Optimizer random seeds control proposed parameters, not bit-exact PCM. Repeated score measurements quantify this smaller remaining uncertainty. Do not average unaligned audio waveforms to judge timbre.

## C64 execution check

`vice_probe.py` requires the locally installed KickAssembler and VICE paths. For a fitted patch:

```sh
rtk proxy .venv/bin/python vice_probe.py results/finalists/guitar/patch.json \
  --out results/vice-guitar --duration 0.8 --note-hz 221.47644388774796
```

The probe builds a real PRG, executes it in VICE, compares the register dump against the direct renderer's exact cycle timestamps, and records a WAV. It blanks the screen and uses busy waits. Register-store instruction counts are only a lower bound for a future IRQ player's CPU cost. Graphics, interrupts, and a full song arrangement are not covered.

The audible instrument segment is located from the register-dump clock and the known pre-roll, with a 20 ms comparison allowance. An unbounded correlation could select a boot or initialization click instead. `vice-instrument.wav` preserves the full raw playback window; the listening page uses a separately peak-normalized copy. A 20 ms trailing hold lets the output backend flush the complete instrument.

VICE 3.10's dummy sound driver leaves its channel count uninitialized. A primary WAV device with warp disabled captures usable audio in this build. The register dump is captured in a separate run. This is a local version issue, not a requirement to record audio through the microphone. See `vice_probe.py` and its receipts for the upstream fix.

## Interpretation

The main metric combines linear/log STFT magnitudes at several resolutions, an amplitude envelope, and transient change. All sounds are DC-removed and peak-normalized for comparison. This measures timbre and envelope independently of absolute playback gain. Keep the raw amplitude and normalization gain when deciding whether a patch is useful in music.

The instrument macro has one SID voice, ADSR, an optional short noise attack, exponential pitch/filter curves, pulse-width movement, and a fixed master volume. The nominal control rate describes curve updates. Gate and noise transitions have additional exact event timestamps, so a 50 Hz replay is not a strict once-per-frame player.

The filter belongs to the chip. It is not an independent filter for every voice. Repeated-note checks preserve the prior oscillator, envelope, and filter state; a real C64 cannot hard-reset SID between instrument notes. A separate guitar recording at another pitch is held out from all fitting.

Measured numerical improvements are not a blind listening test. The listening page exposes the actual original, baseline, and fitted audio so the result can be judged directly. Validation on real SID chips remains separate from emulator execution.

## Files and provenance

- `sid_render.py`: direct reSIDfp rendering and timed register events.
- `fit.py`: bounded candidate families, CMA-ES/random search, loss components, and result export.
- `run_matrix.py`: independent-process experiment matrix and progress receipts.
- `finalists.py`: repeated scoring of distinct finalists and selection by mean spectral error.
- `robustness.py`: repeat spread, chip models, control rates, prior-note history, and transposed holdout.
- `search_checks.py`: independent metric controls and a clearly labeled synthetic recovery experiment.
- `vice_probe.py`: C64 assembly export, register timing verification, and independent VICE PCM capture.
- `assets/manifest.json`, `references.md`: CC0 recordings, licenses, preparation, and hashes.
- `renderer-notes.md`, `optimizer-notes.md`: implementation assumptions and source references.

No code from the third-party `sidmatch` optimizer was copied. Its architecture informed the research direction. Its available instrument exporters were not treated as verified hardware playback.
