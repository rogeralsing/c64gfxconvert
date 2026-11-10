# Offline sample-loop search

`sample_loop_search.py` tried **269 loop candidates across 30 instrument/case
evaluations**, with conservative, balanced and aggressive error budgets. This
is a bounded heuristic search, not a proof of maximum possible compression.
No accepted bank, arrangement or player was changed.

## Results

Savings include actual prefix bytes, loop replication to the current player's
minimum 256 stored loop bytes, and loop/stop markers. Score bytes are unchanged.

| Baseline | Conservative | Balanced | Aggressive |
| --- | ---: | ---: | ---: |
| Stardust, complete 240 s | 538 B | 584 B | 598 B |
| Accepted Hyperbased test, 50 s | 1,190 B | 1,190 B | 1,760 B |
| Current Madness test, 50 s | 0 B | 0 B | 0 B |
| Existing full Hyperbased arrangement, 333.84 s | 267 B | 888 B | 2,364 B |
| Existing full Madness arrangement, 407.04 s | 0 B | 0 B | 0 B |

The full-song rows assess the existing earlier full arrangements with output
gain 3. They are not the newly packed lossless player builds. Loop savings alone
do not make those earlier full arrangements fit resident RAM.

The small conservative candidate worth an optional listening test is
[Hyperbased](hyperbased/conservative/arrangement.json). It changes samples 1
and 8, saving 1,190 bytes, or 6.8% of that test's bank and markers. The fixed
30–50 s full-mix incremental `SequenceLoss` is 0.002915 against the accepted
bank renderer. Loss against the independent original changes by −0.001085.
These small numeric differences do not establish inaudibility or acceptance.

Stardust's conservative candidate changes samples 5 and 14, saving 538 bytes
(2.5%). Its full-mix incremental loss is 0.025551. Madness did not yield a
candidate passing the defined pitch and envelope guards.

## Search and evaluation

The search preserves an exact original prefix. Earlier sustain candidates
retain at least 100 ms at the fastest actual sample-bank playback rate, or the
entire existing prefix when sustain starts sooner. Autocorrelation proposes
shorter periods and several earlier sustain starts. Direct continuation and
slope checks constrain new loop seams. This run searches existing loops longer
than 32 bank bytes; it does not exhaustively optimize short-loop prefixes or
invent loops in nonlooping drums and decays.

Each proposed instrument is replayed at its actual note times and compared
against both the current bank and an independently sample-muted libopenmpt
render. Measurements use `SequenceLoss` with absolute frequency, no octave
folding, no candidate-dependent time shift, and one bounded global level
adjustment. Additional guards constrain carrier shifts, envelope error,
unnormalized RMS changes and seam error.

The primary musical passage is 30–50 s. An instrument absent from that passage
is evaluated in a 20-second context containing its longest audible note. Every
selected candidate must also pass that longest-note context when different
from its primary passage. The complete 30–50 s mixed DAC output is then checked
for combined effects. This provides meaningful active-note coverage; it is not
an exhaustive listening evaluation of every note in every song.

The extra context catches misleading savings. For example, Hyperbased sample
7 offered approximately 2.4 kB of apparent savings in the main passage, where
notes can end before the shortened region is reached. It failed the longer
held-note context and was rejected. Stardust sample 8 lost its apparent
approximately 0.9 kB saving for the same reason. Larger loops in Madness
failed pitch guards even when a waveform-average error looked tolerable.

All 30 evaluated instrument cases pass the objective sanity checks: identity
loss is zero, silence loss exceeds 5, and the octave-up read-rate control has
loss above 0.3. Candidate pitch distances are never folded to pitch class.

Independent originals are decoded at **22,050 Hz**, where each 50 Hz MOD tick
contains exactly 441 frames, then resampled to 11,025 Hz for analysis. Direct
11,025 Hz decoding accumulated integer tick-length drift and was corrected
before the final results; the final caches explicitly include `render22050`
in their names. This issue affected the experiment's evaluator only.

## Artifacts and reproduction

- [method-summary.json](method-summary.json) contains the final table, all
  negative controls and hashes of the script and case reports.
- Every case's `report.json` contains candidates, limits, rejected held-note
  contexts, per-instrument original comparisons and full-mix scores.
- Every profile contains an `arrangement.json` and any changed sample banks,
  ready for the existing PCM4 builder. Unchanged banks retain absolute links
  to their original immutable inputs.
- `offline-candidate-30-50.wav` files are arithmetic references, **not actual
  C64 recordings**. Candidate metadata explicitly marks them unaccepted.

Run from the repository root:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/sample_loop_search.py --case all --candidates 9
```

## Actual C64 evaluation

The conservative Hyperbased50s candidate was built and executed in VICE with
the existing legacy score codec. Its PRG is **29,861 bytes**, saving exactly
1,190 bytes against the accepted31,051-byte test. Both register and audio runs
complete all2,500ticks with zero underruns. Every one of192,431DACbytes matches
the independent integer reference, with zero mismatches. Clock-phase range is
152CPUcycles with endpoint+1cycle; no accumulated sample-clock loss was found.

- [New actual C64 clip only,30–40s](hyperbased/conservative/hyperbased-loop-optimized-c64-30-40s.wav).
- [Independent original, same passage](hyperbased/conservative/hyperbased-original-30-40s.wav).
- [Execution and audio receipt](hyperbased/conservative/actual-c64-evaluation.json).
- [Exact DAC check](hyperbased/conservative/reference/trace-check.json).

The two standalone clips have matched RMS through constant gains and DC
removal only. There is no alternating old version or host-side instrument mix.
This candidate remains **experimental and not listening-accepted**; it does not
replace the accepted Hyperbased bank. The unchanged player format and IRQ need
no additional runtime synthesis. Lossless score optimization makes these lossy
bank changes optional.
