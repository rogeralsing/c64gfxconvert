# Four-channel sampled playback

The supported path is `build_release.py` followed by `run_vice.py` for playback
or capture. VICE uses one fixed profile: **PAL, reSID, MOS8580 + digiboost**,
resampling method 2, mono output at 22,050 Hz. Digiboost is the emulator setting;
the PRG does not reprogram SID voices as additional DC references.

## Instruments and notes

`mod_reader.py` and `timeline.py` preserve the four source tracks, note triggers,
pitch, sample selection, loops, volume and supported effects. Unsupported formats
and effects fail explicitly. The supported inputs are sample-based, four-channel
MODs; external synthesized instruments require separate support.

`pcm4_prepare.py` low-pass resamples the original eight-bit instruments and
quantizes them to four bits, stored one value per byte for fast lookup. A sample
is reused at different playback rates for different notes. An eight-bit
fractional cursor supplies the pitch step. Loop boundaries follow the bank's
resampling divisor; short loops repeat to at least 256 stored bytes.

The default bank scope is the complete song. Score-specific banks are used by
the established Madness build to preserve its approved opening and accommodate
higher notes later. `contextual_banks.py` selects the bank for a complete note
segment, preserving retriggers and the accepted opening.

## Extended tracker support

Candidate builds retain ProTracker finetune, sample-offset memory (`9xx`),
tremolo (`7xy`), fine slides, pattern loops, retrigger, note cut, delayed notes,
pattern delay and tempo changes. Effects still outside the supported set fail
explicitly. Sample-based StarTrekker `FLT4` modules are accepted; external synth
instruments require separate support.

The MOD's CIA or VBlank timing is a source-format property. When the file does
not encode that choice, a hash-bound source receipt can record the independently
verified timing mode. This does not select another C64 playback profile.

Candidate preparation uses `protracker_loops=True`: an instrument-only or
portamento row can change the next loop without restarting the current sample.
Connected instruments share a resampling divisor, and the foreground decoder
stages loop-target changes independently of note triggers. Sample offsets keep
both the bank index and its fractional phase. Tiny exceptional initial DMA
segments can share an existing loop without duplicating the full instrument.

Variable source ticks are rounded cumulatively to DAC samples and split when a
record would exceed the byte-sized counter. The IRQ remains at 256 PAL cycles.
Tick lengths and extended fields are decoded in foreground code. The three
pinned full-song rebuilds retain their original preparation and PRG bytes.

## Mixer and scheduling

The canonical release uses nearest rounding: sum the four volume-scaled
contributions at higher precision, then quantize once to the four-bit DAC.
An arrangement's `mixing.output_gain` is applied through the lookup table;
no extra IRQ mixing work is required. The formula is
`clamp(round(8 + (fine_sum - 128) * gain / 16), 0, 15)`.

Guitar Slinger uses gain 3 before this rounding. At gain 1, quiet guitar phrases
round to the silent midpoint; increasing the recorded WAV's level cannot
recover them. This is a song-specific mixer level within the same digiboost
profile. The three pinned full-song programs retain their established gains.

The CIA sample interval is 256 PAL CPU cycles: 985,248 / 256 = 3,848.625 Hz.
Foreground code decodes the next tracker tick while the IRQ plays the current
tick. The pinned release programs commit voice changes across the last four
sample slots. Extended candidate programs commit at 8/6/4/2 samples remaining,
leaving a recovery IRQ between heavy updates. Their audible offsets are
−7/−5/−3/−1 DAC samples (at most about 1.8 ms early). The source tempo and
256-cycle DAC clock stay unchanged. The independent reference models each
format's stagger and the one-sample output pipeline explicitly.

`pcm4_build.py` assembles `pcm4_player.asm`. The release explicitly selects
`dictionary8`, lossless score compression; its decoder runs in foreground code.
The low-level builder retains older score formats for existing research inputs.
Those formats are not alternative release profiles.

The screen is disabled. Each program fits below `$D000` with no REU, streaming
or additional SID chips. The build checks memory limits.

## Validation

`pcm4_reference.py` supplies the independent integer mixer/cursor model.
Register captures check the actual `$D418` sequence, timing, completed tick count
and prefetch underruns. These checks establish digital playback correctness;
they do not establish perceived sound quality.

Arithmetic receipts also report final-quantizer signal-to-error ratio and the
fraction of prepared musical energy rounded to the midpoint. These catch lost
quiet notes even when every C64 DAC byte matches the model. They do not measure
loss already introduced by sample preparation or replace listening feedback.

The [reproduction guide](REPRODUCE.md) pins complete PRG hashes. Those PRGs were
originally verified under PAL/6581; the old recordings and receipts remain
historical evidence under `results/optimization/`. New captures identify the
fixed digiboost profile explicitly and do not reuse evidence from another model.

Audio captures use VICE's WAV device with warp disabled. A matching register run
anchors the crop. Listening output may remove DC and apply one constant gain.
Keep original audio and C64 audio in separate files.

Earlier fitting, hybrid players and the captured-SID passage tool are research
utilities, outside the release workflow. Their history is in [HISTORY.md](HISTORY.md).
