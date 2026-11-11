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
