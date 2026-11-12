# Native SID mixing

This is the supported C64 music path. It follows the software oscillator and
sample mixing described in [Linus Akesson's Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php).
The C64 mixes a software triangle bass with reusable drum samples through SID
voice 3. Two ordinary SID voices remain available for other musical parts.

## Build and verify

Run from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py
```

Requires the pinned music environment, KickAssembler at `~/.local/bin/kickass`,
VICE at `/opt/homebrew/bin/x64sc`, and the shared
`experiments/mod-hybrid/vice_profile.py` profile: PAL, reSID, MOS8580 + digiboost,
resampling method 2, mono 22,050-Hz recording.

The current Hyperbased proof covers the first 20 seconds. It produces
[a runnable PRG](work/hyperbased/linus-mix/player.prg),
[actual VICE audio](work/hyperbased/linus-mix/hybrid.wav), and a full
[verification receipt](work/hyperbased/linus-mix/verification.json).
The [Hyperbased working folder](work/hyperbased/README.md) contains its four
separate original channels and the current arrangement decisions.

## Current capability

The output clock is one sample every 126 PAL cycles, or 7,819.43 values/s.
Master volume stays constant during music. A sixteen-level software triangle
and fixed-pitch sampled drums share one physical SID voice; this is not a
general mixer for two freely pitched sampled instruments.

The Hyperbased proof retains source channel 1 as software bass, source channel
4 as sampled drums, and source channel 2 as a pulse approximation. SID voice 2
rests. Source channel 3 awaits listening and arrangement decisions. This is
neither the full song nor an exact four-channel MOD reproduction.

The native run verifies all 156,389 mixed values, all 6,000 ordinary SID writes,
126-cycle intervals, and zero underruns. Its minimum measured foreground margin
is 110 cycles per buffer. Screen-on and physical SID operation remain unverified;
listening acceptance is separate from these digital checks.

## Working rules

Follow [AGENTS.md](AGENTS.md). Keep original MOD channels separate and choose
prominent phrases before assigning the C64 voices. Do not choose a source
channel merely because it is easier to encode. The phrase detector is not yet
implemented.

The approved Cream and Hyperbased recordings remain as immutable listening
[references](references/manifest.json). They are not alternate build paths.
