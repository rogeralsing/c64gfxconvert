# Three additional MOD playback tests

The later [optimization study](../optimization/README.md) now provides complete
Hyperbased and Madness programs using lossless score compression. The memory
failures and 50-second files below describe the earlier packing format.

Listening feedback rejected the original Madness and Hyperbased comparisons:
Madness sounded chaotic, and Hyperbased lost its melody behind drums and noise.
The execution checks below passed, but they did not establish musical fidelity.
These original files remain diagnostic baselines rather than accepted results.
Follow-up work is under each song's `diagnosis/` directory.

[Revised Madness and Hyperbased comparisons](corrections/README.md) address
pre-quantization gain and excessive sample-bank filtering. They have new
actual VICE captures and remain candidates awaiting listening evaluation.

These are **50-second resident C64 programs**, using the same corrected
four-PCM player as Stardust Memories. Each original MOD track has its own
sample cursor. Instruments remain reusable samples; the programs contain no
full-song audio recording. Target: PAL C64 with MOS6581, graphics disabled.

## Listen and run

Every comparison contains **20 seconds of the independently decoded original,
0.5 seconds of silence, then 20 seconds of actual C64 output recorded in VICE**.
Both sides use seconds 30–50, with DC removal and separate constant gains to
match RMS. There is no additional EQ, limiting, timing adjustment or host-side
instrument mixing in the C64 recording.

| Song and original authors | Comparison | Verified 50-second PRG | Bytes |
| --- | --- | --- | ---: |
| [Cream of the Earth — Romeo Knight / Red Sector Inc.](https://demozoo.org/music/21557/) | [Original then C64](auditions/cream-of-the-earth-original-then-c64.wav) | [cream-of-the-earth-50s.prg](players/cream-of-the-earth-50s.prg) | 23,812 |
| [A Final Hyperbase / Enigma — Firefox and Tip / Phenomena](https://demozoo.org/music/2233/) | [Original then C64](auditions/hyperbased-original-then-c64.wav) | [hyperbased-50s.prg](players/hyperbased-50s.prg) | 31,051 |
| [4-Mat's Madness — 4-Mat / Anarchy](https://demozoo.org/music/19081/) | [Original then C64](auditions/4mats-madness-original-then-c64.wav) | [4mats-madness-50s.prg](players/4mats-madness-50s.prg) | 23,698 |

The files under `players/` are byte-identical copies of the verified builds.
The build tools retain the historical internal filename `stardust.prg` inside
each song's separate `short/c64/` directory; those files contain the new song.

## Verification and limits

Each program completes all **2,500 music ticks with zero prefetch underruns**
in both the register-dump and audio runs. All **192,431 emitted music DAC
bytes** match the independent integer model, with zero mismatches. The model
checks the sample cursors, looping, note triggers, pitch steps, volume and
final nearest rounding. Timing and exact-byte checks establish execution
correctness; they do not establish subjective audio quality.

The complete original timelines also agree with independent libopenmpt
order, pattern, row and speed observations:

| Song | Original duration | Ticks checked | Timing mismatches |
| --- | ---: | ---: | ---: |
| Cream of the Earth | 241.92 s | 12,096 | 0 |
| A Final Hyperbase | 333.84 s | 16,692 | 0 |
| 4-Mat's Madness | 407.04 s | 20,352 | 0 |

**The complete C64 versions do not fit the current resident memory layout.**
No sample fidelity was reduced to force them to fit. The current limit is
`$D000`; full build attempts ended at `$ECC9`, `$130C2` and `$E34E`, respectively.
Files under `full/c64/` are failed build evidence and are not playable releases.
Use the verified `players/*-50s.prg` files.

This remains a limited MOD converter. These tests required two narrow fixes:

- The reader now counts stored patterns across all 128 order-table entries,
  following [the ProTracker loader](https://github.com/8bitbubsy/pt2-clone/blob/master/src/modloaders/pt2_load_mod31.c#L86-L101).
  Cream contains stored patterns outside its active order list.
- The timeline accepts `E01`, disabling the Amiga LED filter. That is a no-op
  for this filter-disabled PCM backend, while its period-register semantics
  are preserved. Other `E` effects remain rejected.

Stardust's parsed source and complete timeline remain unchanged. Arrangement
metadata now uses each MOD's own title.

Space Debris was downloaded but requires unsupported sample offsets (`9xx`)
and fine volume slides (`EAx`/`EBx`), so it has no playable result in this batch.
The tested Echoing variant has unexplained trailing data and remains rejected
by the strict reader. Neither rejection was bypassed.

## Receipts and reproduction

`manifest.json` records the source, program and audition hashes and all three
results. Each `short/vice/` directory contains the raw VICE WAV, processed
capture, runtime counters and register trace. Each `short/reference/` directory
contains the independent expected DAC stream and `trace-check.json`.
The comparison JSON files also verify the processed C64 WAV against the raw
VICE recording and bind the trace check to the current arrangement.

Exact download URLs, source hashes and music credits are in
`../../sources/*.source.json`. Full original renders and independent timing
checks are under each song's `original/` directory. Silent ending windows in
the older PCM comparison statistics can contain undefined correlation values;
the full-song metrics and timing checks are finite and valid.

Example commands from the repository root, substituting another supported
source file and a separate result directory:

```sh
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/pcm4_prepare.py --source experiments/mod-hybrid/sources/cream-of-the-earth.mod --out experiments/mod-hybrid/results/more-mods/cream-of-the-earth/short --seconds 50
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/pcm4_build.py --input experiments/mod-hybrid/results/more-mods/cream-of-the-earth/short/arrangement.json --out experiments/mod-hybrid/results/more-mods/cream-of-the-earth/short/c64
rtk proxy experiments/sid-inverse/.venv/bin/python experiments/mod-hybrid/more_mods_audition.py experiments/mod-hybrid/results/more-mods/cream-of-the-earth --out experiments/mod-hybrid/results/more-mods/auditions
```

The final packaging command requires completed original, VICE and exact DAC
verification receipts. General capture commands are in `../../PCM-PLAYER.md`.
