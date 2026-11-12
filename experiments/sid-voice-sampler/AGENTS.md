# Canonical C64 music path

Run every shell command through `rtk`. The user selected native Linus-style SID
sampling and mixing. Preserve that direction; do not restore `$D418` PCM4 or a
single-partial flute approximation as a fallback.

## One entry point

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py
```

`linus-mix-player.asm` is the self-contained runtime. `native_playback.py`
builds, verifies and captures it; `native_instruments/` prepares its independent
instrument assets from the pinned MOD. A fresh build needs no historical
`work/` score, recovery recording or generated instrument directory.

Do not revive the old study/probe generators as public entry points. Extend the
canonical player when an arrangement cannot fit; state unsupported behavior.

## Current Hyperbased arrangement

The supported proof is exactly the first twenty seconds, not the full song:

- SID 1: original Amiga C2, the previously accepted ordinary pulse SID part.
- SID 2: original C3 instruments 8/9/10/11 as actual reused sample waveforms.
  A native fractional cursor controls pitch. The clock is504 PAL cycles,
  1,954.86 values/s. Only frequency high is written; the measured transfer is
  `round(virtual_code*105/249)`. This has less bandwidth than the accepted
  7.82 kHz isolated recovery reference. Do not label the new mix listening-approved.
- SID 3: original C1 triangle bass plus original C4 sampled drums, added on C64
  at126 PAL cycles, 7,819.43 values/s. Reused triangle run programs compile the
  approved pitch/phase/volume oscillator; independent drum windows contain no
  bass or mixed song recording. Every approved mixed input remains exact.

All four original channels have assigned parts in this bounded phrase. SID 1
and the triangle bass remain synthesis approximations. Keep all original
channels separate, with their common gain/time origin. Select subsequent parts
by musical phrase; tracker channel numbers do not imply a permanent role.

Never replace a song with flattened host PCM. Preserve timing, triggers, gain
changes, pitch and sample lifetime. Report omitted passages and approximations.
The source prominence detector is still future work.

## Listening decisions

`work/hyperbased/listening-decisions.json` records acceptance. The user accepted
SID 1 and SID 3, and rejected SID 2's orchestral single-partial flute. Immutable
accepted solo WAVs are in `references/hyperbased-stems/`; earlier full-song
Cream/Hyperbased references remain under `references/`.

Preserve those reference bytes. Current SID 1/SID 3 register sequences and event
phases must remain exact. A resampler-phase-preserving startup shift is 54,736 PAL
cycles (1,225 recording samples); do not align listening files on the host. Current
captures need not be byte-identical to older ones: their measured differences
must remain within the documented noise comparison, with strict digital proof.
Compare both accepted WAVs at gain 8 with no time adjustment: maximum 96 PCM16
LSB peak and 25 LSB RMS difference. Current measurements are 80 LSB peak and at
most 21.98 LSB RMS; do not call the WAVs byte-identical.
The accepted sampled C3 recovery clip is not approval of the new lower-rate mix.

## Required proof and delivery

Keep PAL, reSID, MOS8580 + digiboost, resampling 2 and mono 22,050 Hz recording. Recording
rate differs from both native sample clocks. Master volume stays 15 during music;
never write sample amplitudes to `$D418`. Its voice-3-off bit may be set at startup.
Screen-on operation and physical SID fidelity remain unverified.

Deliver runnable `player.prg` and independently captured `all.wav`, `sid-1.wav`,
`sid-2.wav`, `sid-3.wav`. Bass and drums stay together on SID 3. Use the same
runtime, full producer workload, time origin and one gain for every capture.
Mute SID 1 with zero-frequency TEST score states and zero sustain. Mute SID 2 by
keeping TEST set in sampler controls, with zero sustain. Mute SID 3 with zero
sustain and its native output-disable bit; its computed sample stream continues.
Only declared mute constants and SID 1 score fields may differ between programs.
The all-muted run must match an independently static SID control.

Verify all 156,389 SID 3 inputs/prefixes at 126 cycles, all 39,097 SID 2 ring reads
plus the startup neutral latch at 504 cycles, all 3,000 SID 1 writes, counters and
constant master volume. Prove every ring generation was written before its
matching read, including silence; matching values alone can hide underruns.
Measure CPU and memory over the complete delivered phrase after runtime changes.

Listening files allow only a clock-anchored crop, DC removal and one constant
gain. No EQ, limiting, timing adjustment, dynamics, host mixing or noise removal.
Digital correctness does not prove perceived quality or physical bit resolution.

## Scope and ownership

Keep generated banks, raw captures and traces out of Git; publish only selected
PRGs, listening WAVs and compact receipts when requested. Preserve source MOD
provenance. Parallel HVSC and graphics work is outside this task.
