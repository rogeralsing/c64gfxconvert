# Cream: the selected three-minute arrangement

The selected source interval ends at the pattern boundary at 188.16 seconds,
before the next polysynth phrase. Instrument 12's first polysynth passage
starts at 179.48 seconds, within this selection. SID1 is already resting at
the chosen ending. Existing
one-shots continue without new triggers until 188.42 seconds. This avoids
cutting the active melody at the earlier 179.20-second boundary.

The target is an unexpanded 64 KiB C64 with the existing PAL, reSID, MOS8580
and digiboost profile. Both sampling streams use ordinary SID oscillators;
master volume stays constant. Screen-on operation and physical SID fidelity
remain unverified.

## Musical allocation

| Physical voice | Musical source | Playback |
| --- | --- | --- |
| SID1 | Original C1 at 17.92–31.36; C3 elsewhere | Native waveform and hardware-ADSR candidate; listening assessment pending |
| SID2 | Original C4; C1 instrument 10 during the introduction | Reused original instrument samples at 1,954.86 values/s |
| SID3 | Original C2; C1 instrument 11 during the introduction | Existing Q8 sample stream at 7,819.43 values/s |

The SID1 reassignment restores twelve C1 triggers and omits six sparse C3
tonic/octave triggers at 17.92–31.36. Later C1 chords remain omitted.
SID1's native instruments and hardware envelope remain approximations.
SID2's low sampling rate limits its high-frequency percussion. This is an
arrangement, not an exact four-channel Amiga replay.

The rejected SID1 build in `work/cream/three-minute-linus-mix/`, former
4:01.92 player, short approved Cream passage, twenty-second drum audition and
Hyperbased files are preserved. They must not be overwritten as a side effect
of extending this arrangement.

## Native SID1 candidate

`cream_sid1_melody.py` reads its reusable program parameters from
`native_instruments/cream_sid1/voice.json`. Instrument 10 uses triangle+saw
(`$31`) instead of the former flat pulse. The native profile sets AD `$18`
(attack 1, decay 8), SR `$60` (sustain 6, release 0) and pulse width 1966. Other SID1 instruments retain
their earlier waveform recipes under the same hardware envelope.

TEST rests clear GATE. A real source trigger or channel handoff may clear the
preceding active note's GATE for two ticks (40 ms), preserving its frequency and
waveform. Volume-only changes do not insert that extra edge. This allows a
new hardware attack, but shortens those preceding notes and does not reproduce
the MOD's recorded envelopes or all volume slides. Instrument 11's simultaneous
fifth is also not reproduced by a single root waveform.

Startup preserves the former muted SID1 warmup (AD `$00`, SR `$00`, GATE/TEST
`$19`). It then clears GATE and commits the first musical GATE rise before
applying AD `$18`. Preserving that order avoids a measured change to SID2's
initial held-level transient. The selected ADSR profile passes the bounded
phase probes; this does not establish a universal envelope reset for arbitrary
SID states or physical hardware.

This changes only SID1. Both complete SID2/SID3 input streams and sample
clocks must remain exact. The new result is a listening candidate, not an
accepted replacement merely because its native checks pass.

## CPU work without changing sample values

`cream_q8_fast.py` replaces repeated fractional arithmetic with reusable
relative-position tables. For a Q8 step `S`, a table contains
`floor(n * S / 256) mod 256` for `n = 0..255`. Every 256 output values advance
the source base by `S` bytes. The producer splits at frame ends, source-offset
wraps and output-index wraps. Four values per loop reduce branch overhead.

The tables are generated once before playback. They contain addresses into
reused instruments, not song audio. Gain lookup remains native. Zero-gain
blocks write 128 without reading source samples, while preserving the actual
cursor and fractional phase so later gain changes still resume correctly.

Four held pitch changes preserve their Q8 fraction by selecting an equivalent
index in the new table. The preparation proves `n * S mod 256 == fraction` and
retains the actual byte cursor. This avoids restarting the sampled note or
storing a separately rendered pitch-bend waveform.

`cream_long_runtime.py` adds the separate SID2 producer. Three-byte events
contain a 16-bit output count and a reusable cursor/end descriptor ID. The
producer copies into a 256-byte ring ahead of the global 504-cycle reader.
Adaptive 32/16-value chunks and a final boundary check prevent background work
from delaying the next critical SID3 buffer. Notes are prefetched before this
background work. Native ring-generation tracing
must prove every value was written before its matching read, including silence.

## Stock RAM

The main score retains its existing 24-byte logical contract and compressed
transport, with a 512-byte native LZ history. This leaves `$E200..$EFFF` for
generated position tables. The original decoder and history size remain
unchanged for the preserved players.

Only neutral padding is removed from the SID3 instrument banks. Their shorter
ends and 200-byte guards are checked against every original sample value.
SID2 banks store only reused instrument/pitch/gain source-position extents;
they contain neither mixed music nor a continuous song recording. Native
exclusive-end checks supply neutral values after each stored extent.

The safe PRG loader still avoids loading through `$D000..$DFFF`. It stages
high code in `$C400..$CFFF`, restores the original RAM image and then starts
the player. The generated high position tables are zero until normal startup,
so the loader can retain its existing zero-history restoration contract.

## Acceptance evidence

The build must deliver one runnable PRG, a mixed WAV and three independent
full-workload solo captures. Processing is limited to a native-clock crop,
DC removal and one shared gain. No EQ, host mixing or fitted audio alignment
is permitted.

Required checks include every SID1 note, every SID2/SID3 input and register
phase, every ring generation, full CPU deadlines, true-drive autostart,
independent static mute, unchanged protected artifacts and clean PRG rebuilds.
Actual SID2/SID3 audio is compared with the frozen sampler recordings on the
fixed source clock. The rejected flat SID1 recording remains a diagnostic
baseline; matching it is not the repair's audio target. Assess new SID1 phrases
against the independent Amiga channels and the declared native approximation.
Digital proof does not establish perceived sound quality or physical analog
resolution.

Measurements and selected listening files belong in
`work/cream/sid1-repair/`. See its `verification.json` for results
from the actual complete run rather than extrapolated excerpt measurements.
