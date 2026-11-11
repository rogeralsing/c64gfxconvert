# C64 MOD test programs

13 resident C64 test passages. Each instrument remains a reusable sample.
These are roughly 50-second passages, not full-song playback claims.

Use PAL / reSID / MOS8580 + digiboost, resampling method 2. From the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/run_vice.py --play --prg experiments/mod-hybrid/results/rebuild/players/guitar-slinger.prg
```

| Song | Seconds | Program |
| --- | ---: | --- |
| Global Trash 3 v2 | 50.000 | [PRG](players/global-trash-3.prg) |
| Madness Took Me | 50.000 | [PRG](players/madness-took-me.prg) |
| Rink-a-dink | 50.000 | [PRG](players/rink-a-dink.prg) |
| Elysium | 50.000 | [PRG](players/elysium.prg) |
| Global Trash | 50.000 | [PRG](players/global-trash.prg) |
| Mobyle | 50.000 | [PRG](players/mobyle.prg) |
| Livin’ Insanity | 50.000 | [PRG](players/livin-insanity.prg) |
| Elektrik Funk | 50.000 | [PRG](players/elektrik-funk.prg) |
| Technique Unfail / Desert Dream I | 50.000 | [PRG](players/desert-dream-1.prg) |
| Guitar Slinger | 50.000 | [PRG](players/guitar-slinger.prg) |
| Klisje Paa Klisje | 50.000 | [PRG](players/klisje-paa-klisje.prg) |
| Physical Presence | 50.002 | [PRG](players/physical-presence.prg) |
| Condom Corruption | 50.001 | [PRG](players/condom-corruption.prg) |

[Verification summary](verification.json) records hashes, runtime counters and exact DAC comparisons.
These checks do not establish perceived sound quality. Original authorship remains with the composers.
Source download URLs and SHA256 values are in `../../sources/*.source.json`.

Regenerate programs and actual VICE WAVs with:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/build_release.py --candidates --seconds 50 --capture
```

WAVs, raw MODs, banks, traces and build intermediates remain generated local output.
The three pinned full-song releases are documented in [REPRODUCE.md](../../REPRODUCE.md).
