# Cream of the Earth

Romeo Knight / Red Sector Inc. The full arrangement plays the complete
4:01.92 source timeline. Two SID voices use native synthesis; one reads reused
samples with a fractional cursor. It runs on an unexpanded C64.

## Listen and run

- [Full mix](full-linus-mix/all.wav)
- [Full SID1](full-linus-mix/sid-1.wav)
- [Full SID2](full-linus-mix/sid-2.wav)
- [Full SID3: Linus-style samples](full-linus-mix/sid-3.wav)
- [Full runnable PRG](full-linus-mix/player.prg)
- [Measurements and source routing](full-linus-mix/verification.json)
- [Omitted passages](full-linus-mix/coverage.json)
- [Protected passage audio check](full-linus-mix/audio-reference-check.json)

Original C3 uses SID1. SID2 primarily follows C4; the sampled voice primarily
follows C2. The introduction also assigns C1 where specified. C1 is otherwise
omitted, and quiet gaps are not filled automatically. Later chord instruments
use arpeggios; ordinary SID volume slides are simplified to on/off. PCM gains
and the four held pitch changes retain their native cursor state.

Build from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --full
```

Use PAL, reSID, MOS8580 + digiboost and resampling method 2. The PRG blanks the screen
while playing. Recording uses mono 22,050 Hz; native sampling runs at 7,819.43 values/s.
Master volume is constant during music. The WAVs use actual independent VICE
captures, a clock-based crop, DC removal and one common constant listening gain.
No host mixing, EQ, timing adjustment or dynamics are applied.

## Preserved passage

The [26.88-second mix](linus-mix/all.wav), its
[PRG](linus-mix/player.prg), three solo WAVs and the immutable
[approved reference](../../references/cream/reference.wav) remain unchanged.
This is original MOD time 17.92–44.80. Omit `--full` only when explicitly
rebuilding that bounded passage. Its [verification](linus-mix/verification.json)
retains the earlier measurements.

The full player preserves the approved instrument data, AD `$00`, SR `$10`
and continuous GATE policy. Its real-audio gate checks that interval at the
fixed source clock position within the complete performance. This does not
claim the full performance is byte-identical to an isolated recording.

Instrument recipes live in `../../native_instruments/cream/`. Full playback
stores reused source/gain banks rather than a separate expanded bank per pitch.
The shared decoder and NMI remain the same as Hyperbased's; the full Cream
producer replaces unused triangle work with direct Q8 reading and gain lookup.
Digital checks and audio metrics do not replace listening acceptance.
