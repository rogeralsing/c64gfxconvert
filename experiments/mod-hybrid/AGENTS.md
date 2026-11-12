# Shared MOD tools and parallel maintenance

Run every shell command through `rtk`.

For music work, read [../sid-voice-sampler/AGENTS.md](../sid-voice-sampler/AGENTS.md).
Use only `../sid-voice-sampler/build_linus_mix.py`: the native software triangle
and drum mixer follows Linus Akesson's Platform Hopping method. Do not substitute
`build_release.py`, a `$D418` player, a static single-sample arrangement or an
old audition pipeline for that implementation.

Keep the four original MOD channels separate. Review prominent phrases and
instrument roles before choosing C64 voice assignments. Retain melody even when
an easier percussion channel would fit the player. Current Hyperbased mixing
covers twenty seconds and leaves original channel 3 unassigned.

Shared dependencies here remain active: `mod_reader.py`, `timeline.py`,
`protracker_periods.py`, `solo_original.py`, `vice_profile.py`, source receipts,
requirements and the pinned `.venv`. Preserve source identity, tracker effects,
finetune, offsets, loops and note lifetimes. Use PAL, reSID, MOS8580 + digiboost,
resampling method 2 and 22,050-Hz mono capture.

Existing converter internals also support separate parallel research. Preserve
that work; it does not choose the music project's canonical build route.
