# Hyperbased: native C64 arrangement, 3:00

The user-selected ending is exactly 180 seconds. The self-contained PRG is 51,201 bytes and runs in
stock C64 RAM. Two native SID instrument programs accompany Linus-style
oscillator sampling mixed with software triangle bass on C64.

- [Complete performance](all.wav)
- [SID 1](sid-1.wav)
- [SID 2](sid-2.wav)
- [SID 3: sampling and software bass](sid-3.wav)
- [Runnable player](player.prg)
- [Verification, CPU, memory and audio receipts](verification.json)
- [Every omitted passage](coverage.json)
- [Clean rebuild of all five program variants](rebuild-check.json)
- [SID1 audio against the approved reference](sid1-reference-check.json)
- [Scope: other channel data and banks unchanged](repair-scope-check.json)
- [True-drive startup, restored RAM and unchanged music](startup-check.json)

Actual VICE playback checks all 1,407,497 sample values/prefixes at exactly 126
PAL cycles, ordinary SID writes, constant master volume and every consuming
buffer activation. All register and WAV runs complete with zero late buffers.
All 122 approved SID1 audio passages pass the independent reference check.
True-drive D64 autostart passes for the complete three minutes. Before playback,
52,766 native RAM bytes match the original image exactly. A small startup loader
stages high code below I/O, then restores its original addresses. The previous
flat PRG loaded padding across active hardware registers; mode1 RAM injection
and mode0 virtual-filesystem traps did not test that loading path.
The full all-muted recording is identical to the
independently static SID control after the same permitted crop/DC removal.

This startup repair leaves all four existing WAV files byte-identical. Their
CPU, deadline and recording receipts belong to the unchanged native music image.
A separate actual capture from the packaged SID1 player passes all 122 approved
audio passages. No instruments, notes, envelopes or playback code changed.
The screen remains blank during music by design.

The fixed profile is PAL, reSID, MOS8580 + digiboost, resampling 2, mono 22,050 Hz.
Each listening WAV has exactly 3,969,000 frames: 3:00. All four use the same gain,
3.6308204724132565. They are independently recorded performances; no host
mixing, EQ, timing adjustment or dynamics are applied.

This arrangement uses SID timbre approximations and quantized PCM gain. There
are no active source-part allocation omissions before the selected three-minute
ending. The longer version's omitted sections occur after that point. The
earlier [twenty-second reference](../linus-mix/all.wav) is unchanged.

Rebuild from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --full
```

Read [implementation details](../../../FULL-LENGTH.md) before changing native
instrument programs, note decoding, buffering or source routing.
