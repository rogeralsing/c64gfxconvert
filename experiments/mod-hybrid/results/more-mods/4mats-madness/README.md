# 4-Mat’s Madness: additional MOD playback test

Original music: **4-Mat / Anarchy**, [Demozoo source entry](https://demozoo.org/music/19081/).
The exact downloaded MOD and its SHA256 are recorded in `../../../sources/4mats-madness.source.json`.

## Playable result

`short/c64/stardust.prg` plays the first **50 seconds** on PAL C64 / MOS6581.
The existing tool retains its historical output filename; this file contains 4-Mat’s Madness.
It uses four independent original sample tracks, nearest DAC quantization and no residual error feedback.
The program is **23,698 bytes**, ends at **$6491**, and retains 13 reusable sampled instruments.
The expanded sample bank occupies **14,416 bytes**; the compressed score occupies **7,150 bytes**.
No REU, streaming, additional SID chips or long song recording in C64 RAM is used.

Actual audio is `short/vice/stardust-listening.wav` (first 50 seconds) and
`short/vice/stardust-preview.wav` (seconds 30–50). These are VICE recordings, not offline model audio.
The independent full original rendering is `original/original.wav`.

## Verification

The independent libopenmpt decoder matches all **20,352** order/row/pattern/speed observations across
**407.04 seconds**, with zero timing mismatches. The original-sample timeline renderer has whole-song
waveform correlation **0.93292** and per-tick RMS envelope correlation **0.99822** against a controlled
independent decode. These measurements allow resampler, phase, mixer and filtering differences; they do
not prove exact timbre or subjective musical recognition. The silent final comparison window has
undefined correlation metrics, represented as NaN in the existing audio-comparison receipt.

The short arrangement exactly matches the first 2,500 full-song ticks. Its sample-bank hashes and
resampling divisors match the full preparation. All **192,431** actual D418 DAC bytes match the
independent arithmetic reference, with **zero mismatches**. See `short/reference/trace-check.json`,
`short/vice/capture.json`, `short/c64/build.json` and `audit.json`.

## Full-song limit

The complete arrangement is prepared under `full/`, but its resident build is **rejected**:
it ends at **$E34E**, exceeding the **$D000** RAM limit by **4,942 bytes**. Files under `full/c64/`
are preserved failed-build evidence, not a playable full-song program. See `full/failed-build.json`.
No waveform fidelity, instrument routing, pitch or effects were changed to force the full song to fit.
