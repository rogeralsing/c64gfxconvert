# Melody-first checks

Original melody channels alone through SID voice 3. Both ordinary SID voices rest; the other three MOD channels are omitted. Each actual VICE recording lasts 20.00005 s. Global Trash is approved by the user; the two new solos await listening. These do not replace the rejected hybrid previews.

| Song | Original channel | Source passage | PRG bytes | Volume error /64 | Minimum foreground slack cycles | Listening |
| --- | --- | --- | --- | --- | --- | --- |
| global-trash | 3 | 68.96–88.96 s | 19449 | [0, 0] | 376 | accepted |
| stardust-memories | 2 | 61.20–81.20 s | 41920 | [-1, 2] | 61 | unreviewed |
| desert-dream-1 | 3 | 94.44–114.44 s | 30128 | [-1, 1] | 113 | unreviewed |

Each song directory contains player.prg, original-melody.wav, melody-check.json, player-check.json and budget/cpu-budget.json. The named <slug>-melody.wav files are actual C64 recordings. Original-melody.wav is a separate source-channel reference, never mixed into C64 audio.

All three native runs verified all 156,389 sample values, every 126-cycle interval, 6,000 ordinary-voice writes and zero underruns. The separate audio runs also finished without underruns. PAL/reSID/MOS8580 + digiboost, resampling 2, mono 22,050-Hz recording; source playback 7,819.43 values/s.

Stardust uses volume quantum 4; Desert uses quantum 3. Each source waveform keeps its eight-bit bank data and declared original resampling. Lossless loop rotation changes stored loop geometry to remove expensive partial-page end checks; the independently modeled sample stream is byte-identical before and after rotation. No runtime or NMI instructions changed. See preparation.lossless_loop_alignment in each detailed report.

CPU margins apply only to these complete solos; new accompaniment and source sections need a new native deadline check. Listening files use only clock-anchored cropping, DC removal and constant gain8, with no EQ, limiting, time alignment or hostmixing.
