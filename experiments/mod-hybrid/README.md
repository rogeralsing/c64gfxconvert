# MOD music on C64

Convert four-channel MOD songs into resident C64 programs. Each instrument is a
reusable sample played at the note's pitch; the program does not contain a
recording of the whole song.

Use one playback profile: **PAL, reSID, MOS8580 + digiboost** (VICE `-sidmodel 2`).
The player mixes four sampled tracks into `$D418` at 3,848.625 updates/s.

## Build

From the repository root:

```sh
rtk proxy python3 -m venv experiments/mod-hybrid/.venv
rtk proxy experiments/mod-hybrid/.venv/bin/python -m pip install -r experiments/mod-hybrid/requirements.txt
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/build_release.py
```

The builder fetches and checks the MOD sources, then creates one verified PRG
per song under `results/rebuild/players/`: Stardust Memories, Hyperbased and
4-Mat's Madness. [Reproduction details](REPRODUCE.md) cover tools, hashes and capture.

## Test the 13 new candidates

The candidate set includes Global Trash 3, Madness Took Me, Rink-a-dink,
Elysium, Global Trash, Mobyle, Livin’ Insanity, Elektrik Funk, Desert Dream I,
Guitar Slinger, Klisje Paa Klisje, Physical Presence and Condom Corruption.

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/build_release.py --candidates --seconds 50 --capture
```

This builds one passage per song, checks its tracker flow against libopenmpt,
compares the actual C64 DAC bytes with the integer model, and records VICE audio
using the same digiboost profile. `--songs global-trash-3 rink-a-dink` selects a
subset for a focused rerun. Outputs stay under `results/rebuild/`: named PRGs in
`players/`, listening WAVs in `audio/`, and per-song proofs in each song folder.
`candidate-manifest.json` reports every requested song and any failure. These
are test passages, not full-song release claims.

## Play

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --play --prg experiments/mod-hybrid/results/rebuild/players/hyperbased-full.prg
```

The screen turns black while music plays. Change the filename to
`stardust-memories-full.prg` or `4mats-madness-full.prg` to choose another song.
The launcher and capture tool use the same fixed digiboost profile.

## Development

- [AGENTS.md](AGENTS.md): project rules, output policy and validation.
- [PCM-PLAYER.md](PCM-PLAYER.md): sample banks, mixer, score and memory layout.
- [HISTORY.md](HISTORY.md): earlier SID approximations, diagnostic variants and measurements.

Keep one current result per song. Existing PAL/6581 recordings and optimization
receipts are historical baselines; they retain their original labels.
