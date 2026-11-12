@/Users/rogerjohansson/.codex/RTK.md

## Music work

The canonical music implementation is the native Linus-style mixer in
`experiments/sid-voice-sampler/`. Read its `AGENTS.md` before music changes.
Use `build_linus_mix.py`: software triangle bass and reusable drum samples
share SID voice 3, leaving two ordinary SID voices available.

Keep the original MOD's four channels separate and choose prominent passages
before assigning C64 voices. Never silently omit a melody to fit an easier
channel. The current Hyperbased proof is twenty seconds; channel 3 remains
unassigned. Do not describe it as a complete four-channel port.

Do not revive the old `$D418` catalog, static single-sample arrangements or
removed audition builders as a fallback. Approved recordings under
`references/` are listening references, not alternative build entry points.
Preserve unrelated graphics and parallel HVSC work.
