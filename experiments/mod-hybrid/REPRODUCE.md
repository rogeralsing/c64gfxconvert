# Reproduce the sampled-MOD release

The three full-song programs are reproducible from checked MOD sources.
Generated arrangements contain checkout-specific paths; regenerate them rather
than copying old build directories. Download receipts under `sources/` retain
source URLs, authorship, sizes and SHA256 hashes.

## Tools and build

Tested with Python 3.14 and the pinned packages in `requirements.txt`.
KickAssembler must be available as `~/.local/bin/kickass`; VICE `x64sc` as
`/opt/homebrew/bin/x64sc`. Independent original rendering also uses libopenmpt.

Run from the repository root:

```sh
rtk proxy python3 -m venv experiments/mod-hybrid/.venv
rtk proxy experiments/mod-hybrid/.venv/bin/python -m pip install -r experiments/mod-hybrid/requirements.txt
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/build_release.py
```

The builder downloads missing sources and verifies their size and hash. Existing
mismatched sources are rejected without overwriting them. It recreates the
sample banks and score, assembles with `dictionary8`, and verifies complete PRG
hashes before exporting. `--out PATH` supports an isolated validation build;
normal work uses the same `results/rebuild/` directory.

| Program in `results/rebuild/players/` | Duration | Bytes | SHA256 |
| --- | ---: | ---: | --- |
| `stardust-memories-full.prg` | 240 s | 37,170 | `ee0b7514369a9e1d55a4523500d21c87d901a76b92a65c3d18b988b379e0e29b` |
| `hyperbased-full.prg` | 333.84 s | 50,429 | `0434f8171b94a1c6f44d9923b2143fc91b8688443061f5db3b49090297a4a980` |
| `4mats-madness-full.prg` | 407.04 s | 45,039 | `3961595a2efa07e0338f058dd7d56ae1006aac6210aed397c104e0884f590df6` |

`manifest.json` records source/program identities and the fixed playback profile.
Digiboost changes the VICE configuration; it does not create another PRG variant.

## Play and capture

Both commands use **PAL, reSID, MOS8580 + digiboost**, resampling method 2,
22,050 Hz mono. No SID-model or voice-boost variant selection is needed.

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --play --prg experiments/mod-hybrid/results/rebuild/players/hyperbased-full.prg
```

The black screen is expected. For a complete register and audio capture:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --prg experiments/mod-hybrid/results/rebuild/hyperbased/c64/stardust.prg --symbols experiments/mod-hybrid/results/rebuild/hyperbased/c64/pcm4.sym --out experiments/mod-hybrid/results/rebuild/hyperbased/vice --duration 333.84
```

`--mode registers` or `--mode audio` runs only one capture stage. Audio-only
requires a matching register capture for the same program and playback profile.
Reuse the song's output directory; the runner rejects stale evidence when its
identity differs. WAV capture runs at normal speed.

Historical PAL/6581 receipts and recordings under `results/optimization/` retain
their original model. They establish the pinned program identity and earlier
validation; they are not relabeled as digiboost recordings. See
[HISTORY.md](HISTORY.md) for earlier research.

## Candidate passages

Use `build_release.py --candidates --seconds 50 --capture` for all 13 downloaded
classics. The build verifies each source receipt before processing it. The
candidate manifest is separate from the three pinned full-song release hashes.
Each successful entry binds its PRG, current digiboost recording, complete
tracker-flow check and DAC-byte comparison. A failed entry is not a completed
conversion; the command exits nonzero if any requested song fails.
