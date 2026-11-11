# A sampled MOD channel with two ordinary SID voices

This bounded arrangement adds synthesized accompaniment to the accepted
26.88-second **Cream of the Earth** channel-2 demonstration. The sampled input
is byte-identical to that solo. Both the solo and the original CC0-guitar
reference remain unchanged.

## Run

From the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_mod_hybrid.py --capture --budget
```

Outputs under `results/mod-channel-hybrid/`:

- `player.prg`: runnable C64 program.
- `hybrid.wav`: actual VICE audio of the complete arrangement.
- `verification.json`: input identities, native playback, audio and budget.
- `synth-input.json`: source-channel mapping, pitch calibration and limitations.
- `budget/cpu-budget.json`: non-invasive CPU measurements.

Interactive playback uses the same fixed emulator profile:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --play --prg experiments/sid-voice-sampler/results/mod-channel-hybrid/player.prg
```

The display is disabled. The program stops after its silent tail.

## Arrangement

The source range is 17.92–44.80 seconds: three patterns and 1,344 tracker ticks.

| SID voice | Source | Implementation |
| --- | --- | --- |
| 3 | MOD channel 2, instruments 7–9 | Accepted eight-bit reusable sample banks; C64 computes pitch and position |
| 1 | MOD channel 3, instrument 10 | Pulse melody, 17 source note starts |
| 2 | MOD channel 4, instruments 1–6 | Triangle/noise percussion, 165 source hits |

MOD channel 1 contains chord-like recordings and is omitted. This is a
three-channel arrangement, not a complete MOD conversion. No HVSC instrument
programs are imported; the parallel HVSC work is untouched.

The original `electronicguitar` instrument is a one-shot recording. Its first
8,192 source samples yield a measured period of 32.38197 samples, with
autocorrelation 0.95682. The pulse frequency follows that root and the original
MOD periods. It does not reproduce the recording's timbre or pitch drift.
Source-cursor RMS determines when its audible tail ends.

Percussion follows the original trigger times and periods, using short
triangle sweeps or noise bursts. These are handcrafted substitutes, not the
original drum recordings. Source amplitude is used to end tails; source
volume curves are not reproduced continuously.

Both synth voices settle at a quiet fixed sustain of 1 before playback.
Gate remains set across notes. Triangle plus TEST (`$19`) establishes their
resting level. This avoids full-volume envelope attacks beside the sampled
voice. The melody pulse width is 1,966 out of 4,096, approximately 48%.

## Clock, CPU and RAM

Voice 3 still receives **7,819.428571 values/s**, one every **126 PAL cycles**.
The audio recording uses **22,050 Hz mono**. The profile remains PAL, reSID,
MOS8580 + digiboost and resampling method 2.

The score stores eleven bytes per tick: the five accepted sample fields plus
frequency low/high and control for each synth voice. Foreground code prepares
those six values alongside the next sample buffer. It commits them after the
critical eight-cycle buffer-pointer switch. The NMI retains the accepted
instruction sequence except for its relocated final jump address.

| Measurement over the complete phrase | Result |
| --- | ---: |
| NMI CPU share | 72.84% |
| Foreground fill cost | 4,540–4,893 cycles per buffer |
| Minimum buffer-deadline margin | 1,102 wall cycles / 295 available foreground cycles |
| Pointer-switch cost | 8 cycles |
| Minimum pointer-commit margin before the next NMI | 6 cycles |
| Interrupted pointer switches | 0 |
| Reusable sample banks | 2,816 B |
| Score | 14,784 B |
| Working-buffer reservation | 512 B; at most 314 values active |
| PRG size | 24,001 B |
| Program end | `$65C0` |
| Contiguous space before `$D000` | 27,200 B |

Wall-cycle margins include time spent in NMI. Only the foreground figure
represents extra work available to the renderer. The pointer margin is narrow;
these results establish this program and phrase, not arbitrary added work.
The PRG stores reusable instruments and a score, not a recording of the entire
passage. The existing [solo measurements](MOD-CHANNEL.md) explain the alternating
156/157-value buffers that preserve the source's 50-Hz tracker timing.

## Native proof and audio balance

Full VICE runs verify:

- All 210,186 sampled input values equal the accepted solo.
- All 210,185 consecutive latch gaps are exactly 126 cycles.
- All 8,064 ordinary SID frequency/control writes match the prepared score.
- Synth commits occur 176–305 cycles after the old buffer's final latch.
- All 1,344 buffers complete with zero underruns, including the audio run.
- No `$D418` writes occur during the music stream.

A clean build and fresh capture produced byte-identical PRG, WAV and expected
sampled input. Corrupting one expected synth frequency byte caused verification
to fail while the sampled-input check still passed. These receipts are retained
beside the main verification report.

A separate native diagnostic changes only the two synth control columns to
their resting value. Every instruction, sample bank, sample field, frequency
and envelope byte remains unchanged. Its first latch and all event timestamps
match the combined run. Numeric subtraction of the two clock-cropped raw
captures estimates the combined synth contribution at **−12.05 dB RMS relative
to the sampled part**. This is a whole-phrase electrical level estimate, not a
perceptual loudness measurement; short synth hits can have a different balance.
Details and linearity/rounding limits are in `component-check/levels.json`.
That subtraction is analysis only; no mixed or aligned audio is delivered.

The combined capture's DC-removed raw peak is 0.08893. Its listening file uses
one constant gain of 8 and has no clipping. Delivery applies only a
clock-anchored crop, DC removal and constant gain: no EQ, dynamics, alignment,
time stretching or host SID mixing.

Digital correctness does not establish pleasant timbre or a suitable musical
balance. Those remain listening judgments. Physical SID behavior, screen-on
operation, multiple software-mixed sampled tracks and complete MOD integration
remain unverified.
