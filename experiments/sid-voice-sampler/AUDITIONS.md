# Twenty-second MOD auditions

These previews let the user judge which of the repository's 19 MODs have
potential with the accepted SID-voice sampler and existing SID sound templates.
They are listening candidates, not approved full-song conversions.

For the source-dependent regression tests, fetch the pinned input modules:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/fetch_sources.py --songs cream-of-the-earth hyperbased elysium global-trash stardust-memories
rtk proxy experiments/mod-hybrid/.venv/bin/python -m unittest discover -s experiments/sid-voice-sampler/tests -v
```

Builders also download missing modules into their own output directory and
verify the recorded size and SHA256 before preparing any instruments.

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_auditions.py --plans experiments/sid-voice-sampler/auditions.json --capture --jobs 3
```

Use `--songs <slug> ...` to rebuild selected previews. Without `--capture`, the
command prepares and assembles only. Source MODs and pinned receipts live in
`../mod-hybrid/sources/`; the existing music environment and native tools are
documented in the main experiment README.

The three rejected hybrid arrangements now fail the melody-channel gate
instead of silently rebuilding the known omissions. Rebuild their corrective
solos with the melody command below; rework their accompaniment separately.
Use `--songs` to select the other hybrid candidates.

The runtime is the unchanged `mod-channel-hybrid-player.asm`. SID voice 3 plays
reusable eight-bit sample banks at one value every 126 PAL cycles (7,819.43 Hz).
The other two voices use the accepted pulse, triangle, arpeggio and percussion
recipes, with source pitch calibration and declared sound substitutions.
Master volume remains constant. Playback and recording use PAL/reSID/MOS8580
with digiboost, resampling 2 and mono 22,050-Hz WAV.

`auditions.json` declares candidate source passages and channel mappings. A
passage begins at a real sampled note. In-note audible gain changes, short DMA
segments and unsupported loop changes are rejected. Loop waveforms can be
repeated inside a bounded reusable instrument bank; the C64 still computes
note pitch and position. Offset variants preserve the original start position.
Tracker durations determine cumulative buffer lengths, rather than assuming
every MOD uses 20-ms ticks. Every delivered passage needs actual native and
audio runs with zero underruns.

`audition_instruments.py` preserves existing source-matched recipes and proposes
only measured template uses. Reviewed decisions in `audition-overrides/`
document their source identity, original template, measurement and limitation.
Ambiguous sources can be omitted; every preview records its retained and
omitted source channels. New proposals are not claims of exact source timbre.

Outputs under `results/auditions-20s/`:

- `audio/<slug>-sid-preview.wav`: one actual VICE listening file per MOD.
- `players/<slug>-sid-preview.prg`: its runnable resident C64 program.
- `<slug>/instruments/`: reusable sample banks in ASM/binary/JSON form.
- `<slug>/sid-instruments/`: SID recipes and template provenance.
- `<slug>/audition.json`: source range, channel omissions, identities and checks.
- `manifest.json`: all 19 entries, including any pending or failed previews.

Cream uses the first twenty seconds of the accepted 17.92–44.80 s phrase. Its
prepared sample stream and 6,000 SID register values match that reference.
Accepted Cream, Hyperbased, their instrument libraries and player source are
checked for unchanged hashes around each build. The rejected four-bit `$D418`
catalog is not used to generate these files.

Listening files use only a clock-anchored crop, DC removal and one constant
gain. No host mixing, EQ, dynamics or time alignment hides player problems.
Digital checks and the user's listening assessment are separate outcomes.

## Melody corrections

The user rejected the Desert Dream, Global Trash and Stardust previews.
Their identified melody channels are now required by `auditions.json`;
automatic eligibility must not omit those channels. `audition-listening.json`
records the rejection and the separately accepted Global Trash melody solo.

Build isolated original melodies before adding accompaniment:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_melody_checks.py --songs global-trash stardust-memories desert-dream-1
```

These are melody-only checks, not replacement hybrid previews. Each has its
own runnable PRG, actual VICE recording, separate original-channel reference
and native verification under `results/auditions-20s/melody-checks/`. The
ordinary SID voices rest. Held-note volume changes use the gain-bank renderer;
the selected volume quantum and its error are reported explicitly.

`aligned_melody_banks.py` moves fixed loop endpoints to page boundaries by
continuing and rotating the existing quantized waveform. An independent
replay must preserve every prepared sample before the native run. This avoids
expensive partial-page checks without modifying either player or the NMI.
Trimmed gain-bank prefixes require a fresh audible-read proof; independent
loop-target changes remain unsupported. See `results/auditions-20s/melody-checks/README.md` and each
song's `budget/cpu-budget.json` for measured RAM and deadline limits.
