@/Users/rogerjohansson/.codex/RTK.md

## Music work

The canonical music implementation is the native Linus-style mixer in
`experiments/sid-voice-sampler/`. Read its `AGENTS.md` before music changes.
Use `build_linus_mix.py`: bass and sampled drums share SID voice 3; original
channel 3 samples use SID voice 2; SID voice 1 retains the accepted pulse part.

Keep the original MOD's four channels separate and choose prominent passages
before assigning C64 voices. Never silently omit a melody to fit an easier
channel. The current Hyperbased proof is twenty seconds. Channel 3 uses actual
instrument waveforms at 1.95 kHz, replacing the rejected flute approximation.
It is not a full song or an exact MOD replay.

Do not revive the old `$D418` catalog, static single-sample arrangements or
removed audition builders as a fallback. Approved recordings under
`references/` are listening references, not alternative build entry points.
Preserve unrelated graphics and parallel HVSC work.
