# Shared MOD tools

Music work continues in the [native SID mixer](../sid-voice-sampler/README.md).
Its single build entry point is:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py
```

This directory supplies the pinned Python environment, original MOD reader,
tracker timeline, source receipts, independent Amiga-channel renderer and VICE
profile. Install those dependencies from the repository root:

```sh
rtk proxy python3 -m venv experiments/mod-hybrid/.venv
rtk proxy experiments/mod-hybrid/.venv/bin/python -m pip install -r experiments/mod-hybrid/requirements.txt
```

The current profile is PAL, reSID, MOS8580 + digiboost. Read the
[mixer instructions](../sid-voice-sampler/AGENTS.md) before music changes.
Existing converter internals remain for separate maintenance; they are not a
fallback for the current SID-voice mixing work.
