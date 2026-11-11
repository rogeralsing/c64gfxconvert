# Fresh-core two-voice snare experiment

The same `layered_check.py`, bounds, seed 1, and 600-render budgets were rerun
after repairing the renderer to construct a fresh native SID for each render.
The old cached-reset evidence remains untouched in `../layered-snare/`.

The fresh renderer SHA-256 is
`ecc5755de95267fb52b5e25084cda7a25907285e4a652306b1e0709532146550`.
Sources were frozen before the run under `source-snapshot/`; `environment.json`
records source hashes, installed package versions, and Python version.

## Program and resource cost

Filtered SID noise on voice 1 plays simultaneously with an unfiltered triangle
body on voice 2. Fifteen parameters describe the two envelopes, noise frequency,
body pitch drop, and global filter curve; three families select low-pass,
band-pass, or high-pass filtering. Voice 1 alone is routed through the filter.
The second voice's global-register writes are removed before merging events.

Each search evaluates 600 programs, including the same first 150 parameter
sets. Every family receives 200 candidates. The primary objective is the same
normalized spectral/envelope AudioLoss used in the main matrix. Fixed master
volume is 15; per-render normalization is only used for scoring and listening,
not as a hidden SID playback feature. No PCM data is needed for playback.

| Method | Best search score | Five further renders: mean ± population SD | Register writes | Search wall time |
| --- | ---: | ---: | ---: | ---: |
| CMA-ES | 1.470685 | 1.470568 ± 0.000150 | 115 | 194.61 s |
| Random | 1.501034 | 1.500645 ± 0.000976 | 52 | 350.24 s |

CMA-ES achieves approximately 2.0% lower repeated mean loss in this single seed.
Search timing occurred alongside other experiments and does not establish
relative algorithm throughput. Five score checks per method are additional
evaluation work outside each 600-candidate search budget.

Both traces retain at least eight cycles between writes and use two SID voices
plus the shared filter. The six-cycle store-only lower bounds are approximately
0.08755% and 0.03959% respectively; these exclude player/parser/interrupt work.
No assembled C64 replay was verified for this two-voice experiment.

## Repeatability

A second batch of five native renders per winner was made using the frozen
fresh sources. Every waveform is retained under `stability/`; `stability.json`
contains scores, peaks, envelopes, and pairwise raw waveform differences.

| Method | Second batch mean ± SD | Median pairwise raw PCM difference RMS | Median normalized envelope relative RMS difference |
| --- | ---: | ---: | ---: |
| CMA-ES | 1.470528 ± 0.000194 | 0.00002493 | 0.03236% |
| Random | 1.500990 ± 0.000559 | 0.00005422 | 0.06251% |

The matching 150-program prefixes have median absolute score difference
0.000340 and maximum 0.009527. Native dither still means the renderer is not
bit-identical, but winner-level variation is much smaller than under the old
cached-reset configuration.

## Interpretation limits

This is an exploratory one-seed search, not a controlled ablation of voice
count. Its parameter space and CMA population size differ from the main
one-voice macro. Any comparison with that experiment must account for these
differences and the additional voice/filter resources. Fresh one-voice snare
results were not yet available when this note was written, so this result alone
does not establish a two-voice benefit. Numerical loss also does not establish
audible realism or real-chip fidelity.

The reference is the original recorded acoustic snare target; no synthetic SID
target was substituted. Best normalized audio, raw float audio, target audio,
patch parameters, event traces, complete histories, and repeatability evidence
are retained for review.
