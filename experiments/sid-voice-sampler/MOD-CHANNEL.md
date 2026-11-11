# A real MOD channel through SID voice 3

This is the next bounded experiment after the published CC0-guitar reference.
It plays **Cream of the Earth, channel 2, source 17.92–44.80 seconds**: three
complete patterns, 1,344 tracker ticks, 152 note starts and three reusable
one-shot instruments. The original song is by Romeo Knight / Red Sector Inc.
Its existing source receipt records the download URL and SHA256.

## Run

From the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_mod_channel.py --capture --budget
```

Results are written only under `results/mod-channel/`:

- `player.prg`: runnable resident C64 program.
- `mod-channel.wav`: actual VICE audio of the complete isolated channel.
- `verification.json`: input, native playback, audio, memory and CPU proofs.
- `budget/cpu-budget.json`: compact non-invasive CPU measurements.
- `input.json`: source range, instrument banks, pitch rounding and timing.
- `waveform-check.json`: objective waveform/spectral diagnostics.

The published `player.asm`, `probe.asm`, `build.py`, PRG and WAV remain unchanged.
The new builder checks their recorded identities before and after its work.
It reads the existing MOD parser/timeline and playback profile; it does not
change or run the parallel HVSC converter or graphics work.

## Why this channel

The reference NMI already consumes 72.71% of the CPU. Its remaining worst-case
rendering margin is too small for a naive eight-cycle volume lookup on every
sample, let alone another mixed sampled voice.

This channel needs no such lookup. Instruments 7, 8 and 9 always use MOD volume
41, 48 and 28 respectively. The builder applies those constant levels once to
their reusable eight-bit banks. The selected patterns require no loops,
offsets, active volume changes or unsupported commands. The builder rejects
such states rather than discarding them.

| Instrument | Source bytes | Decimation | Stored bank, with neutral padding |
| --- | ---: | ---: | ---: |
| 7 | 1,058 | 2 | 768 B |
| 8 | 2,468 | 3 | 1,024 B |
| 9 | 2,892 | 3 | 1,024 B |
| Total | 6,418 | | **2,816 B** |

The score stores five bytes per tracker tick: pitch step, retrigger, instrument
start/end pages and working-buffer start. It occupies 6,720 bytes. The C64
computes the fractional sample cursor while filling the next working buffer;
the program does not store a 210,186-byte recording of the whole passage.

## Timing and budget

The output clock remains exactly **126 PAL cycles**, or **7,819.428571 values/s**.
The recording rate is separately **22,050 Hz mono**. Playback and capture use
PAL / reSID / MOS8580 + digiboost / resampling method 2.

The reference's fixed 156-value buffers run at 50.1245 Hz. That is suitable for
its own short score, but would accelerate a 50-Hz MOD by 0.249%. This experiment
instead rounds cumulative tracker time onto the fixed sample clock:

- 822 buffers contain 156 values; 522 contain 157.
- Total: 210,186 values, 26.879969307 seconds.
- End-time error against the 26.88-second source phrase: −30.69 microseconds.
- Eight-bit cursor-step rounding introduces −4.44 to +7.35 cents across the
  seven source periods. This is disclosed pitch quantization, not exact Paula
  playback.

The two working pages reserve 512 bytes; at most 314 values are active. The
NMI uses the reference's 92-byte instruction sequence, except the relocated
address of its final jump. The foreground preloads the next buffer address in
X/Y before waiting for the boundary. Only two stores occupy the critical
pointer switch: eight cycles instead of fourteen. The NMI preserves X/Y.

Measured over the complete final program:

| Measurement | Result |
| --- | ---: |
| NMI CPU share | 72.82% |
| Foreground fill cost | 4,480–4,828 cycles per buffer |
| Minimum buffer-deadline margin | 1,594 wall cycles / 425 available foreground cycles |
| Pointer-switch cost | 8 cycles |
| Minimum pointer-commit margin before next NMI | 8 cycles |
| Interrupted pointer switches | 0 |
| Program size | 15,937 B |
| Program end | `$4640` |
| Contiguous space before `$D000` | 35,264 B |

`measure_budget.py` adds VICE monitor tracepoints, not instrumentation code to
the player. It measures each fill, NMI and boundary over the complete phrase,
and independently checks that profiling preserves every 126-cycle latch gap.
The deadline margin includes time spent in NMI; only the foreground-cycle
figure represents additional work the CPU could execute there.

## Evidence and limits

Native VICE verification checks every generated input value against a separate
logical cursor model, all latch intervals, all 1,344 completed buffers and zero
underruns. The actual audio run must also complete every buffer without misses.
There are no `$D418` writes during the music stream. SID voices 1 and 2 remain
silent in this test, keeping the sampled channel easy to assess by itself.

A clean build and fresh audio capture in a separate output directory produced
byte-identical PRG, WAV and expected input bytes. A negative control with one
corrupted expected value was rejected with exactly one mismatch. These compact
receipts are retained in `verification.json` and `negative-control.json`.

The complete recording agrees with its intended digital input: whole-phrase
spectral cosine is 0.9968 in the 50–3,500 Hz band. The original-source-channel
comparison is 0.9878. These are diagnostics, not perceptual acceptance. Only
waveform analysis estimates one bounded global analog-path latency; that
estimate is never applied to a listening file.

Delivered audio uses only a clock-anchored crop, DC removal and a constant gain.
There is no EQ, host mixing, dynamics, time shifting or time stretching. This
does not measure effective analog bit depth on a physical SID. Screen-on
operation, additional mixed sample channels and full MOD integration remain
unverified. The separate [MOD hybrid experiment](MOD-HYBRID.md) now adds two
ordinary SID voices to this exact sampled input, while preserving this solo.

Mechanism: [Linus Akesson's Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php).
