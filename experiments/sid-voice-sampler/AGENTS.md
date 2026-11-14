# Canonical C64 music path

Run every shell command through `rtk`. The user selected native Linus-style SID
sampling and mixing. Preserve that direction; do not restore `$D418` PCM4 or a
single-partial flute approximation as a fallback.

## One entry point

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --full
```

`full_length_player.asm` is the full-song runtime; `full_length_playback.py`
builds, verifies and captures it. `full_length_instruments.py`,
`full_length_sid.py` and `full_length_score.py` prepare reused instruments,
native SID programs and compressed note data from the pinned MOD.
Omitting `--full` retains the twenty-second `linus-mix-player.asm` reference,
prepared and captured through `native_playback.py` and `native_instruments/`.
A fresh build needs no historical `work/` score, recording or generated banks.

Use the same entry point with `--song cream --full` for the complete 4:01.92
Cream arrangement. Omitting `--full` preserves its approved 26.88-second passage
(original MOD time 17.92–44.80). A request to port the next song requires its
full length; a fresh recording of this excerpt alone is not completion.
`cream_instruments.py`, `cream_sid.asm` and the recipes in
`native_instruments/cream/` preserve the approved source-channel allocation:
SID1=C3 pulse, SID2=C4 triangle/noise percussion, SID3=C2 reused PCM; C1 chords
are explicitly omitted. Both ordinary voices retain AD `$00`, SR `$10` and
continuous GATE through TEST rests. Never interpret Cream instrument numbers
using Hyperbased's SID programs. `cream_playback.py` shares the native runtime,
decoder, linker and digital checks; `cream_reference.py` checks actual mixed
audio against the immutable approved Cream recording without alignment or gain
fitting. Its guard must reject silence and equal-level noise. Keep the approved
passage and Hyperbased bytes fixed when extending.

Full Cream keeps the shared NMI and decoder but selects the optional
`cream_fractional.py` Q8 cursor in `full_length_runtime.build`. It replaces
unused software-triangle work, reads original reusable banks, and preserves
fractional position across held pitch and gain changes. Do not expand the song
into per-pitch banks: those measured 58,280 bytes before other data. Full PCM
uses centre 128 directly and 256 guard values, with identity or gain lookup pages.
The bounded player still uses centre 113 plus neutral triangle 15; keep its bytes.
The full introduction assigns C1 where specified; C1 is otherwise omitted even
when another allocated track rests. New chord instruments use explicit major,
minor and sus4 arpeggios. Ordinary SID volume slides remain an on/off
approximation with continuous SR `$10`; do not claim exact source dynamics.
`cream_reference.compare_full` checks the approved interval at its fixed native
clock position in the full recording. Never fit an offset or relax its bounds
to hide a player regression. Full builds protect the short Cream PRG/WAVs too.

Do not revive the old study/probe generators as public entry points. Extend the
canonical player when an arrangement cannot fit; state unsupported behavior.

## Complete Hyperbased arrangement

The user selected the ending at exactly 3:00. Play the first 9,000 ticks and
produce exactly 180-second WAVs. Validate the complete pinned 16,692-tick source
before selecting that interval; do not restore the 333.84-second ending without
new direction. Read `FULL-LENGTH.md` before changing it. SID1/SID2 run native
instrument programs, while SID3 mixes software triangle bass and a reused PCM
stream at 126 PAL cycles. Source roles change by musical passage.

Preserve the actual orchestral attacks. There are no active source-part
allocation omissions before the selected end. The later third-lead section
and instrument22 effect are outside it. Keep the SID timbre approximations
explicit; assigned channels do not establish exact four-channel Amiga replay.

The decoder's `tick_record` can hold the following tick while `voice_record`,
the pending SID fields and `pending_flags` retain the current one. Decode one
tick ahead, after completing and checking the current mixed buffer. Moving
decode back inside the critical fill caused 621 late buffers. Preserve native
frame-count calculation, PCM ends/loops, gain shifts and continuous cursors.
No per-tick PWM stream, song waveform windows or external RAM are allowed.

The native frequency dictionary and chord tables preserve source pitch.
Reusable declarations for all 24 source instruments live under
`native_instruments/hyperbased_full/`; native programs are in
`full-length-sid.asm`. Additional notes must fail explicitly if they exceed
dictionary/table bounds, rather than truncating an index.

## Preserved twenty-second arrangement

The separate earlier proof covers exactly the first twenty seconds:

- SID 1: original Amiga C2, the previously accepted ordinary pulse SID part.
- SID 2: original C3 instruments 8/9/10/11 as actual reused sample waveforms.
  Reusable instrument/pitch/gain variants are compiled before playback. A native
  integer cursor advances through each note; gain changes preserve its elapsed
  position. COPY32 uses a suffix lookup table and an unrolled copy kernel.
  The clock is 504 PAL cycles,
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

Approved sound is a constraint, including its envelope and control history.
Keeping the old WAV on disk while changing the player's audible behavior does
not preserve that approval. Freeze approved instruments during unrelated work.
Memory or CPU pressure never authorizes changing their sound. Use lossless
optimizations, keep a shorter arrangement or report the measured limit; present
any proposed audible change separately before treating it as accepted.

The SID1 regression demonstrated why matching a new model is insufficient:
zero sustain in TEST rests silenced later notes despite correct frequency and
CONTROL values. The accepted first twenty seconds hold sustain `$20` throughout
rests and keep GATE continuous. Descriptor byte1 marks that policy; boundary
prewrites repeat the previous control rather than adding a GATE or TEST edge.
Do not replace this with new envelope attacks or compensate using host gain.

`sid1_reference.py` checks every one of 122 audible passages against the pinned
approved recording. This real-audio gate must pass before new listening WAVs
and the normal player are delivered. It must reject the known broken recording,
not just compare generated register data with its own model. Changes outside
SID1 must stay frozen while repairing SID1; verify their data byte for byte.

The acceptance and byte-preservation rules in this section describe the
separate twenty-second reference. Full-length arrangement changes must preserve
those reference files, not claim that the new full mix is byte-identical to
them. The full arrangement has its own digital proof and still needs listening
assessment.

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

The CPU optimization preserves the complete SID register dump and all four
current WAVs byte for byte. See `CPU-PROFILE.md` and the compact
`work/hyperbased/linus-mix/optimization-check.json` comparison. Keep the source
model's pitch/gain quantization exact when compiling bank variants. New pitches
need derived banks; held-pitch changes and loop wraps are not silently supported.

## Agreed CPU and memory limits

The user reverted the GeoRAM/full-song experiment. Continue with this native
mixer on an unexpanded 64 KiB C64. Use sampling only for parts that fit the
measured CPU budget, use ordinary SID synthesis for other suitable parts, and
report omitted passages. Do not add external memory or expand a song into
score-timed waveform windows to force full-length playback.

Choose SID programs, short periodic waveform tables or original samples per
instrument and passage. The user explicitly prefers this flexible choice;
melodies may retain distinctive samples, and bass/drums need not always use PCM.
The one-PCM budget diagnostic under `studies/` intentionally omits original C3;
do not present it as a musical replacement. The complete implementation uses
the native decoder and SID programs described above, not that diagnostic.

Preserve reusable instrument assets and separate note data. The retained CPU
optimization is verified for the first 20 seconds only: its C3 waves grow 947 bytes,
but combined instrument/score/table data shrinks 525 bytes and the PRG stays
48,138 bytes. That bounded result does not establish memory efficiency for a
complete song. Measure instrument variants, note storage and total memory
before extending it; accept sampling/polyphony limits when necessary.

## Required proof and delivery

Keep PAL, reSID, MOS8580 + digiboost, resampling 2 and mono 22,050 Hz recording.
The recording rate differs from the native sample clocks. Master volume stays 15 during music;
never write sample amplitudes to `$D418`. Its voice-3-off bit may be set at startup.
Screen-on operation and physical SID fidelity remain unverified.

Deliver runnable `player.prg` and independently captured `all.wav`, `sid-1.wav`,
`sid-2.wav`, `sid-3.wav`. Sampled parts and software bass share SID3 in the full
arrangement; physical source roles rotate. Use the same
runtime, full producer workload, time origin and one gain for every capture.
In the full arrangement, mute ordinary voices with `$18`, zero frequency and
zero sustain as described below. In the preserved reference, mute SID1 with
zero-frequency TEST score states and zero sustain; mute its sampled SID2 by
keeping TEST set in the sampler controls with zero sustain. In both players,
mute SID3 with zero sustain and its native output-disable bit while its computed
sample stream continues. Only declared mute constants may differ in full-song
programs; the preserved reference also permits its declared SID1 score fields.
The all-muted run must match an independently static SID control.

For the selected three minutes, verify all 1,407,497 SID3 values/prefixes, all
ordinary SID values, native triggers, end/loop state, full source-tick count,
master volume and exact shutdown. Trace every consuming buffer activation and
require zero late buffers in register and audio runs. Verify normal autostart,
clean PRG reproduction and the full static-mute control. Count prefetched note
decoding separately in the CPU partition.

Full-length PRG autostart must pass true-drive disk loading
(`-autostartprgmode 2`). Mode1 injects RAM; mode0 virtual-filesystem traps also
load the old flat image successfully in VICE and do not cover this failure.
Never disk-load a flat image through `$D000..$DFFF`:
it writes to active VIC/SID/CIA registers before the player starts. Keep the
`prg_loader.py` startup packaging, its declared free staging arena and the
`verify_prg_startup.py` restored-RAM proof. Packaging must preserve every native
playback byte and address; startup fixes do not authorize sound changes.

Full-length ordinary-voice mutes must use TEST with GATE clear (`$18`), zero
frequency and zero sustain. `$19` retriggers the envelope during note gate
prewrites and creates audible DC pulses, even with sustain zero. Do not remove
the independent full-length static-SID comparison or hide these pulses with
host audio processing. This does not authorize changing the preserved reference.

For the preserved reference, verify all 156,389 SID3 inputs/prefixes at 126
cycles, all 39,097 SID2 ring reads
plus the startup neutral latch at 504 cycles, all 3,000 SID 1 writes, counters and
constant master volume. Prove every ring generation was written before its
matching read, including silence; matching values alone can hide underruns.
Measure CPU and memory over the complete delivered phrase after runtime changes.
Partition costs without double counting interrupt time inside foreground work.
The residual includes main-loop control and busy waits; it is not guaranteed
uniform spare time. Keep startup/prefill and shutdown outside the stated CPU
comparison interval.

Listening files allow only a clock-anchored crop, DC removal and one constant
gain. No EQ, limiting, timing adjustment, dynamics, host mixing or noise removal.
Digital correctness does not prove perceived quality or physical bit resolution.

## Scope and ownership

Keep generated banks, raw captures and traces out of Git; publish only selected
PRGs, listening WAVs and compact receipts when requested. Preserve source MOD
provenance. Parallel HVSC and graphics work is outside this task.
