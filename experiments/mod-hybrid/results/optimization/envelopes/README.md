# Method B: attack, short periodic waveform and amplitude envelope

`sample_envelope_search.py` implements and evaluates this method with the
unchanged four-PCM player. It preserves the initial attack, fits a periodic
sustain waveform, and compiles a separate amplitude envelope into existing
50 Hz volume fields. There is no new envelope engine or playback codec.

The original MOD source hashes are checked. The full Stardust, Hyperbased and
Madness arrangements use their original bank, gain and note context throughout
each baseline/candidate comparison. Independent original audio is decoded by
libopenmpt. No listening quality judgment is claimed; actual whole-song VICE
register verification is documented below.

## Search and evaluation

- Only large looped samples with periodic, non-noisy sustain are eligible.
  The four largest qualifying banks per song are fitted.
- Period candidates come from autocorrelation. Up to 256 bank samples are
  allowed for the conservative point and 128 for the aggressive point.
- Conservative points preserve the complete original attack before the source
  loop. Balanced points retain at most 512 attack bytes and allow periods up
  to 192 bytes. Aggressive points retain at most 128 bank bytes of attack.
- Plain-loop and envelope variants are optimized separately against the same
  original bank. Envelope variants normalize the periodic waveform and compile
  compensating gains into the existing 16 volume levels.
- Every changed instrument is checked in its first active note and longest
  held note, using full replay history and instrument-isolated fine-mixer
  audio. Later-only material is therefore not approved from a silent 30–50 s
  preview. For example, Hyperbased sample 23 is checked at 181.10–184.94 s
  and 238.70–246.72 s. Whole-mix 30–50 s metrics are also reported.
- Note triggers, sample assignments, pitch steps, tick timing and routing are
  asserted unchanged. Only selected bank waveforms/loops and envelope volume
  fields change. Volume values remain within 0–64.

All six baseline/conservative-envelope linear reconstructions reproduce the
independent arithmetic model's 192,431 DAC bytes over the first 50 seconds
exactly. See `linear-model-check.json`. This verifies the evaluation renderer,
not perceptual fidelity.

## Actual memory accounting

The table includes the builder's minimum-256-byte loop expansion and sample
markers. Envelopes have no separately stored runtime arrays: their complete
cost is the change in compressed score size, after checking all eight legacy
packet grouping sizes. Positive net values are savings; negative values grow.

| Song | Point | Sample RAM saved | Added compressed score | Net RAM saved |
| --- | --- | ---: | ---: | ---: |
| Stardust | Conservative plain loop | 7,607 | 0 | 7,607 |
| Stardust | Conservative envelope | 7,505 | 384 | 7,121 |
| Stardust | Balanced plain loop | 9,193 | 0 | 9,193 |
| Stardust | Balanced envelope | 9,258 | 2,045 | 7,213 |
| Stardust | Aggressive plain loop | 10,771 | 0 | 10,771 |
| Stardust | Aggressive envelope | 10,793 | 4,699 | 6,094 |
| Hyperbased | Conservative plain loop | 4,988 | 0 | 4,988 |
| Hyperbased | Conservative envelope | 4,838 | 2,208 | 2,630 |
| Hyperbased | Balanced plain loop | 6,988 | 0 | 6,988 |
| Hyperbased | Balanced envelope | 7,060 | 3,288 | 3,772 |
| Hyperbased | Aggressive plain loop | 7,845 | 0 | 7,845 |
| Hyperbased | Aggressive envelope | 7,825 | 3,918 | 3,907 |
| Madness | Conservative plain loop | 2,631 | 0 | 2,631 |
| Madness | Conservative envelope | 2,691 | 2,936 | **−245** |
| Madness | Balanced plain loop | 5,960 | 0 | 5,960 |
| Madness | Balanced envelope | 5,952 | 4,295 | 1,657 |
| Madness | Aggressive plain loop | 7,619 | 0 | 7,619 |
| Madness | Aggressive envelope | 7,684 | 5,776 | 1,908 |

## Fidelity tradeoff

Spectral error is multi-resolution STFT magnitude difference divided by the
reference magnitude norm. Values are errors, not recognition percentages.
Original comparison uses one fixed gain calibration inherited from the
baseline; candidates do not receive per-note level or timing alignment.

| Song | Baseline vs original | Conservative plain vs baseline | Conservative envelope vs baseline | Conservative envelope vs original |
| --- | ---: | ---: | ---: | ---: |
| Stardust | 0.411 | 0.239 | 0.246 | 0.427 |
| Hyperbased | 0.506 | 0.092 | 0.091 | 0.508 |
| Madness | 0.590 | 0.472 | 0.500 | 0.609 |

The separate envelope improves some sustained instruments. Stardust sample
11's active 0–7.2 s spectral error improves from 0.461 for the plain loop to
0.393 with the envelope, with envelope correlation 0.954 and normalized
envelope RMSE 0.171. Hyperbased sample 7's longest held note improves from
0.420 to 0.358, with envelope correlation 0.994.

Those are limited improvements. The envelope does not preserve evolving
harmonic structure, and its added score commands outweigh its extra bank
savings relative to the plain-loop method in every tested aggregate point.
Madness remains particularly poor. Aggressive variants can change which
partial dominates by an octave or more, even when note steps remain intact.
Dominant-peak errors are explicitly labeled as spectral-peak measurements;
they are not reliable fundamental-pitch estimates for composite samples.

**The tested envelope method is not a clear overall improvement over plain
loops under this player's volume and score constraints.** It is a runnable
prototype with measured tradeoffs, not an accepted replacement for the source
samples.

## Runnable candidates

Every point has an `arrangement.json`, bank files, `report.json`, and a clearly
named offline 30–50 s WAV. The complete Stardust conservative-envelope program
was assembled successfully with the unchanged runtime:

- `stardust/conservative-envelope/c64/stardust.prg`: **38,495 bytes**.
- Resident end: `$9E5E`, below `$D000`.
- Full score: 12,000 ticks.
- Original PRG: 45,616 bytes; net reduction: **7,121 bytes**, including the
  extra 384 compressed score bytes.

The full 240-second PRG also completed an actual VICE register run: all
12,000 ticks, zero underruns, and all 923,670 emitted music DAC bytes matched
the independent reference exactly. Clock phase range was 184 cycles with
endpoint error +1 cycle. Evidence is under that profile's `vice/` and
`reference/` directories. No new audio capture or listening approval is claimed.
Hyperbased and Madness JSONs can be combined with a compatible score codec
experiment, but no complete resident PRG is claimed for them here.

Run from the repository root:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/sample_envelope_search.py --max-samples 4
```

`summary.json` contains the complete source identities, fit parameters,
per-instrument contexts, pitch-peak/envelope/spectral metrics and RAM results.
