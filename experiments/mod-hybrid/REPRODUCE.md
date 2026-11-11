# Reproduce the sampled-MOD release

The three selected full-song programs are reproducible from source. Generated
arrangements and assembler inputs contain checkout-specific absolute paths;
regenerate them instead of copying old `results/` directories between machines.
The download receipts under `sources/` record exact source URLs, sizes and SHA256
hashes. The original MOD binaries are downloaded separately and are not required
to be stored in Git.

## Tested tools

The release was built on macOS using Python 3.14 and the exact packages in
`requirements.txt`. KickAssembler must be available as `~/.local/bin/kickass`.
The optional capture tool expects VICE `x64sc` at `/opt/homebrew/bin/x64sc`.
Independent original-audio rendering additionally needs Homebrew `libopenmpt`
and `openmpt123`. Neither VICE nor libopenmpt is needed to reproduce the PRGs.

Run from the repository root:

```sh
python3 -m venv experiments/mod-hybrid/.venv
experiments/mod-hybrid/.venv/bin/python -m pip install -r experiments/mod-hybrid/requirements.txt
experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/fetch_sources.py
experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/build_release.py
```

The fetcher reuses an existing matching source file. It rejects an existing or
downloaded file with a different size or hash without overwriting it. The build
script recreates every sample bank and score, assembles with `dictionary8`, and
requires the complete PRG hashes to match the verified release before exporting
them. Use `--out PATH` to choose a separate generated output directory.

Output defaults to `experiments/mod-hybrid/results/rebuild/players/`:

| Program | Duration | Bytes | SHA256 |
| --- | ---: | ---: | --- |
| `stardust-memories-full.prg` | 240 s | 37,170 | `ee0b7514369a9e1d55a4523500d21c87d901a76b92a65c3d18b988b379e0e29b` |
| `hyperbased-full.prg` | 333.84 s | 50,429 | `0434f8171b94a1c6f44d9923b2143fc91b8688443061f5db3b49090297a4a980` |
| `4mats-madness-full.prg` | 407.04 s | 45,039 | `3961595a2efa07e0338f058dd7d56ae1006aac6210aed397c104e0884f590df6` |

`manifest.json` uses relative program paths and records the verified source and
output identities. Intermediate arrangements and assembler files are local
generated inputs; their paths are not part of the PRG bytes.

## Optional full execution check

For example, capture Hyperbased's complete register stream and runtime counters:

```sh
experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --prg experiments/mod-hybrid/results/rebuild/hyperbased/c64/stardust.prg --symbols experiments/mod-hybrid/results/rebuild/hyperbased/c64/pcm4.sym --out experiments/mod-hybrid/results/rebuild/hyperbased/vice --duration 333.84 --mode registers
```

The optimization study's receipts document full PAL/6581 execution and exact
DAC-byte comparisons for all three selected programs. Rebuilding the same PRG
bytes preserves that program identity; another SID model or real hardware is a
separate validation target.

The older inverse-SID and native reSID experiments use additional dependencies
from `../sid-inverse/requirements.txt` and separately obtained VICE/GoatTracker
source archives. They are not needed for this PCM4 release. Historical reports
may link large generated audio, traces and search caches kept only in the local
research workspace; rebuild the relevant experiment to regenerate them.
