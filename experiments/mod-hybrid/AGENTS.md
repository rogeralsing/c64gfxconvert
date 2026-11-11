# MOD converter instructions

This directory owns the sampled MOD-to-C64 converter. Follow the repository's
instructions too. Run shell commands through `rtk`.

## Accepted music baseline — 2026-11-11

Continue MOD music work from the accepted Linus Åkesson/SounDemoN-style SID
voice sampler in `../sid-voice-sampler/`. The working entry point is
`build_mod_hybrid.py` with `instruments/cream-of-the-earth/`, including its
reusable ASM sample banks and JSON SID recipes. Follow that directory's
[AGENTS.md](../sid-voice-sampler/AGENTS.md) for the reference identities and
reproduction command.

The accepted Cream version uses eight-bit sample data through ordinary SID
voice 3 at 126 PAL cycles per value (7,819.43 Hz), constant master volume, and
two ordinary SID accompaniment voices. The user explicitly prioritizes this
sound quality over retaining every MOD channel; declare any omitted channels.

Do not substitute the older four-bit `$D418` PCM4 converter when asked to reuse
these sounds or port more songs. Most recordings from that catalog were
rejected. The later `build_full_cream.py` arrangement was also rejected: reusing
some bank bytes did not make its new arrangement and instrument approximations
an accepted extension. Preserve the positively reviewed Hyperbased outputs.

Before extending the player, rebuild the accepted Cream reference from the
existing instrument files and verify byte-identical PRG and actual VICE WAV.
Then change one bounded part at a time and compare the same source passage,
one channel at a time. Do not replace instrument recipes, reduce sample detail
or invent new approximations while claiming only to reuse the accepted sounds.
Register equality and zero underruns do not establish acceptable sound.

## Existing PCM4 and HVSC paths

The instructions below describe maintenance of these existing paths. They do
not select PCM4 as the default for new SID-voice music ports.

- Keep the four original MOD tracks as independently pitched, reusable samples.
  When maintaining PCM4, use its existing player and `$D418` DAC; do not replace
  a song with one long recording.
- Use one playback profile: PAL, reSID, MOS8580 + digiboost (`-sidmodel 2`),
  resampling method 2 and 22,050 Hz mono. Keep its definition in
  `vice_profile.py`; playback, capture and manifests must agree.
- Digiboost means the VICE setting. Do not add voice-boost hacks, SID-model
  alternatives, clock variants or automatic comparison matrices unless the user
  explicitly requests a new experiment.
- The PCM4 sample IRQ stays at 256 PAL CPU cycles (3,848.625 Hz). Keep nearest
  rounding, the established per-song gains and `dictionary8` release scores.
  Change sound or timing deliberately and verify the affected song.
- Source tracker ticks may vary with BPM or VBlank speed while that DAC clock
  remains fixed. Preserve source finetune, offsets, delayed/retriggered notes,
  pattern loops and loop-target changes. Do not delete unsupported commands or
  set finetune to zero to make an input pass. Ambiguous source timing may be
  declared only in a matching source receipt with independent provenance.

## Workflow and outputs

This section applies to the existing converter paths. New SID-voice ports use
the accepted entry point and instructions linked above.

- Start with [README.md](README.md) and [REPRODUCE.md](REPRODUCE.md).
  `build_release.py` is the release entry point; `run_vice.py` owns playback
  and capture. Use this directory's pinned requirements and `.venv`.
- Use `results/rebuild/` for current work: one named PRG per song in `players/`
  and one capture directory per song. Reuse those paths instead of creating
  old/new/boost/filter variants. Temporary verification outputs stay ignored.
- Keep original and C64 audio in separate files. Present only the current C64
  result unless comparison is requested; never concatenate original/old/new
  versions into a listening file.
- Preserve source MODs, provenance, licenses and accepted baselines. Keep
  generated banks, assembler intermediates, logs, raw traces and caches out of
  Git. Check in only selected final artifacts and compact verification receipts
  when publication is requested.
- Historical source and results are documented in [HISTORY.md](HISTORY.md).
  They are outside the supported workflow. Do not run old audition generators
  or revive retired variants during routine conversion.

## Verification

- Preserve the pinned release PRG hashes for configuration-only cleanup.
  Do not update expected hashes merely to make a failing check pass.
- For playback changes, check the affected note sequence with the independent
  integer reference, then actual VICE register output and runtime counters.
  For a full-song claim, verify the full song.
- Capture identity includes PRG bytes, emulator profile and duration. Never
  reuse or relabel a PAL/6581 recording as digiboost evidence.
- Diagnose sound problems one channel at a time over a complete phrase.
  Preserve melody, pitch, triggers and loop behavior before optimizing timbre.
- Actual VICE audio may use DC removal and a constant gain. Do not hide player
  defects with host mixing, EQ, limiting, pitch shifts or time alignment.
- Hashes and register matches do not prove that music sounds good. Report
  objective checks separately from the user's listening feedback.
