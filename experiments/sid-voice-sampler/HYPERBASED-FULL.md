# Complete Hyperbased SID/sample arrangement

The full three-channel arrangement plays **333.84 seconds (5:33.84)**, from
the beginning to the end of Hyperbased's 64-order list. It uses 16,692 tracker
ticks. The accepted 10.56-second [excerpt](HYPERBASED.md) remains unchanged.

## Build and play

From the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_full_hyperbased.py --capture --budget
```

Outputs under `results/hyperbased-full/`:

- `player.prg`: complete resident C64 player, 45,554 bytes.
- `hybrid.wav`: full actual VICE performance, 333.84 seconds.
- `verification.json`: source, preparation, compression, native, audio and CPU receipts.
- `full-synth.json`: every prepared SID register row and instrument analysis.
- `full-model.json`: prepared sample states and gain-bank metadata.
- `budget/cpu-budget.json`: compact full-song CPU measurements.

`--assemble-only` prepares and assembles without VICE. A normal build always
verifies native register playback; `--capture` additionally records the full
performance in real time. Playback:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --play --prg experiments/sid-voice-sampler/results/hyperbased-full/player.prg
```

Profile: PAL / reSID / MOS8580 + digiboost / resampling method 2. Screen off.
The output clock remains 126 PAL cycles, **7,819.428571 values/s**. Recording
uses the separate **22,050 Hz mono** rate.

## Arrangement and quality choices

Source channel 4 uses the sampled SID voice. Source channels 2 and 1 use the
two ordinary SID voices. Source channel 3 remains omitted, as in the accepted
excerpt. Full duration does not mean exact four-channel MOD reproduction.

The entire song changes instruments and channel roles. The complete version
therefore adds 17 sampled instruments and 22 SID alternatives:

- [Sample library](instruments/hyperbased-full-samples/library.json): individual
  instrument descriptors and 36 reusable gain-bank ASM files.
- [SID library](instruments/hyperbased-full-sid/library.json): individual
  triangle, pulse, percussion and chord recipes. Physical voice levels and
  pulse widths live in this manifest because instruments can use both voices.

Chords 12, 13, 15 and 16 become declared 50-Hz arpeggios. They are not assigned
the misleading low ACF common-period roots. Other tones use measured roots;
percussion uses noise or triangle sweeps. Source loop targets are tracked
separately from note triggers. Fixed quiet SID levels approximate continuous
amplitude fades. Instrument 8 follows its dominant audible partial on the SID
track; its original composite fundamental is an octave below that partial.

Sample volume uses nearest levels **0, 16, 32, 48, 64**, with half steps rounded
up. The maximum gain error is −7/+8 source units out of 64. Several newly used
instruments receive additional low-pass decimation to fit RAM. Instruments
2–6 retain the accepted excerpt's bank data exactly. The excerpt's 528 SID
register states are also preserved.

The eight-bit fractional sample step introduces −27.37 to +11.18 cents of
pitch quantization over this preparation. Resampled loop endpoints add about
+12.23 cents for sample 8 and −0.50 for 23. These are declared preparation
approximations, not post-processing of the recording.

## Runtime and storage

The PRG stores **24,576 bytes** of reusable sample gain banks. Each bank retains
only its actually used prefix. Its logical cursor end can lie beyond that
physical prefix. Mute and ended states execute `LDA #128; NOP`, with the same
four-cycle cost as the ordinary sample read, preventing stray reads. Muting
preserves cursor progression; volume-bank changes do not restart notes.

Three page-aligned dictionaries hold **189 / 247 / 215** PCM/lead/bass states.
Independent twelve-tick chunks and a pointer playlist reproduce all states
exactly. Score data occupies **18,853 bytes before alignment**, rather than
183,612 bytes of raw eleven-byte rows. A 175-tick buffer-length table preserves
the source's 50-Hz timing with alternating 156/157-value buffers.

The NMI retains the accepted 92 instruction bytes except its relocated final
jump address. Runtime ends at `$0C5C`; banks start at `$1000`. The complete
program ends at `$B9F1`, leaving **5,647 bytes before `$D000`**. The C64 computes
sample cursor progression and emits the stream; no full-song PCM recording
is stored in the program.

## Whole-song verification

- Fresh independent libopenmpt decoding matches all **16,692 ticks / 2,888 rows**
  for order, row, pattern and speed. Source duration is 333.84 seconds.
- A separate scalar sample replay matches all **2,610,438 prepared values**.
- Actual VICE register playback matches every sample input, every one of the
  **2,610,437 consecutive 126-cycle latch gaps**, and all **100,152 SID writes**.
- Register and actual audio runs complete all 16,692 buffers with **zero misses**.
- No `$D418` writes occur during music.
- Full compression roundtrip and fresh assembly preserve every score state.
  Fresh default preparation produces an identical PRG and sample model.
- A copied-library voice-setting mutation changes the compiled PRG, proving
  the manifest settings are consumed. Mini native tests cover gain changes,
  mute/resume, one-shot completion, retrigger, loops and clock-table wrap.

Full-song non-invasive CPU profiling measures:

| Measurement | Result |
| --- | ---: |
| NMI CPU share | 72.74% |
| Foreground fill cost | 4,402–5,166 cycles per buffer |
| Minimum deadline margin | 94 wall cycles / 15 available foreground cycles |
| Minimum pointer-commit margin | 6 cycles |
| Interrupted pointer swaps | 0 |

That is a narrow measured CPU margin. A separate high-step loop stress case
exceeded it; the real song's loops use steps no higher than 68 and the full
song passes. This player is bounded to this preparation, not arbitrary MOD
instruments or extra work. Screen-on operation and physical SID are unverified.

The actual WAV has 7,361,172 mono frames. Delivery applies only a clock crop,
DC removal and a constant gain, with no clipping. No EQ, dynamics, host mixing
or time alignment conceals player errors. Digital agreement does not establish
perceived sound quality. Only one full audio run was made; PRG/model rebuilding,
register verification and CPU profiling are separate checks.
