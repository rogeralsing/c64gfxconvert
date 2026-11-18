# Cream SID2 drum repair — listening candidate

This candidate plays original MOD time 17.92–37.92 seconds. It is a bounded
twenty-second test, not a completed repair of the full song. The existing full
Cream player, short reference and Hyperbased artifacts remain unchanged.

- [Full mix](all.wav)
- [SID1: preserved pulse melody](sid-1.wav)
- [SID2: original drum sampling](sid-2.wav)
- [SID3: preserved sampled bass](sid-3.wav)
- [Original Amiga C4 for the same twenty seconds](original-c4.wav)
- [Runnable PRG](player.prg)
- [Normal true-drive autostart](autostart-check.json)
- [Byte-identical clean rebuild](rebuild-check.json)
- [Only declared mute bytes differ between output variants](isolation-check.json)
- [Verification and measured limits](verification.json)

SID2 now plays six reusable original C4 drum samples through the oscillator
sample-and-hold method at 1,954.86 values/s. It replaces the short, flat
triangle/noise drum approximations. The 504-cycle lane discards frequencies
above approximately 977 Hz, so hihat brightness remains limited. This has not
received listening approval. Original C1 remains omitted in this interval.

SID1 keeps the same pulse, sustain, note values and musical event phases.
SID3 retains every approved sample code and its 126-cycle clock. The first
native latch is cycle 2,300,170, matching the earlier actual Cream capture.
The new COPY32 startup guard leaves space for its largest block; the original
241 threshold could wrap and overwrite unread startup values for long drums.

All five output/mute variants pass all 156,389 SID3 sample codes, all 39,097
SID2 inputs and global sample-clock phases, all SID1 notes and shutdown.
Every ring read follows the correct producer generation. The CPU maximum NMI
is 124 cycles; minimum foreground margin is
3050 cycles. Ring write-to-read margin is
85764 cycles. No late buffers occur.

The four WAVs are independent full-workload VICE recordings at mono 22,050 Hz.
They use one common export gain, 5.947112, reduced uniformly to prevent
clipping from the stronger drum signal. Hardware SID1/SID3 levels did not change.
No EQ, host mixing, dynamics, time alignment or control subtraction is applied.

Actual SID1/SID3 solo comparisons retain their raw startup difference of about
104 PCM16 LSB peak and less than 1.5 LSB RMS at fixed comparison gain 8. The
raw peak is not within the 96 LSB capture-noise bound. After 45 ms it is below
24 LSB. An independent muted-control comparison attributes the common startup
settling; analysis residuals are below 65 LSB peak and 1 LSB RMS. This analysis
never changes a listening file. New WAVs are not claimed byte-identical to the
approved ones.

Build from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --sid2-repair
```

Normal VICE true-drive D64 autostart also passes the complete musical trace.
All five output variants reproduce byte for byte in a fresh build directory.
