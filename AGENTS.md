@/Users/rogerjohansson/.codex/RTK.md

## Music work

The canonical music implementation is the native Linus-style mixer in
`experiments/sid-voice-sampler/`. Read its `AGENTS.md` before music changes.
Use `build_linus_mix.py --full` for the complete Hyperbased arrangement: native
SID instrument programs use two voices, and Linus-style PCM plus software bass
share SID voice 3. Physical roles change with the musical passage. The default
without `--full` preserves the earlier twenty-second dual-sampler reference.
Use `build_linus_mix.py --song cream --full` for the complete 4:01.92 Cream
arrangement. Omitting `--full` preserves its approved original interval
17.92–44.80. Preserve Hyperbased and every approved reference while extending it.
Taking or finishing the next song means a full-length player and recording;
rebuilding an already approved excerpt does not complete that request.

Keep the original MOD's four channels separate and choose prominent passages
before assigning C64 voices. Never silently omit a melody to fit an easier
channel. The active arrangement ends at the user's chosen 3:00 and retains real
orchestral attacks with native SID melody programs. It is not an exact MOD
replay; omitted passages and timbre
approximations are documented in `experiments/sid-voice-sampler/FULL-LENGTH.md`.
The preserved twenty-second reference uses actual C3 instrument waveforms at
1.95 kHz on SID2, replacing the rejected flute approximation.

Do not revive the old `$D418` catalog, static single-sample arrangements or
removed audition builders as a fallback. Approved recordings under
`references/` are listening references, not alternative build entry points.
Preserve unrelated graphics and parallel HVSC work.
