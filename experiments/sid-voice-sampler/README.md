# Native SID sampling and mixing

The supported music player combines ordinary SID synthesis with samples played
through SID oscillators. The current Hyperbased arrangement covers its first
twenty seconds: source C2 uses an ordinary pulse voice, C3 uses its original
instrument samples, and software bass from C1 shares the third SID voice with
sampled C4 drums.

It follows the sample-and-hold technique described in
[Linus Åkesson's Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php).
The mix runs on the C64 with constant master volume.

## Build and record

Run from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py
```

This is the single build entry point. It prepares instrument data from the
original MOD, assembles the player, verifies native playback and records the
mix and physical SID stems independently in VICE. Cached generated song data
is not required. Use `--assemble-only` to stop before playback and recording.

Requires the music Python environment, KickAssembler at `~/.local/bin/kickass`
and VICE at `/opt/homebrew/bin/x64sc`. The fixed profile is PAL, reSID,
MOS8580 + digiboost, resampling method 2 and mono 22,050-Hz recording.

## Generated outputs

After running the command:

- [Runnable player](work/hyperbased/linus-mix/player.prg)
- [All three SID voices](work/hyperbased/linus-mix/all.wav)
- [SID 1: original C2, pulse synthesis](work/hyperbased/linus-mix/sid-1.wav)
- [SID 2: original C3 instruments, sampled](work/hyperbased/linus-mix/sid-2.wav)
- [SID 3: C1 software bass and C4 sampled drums](work/hyperbased/linus-mix/sid-3.wav)
- [Verification and measurements](work/hyperbased/linus-mix/verification.json)
- [Stem isolation checks](work/hyperbased/linus-mix/stems-check.json)

The WAVs share one time origin and listening gain. The full mix is a separate
native capture. Digital verification and listening approval are separate;
the restored sampled C3 part still needs listening assessment. SID 1 and SID 3
retain their accepted note/register sequences, with small measured capture
differences documented in [the technical notes](DUAL-SAMPLER.md).

Read [the signal path and limits](DUAL-SAMPLER.md),
[the Hyperbased channel comparison](work/hyperbased/README.md) and
[project instructions](AGENTS.md) before changing the arrangement. Preserved
[listening references](references/manifest.json) are not alternate build paths.
