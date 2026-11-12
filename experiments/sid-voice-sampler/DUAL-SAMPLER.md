# Hyperbased: two sampled SID voices and one ordinary voice

The current proof covers the first twenty seconds of Hyperbased by Firefox
and Tip / Phenomena. All four original MOD parts have an assigned output:

| Physical SID voice | Original MOD channel | Current sound |
| --- | --- | --- |
| SID 1 | C2 | Existing pulse-wave approximation |
| SID 2 | C3 | Original instruments 8, 9, 10 and 11, played as samples |
| SID 3 | C1 and C4 | Software triangle bass plus original sampled drums |

SID 1 and SID 3 retain the previously accepted arrangement. SID 2 now uses
the original sampled instruments. Its lower playback bandwidth is an explicit
tradeoff; it is not identical to the earlier 7.82-kHz sampled C3 recovery.
Listening acceptance of this new combination remains separate from its digital
checks. Original MOD provenance is recorded in
[hyperbased.source.json](../mod-hybrid/sources/hyperbased.source.json).

## Signal generation

The oscillator prepares an amplitude, a brief triangle-wave enable transfers
it to the output, and the disabled waveform approximately retains that level
until the next transfer. This is the SounDemoN method described in
[Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php).
It uses normal SID voices; sample values are not written to master volume
register `$D418`.

SID 3 receives a new value every **126 PAL cycles**, or **7,819.43 values/s**.
The host compiler turns the approved software triangle oscillator into reusable
run programs. Each command supplies a triangle level and its ending position;
equal pitch, volume, phase and buffer length reuse the same program. The C64 interprets
these commands and adds the independent drum sample for every output value.
Neither the sum nor a complete recorded channel is stored.

The drum assets retain the original instrument, pitch, gain and sample position.
Shared windows remove unused prefixes, tails and page padding. The bass/drum
sum stays within unsigned-byte headroom: no wrapping, clipping or amplitude compression
is used.

SID 2 receives values every **504 PAL cycles**, or **1,954.86 values/s**. Its
reusable original-instrument windows have gain applied before playback. The
C64 retains the fractional pitch cursor across frames and gain changes, resets
it on actual note triggers, and advances it while an active source is muted.
Prepared active-prefix counts stop each one-shot at its source boundary.
The source loop metadata is retained, but no loop wrap is exercised in these
twenty seconds.

SID 2's frequency low byte remains zero. A virtual eight-bit input value `v`
becomes frequency high byte `round(v × 105 / 249)`, with ties rounded to even.
The measured transfer window supplies the coefficient 249; 105 is the reference
coefficient. This adds at most **1.1714 virtual input codes** of quantization
error in the prepared stream. It is not a measurement of analog bit resolution
on physical hardware.

## Clocks and buffers

Both sampled outputs use one continuous 126-cycle interrupt clock. SID 2 uses
its global modulo-four phase; the phase is never restarted at a tracker frame.
The first musical SID 2 latch is a separately primed neutral value. Subsequent ring
values correspond to SID 3 indices 4, 8, 12 and so on.

The 50-Hz score uses alternating 156/157-value SID 3 buffers to preserve its
original time axis. The NMI activates a completed buffer automatically. C3
production runs in bounded foreground chunks and supplies a 256-byte ring.
Register-stream checks alone cannot detect repeated stale silence, so a
separate instruction trace checks that every ring read follows its matching
producer write.

The sampled-voice timings, relative to each SID 3 latch, are:

| Output | Global phase | Register events |
| --- | --- | --- |
| SID 3 | Every interrupt | Triangle on +0, off +6, TEST +12, frequency high +20, release +26 |
| SID 2 | Index modulo 4 = 0 | Triangle on +35, TEST +41 |
| SID 2 | Index modulo 4 = 2 | Frequency high +37, release +43 |

After startup, SID 1 receives its frequency/control writes at +53, +60 and +67 in the
first interrupt of each newly active score frame. Master volume stays at 15
during music. Stem isolation may set SID's voice-3-off bit once at startup;
that does not change the volume nibble or the emulator profile.

## Build and verification

The only public command is in [README.md](README.md).
[build_linus_mix.py](build_linus_mix.py) calls
[native_playback.py](native_playback.py); the complete runtime is
[linus-mix-player.asm](linus-mix-player.asm). Data preparation lives under
[native_instruments/](native_instruments/), beginning with
[prepare_music.py](native_instruments/prepare_music.py).

A fresh build derives its baseline, globally phased C3 score, reusable gain
windows and linked data from source assets. It does not require historical
generated scores. The current assembled PRG is **48,138 bytes**. A clean rebuild
reproduced both the PRG and current full-mix WAV byte for byte. The generated
[verification receipt](work/hyperbased/linus-mix/verification.json) records its
actual identity and complete-run measurements.

The verified bounded stream contains:

- **156,389** SID 3 mixed input values with 126-cycle latch intervals.
- **39,097** SID 2 ring values and **one startup-neutral latch**, with 504-cycle
  latch intervals.
- **3,000** ordered SID 1 frequency/control writes.

The complete native run checks every value and register slot, buffer
completion, the causal ring read/write sequence, constant master volume and
CPU deadlines. The current measurement gives:

| Measurement | Result |
| --- | ---: |
| NMI CPU share | 72.43% |
| Longest complete NMI | 125 CPU cycles |
| SID 3 foreground fill | 2,507–4,364 CPU cycles per buffer |
| Minimum foreground deadline margin | 543 CPU cycles |
| Minimum NMI pointer-commit margin | 13 CPU cycles |
| C3 production including background control | 38.13 CPU cycles per value |
| Minimum C3 producer-write to consumer-read margin | 63,577 PAL cycles, 64.53 ms |
| Maximum occupied C3 ring entries | 250 of 256 |
| Independent instrument data and score | 41,841 bytes |
| Loaded PRG payload, excluding its two-byte header | 48,136 bytes |
| Conservative RAM budget, including stack | 49,903 bytes |

These are whole-phrase measurements with the display disabled, not a budget
for screen-on playback.

Every listening WAV is its own complete VICE capture. The full mix is not
assembled from stems on the host. All files currently use one constant gain
of 8; the full-mix peak is 0.98775 of full scale. The all-muted signal matches
an independent static-SID control exactly
under this profile; this checks leakage with the outputs disabled.

## Capture comparison and limits

SID 1 and SID 3 retain their accepted register sequences, including startup
and note events, under one constant 54,736-cycle time-origin shift. Their new
WAVs are not byte-identical to the old recordings. At reference gain 8, the
measured PCM16 differences are:

| Stem | Maximum difference, PCM16 LSB | RMS difference, PCM16 LSB |
| --- | ---: | ---: |
| SID 1 | 80 | 21.978 |
| SID 3 | 80 | 13.859 |

The comparison retains the original time axis and applies no alignment or
audio correction. The cause of these small capture differences has not been
isolated. The immutable earlier stems are retained under
[references/hyperbased-stems/](references/hyperbased-stems/).

The shared profile is PAL, reSID, MOS8580 + digiboost, resampling method 2 and
mono **22,050-Hz recording**. That recording rate is distinct from either C64
output rate. Listening files use only a clock-anchored crop, DC removal and
one shared constant gain. EQ, alignment, pitch correction, dynamics and host
mixing are not part of the listening pipeline.

The display is disabled. Screen-on timing and physical SID playback have not
been verified. Exact emulator register timing does not establish physical
waveform fidelity or perceived sound quality.

This is neither a full-song Hyperbased conversion nor a general four-channel
MOD player. C1 and C2 remain synthesis approximations, and C3 loses bandwidth
at its lower sample rate. Future passages need explicit instrument, lifetime,
CPU and RAM checks before extending this proof.
