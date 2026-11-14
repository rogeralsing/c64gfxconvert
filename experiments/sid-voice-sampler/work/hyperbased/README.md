# Hyperbased working folder

The active arrangement ends at exactly 3:00, as selected by the user. Keep original
MOD channels separate and compare complete musical phrases before changing
voices. Read [the full-length implementation and limits](../../FULL-LENGTH.md).

## Complete native C64 performance

- [All three SID voices](full-linus-mix/all.wav)
- [SID 1](full-linus-mix/sid-1.wav)
- [SID 2](full-linus-mix/sid-2.wav)
- [SID 3: PCM and software bass](full-linus-mix/sid-3.wav)
- [Runnable PRG](full-linus-mix/player.prg)
- [Complete verification](full-linus-mix/verification.json)

Two ordinary SID voices execute native programs, and SID3 plays reused PCM
mixed with software bass. Physical source roles change with the passage. The
selected three-minute interval has no active source-part allocation omissions.
Later source sections are excluded. SID timbres and dynamics remain
approximations rather than an exact Amiga replay.

Build through the single entry point with `--full`. The sections below describe
the preserved twenty-second reference and its listening decisions.

## Preserved twenty-second performance

- [All three SID voices](linus-mix/all.wav)
- [SID 1: original channel 2](linus-mix/sid-1.wav)
- [SID 2: original channel 3 samples](linus-mix/sid-2.wav)
- [SID 3: channel 1 triangle bass plus channel 4 drums](linus-mix/sid-3.wav)
- [Runnable PRG](linus-mix/player.prg)
- [Complete verification](linus-mix/verification.json)

SID 2 uses reusable instrument/pitch/gain sample variants at 1.95 kHz, replacing the rejected
flute approximation. SID 3 mixes bass and drums on C64 at 7.82 kHz. SID 1 keeps
the accepted pulse part. All four source parts have assigned outputs; this is
not a full-song or exact four-channel MOD conversion.

The WAVs are independent VICE recordings with a shared time origin and gain 8.
There is no host mixing, EQ, alignment or noise removal. All buffers and both
sample clocks pass complete digital verification. The all-muted output matches
a static-SID control. Physical SID and screen-on operation remain unverified.

## Original Amiga channels

The following independent libopenmpt renders retain common settings, gain and
silence. These are decoder outputs, not physical Amiga recordings.

| Source | Full 5:33.84 | First twenty seconds |
| --- | --- | --- |
| Complete MOD | [WAV](amiga-original.wav) | [WAV](amiga-20s/amiga-original.wav) |
| Channel 1 | [WAV](amiga-channel-1.wav) | [WAV](amiga-20s/amiga-channel-1.wav) |
| Channel 2 | [WAV](amiga-channel-2.wav) | [WAV](amiga-20s/amiga-channel-2.wav) |
| Channel 3 | [WAV](amiga-channel-3.wav) | [WAV](amiga-20s/amiga-channel-3.wav) |
| Channel 4 | [WAV](amiga-channel-4.wav) | [WAV](amiga-20s/amiga-channel-4.wav) |

[Source analysis](channel-map.json) retains the full instrument inventories and
original note events. [Original-channel receipt](original-channels.json) pins
the source and isolation check. Rebuild these source WAVs with
`render_original_channels.py`; that check never host-mixes a listening file.

## Listening decisions and reproducibility

The user accepted the earlier isolated SID 1 and SID 3 performances and the
short sampled C3 recovery reference. [Listening decisions](listening-decisions.json)
preserve their identities. Accepted original solo WAVs are immutable under
[references/hyperbased-stems](../../references/hyperbased-stems/).

New SID 1/SID 3 register sequences are preserved exactly under a calibrated
startup shift. Their captured WAVs differ by at most 80 PCM16 LSB, with RMS
differences 21.978 and 13.859 LSB at gain 8. They are not byte-identical files.
The new lower-rate SID 2 and complete mix still need listening assessment.

Build, capture and measure through the sole supported command:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py
```

COPY32 and a suffix lookup remove per-sample pitch arithmetic. A native integer
cursor preserves note position and gains. The optimized complete SID trace and
all four WAVs are byte-identical to the preceding player. See the
[CPU profile](../../CPU-PROFILE.md).

A fresh build needs source assets, not older generated scores. Its PRG and full
mix WAV reproduce byte for byte. Normal VICE autostart also passed. See
[technical details](../../DUAL-SAMPLER.md), [CPU budget](linus-mix/budget/cpu-budget.json),
[RAM budget](linus-mix/memory-budget.json), [rebuild proof](linus-mix/rebuild-check.json)
and [autostart proof](linus-mix/autostart-check.json).
