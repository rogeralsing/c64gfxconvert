# Separate instruments for Cream of the Earth

The accepted 26.88-second hybrid arrangement now reads its ten instruments from
[instruments/cream-of-the-earth/](instruments/cream-of-the-earth/). Notes,
tracker timing and track allocation remain in the arrangement. These are the
instruments used by the three-channel demonstration; the omitted chord channel
is still outside this experiment.

A second independent library and channel plan now exists for
[Hyperbased](HYPERBASED.md). `build_mod_arrangement.py` reads that declared
phrase and its two tonal SID tracks; the original Cream entry point below
keeps its existing channel plan.

## Build and listen

From the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_mod_hybrid.py --instruments experiments/sid-voice-sampler/instruments/cream-of-the-earth --out experiments/sid-voice-sampler/results/instrument-library --capture
```

The instrument directory is the default. `--instruments` lets a copied set be
adjusted without editing the build code. It selects instruments for this same
arrangement, not an arbitrary source MOD.

The command writes `player.prg`, actual VICE `hybrid.wav` and `verification.json`
under `results/instrument-library/`, preserving the published hybrid and solo
outputs. Omit `--capture` for native register verification without a WAV;
`--budget` also measures CPU timing.

## Files and editing

[library.json](instruments/cream-of-the-earth/library.json) lists ten JSON
descriptors and retains the source receipt and MOD SHA256. Each descriptor has
the source instrument number, original name and kind.

| Source instruments | Kind | Examples |
| --- | --- | --- |
| 1–6 | SID percussion recipes | [01-kick.json](instruments/cream-of-the-earth/01-kick.json), [04-snare.json](instruments/cream-of-the-earth/04-snare.json) |
| 7–9 | Sample descriptors and assembler data | [07-bass.json](instruments/cream-of-the-earth/07-bass.json), [07-bass.asm](instruments/cream-of-the-earth/07-bass.asm) |
| 10 | SID pulse melody recipe | [10-pulse-melody.json](instruments/cream-of-the-earth/10-pulse-melody.json) |

The seven SID recipes describe pulse width, quiet sustain, waveform controls,
pitch sweeps, duration and source-RMS tail thresholds. The pulse recipe also
holds source-period analysis settings. The compiler follows MOD notes and
periods to generate register writes. Instrument files contain no note sequence
or recording of the whole passage.

For example, change `pulse_width` in `10-pulse-melody.json` to change the melodic
voice's pulse width. Change a percussion recipe's `duration_s` to change its
maximum tail. Rebuild, verify and capture after editing. The original recorded
envelopes remain approximated by the quiet SID recipes.

The runtime prewarms one sustain level per synth voice. All six percussion
recipes must share one sustain level. Rest is triangle + TEST + gate (`$19`).
Arbitrary ADSR programs, filter programs, sync/ring dependencies and general
instrument bytecode are not supported.

## Reusable sample data

Each sample `.asm` contains only `.byte` data and is imported directly by the
assembler. The arrangement supplies labels and page alignment. Its JSON
descriptor records byte count, SHA256, fixed source volume and decimation.
The loader rejects executable instructions in sample includes.

The banks contain 768, 1,024 and 1,024 bytes including neutral padding. The C64
pitches and reuses these instruments. This extraction preserves the accepted
banks: descriptor hashes, prepared source bytes, volume and decimation must
agree. Replacing a sample, adding loops or changing gain requires a separately
verified preparation path; changing those fields alone is rejected here.

## Verification and limits

The default library reproduces the accepted **24,001-byte PRG**, SHA256
`259db8ce3a6f01f07f60059ae596b78511ae28304422f4f9402654ea2a1c7b44`.
Its instructions, banks and score are identical. The existing
[CPU and memory limits](MOD-HYBRID.md) therefore still apply to this binary.

Receipts record every library file's hash. A fresh native capture checks all
sample values and SID writes with PAL / reSID / MOS8580 + digiboost. Listening
audio uses only a clock crop, DC removal and constant gain. Instrument
separation adds no fourth track or general MOD support. Physical SID and
screen-on operation remain unverified.

The extraction checks also rebuild a relocated library, change pulse width
through its JSON file, shorten a kick through its JSON file, and reject a
corrupted sample include. These use temporary copies; the delivered audio and
default definitions remain unchanged. Results are in
`results/instrument-library/library-checks.json`.
