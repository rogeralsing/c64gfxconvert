# Canonical C64 music path

Run every shell command through `rtk`. The user selected the Linus-style native
mixer on 2026-11-12 and explicitly requested removal of older variants so work
does not fall back to them. This direction supersedes the earlier experiment
entry points and audition workflows.

## One entry point

Use only this build command from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py
```

`linus-mix-player.asm` is the runtime. Its C64 foreground loop mixes a software
triangle bass with reusable fixed-rate drum samples; SID voice 3 emits the sum
using the SounDemoN sample-and-hold mechanism. Two ordinary SID voices remain
available. Four logical musical parts can therefore share three physical SID
voices. The current mixer is not two freely pitched sampled-instrument players.

Do not restore the older `$D418`/PCM4 path, a single-sample-only player, an old
audition generator, or a different SID profile as a fallback. Extend the native
mixer deliberately when it cannot yet express an arrangement. State the missing
capability instead of silently changing the sound architecture.

## Musical decisions

- Keep all four original MOD channels separate in the song's working folder.
  Preserve their common time origin and gain; do not normalize them separately.
- Listen to complete phrases and identify their roles before assigning voices.
  Channels can change roles during a song. Select the prominent musical parts
  by sequence, not a fixed channel label or encoding convenience.
- Preserve note timing, pitch, triggers, gain changes and sample lifetimes.
  Report every omitted channel or passage and every synthesis approximation.
- Do not turn an ambiguous pitched instrument into noise, a kick, a guessed
  octave or an invented chord arpeggio to make it fit. Validate its isolated
  source phrase before proposing a replacement.
- Reuse instrument data and C64 synthesis. Never replace a song with a flattened
  host recording. A prominence detector remains future work; do not claim one
  exists or treat energy alone as musical importance.

The current Hyperbased proof is exactly its first 20 seconds: original channel
1's software triangle bass plus channel 4's sampled drums on SID voice 3,
channel 2's pulse approximation on SID voice 1, and SID voice 2 resting.
Original channel 3 remains unselected pending listening. Do not call this a
full song or an exact four-channel MOD conversion. A separate four-logical-part
runtime probe proves technical capacity, not that musical arrangement.

## Signal path and proof

Keep PAL, reSID, MOS8580 + digiboost, resampling method 2, and mono 22,050-Hz
recording. Use `../mod-hybrid/vice_profile.py`. The C64 sample clock is 126 PAL
cycles, or 7,819.43 values/s; the recording rate is a different quantity.
Master volume stays constant during music. Do not send sample values to `$D418`.

Mix on the C64. Retain independent bass and drum inputs, linear headroom and
the native mixed output comparison. Verify every input code, every 126-cycle
latch gap, all ordinary SID writes, terminal counters and zero underruns in
actual VICE. Measure CPU and RAM over the complete delivered phrase after
runtime or arrangement changes. A short probe does not prove a longer run.

The current 20-second proof checks 156,389 mixed values and 6,000 SID writes.
Minimum measured foreground slack is 110 cycles per buffer. Screen-on operation
and physical SID fidelity have not been verified. Digital correctness does not
establish acceptable sound or physical analog bit resolution.

Deliver a runnable PRG, actual VICE WAV and compact measurements. Listening
files may use only a clock-anchored crop, DC removal and one constant gain.
Do not hide faults with EQ, limiting, alignment, pitch correction, dynamics or
host mixing. Distinguish listening approval from measured correctness.

## References and ownership

Approved Cream and Hyperbased WAV/PRG files are retained only under
`references/cream/` and `references/hyperbased/`, with identities in
`references/manifest.json`. Preserve those bytes as listening references. They
are not build instructions or alternate player implementations.

Keep generated instrument pages, scores, logs, raw captures and traces out of
Git. Publish only selected listening files, runnable programs and compact
receipts when requested. Preserve source MOD provenance.

Parallel HVSC and graphics work is outside this task. Do not include or rewrite
it automatically during cleanup, commits or publication.
