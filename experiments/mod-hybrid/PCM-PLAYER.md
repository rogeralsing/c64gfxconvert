# Four-channel sampled playback on C64

The [optimization study](results/optimization/README.md) adds lossless score
compression and verified complete Hyperbased (5:33.84) and Madness (6:47.04)
programs. Stardust shrinks from 45,616 to 37,170 bytes with unchanged sample
banks. Use `pcm4_build.py --score-codec dictionary8`; the default remains the
byte-compatible legacy format documented below.

Additional verified 50-second tests of Cream of the Earth, A Final Hyperbase
(Enigma), and 4-Mat's Madness are in [results/more-mods/README.md](results/more-mods/README.md).
Those full songs exceed the current resident memory layout; the linked test
programs and actual VICE comparison recordings are complete for their 50s scope.

The current player runs the complete four-minute **Stardust Memories** by
Jester / Sanity as four independent sampled MOD tracks. Every instrument is a
short reusable sample. The program does not store a full-song recording.

- Program: `results/pcm4-clean/c64/stardust.prg`, **45,616 bytes**.
- Instruments: **16**, occupying **21,683 bytes** after loop expansion.
- Compressed score: **21,784 bytes**, representing all **12,000 ticks**.
- Note triggers per original track: **1869, 694, 1096, 212**.
- Target: PAL C64, MOS6581, graphics disabled.
- Output: mono, four-bit volume DAC at **3,848.625 updates/s**.
- Corrected actual VICE recording, first 50s: `results/pcm4-clean/short/vice/stardust-listening.wav`.
- Level-matched before/after audition: `results/pcm4-clean/audition/`.

The load image ends at `$BA2F`, below I/O at `$D000`. No REU, streaming or
additional SID chips are required. SID oscillators remain muted; playback
uses the volume-register DAC at `$D418`.

## Sample and score preparation

`pcm4_prepare.py` retains the original four-channel note and effect timeline.
The independently checked MOD reader handles the effects used by this song.
Unsupported effects and nonzero instrument finetune fail explicitly; this is
not yet an unrestricted MOD player.

Original eight-bit instrument waveforms are low-pass resampled and quantized
to four-bit values, stored one per byte for fast lookup. The divisor is chosen
per instrument from its highest actual playback rate in the whole song.
Divisors are 5–8, retaining at least the pre-DAC bandwidth of the approved
single-channel divisor-8 control. Playback uses an eight-bit fractional sample
cursor; its step never exceeds 250. Loop boundaries are scaled to the bank.
Short loops are repeated to at least 256 stored bytes to reduce boundary work,
without changing the repeating waveform's period.

The optional `--bank-scope score` chooses divisors from only the selected score,
instead of the complete source song. This preserves more usable bandwidth in
short test passages when much higher notes occur later in the source. Such
banks and fractional steps must be rebuilt before using another score.
The default remains `song`, preserving previous builds. In `score` mode,
short source loops are repeated to a length divisible by the resampling
divisor before filtering, preserving their original repeating pitch.

Each source track retains its own sample selection, pitch, trigger, loop and
volume state. Equal original note triggers are not replaced by audio excerpts.

## Mixing and scheduling

The mixer first looks up each voice's volume-scaled contribution at greater
precision than the final four-bit DAC. It sums all four contributions and
rounds once to the nearest four-bit DAC code, with ties to even. It does not
separately round each channel into a small per-voice DAC range.

The safe numeric range of the fine sum is 8–232; the byte accumulator cannot
overflow. The corrected complete digital reference uses DAC values 3–13 with
no digital clipping. Four voices share the final four-bit output, so quiet
material can still be rounded away and effective resolution depends on the mix.

Arrangements may explicitly set `mixing.output_gain` for nearest rounding.
The default is 1; the formula is `clamp(round(8+(fine_sum-128)*gain/16),0,15)`.
The gain is applied before quantization through a lookup table, adding no IRQ
work. Increasing it makes quiet material survive quantization but can clip
louder peaks. The reference reports clipped sample counts. It is not enabled
globally: the original Stardust build remains byte-identical at gain 1.

`pcm4_build.py --dc-boost` is a separate experimental option. It initializes
all three SID voices with test, gate and pulse bits and full sustain as
constant-DC references for the volume DAC. It changes the PRG and is disabled
by default. The three release programs retain their original initialization;
the option has assembly validation, not real-chip loudness or quality proof.

The earlier player in `results/pcm4/` used residual error feedback. That
reduced low-frequency quantization error but pushed substantial error into
the audible 1.5–2kHz band at this low DAC clock. The user reported an
applause-like noise. Controlled arithmetic and native-SID probes found this
excess even with perfectly uniform sample timing, identifying quantization
as the main cause. The current default removes that feedback. All original
sample banks, note states, pitch, loop and volume data are unchanged.
Missing `mixing.mode` in old arrangements preserves their legacy feedback
algorithm; explicit `nearest` selects the correction. Unknown modes fail.
Old binaries and recordings remain available as diagnostic evidence.

The assembly uses self-modifying sample addresses, fractional steps and volume
operands. Foreground code decodes the next tick while the current tick plays.
Changes are committed one voice at a time across the final four sample slots.
With the one-sample output pipeline, voices begin their next state 3, 2, 1 and
0 sample periods before the nominal tick boundary. The largest deliberate
stagger is under 0.8ms; the reference models it explicitly.

The IRQ preserves A and may use Y. Foreground indexed reads protect Y briefly
with saved interrupt state; descriptor reads use X, which the IRQ leaves
untouched. This optimization removed the first version's late prefetches and
cumulative clock drift. Failed builds and captures remain under `attempt-1`.

## Verification

The final full PRG completed all 12,000 ticks with zero prefetch underruns.
An independent integer mixer, cursor and scheduler model generated 923,670
expected DAC bytes. Every actual D418 byte in VICE matched, with **zero
mismatches**, anchored to the capture clock without alignment search.

Observed DAC intervals are **196–331 CPU cycles**, median 256. The cumulative
clock-phase range is 185 cycles and the endpoint differs by only +1 cycle.
There is no detected accumulated timing drift across the four-minute score.
This does not claim that every individual IRQ completes within 256 cycles;
occasional delayed interrupts recover without losing the verified stream.

Evidence:

- `results/pcm4-clean/c64/build.json`: binary, memory, bank and source hashes.
- `results/pcm4-clean/vice/capture.json`: whole-song actual execution and timing.
- `results/pcm4-clean/short/vice/capture.json`: first-50s actual WAV capture.
- `results/pcm4-clean/reference/actual-trace-check.json`: complete DAC comparison.
- `results/pcm4-clean/reference/reference.json`: independent digital model.
- `results/pcm4-clean/audition/`: actual before/after comparison and audit.
- `results/pcm4/noise-diagnosis-model/`: quantization-error ablation.
- `results/pcm4/noise-diagnosis-core/`: uniform-clock versus actual-clock probe.
- `results/pcm4/noise-diagnosis-mix/`: original, approved solo and mix evidence.

The corrected whole four-minute PRG is verified through its full register
stream. Only its first 50 seconds have a new actual WAV capture so far; the
earlier four-minute WAV under `results/pcm4/` contains the noisy algorithm.

This validation targets the installed PAL/6581 VICE configuration. Real-chip
DAC variation and 8580 playback have not been measured. Listening files use
only DC removal and constant level adjustment; there is no host-side mixing
of the four instrument tracks in the actual VICE recording.

## Build and capture

Run from the repository root with the existing Python environment,
KickAssembler and VICE:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/pcm4_prepare.py
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/pcm4_build.py
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/run_vice.py --prg experiments/mod-hybrid/results/pcm4-clean/c64/stardust.prg --symbols experiments/mod-hybrid/results/pcm4-clean/c64/pcm4.sym --out experiments/mod-hybrid/results/pcm4-clean/vice --duration 240
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/pcm4_reference.py --input experiments/mod-hybrid/results/pcm4-clean/arrangement.json --out experiments/mod-hybrid/results/pcm4-clean/reference --trace experiments/mod-hybrid/results/pcm4-clean/vice/registers.txt --capture experiments/mod-hybrid/results/pcm4-clean/vice/capture.json
```

The exact original MOD download and authorship are recorded in
`sources/stardust-memories.source.json`. Earlier SID approximations and the
approved single-channel PCM control are preserved under their original paths.

## Experimental captured SID passages

`sidtrace_extract.py` builds a short resident replay from VICE sound-device
`dump` output (`delta register value` decimal lines). It extracts D418 volume
nibbles and timestamped voice/filter writes; it does not read a SID file or
convert an arbitrary tune. The current input contract requires D418 mode
nibble `$3` throughout the chosen passage.

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/sidtrace_extract.py --dump /absolute/registers.txt --window 1 13 --out experiments/mod-hybrid/results/sidtrace-poc
```

The default tick is 256 PAL CPU cycles. `--tick-cycles 154` selects the faster
experimental clock. The passage must fit a 16-bit sample count and end below
`$CF00`; dense register writes can exceed an IRQ's time budget. Diagnostic
options include `--boost-voice3`, `--all-boost`, `--digi-only`,
`--channels-only` and `--no-filter`. These variants are not release programs.
Synthetic PAL VICE checks cover event values and due-tick replay across the
low-byte wrap; they do not establish fidelity or timing for a whole SID tune.
