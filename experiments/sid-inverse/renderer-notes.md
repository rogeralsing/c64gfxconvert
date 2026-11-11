# Direct SID rendering

`sid_render.py` drives one voice of the actual reSIDfp emulator through
`pyresidfp`; it does not substitute ordinary software oscillators. The direct
extension API is required because its `clock(int cycles)` preserves cycle
timestamps. The higher-level wrapper accepts `datetime.timedelta` instead.

Sources: [pyresidfp](https://github.com/pyresidfp/pyresidfp),
[native bindings](https://github.com/pyresidfp/pyresidfp/blob/main/src/pyresidfp.cpp),
[wrapper](https://github.com/pyresidfp/pyresidfp/blob/main/src/pyresidfp/sound_interface_device.py).
The dependency is GPL-2.0-or-later. It contains emulator code copied from
libsidplayfp. The installed dependency version belongs in the run receipt.

## Patch and event contract

- `render_patch` returns mono `numpy.float64` audio, with exactly
  `round(duration_s * sample_rate)` samples, scaled from native signed 16-bit
  samples by 32768. It does not normalize gain or remove DC.
- PAL clock is fixed at 985248 Hz. Models are `6581` and `8580`.
- Only voice 1 is active. Filter routing includes only voice 1. Volume is 15.
- Pitch in semitones and cutoff in register space decay exponentially:
  `end + (start - end) * exp(-t / tau)`. A zero time constant selects `end`.
- Pitch frequency is `note_hz * 2**(semitones / 12)`. The SID frequency register
  is `round(hz * 2**24 / 985248)`, saturated to 0..65535.
- Pulse width moves linearly between endpoints during `gate_s`, then holds.
  Normalized pulse and cutoff map to 0..4095 and 0..2047 respectively.
  Filter cutoff is not a linear frequency in Hz, especially on the 6581.
- Positive `attack_noise_s` selects noise before the requested waveform.
  These waveforms are alternatives; they are not bitwise combined waveforms.
- `patch_events` returns `(cycle, register_offset, byte)` tuples. Each event
  uses a physical SID register offset, so `$D400 + register_offset` is the
  C64 address. Event time zero is the first patch write.
- Initial patch setup takes ten writes; the gate opens at cycle 80. Ordinary
  modulation updates use the requested control rate, 200 Hz by default.
  Gate/noise transitions also receive their own rounded cycle timestamps.
- All writes are serialized at least eight cycles apart, including collisions
  between control updates and transitions. A collision can delay an event.
  This permits a real 6510 player; no two writes occur on one cycle.
- Inputs outside numeric bounds are clipped to hardware/declared limits.
  Non-finite values and unsupported models or sample rates are rejected.

## Initialization and repeated notes

Every evaluation constructs a fresh native SID and executes `initialization_events()`:
zero registers 0..24, set voice 1 TEST, then set master volume 15. These writes
are eight cycles apart. Exactly `PRE_ROLL_CYCLES` (49262) cycles pass from the
first initialization write to the first patch write. Initialization samples
are discarded, allowing the output filter to settle before scoring.

A C64 exporter can reproduce those writes and delays. A real SID cannot reset
all hidden oscillator/envelope/filter state through register writes. Holding
TEST resets the oscillator, but does not reset the envelope's internal rate
counter. A fresh-emulator candidate is therefore not proof of exact repeated
note behavior in a tracker. Repeated notes need their own verification with
the previous note's release and filter state preserved. A practical hardrestart
can clear gate and select fast release before each note, at the cost of a
preparation gap; this experiment does not claim that it removes every hidden
state difference.

reSIDfp has model-specific analogue approximations. It is useful for fitting,
but an emulator fit is not evidence that every physical 6581 sounds identical.
VICE is an independent full-machine replay check, not a bit-identical oracle
for this reSIDfp version. Low-level sample rounding can also differ between
successive runs. The dependency's
[FilterModelConfig.h](https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/FilterModelConfig.h)
contains a shared model's 1024-entry dither sequence and mutable index. Public
SID reset and constructing another SID do not reset that index. Fitting should
not depend on single-bit PCM identity.

Each `render_events` call owns its native chip. Multiple notes inside one event
trace deliberately share that chip and preserve state. Use separate processes
for parallel fitting. The wrapper does not expose state save/restore. The final
partial sample is trimmed or extended by endpoint repetition to meet the exact
array length.

## Local behavior and throughput

With pyresidfp 0.17.0, a 0.6-second render at 22050 Hz produced exactly 13230
finite float64 samples. All four waveforms produced non-silent output on both
chip models. A representative modulated pulse/noise patch compiled to 289
writes with a minimum spacing of eight cycles and the first gate at cycle 80.
One hundred 0.6-second renders took 5.266 seconds, about 18.99 evaluations per
second, after initial table creation. This is a local observation, not a speed
guarantee for other machines or patches.

Two consecutive renders of that patch differed by RMS 0.000333 and peak
0.001282 in full-scale units, approximately 42 native integer steps at the
peak. The scoring function must tolerate this measured emulator variability.
Waveform identity and exact PCM reproducibility are different acceptance
conditions; this renderer establishes the former, not the latter.

A first focused follow-up compared ten cached/reset renders with ten newly
constructed SID renders. Cached rendering took 0.342 seconds and fresh
construction took 0.353 seconds. Both retained small sample differences. That
single-patch check did not establish isolation from arbitrary preceding notes.

## Reset isolation correction

The initial renderer reused one SID and called native `reset()`. That was not
a complete fresh-state reset. Source inspection and the later two-voice
experiment exposed a second, much larger source of variation:

- [WaveformGenerator::reset](https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/WaveformGenerator.cpp)
  explicitly preserves the oscillator accumulator. Initialization sets TEST
  only on voice 1, so a layered instrument's voice 2 retained preceding phase.
- [EnvelopeGenerator::reset](https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/EnvelopeGenerator.cpp)
  preserves the envelope counter.
- [Filter::reset](https://github.com/pyresidfp/pyresidfp/blob/main/src/residfp/Filter.cpp)
  only writes cutoff, mode and resonance registers. It does not clear the
  filter's voltage history or integrator capacitor state.

Calling that operation a full oscillator/envelope/filter reset was incorrect.
Shared dithering alone did not explain the observed score changes. A fresh
native SID now isolates every candidate. Immutable native model tables remain
shared by the dependency. Continuous note histories still use one instance.

`reset_diagnosis.py` retains an explicit cached factory to reproduce the old
lifecycle after this fix. The receipt is
`results/reset-diagnosis/diagnosis.json`. Five rerenders after each of three
different preceding patches measured the same layered patch as follows:

- Cached/reset: spectral standard deviation 0.055–0.070; condition means
  1.511–1.630.
- Fresh native SID: standard deviation 0.00012–0.00028; means 1.6689–1.6692.
- Extending the cached pre-roll to 0.2 or 1 second did not solve the problem.
- Disabling filtering still left large cached variation in the layered case,
  consistent with the retained second oscillator phase.
- Three separate fresh processes scored the layered patch with standard
  deviation 0.00035. Small residual emulator noise remains; bitwise identity
  is not the acceptance condition.

The earlier sweep and layered search used the cached lifecycle. Their receipts
are retained as provisional evidence and must not be pooled with corrected
fresh-instance searches.

The diagnosis replays captured real patches from `reset-cases.json`; it does
not require old generated search directories. Its final verification calls the
actual current renderer after each of the three preceding sounds, without
replacing its native factory. `decision.applied` is derived from measured
score stability, predecessor mean agreement and agreement with independently
forced fresh-instance controls. The declared tolerance is 0.005 spectral
units; the script writes those checks and thresholds in
`fresh_core_verification` and exits unsuccessfully if they fail. To reproduce
this evidence without replacing the original receipt:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/sid-inverse/reset_diagnosis.py \
  --out experiments/sid-inverse/results/reset-diagnosis-reproduced
```

## Robustness measurements

After completed fitting runs exist, run:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/sid-inverse/robustness.py \
  --results-dir experiments/sid-inverse/results/finalists \
  --out experiments/sid-inverse/results/robustness
```

The script accepts finalists selected by repeated scores regardless of their
original search method or objective. Otherwise it selects the lowest stored
spectral loss per instrument from 200 Hz CMA runs. It averages ten **scores**, reporting their
population standard deviation and full range. It does not average raw
waveforms, which could cancel when their phases differ. Fresh-note repetition
and continuous retriggering are separate conditions.

The same learned patch is replayed at 50, 100, 200 and 400 Hz control rates and
on both chip models. These comparisons do not retrain the patch. Continuous
history cases render two notes in one SID instance, keeping full chip state
between the notes; only the initial render resets the emulator. The second
note is scored against its original target. Both the scored segment and full
raw sequence are retained.

The guitar holdout uses a different original recording, verified against the
asset manifest. The trained patch is replayed at that recording's measured
root frequency. No holdout fitting occurs. Raw WAVs retain float samples;
listening WAVs use the fitting score's DC removal and peak normalization.
