@/Users/rogerjohansson/.codex/RTK.md

## Music work

The canonical music implementation is the native Linus-style mixer in
`experiments/sid-voice-sampler/`. Read its `AGENTS.md` before music changes.
Use `build_linus_mix.py --full` for the complete Hyperbased arrangement: native
SID instrument programs use two voices, and Linus-style PCM plus software bass
share SID voice 3. Physical roles change with the musical passage. The default
without `--full` preserves the earlier twenty-second dual-sampler reference.
Use `build_linus_mix.py --song cream --full` for the selected 3:08.42 Cream
arrangement on an unexpanded 64 KiB C64. SID2 and SID3 both use Linus-style
sampling; the SID1 repair uses a separately declared native instrument program
and restores C1's figure at 17.92–31.36. Its listening assessment is pending.
The active output is `work/cream/sid1-repair/` under the canonical implementation.
Notes stop at the 3:08.16 phrase boundary and existing sounds drain. Preserve
the rejected SID1 build in `work/cream/three-minute-linus-mix/` and the former
4:01.92 baseline. Omitting `--full` preserves its approved original interval
17.92–44.80. Preserve Hyperbased and every approved reference while extending it.
Taking or finishing the next song means a full-length player and recording;
rebuilding an already approved excerpt does not complete that request.

Keep the original MOD's four channels separate and choose prominent passages
before assigning C64 voices. Never silently omit a melody to fit an easier
channel. The Hyperbased arrangement ends at the user's chosen 3:00 and retains real
orchestral attacks with native SID melody programs. It is not an exact MOD
replay; omitted passages and timbre
approximations are documented in `experiments/sid-voice-sampler/FULL-LENGTH.md`.
The preserved twenty-second reference uses actual C3 instrument waveforms at
1.95 kHz on SID2, replacing the rejected flute approximation.

Do not revive the old `$D418` catalog, static single-sample arrangements or
removed audition builders as a fallback. Approved recordings under
`references/` are listening references, not alternative build entry points.
Preserve unrelated graphics and parallel HVSC work.
