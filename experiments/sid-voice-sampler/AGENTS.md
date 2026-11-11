# SID-voice music research

Run every shell command through `rtk`. Preserve the original guitar prototype,
accepted Cream solo/hybrid and accepted Hyperbased excerpt/full artifacts.
Do not include parallel HVSC or graphics changes automatically.

The user explicitly chose SID sound quality over retaining every MOD channel on
2026-11-11. Use the accepted eight-bit voice-3 sampler with ordinary SID voices
for accompaniment. Declare source channel mappings, omitted channels, source
range and instrument approximations in every song report. A three-channel
arrangement must not be described as exact four-channel MOD reproduction.

The accepted working entry point is `build_mod_hybrid.py` with
`instruments/cream-of-the-earth/`. The later `build_full_cream.py` arrangement
was rejected in listening review on 2026-11-11 and must not replace that base.
Reproduce the accepted reference before extending it. Do not introduce new
instrument approximations or change the arrangement while claiming only to
reuse the accepted sounds. Isolate and verify each intentional extension.

The accepted 26.88-second Cream reference was rebuilt from those same reusable
instrument files and recorded again in VICE. Both artifacts matched exactly:

- PRG, 24,001 bytes: `259db8ce3a6f01f07f60059ae596b78511ae28304422f4f9402654ea2a1c7b44`.
- WAV: `d361e57e9f1eddeb34ee5436bfef93dcc9873953e8d67d637d310b0ca0934024`.

Reproduce from the repository root into a separate output directory:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_mod_hybrid.py --instruments experiments/sid-voice-sampler/instruments/cream-of-the-earth --out experiments/sid-voice-sampler/results/cream-reference-check --capture
```

Compare its `player.prg` and `hybrid.wav` against the hashes above and the
accepted files in `results/mod-channel-hybrid/`. Preserve the accepted files;
do not change expected hashes merely to accept a different sound. The restored
copies and proof are in `results/cream-reference-restored/`.

The accepted phrase starts at source time 17.92 s and ends at 44.80 s. A full
song starting at 0 s is a different listening passage. Match source passages
before comparing sounds; explicitly review any new sections and instruments.

Keep PAL/reSID/MOS8580 + digiboost, resampling 2 and mono 22,050-Hz recording.
The working SID-voice sampler uses a 126-PAL-cycle NMI (7,819.43 values/s), eight-bit
sample data and constant master volume. Preserve that signal path and its
accepted references. The older four-bit `$D418` catalog in `../mod-complete/`
is a rejected listening diagnostic, with the positively reviewed Hyperbased
output retained separately.

Use independently pitched reusable instruments and native C64 synthesis, never
a flattened host recording. Compare identical source passages one channel at a
time before claiming instrument quality. Preserve supported note timing,
pitch, triggers, sample lifetimes and loop-pointer behavior. Explicitly report
volume palettes, resampling, chord arpeggios and other preparation tradeoffs.

Deliver runnable PRGs and actual VICE recordings. Verify every input value,
126-cycle latch gaps, synth writes, completion counters and zero underruns.
Check CPU and RAM budgets for runtime changes or a new full-song arrangement.
Digital correctness and user listening acceptance are separate outcomes.

Listening files may use a clock-anchored crop, DC removal and one constant gain.
Do not conceal faults with EQ, limiting, time alignment, host mixing or pitch
processing. Preserve the existing source recipes and artifact identities while
adding narrowly scoped configuration to shared compilers.

## Current audition task

The user requested approximately twenty seconds from each of the 19 original
MODs to judge potential. Use `build_auditions.py`, `auditions.json` and the
unchanged accepted `mod-channel-hybrid-player.asm`; see [AUDITIONS.md](AUDITIONS.md).
Keep one named WAV and PRG per MOD under `results/auditions-20s/`. Report the
source passage and all omitted channels. Do not resume full-song conversions
or the rejected `$D418` catalog for this task.

The twenty-second Cream anchor must retain the accepted sample input and all
6,000 SID values. Other previews reuse approved sound templates with explicit
source calibration/substitution metadata. Ambiguous instruments must not be
forced to an invented octave or quietly dropped from a supposedly retained
channel. Preserve reusable instrument files and verify every delivered clip
in actual VICE before labeling it recorded; listening approval remains open.

## Melody-first gate

The user reaffirmed the original workflow after rejecting Desert Dream,
Global Trash and Stardust auditions: identify the original melody channel
first, make that complete phrase work alone, then add bass and percussion.
Do not choose a sampled channel merely because its gain/loop behavior is easy
to encode. Never omit the main melody to satisfy technical eligibility.

Review the source channel's musical role and note movement. A falling spectrum
or an automatic `drum` classification is not evidence that a pitched riff is
a kick: Global Trash instrument 9 and Stardust basinstrument 5 were wrongly
replaced that way. Preserve such sources as sampled melody/bass until their
intended SID replacement has been checked in isolation.

Use `build_melody_checks.py` and `melody-checks.json` for the three corrective
solo checks. Preserve original waveforms, source periods, triggers and audible
volume changes. If the static-gain player cannot retain the melody, keep the
melody and use the existing gain-bank SID-voice renderer; disclose any volume
quantization. Both use eight-bit data and the same 126-cycle sample-and-hold
method. Do not substitute a convenient rhythm track for the lead.

The user approved `results/auditions-20s/melody-checks/global-trash-melody.wav`
(source channel 3, 68.96–88.96 s): “den låter bra nu!”. Preserve this melody
before adding accompaniment. WAV SHA256:
`ee32281a49d78cd8ca02400204eb1c686dbbc4f4495ddf7cedb8027e9b16082b`;
PRG SHA256: `28477b95f4d0d7abb268e791bdc48a89526f06ecd8721fcff9c09cab312ad8c6`.
Listening decisions and artifact identities are in `audition-listening.json`.
