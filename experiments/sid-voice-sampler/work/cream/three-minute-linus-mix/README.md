# Cream of the Earth — selected 3:08.42 arrangement

This is the complete selected arrangement for an unexpanded 64 KiB C64.
New notes stop at the source pattern boundary at 188.16 seconds, where SID1
already rests. Existing bass and drums drain until 188.42 seconds.

- [All three voices](all.wav)
- [SID1: native melody programs](sid-1.wav)
- [SID2: original sampled percussion](sid-2.wav)
- [SID3: original sampled bass and other C2 instruments](sid-3.wav)
- [Runnable PRG](player.prg)
- [Full verification and CPU/memory measurements](verification.json)
- [Preserved melody and bass audio](preserved-parts-check.json)
- [Explicit source-channel omissions](coverage.json)
- [Clean rebuild](rebuild-check.json)

SID2 uses the Linus-style oscillator method at 1,954.86 values/s; SID3 uses
the same principle at 7,819.43 values/s. SID1 retains the earlier native pulse
and arpeggio programs. C1's instruments 10/11 are included in the introduction;
later C1 chords remain omitted. SID2's limited bandwidth reduces hihat
brightness. The introduction on SID2 now uses actual instrument 10 samples.
This is not an exact four-channel Amiga replay.

No REU, GeoRAM, external streaming or flattened song recording is used.
Instrument samples are reused. Position tables are generated in ordinary C64
RAM before playback; the compressed main score uses 512 bytes of history.
Read [the implementation](../../../CREAM-THREE-MINUTE.md) for the memory layout
and lossless CPU optimizations. The PRG is 51,201 bytes.

All five output/mute variants pass every one of 1,473,337 SID3 inputs and
368,334 SID2 inputs, all global register phases and every SID1 note. All
9,421 buffers finish without a late buffer. Full ring-generation tracing has
no stale reads or overwrites; minimum write-to-read margin is
36,853 cycles. Maximum NMI is
125 cycles; minimum foreground margin is
699 cycles. This does not establish
capacity for another sample channel or a visible display.

Normal true-drive D64 autostart passes, including restored native RAM and the
complete musical trace. All five native and packaged PRGs rebuild byte for
byte in a fresh temporary directory. Original full/short Cream, the drum
audition, Hyperbased and protected references remain unchanged.

Each WAV is an independent actual VICE recording, mono 22,050 Hz and
4,154,662 frames. All use one common gain, 5.101806. Only a native-clock crop,
DC removal and that constant gain are applied. No EQ, host mixing, fitted
alignment, dynamics or noise removal is used.

Actual SID1/SID3 music passes the unchanged .98–1.02 window-level and .99
spectral bounds against the previous full recording. Declared SID1 rests
retain the same per-window level check and use pooled band power for the .99
spectral check. The reference's own independent noise-floor windows fail a
per-200-ms spectral comparison, so they are not treated as instruments.
No listening samples are changed by this analysis.

Use PAL, reSID, MOS8580 + digiboost and resampling method 2. Screen blanking
is intentional. Physical SID operation and screen-on playback remain unverified.

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --full
```
