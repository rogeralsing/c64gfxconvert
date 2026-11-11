# Sampling through an ordinary SID voice

Standalone research experiment based on the SounDemoN method explained by
[Linus Akesson in Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php).
It writes only this directory and does not change the MOD converter or the
parallel HVSC hybrid work.

## Run

From the repository root, using the existing pinned music environment:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build.py --capture
```

Requires the existing music requirements, KickAssembler at
`~/.local/bin/kickass`, and VICE at `/opt/homebrew/bin/x64sc`.
The build imports the shared `mod-hybrid/vice_profile.py`: PAL, reSID,
MOS8580 + digiboost, resampling method 2, mono 22,050 Hz recording.

Outputs under `results/`:

- `player.prg`: resident demonstration, about 6.38 seconds.
- `voice-sampler.wav`: actual VICE performance, first the guitar alone and then
  the same phrase with two ordinary SID synthesizer voices.
- `guitar-voice.wav` and `guitar-and-sid.wav`: separate crops of those sections.
- `report.json`: build identities and completed measurements.
- `probe-check.json`: native oscillator transfer measurement.
- `player/player-check.json`: native clock, input and ordinary-voice checks.
- `waveform-check.json`: solo audio compared with its intended PCM input.

Interactive playback:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --play --prg experiments/sid-voice-sampler/results/player.prg
```

The display is disabled. The program stops in a loop after its silent tail.

## What it demonstrates

Voice 3 is an oscillator-based sample-and-hold. Its waveform is briefly enabled
to latch the triangle value, then disabled to retain that level. Resetting the
phase and choosing the frequency controls the next level. The master volume
remains 15 throughout playback; no sample values are written to `$D418`.

An NMI every 126 PAL cycles supplies **7,819.43 sample values/second**. A clock
slide removes instruction-boundary interrupt jitter before each latch. Two
156-byte buffers let foreground code compute the next frame of audio while
the interrupt plays the current frame. These buffers are working memory, not
stored recordings of the whole piece.

The C64 computes fractional sample cursors for four pitches of the same short
guitar recording. The bank is eight-bit data stored once, and the eight-note
score reuses it. The second four notes add a triangle bass and a pulse harmony
on SID voices 1 and 2. Their quiet envelopes settle before the waveforms are
enabled, and their state is committed when the corresponding PCM buffer
becomes active.

The guitar is the existing CC0 FreePats nylon-string A3 asset, not an HVSC
instrument or a SID approximation. Its source, preparation, original archive
and hashes are retained in `../sid-inverse/assets/manifest.json`; this build
copies that provenance into `results/input.json` and checks the input hash.

## Proof and limits

The independent native probe tries all 256 input codes and saves voice 3's
`OSC3` readback. More than 16 distinct monotonic levels demonstrate that the
signal is not restricted to the ordinary four-bit volume DAC. The readback is
only eight bits; its distinct-level count is **not** a physical-chip effective
resolution measurement.

The musical proof checks every input frequency code against a separate Python
cursor model, every latch interval, all six ordinary-voice frequency/control
writes per frame, generated buffers, and underruns. The audio run must also
complete all buffers without underruns. It uses a fresh matching VICE run;
register-dump output is never substituted for emulator audio.

Audio delivery uses only a clock-anchored crop, DC removal and one constant
gain. The solo diagnostic compares spectra on their native time axis and
reports waveform agreement with one analysis-only bounded analog latency.
No alignment, EQ, compression, host SID mixing or time stretching is applied
to the delivered recordings.

This is an emulator-verified research prototype. It has not been tested on a
physical SID. Screen-on operation, multiple mixed sample tracks, a complete MOD
player, and fitting a short synthesized instrument program are separate work.
The guitar here remains sampled data; the new mechanism changes how SID emits
that data and leaves two oscillator voices available for synthesis.

## Further reading

- [Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php):
  oscillator sample-and-hold, buffering, jitter, badlines and CPU scheduling.
  Our first proof keeps the display off and uses a simpler clock slide; it
  does not reproduce the article's final distributed-jitter implementation.
- [A Mind Is Born](https://linusakesson.net/scene/a-mind-is-born/): a different
  avenue, compact procedural SID music. It explains how small scripts,
  frequency changes, waveform combinations and envelopes create evolving
  synthesized sounds without storing their audio waveform.
- [SounDemon's Vicious SID explanation](https://codebase64.c64.org/doku.php?id=base:vicious_sid_demo_routine_explained):
  original background and one/two-oscillator variants of sample playback.
