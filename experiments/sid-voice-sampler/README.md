# Native SID sampling and mixing

The music player combines reusable native SID instrument programs with samples
played through a SID oscillator. The full Hyperbased arrangement covers the
user-selected ending at exactly 3:00. Two ordinary SID voices and a Linus-style
sample voice share the musical parts; the latter also mixes software triangle
bass on C64. The earlier twenty-second dual-sampler reference is preserved.

It follows the sample-and-hold technique described in
[Linus Åkesson's Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php).
The mix runs on the C64 with constant master volume.

The target is an unexpanded 64 KiB C64. Select sampled parts within the measured
CPU budget and use ordinary SID sounds where suitable. Full-length playback
must not be forced by expanding waveform data or adding external memory.

Hyperbased's three-minute arrangement is preserved. Cream of the Earth now
selects 3:08.42, ending at a musical phrase with existing sounds allowed to drain.
It uses two oscillator sampling voices and one native SID program on a stock
64 KiB C64. Its approved 26.88-second excerpt remains fixed. See
[Cream's work folder](work/cream/README.md) and [the work queue](REPERTOIRE.md).
The former 4:01.92 Cream SID2 was rejected in listening; its SID3 is accepted.
The subsequent SID1 was also rejected. The current SID1 candidate restores an
omitted figure and uses a separate native instrument program; listening
assessment is pending. Both sampler streams remain fixed. Read
[the implementation and limits](CREAM-THREE-MINUTE.md).

Read [the full-length implementation and limits](FULL-LENGTH.md) for its native
instrument programs, compact note data, scheduling and explicitly omitted parts.
The [earlier budget plan](work/hyperbased/full-length-budget/PLAN.md) retains its
historical diagnostic measurements.

## Build and record

Run from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --full
```

This is the single build entry point. It prepares reusable instruments and
note data from the original MOD, assembles the player, verifies native playback
and records the mix and physical SID stems independently in VICE. Cached song
data is not required. Use `--assemble-only` to stop before verification and
recording. Omit `--full` to rebuild the preserved twenty-second reference.

Build the selected complete Cream arrangement:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --full
```

Omit `--full` only to rebuild the approved original-MOD interval 17.92–44.80.
The active result is `work/cream/sid1-repair/`. SID1 selects C1 at 17.92–31.36
and C3 elsewhere. Its guitar uses triangle+saw with hardware ADSR; this does
not reproduce every original volume curve or sample envelope. Later C1 chords
remain omitted. The rejected SID1 build in `work/cream/three-minute-linus-mix/`
and the previous 4:01.92 result remain preserved baselines.
`--full` without `--song cream` continues to select three-minute Hyperbased.

Requires the music Python environment, KickAssembler at `~/.local/bin/kickass`
and VICE at `/opt/homebrew/bin/x64sc`. The fixed profile is PAL, reSID,
MOS8580 + digiboost, resampling method 2 and mono 22,050-Hz recording.

## Generated outputs

After running the command:

- [Full-length player](work/hyperbased/full-linus-mix/player.prg)
- [All three SID voices](work/hyperbased/full-linus-mix/all.wav)
- [SID 1](work/hyperbased/full-linus-mix/sid-1.wav)
- [SID 2](work/hyperbased/full-linus-mix/sid-2.wav)
- [SID 3: native PCM and software bass](work/hyperbased/full-linus-mix/sid-3.wav)
- [Verification and measurements](work/hyperbased/full-linus-mix/verification.json)
- [Every omitted passage](work/hyperbased/full-linus-mix/coverage.json)

The WAVs share one time origin and listening gain; each is a separate native
capture. Digital correctness and listening approval are separate. The full
build also checks 122 SID1 audio passages against the immutable accepted
recording before replacing listening files. Approved sounds must remain fixed
while unrelated parts are changed; see [the SID1 regression](SID1-REGRESSION.md).
The arrangement retains actual orchestral attacks but approximates other timbres
with SID programs and software triangle bass. All active source parts have
assigned outputs before the selected ending; later source sections are excluded.

The unchanged [twenty-second mix](work/hyperbased/linus-mix/all.wav) and its
[verification](work/hyperbased/linus-mix/verification.json) remain available for
comparison. Its signal path is documented in [DUAL-SAMPLER.md](DUAL-SAMPLER.md).

Read [the measured CPU profile and optimizations](CPU-PROFILE.md),
[the signal path and limits](DUAL-SAMPLER.md),
[the Hyperbased channel comparison](work/hyperbased/README.md) and
[project instructions](AGENTS.md) before changing the arrangement. Preserved
[listening references](references/manifest.json) are not alternate build paths.
