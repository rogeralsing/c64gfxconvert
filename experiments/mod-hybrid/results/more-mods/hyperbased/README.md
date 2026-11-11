# A Final Hyperbase / Hyperbased

Music by Firefox and Tip / Phenomena. Source and download provenance are in
`../../../sources/hyperbased.source.json`.

The first 50 seconds play on the existing PAL/6581 four-channel PCM player.
This retains 16 reusable original instrument samples; it does not store a
50-second mixed recording in C64 RAM. The corrected nearest-rounding mixer
runs at 3,848.625 DAC updates per second without residual error feedback.

- Playable program: `short/c64/stardust.prg`, 31,051 bytes, ends at `$814A`.
- Actual VICE recording: `short/vice/stardust-listening.wav`, 50 seconds.
- Actual VICE listening excerpt: `short/vice/stardust-preview.wav`, seconds 30–50.
- Independent original: `original/original.wav`, 333.84 seconds.
- Original excerpt: `original/original-preview.wav`, seconds 30–50.

The shared tools retain the historical `stardust` output filenames; this
folder contains Hyperbased, not Stardust Memories.

Both the register and audio captures completed 2,500 ticks with zero
prefetch underruns. All 192,431 expected DAC bytes match the actual VICE bus
trace exactly. Clock phase spans 153 cycles and ends +1 cycle from the ideal
sample schedule. Individual DAC intervals span 197–352 cycles around the
256-cycle timer; this is not a claim of constant interrupt latency.

`short/reference/reference.json`, `short/reference/trace-check.json` and
`short/vice/capture.json` contain the corresponding receipts. Rebuilding the
short arrangement after correcting its metadata title produced the same PRG
SHA256 as the actual capture:
`95e0d8ed1c9598c716edd3ad004e30e3cfde2da59e363bb2b678cec81a3e69c9`.

The independent libopenmpt render agrees on all 16,692 order/row/pattern/speed
ticks over 333.84 seconds. A separate controlled original-sample replay
comparison gives waveform correlation 0.9311 and tick-envelope correlation
0.999730. These checks do not establish perceived sound quality.

## Full-song memory limit

The unchanged-quality full resident build does not fit. Its compressed score
alone occupies 49,666 bytes, plus 23,619 source-bank bytes before loop
expansion and player overhead. The attempted end address is `$130C2`, beyond
the `$D000` limit. `full/build-failure.json` records this failure. Files under
`full/c64/` are failed build evidence and must not be used as a playable
program. No full-song C64 execution or listening capture is claimed.
