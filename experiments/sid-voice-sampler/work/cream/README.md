# Cream of the Earth

Romeo Knight / Red Sector Inc. The active arrangement plays **3:08.42** on an
unexpanded 64 KiB C64. It combines original samples on SID2/SID3 with the
native SID1 repair candidate. **Listening assessment is pending.**

New notes stop at the source pattern boundary at **3:08.16**, where SID1 is
already resting. Existing sounds drain before the player stops.

## Listen and run

- [Mix](sid1-repair/all.wav)
- [SID1](sid1-repair/sid-1.wav)
- [SID2](sid1-repair/sid-2.wav)
- [SID3](sid1-repair/sid-3.wav)
- [Runnable PRG](sid1-repair/player.prg)
- [Verification and measurements](sid1-repair/verification.json)
- [Instrument allocation and omissions](sid1-repair/coverage.json)
- [Implementation and limits](../../CREAM-THREE-MINUTE.md)

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --full
```

Use PAL, reSID, MOS8580 + digiboost and resampling method 2. Screen blanking is
intentional. The recording rate is mono 22,050 Hz; SID3 updates at 7,819.43
values/s and SID2 at 1,954.86. Master volume stays constant during the music.
No external memory, flattened song recording or host mixing is used.

SID1 follows C1 at 17.92–31.36 and C3 elsewhere. This restores twelve C1
triggers while omitting six sparse C3 tonic/octave triggers. Its guitar now
uses triangle+saw and hardware ADSR; GATE preparation can shorten preceding
notes by 40 ms. This approximates the source rather than reproducing its
recorded envelope, every volume slide or instrument 11's simultaneous fifth.
The reusable parameters are in
[`native_instruments/cream_sid1/voice.json`](../../native_instruments/cream_sid1/voice.json).

SID2 follows C4 and plays C1's instrument 10 in the
introduction. SID3 follows C2 and plays C1's instrument 11 in the introduction.
Both complete sampler streams and their clocks stay fixed. Later C1 chords
remain omitted. SID2 has limited hihat bandwidth. See
[the listening decisions](listening-decisions.json); technical checks do not
replace assessment of the new full mix.

## Preserved references

The [twenty-second original-drum audition](sid2-repair/README.md),
[approved 26.88-second passage](linus-mix/all.wav),
[immutable old reference](../../references/cream/reference.wav) and
[former 4:01.92 baseline](full-linus-mix/README.md) remain unchanged.
The [previous 3:08.42 build](three-minute-linus-mix/README.md) also remains
intact: its SID1 was rejected and is a diagnostic baseline. The former
4:01.92 build's synthetic SID2 was rejected. Neither is the active full build.

Omitting `--full` rebuilds only the approved original-MOD interval
17.92–44.80. `--song cream --sid2-repair` rebuilds only the later twenty-second
drum audition. Neither command completes or replaces the active three-minute
arrangement.
