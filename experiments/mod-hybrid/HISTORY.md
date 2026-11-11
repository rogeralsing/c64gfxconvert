# Historical music experiments

This is the documentation preserved before the digiboost cleanup on 2026-11-11. References to “current”, alternative players, hardware profiles and generated paths describe those earlier experiments. Follow [README.md](README.md) for the supported workflow.

The recorded PAL/6581 measurements and audio remain historical evidence; they are not digiboost captures. Large intermediate files may exist only in the research workspace.

## Earlier MOD-to-SID research

# Stardust Memories: C64 sampled music

Lossless score compression now enables complete Hyperbased and Madness on
ordinary C64 memory. The [optimization study](results/optimization/README.md)
compares automatic sample loops, loop/envelope reconstruction, score codecs
and exact sample-tail trimming, with complete execution evidence and runnable
programs. The older experiments below remain available as historical results.

The current playable result is the complete four-channel **sample-only**
version: `results/pcm4-clean/c64/stardust.prg` (45,616 bytes, four minutes).
It follows the approved instrument-sample playback approach. Build commands,
audio and full verification are documented in [PCM-PLAYER.md](PCM-PLAYER.md).
The SID approximation experiments below remain historical comparisons.

The earlier four-PCM residual quantizer created excessive upper-band noise.
The current player rounds the combined mix directly; the before/after actual
C64 audition is `results/pcm4-clean/audition/c64-before-then-after.wav`.

## Current isolated-channel fitting

The current fitting work focuses on original MOD channel 2 only, comparing
the complete 30–50s phrase. Several-note instrument search, whole-phrase
refinement, existing GoatTracker instrument programs, and actual C64 replay
are documented in `results/channel-fit-2/README.md`. That directory contains
original/optimized-SID audition pairs and a separate actual-C64 PCM control.
The earlier full-song arrangements below remain prototypes; their execution
checks did not establish that their instrument sounds were good.

## Channel-by-channel audition

The listening comparison now isolates each original MOD track. Each file
contains the original for 20 seconds, a 0.5-second pause, then the C64 version
of that same track and passage. Both sides have equal RMS through constant
gain only. The musical passage is seconds 30–50; all other tracks are muted.

- Lead, MOD track 2: `results/channel-solos/comparisons/channel-2-original-then-c64.wav`.
- Bass, MOD track 3: `results/channel-solos/comparisons/channel-3-original-then-c64.wav`.
- Accompaniment, MOD track 4: `results/channel-solos/comparisons/channel-4-original-then-c64.wav`.
- Percussion, MOD track 1: `results/channel-solos/comparisons/channel-1-original-then-c64.wav`.

Original solos use libopenmpt's interactive channel-mute API. Each fresh
decoder renders from song start before the passage is cropped. Their sum
reconstructs the original reference within four PCM16 LSBs. C64 solos run
separate actual 50-second PRGs in VICE; selected-track parameters remain
identical to v2 and only other tracks' volumes are zeroed. A selected track
retains all its instruments, including any percussion in that track.
These are solo playbacks of the existing arrangement, with no further fitting.

Preparation tools are `solo_original.py`, `solo_c64.py`, and `compare_solos.py`.
`results/channel-solos/comparisons.json` records the source files, ordering,
gain factors and hashes; `results/channel-solos/audit.json` checks isolation
and the actual packaged PCM segments. Shared SID volume behavior means C64
solos need not sum exactly to the full mix.

## Current melody-first revision

The current revision gives the lead its own SID oscillator. The first two-SID,
two-PCM version ran correctly but failed listening evaluation: the melody was
weak and the overall sound too dark. The principal mechanism was PCM
quantization. In seconds 30–50, the volume lookup rounded 79.56% of sample 14's
already nonzero four-bit data back to silence. The lead therefore needs a
better rendering path, not merely a master-volume increase.

| Original MOD track | Current C64 output |
| --- | --- |
| 1 | Software PCM percussion |
| 2 | SID lead |
| 3 | SID bass |
| 4 | SID accompaniment |

The volume-register DAC does not consume a SID oscillator, so this version
uses all three. Its DAC baseline is 12 with percussion excursions of about
three volume steps. The lead gain is 2.2, with bass and accompaniment at 0.65,
before clamping and SID sustain quantization. The source notes and effects
remain unchanged. These are deliberate arrangement choices.

Some source sounds have weak low-frequency repetition with a stronger higher
carrier. Overrides in `results/melody-v2/instrument-overrides.json` use
contextual spectral measurements and bounded native SID comparisons. For
example, sample 14's strong 748 Hz line is approximated by a triangle near
748 Hz; samples 6 and 8 use twice the earlier oscillator frequency. This is a
carrier-oriented timbre approximation, not a claim to reproduce every partial.

- Full runnable song: `results/melody-v2/full/c64/stardust.prg`, 41,999 bytes.
- New comparison audio: `results/melody-v2/short/vice/stardust-preview.wav`,
  seconds 30–50 captured from the matching 50-second C64 build in VICE.
- Original comparison: `results/reference/original-preview.wav`.
- Diagnosis: `results/lead-diagnosis/lead-diagnosis.json` and
  `results/melody-diagnosis/diagnosis.json`.

All 12,000 ticks of the full version execute without sequencer backlog or
missed DAC deadlines. Actual frequency and sustain registers of all three SID
voices match the arranged score at each tick's 10ms observation point.
Receipts are under `results/melody-v2/full/vice/`. The short build additionally
has actual WAV capture and the same register checks. No full-length v2 WAV
has been captured; the four-minute WAVs below belong to the earlier version.
Timing checks do not establish perceptual quality; listen to the new preview.

Rebuild the current full program from the repository root:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/arrange.py --melody-first --overrides experiments/mod-hybrid/results/melody-v2/instrument-overrides.json --out experiments/mod-hybrid/results/melody-v2/full
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/build_c64.py --input experiments/mod-hybrid/results/melody-v2/full/arrangement.json --out experiments/mod-hybrid/results/melody-v2/full/c64
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/run_vice.py --prg experiments/mod-hybrid/results/melody-v2/full/c64/stardust.prg --symbols experiments/mod-hybrid/results/melody-v2/full/c64/stardust.sym --out experiments/mod-hybrid/results/melody-v2/full/vice --mode registers
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/verify_playback.py --arrangement experiments/mod-hybrid/results/melody-v2/full/arrangement.json --capture experiments/mod-hybrid/results/melody-v2/full/vice/capture.json
```

For the short listening build, use `arrange.py --seconds 50` with output
`results/melody-v2/short`, build into that directory's `c64`, then capture with
`run_vice.py --duration 50` into its `vice` directory. The existing pinned
`sid-inverse/.venv` supplies NumPy, SciPy and SoundFile. KickAssembler and VICE
are required for native builds and capture. Both 2+2 and 3+1 layouts remain
supported by the backend. Target remains PAL/6581, with graphics disabled.

## Earlier two-SID, two-PCM prototype

This experiment converts the complete four-minute **Stardust Memories** by
Jester / Sanity into two SID tones and two software PCM voices. The target is
a PAL C64 with a 6581 SID. The source is the MOD used in Sanity's *World of
Commodore* (1992), downloaded from [Demozoo](https://demozoo.org/music/21462/).
Original authorship and copyright remain with their respective owners.

## Listen and run

The independent original rendering is `results/reference/original.wav`.
`original-preview.wav` contains seconds 30–50, the common comparison window.
The runnable C64 program is `results/c64/stardust.prg` (51,168 bytes).
`results/vice/stardust-listening.wav` is the full VICE capture with constant
listening gain; `stardust-preview.wav` contains the same seconds 30–50.
The audio is produced by the assembled C64 program, not a host-side mix.

## Arrangement

| Original MOD track | C64 output |
| --- | --- |
| 1 | Software PCM voice 1 |
| 2 | Software PCM voice 2 |
| 3 | SID voice 1 |
| 4 | SID voice 2 |

Fixed routing preserves every note trigger without voice stealing. This does
not preserve every original timbre: percussion appearing on tracks 3/4 also
uses a SID approximation. SID pitch follows the original sample's measured
periodicity, and SID volume follows the sampled envelope and tracker effects.
Pulse widths for samples 5 and 11 come from a bounded harmonic comparison;
this is not a full evolutionary SID fit.

The PCM bank contains 13 samples, resampled to one quarter of their original
sample count and quantized to four bits stored in one byte per value. Its
17,681 bytes replace 70,718 bytes of original PCM. Playback uses two software
voices mixed into the SID volume register, `$D418`, at 3,848.625 updates/s.
The register also controls SID master volume, so PCM modulates the two tonal
voices. This is an audible limitation of this first 6581 arrangement.

Screen/graphics integration, 8580 support and real-hardware measurements are
separate work. This directory does not claim a general MOD player: unsupported
effects, nonzero finetune and BPM changes fail explicitly.

## Reproduce preparation

Run from the repository root. The existing `sid-inverse/.venv` supplies NumPy,
SciPy and SoundFile. The independent reference also requires libopenmpt
(`brew install libopenmpt`; tested version 0.8.10). C64 builds use KickAssembler;
captures use VICE `x64sc`.

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/reference.py
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/analyze_instruments.py
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/arrange.py
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/build_c64.py
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/run_vice.py --prg experiments/mod-hybrid/results/c64/stardust.prg --symbols experiments/mod-hybrid/results/c64/stardust.sym
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/verify_playback.py
```

`sources/stardust-memories.source.json` records the exact download variant and
checksum. The Demozoo file has 19 patterns; a separately catalogued Mod Archive
variant has 20. Do not apply that variant's checksum to this source.

## Evidence

- `results/reference/reference.json`: all 12,000 executed ticks agree with
  independent libopenmpt order, row, pattern and speed; duration 240 seconds.
- `results/reference/audio-comparison.json`: original four-PCM replay driven
  by this timeline versus an independent controlled libopenmpt render.
  Full-song waveform correlation 0.92968, per-tick RMS correlation 0.999807.
  This checks note/effect/envelope behavior, not the quality of SID timbres.
- `results/instrument-analysis.json`: periodicity, sample features and the
  limited harmonic comparison behind the SID mapping.
- `results/arrangement.json`: complete hardware-voice score, original routing,
  sample bank and explicit synthesis limitations.
- `results/c64/build.json`: 19 shared sequence blocks, 31 order entries,
  31,833 bytes of score and 17,679 bytes of trimmed PCM. All 12,000 packed
  ticks reconstruct the quantized arrangement. The resident program ends at
  `$CFDF`, leaving 33 bytes before I/O at `$D000`.
- `results/vice/capture.json`: the assembled C64 program completes all
  12,000 ticks without sequencer backlog. DAC intervals are 161–356 cycles
  around a 256-cycle clock, with no missed deadlines. One extra boundary
  write gives a measured stream span of 240.000259 seconds.
- `results/vice/score-check.json`: actual SID frequency and sustain registers
  match the arranged values for both voices on every tick, observed 10ms into
  each tick. This checks the 6502 packet decoder at its output boundary.

The first native run exposed a flag bug in `get_byte`: pointer increments
overwrote the N/Z flags needed by the command parser. Returning flags from
the loaded byte fixed it. `results/vice-parser-bug/score-check.json` retains
the failing native-register comparison; the corrected run has zero mismatches.
Failed-attempt files are evidence, not listening artifacts.

VICE audio capture uses its primary WAV device with warp disabled. A separate
register-dump run supplies the cycle anchor for cropping the song. Do not use
the VICE 3.10 dummy device for WAV recording: that build does not initialize
its channel count. The capture monitor disables the player at its `done`
routine and advances a short silent tail to flush the final audio fragment.

The original replay semantics are checked against the
[ProTracker 2.3D clone](https://github.com/8bitbubsy/pt2-clone/blob/master/src/pt2_replayer.c).
The independent reference uses [libopenmpt](https://lib.openmpt.org/doc/).


---

## Earlier PCM4 baseline documentation

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
