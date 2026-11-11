# Hyperbased: sampled drums with SID melody and bass

The [complete 333.84-second arrangement](HYPERBASED-FULL.md) is now available.
This page preserves the accepted excerpt and its original measurements.

The second instrument-library arrangement uses **Hyperbased**, by Firefox and
Tip / Phenomena. It plays source **37.44–48.00 seconds**, a 10.56-second phrase
with 528 tracker ticks. The cut starts at order 9, pattern 11, row 8, tick 0;
it does not claim to contain complete patterns or the whole song.

## Run

From the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_mod_arrangement.py --capture --budget
```

The default [arrangement](arrangements/hyperbased.json) declares the source
range, track allocation, omitted channel and instrument-library directory.
Results go to `results/hyperbased/`:

- `player.prg`: runnable C64 program.
- `hybrid.wav`: actual VICE recording.
- `verification.json`: source, instruments, native playback, audio and budget.
- `synth-input.json`: measured roots, source note counts and synthesis limits.
- `budget/cpu-budget.json`: full-phrase CPU measurements.

Playback uses the existing profile:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --play --prg experiments/sid-voice-sampler/results/hyperbased/player.prg
```

## Arrangement and instruments

| SID voice | Original MOD channel | Implementation |
| --- | --- | --- |
| 1 | 2, instrument 7 | Pulse lead; 12 source note starts |
| 2 | 1, instrument 1 | Triangle bass; 54 source note starts |
| 3 | 4, instruments 2–6 | Reusable sampled drums; 77 source hits |

Source channel 3 is omitted. Its instrument has an ambiguous octave; assigning
it an unverified root would risk the wrong notes. This is a three-channel
arrangement. The two tonal parts use handcrafted SID approximations, not HVSC
programs or faithful copies of the original recordings.

The seven definitions live in
[instruments/hyperbased/](instruments/hyperbased/). The
[pulse lead](instruments/hyperbased/07-pulse-lead.json) and
[triangle bass](instruments/hyperbased/01-triangle-bass.json) are JSON recipes.
The five drums have JSON descriptors and pure-byte `.asm` banks. The library
retains the original source URL, byte count and SHA256.

Pitch analysis uses each original instrument's first 8,192 samples, with
eightfold interpolation and a separately selected period-search band:

| Instrument | Measured period in source samples | Autocorrelation | Resulting pitch range |
| --- | ---: | ---: | --- |
| 7, lead | 40.01935 | 0.97007 | About 138–207 Hz |
| 1, bass | 159.63780 | 0.89122 | About 39–78 Hz |

The bass has chorus/pitch drift. A constant triangle preserves the measured
root but loses its rich recorded overtones. The lead uses pulse width 1,966.
Prewarmed sustain levels are 2 for the lead and 1 for the bass. Source volume
zero causes rest, and source RMS gates tails; continuous volume fades are
approximated by fixed quiet levels.

The host follows each source instrument's original cursor, including the bass
already in progress at the cut and the tonal instruments' loops. This only
determines the prepared SID note/tail sequence. The sampled drum channel still
requires constant-volume one-shot instruments; it does not gain sample-loop
or arbitrary MOD-effect support.

## Timing, CPU and memory

The profile remains PAL / reSID / MOS8580 + digiboost / resampling method 2.
SID voice 3 receives **7,819.428571 values/s**, one every **126 PAL cycles**.
The separate recording rate is **22,050 Hz mono**.

There are 323 buffers of 156 values and 205 of 157: **82,573 values** total.
Playback lasts 10.559978807 seconds, approximately 21.19 microseconds short of
the source cut. The WAV rounds to exactly 10.56 seconds at its recording rate.

| Full-phrase measurement | Result |
| --- | ---: |
| NMI CPU share | 72.95% |
| Foreground fill cost | 4,772–4,948 cycles per buffer |
| Minimum deadline margin | 957 wall cycles / 243 available foreground cycles |
| Pointer switch | 8 cycles; zero interrupted switches |
| Minimum pointer-commit margin | 6 cycles |
| Reusable drum banks | 4,096 B |
| Score | 5,808 B |
| Working-buffer reservation | 512 B |
| PRG size | 16,305 B |
| Program end | `$47B0` |
| Contiguous space before `$D000` | 34,896 B |

The small foreground margin applies to this measured phrase. Available RAM
does not imply enough CPU for another software-mixed sample channel. The PRG
stores five short reusable banks and a score, not an 82,573-byte recording.

## Verification and limits

Actual VICE runs verify all 82,573 sample inputs against an independent cursor
model, all 82,572 consecutive 126-cycle latch intervals, all 3,168 ordinary SID
frequency/control writes and all 528 completed buffers. There are no underruns
in either register capture or audio capture, and no `$D418` writes during music.

A clean rebuild and fresh capture produce byte-identical PRG and WAV. All 84
nonzero-volume lead ticks and 440 nonzero-volume bass ticks remain active;
source-RMS gating adds no extra rests in this cut.

A separate native diagnostic changes only the two ordinary-voice control
columns to their resting value. All event timestamps and sample inputs still
match. Analysis-only subtraction estimates the two synth voices together at
7.68 dB RMS below the sampled drums. The full raw peak is 0.11899, with 18.49 dB
headroom and no clipping. This whole-phrase level estimate does not establish
perceived balance. No derived listening file is made from that subtraction.

The generalized sample compiler also reproduces the accepted Cream of the
Earth solo PRG byte-for-byte. The updated library loader and static second-voice
pulse-width label preserve the accepted Cream hybrid binary as well. The old
PRGs, recordings and reference receipts remain unchanged.

Listening audio uses only a clock-anchored crop, DC removal and constant gain.
No EQ, dynamics, host mixing or time alignment masks playback problems. Native
correctness establishes the prepared sequence, not perceived timbre or musical
balance. Screen-on operation and physical SID playback remain unverified.
