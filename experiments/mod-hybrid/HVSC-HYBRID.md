# HVSC instruments with MOD samples

`hvsc_hybrid.py` builds a native C64 experiment using real SID oscillators and
reusable MOD samples together. It covers Guitar Slinger from 5.50 to 14.46 s:
one complete 64-row pattern, 448 ticks, 8.96 seconds.

| MOD track | Playback |
| --- | --- |
| 1 | Real SID voice: pulse melody |
| 2 | Original sampled guitar chords |
| 3 | Real SID voice: melody echo |
| 4 | Original sampled bass/accompaniment |

The sampled-only Guitar Slinger reference is kept separately. This experiment
does not replace that program or claim full-song hybrid support.

## Source sounds

HVSC SID files contain executable music players and song data, rather than a
standard instrument bank. `hvsc_extract.py` executes the original players in
VSID and records their voice registers. Hash-bound receipts preserve the
official download URL, composer, subtune, voice and source note position.

The current source collection includes Jeroen Tel, Chris Hülsbeck, Martin
Galway, Rob Hubbard, Matt Gray, Tim Follin and Thomas Mogensen / DRAX. The first
listening tests use sounds from Hawkeye, The Great Giana Sisters and Wizball.
Composition and player authorship remain with their original authors.

The importer keeps ordered writes and complete register states per source
update. It bounds each candidate before the donor's next note, including
legato notes with an unchanged gate. It excludes filter, oscillator-sync and
ring-modulation dependencies that a standalone voice cannot reproduce. These
are observed note programs, not proof that each candidate is a distinct or
generally reusable instrument.

## Adaptation and playback

The melody sample has a clear repeating pulse period. Its measured fundamental
and the MOD's actual per-tick periods determine SID frequency, including slides
and vibrato. Donor waveform, pulse-width movement and attack/decay are retained;
their update sequence is sampled onto the MOD's 50-Hz ticks. The last gated
donor state holds until the MOD note ends. Sustain follows MOD volume, and a
one-tick hard restart precedes retriggers. The donor's melody is not imported.

SID attack peaks cannot be independently scaled like PCM amplitude. Nonzero
sustain is required for the combined lead/echo test; quiet dynamics and timbre
remain listening judgments. Shared filter and multi-voice instruments are
outside this first experiment.

The combined hybrid uses 0.4 times the SID sustain level so the sampled chords
and bass remain audible. Composer solos and patch ranking keep their original
level. This changes only SID sustain: pitch, waveform, pulse program, release,
gates and PCM gain 3 remain the same. SID master volume cannot balance these
components independently because `$D418` is also the sample DAC.

`build_c64.py` has an optional ordered raw-register packet for this experiment.
The C64 executes those writes while its sample IRQ runs every 256 PAL cycles.
The raw hybrid mixes its two PCM contributions at higher precision, then rounds
once with gain 3, preserving more bass than the historical per-voice rounding.
The 9xx chord offset uses a reusable one-shot suffix rather than restarting the
sample. Existing PCM4 release programs and historical backend behavior remain
unchanged.

All listening files come from actual C64 programs inside VICE: PAL, reSID,
MOS8580 + digiboost, resampling method 2, mono 22050 Hz. There is no host-side
mixing of a SID recording with samples. `$D418` still controls SID master volume,
so the sampled component also modulates synthesized voices.

## Reproduce

Use the existing `.venv`, KickAssembler, VICE and libopenmpt dependencies.
`sources/hvsc.source.json` pins the official SID downloads. The extractor fetches
missing sources, verifies their hashes and writes local source receipts.

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/build_release.py --songs guitar-slinger --seconds 50
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/hvsc_extract.py --seconds 60
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/mod-hybrid/hvsc_hybrid.py --capture
```

Results stay under `results/rebuild/hvsc-hybrid/`. Each composer has one current
SID-only melody file; `hybrid.wav` includes both SID voices and both sample
tracks. The manifest names the selected donors and records the exact source
range, program/audio hashes and runtime proofs. Earlier discovery captures used
30 seconds for most sources and 60 seconds for Tel's Hawkeye/Cybernoid; their
receipts retain those durations. A longer fresh discovery can select another
candidate, so compare selected IDs and source hashes when reproducing a sound.

The fast ranking uses the official VICE reSID core with the same fixed
digiboost settings. It compares a complete original melody note, including its
pitch and volume changes. Final acceptance checks ordered actual C64 SID bus
writes, tick timing, PCM clock and underruns over the complete phrase. These
checks establish execution, not perceived sound quality.

Primary references:

- [HVSC SID format](https://www.hvsc.c64.org/download/C64Music/DOCUMENTS/SID_file_format.txt)
- [HVSC STIL metadata](https://www.hvsc.c64.org/download/C64Music/DOCUMENTS/STIL.txt)
- [HVSC collection and mirrors](https://www.hvsc.c64.org/downloads)
