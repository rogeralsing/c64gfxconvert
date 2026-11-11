# C64 MOD optimization study

Three subagents implemented and evaluated separate methods. The parent also
measured exact sample reachability and integrated the selected full-song builds.
Accepted sample banks and old binaries remain available for comparison.

**The strongest result is lossless score compression.** It makes complete
Hyperbased and Madness programs fit ordinary resident C64 memory. Automatic
sample looping is useful for selected instruments, but the large apparent
savings often remove evolving timbre. The selected full programs do not use
the lossy loop or envelope approximations.

## Methods and measured outcomes

| Method | Actual result | Fidelity and selection |
| --- | --- | --- |
| Shorter sustain loops | 269 candidates across 30 instrument cases. Conservative savings: 538 B for full Stardust, 1,190 B for the accepted Hyperbased 50 s test, 0 B for Madness. | Active-note and longest-note guards reject many larger apparent savings. A Hyperbased candidate was executed and recorded in VICE; it remains experimental. |
| Attack, periodic waveform and separate envelope | 18 points: three songs, three budgets, with/without envelope. Conservative envelope net savings: Stardust 7,121 B; Hyperbased 2,630 B; Madness **−245 B**. | Added volume commands consume score RAM. Envelopes improve some amplitude curves but retain timbre loss and do not clearly beat plain loops overall. Full Stardust candidate executed correctly in VICE. |
| Lossless score dictionaries | Net complete-program savings with unchanged banks: Stardust **8,446 B**, Madness **16,414 B**, Hyperbased **25,542 B**. | Selected. Complete restored score bytes and tick states match, with actual whole-song DAC verification. Decoder runs in foreground; no IRQ work is added. |
| Exact sample reachability | Complete-score savings including markers: Stardust **373 B**, Madness **79 B**, Hyperbased **46 B**. | All 923,670 / 1,566,544 / 1,284,825 modeled DAC bytes remain identical. Too small to be the main solution. Not needed in the selected builds. |

Sample methods count the player's minimum 256 stored loop bytes and all sample
markers. Envelope costs include the actually repacked score, not just the bank.
Those studies compare candidates with the same legacy score codec; dictionary
compression is evaluated separately. Numbers describe tested arrangements,
not a universal saving for every MOD or a globally optimal search.

## Selected complete programs

| Song | Duration | Program | Size | Whole-song actual DAC verification |
| --- | ---: | --- | ---: | ---: |
| Stardust Memories | 4:00 | [PRG](players/stardust-memories-full.prg) | 37,170 B | 923,670 bytes, zero mismatches |
| Hyperbased / A Final Hyperbase | 5:33.84 | [PRG](players/hyperbased-full.prg) | 50,429 B | 1,284,825 bytes, zero mismatches |
| 4-Mat's Madness | 6:47.04 | [PRG](players/4mats-madness-full.prg) | 45,039 B | 1,566,544 bytes, zero mismatches |

All three finish with zero prefetch underruns on PAL/6581 VICE. The sampled
output remains four-bit mono at 3,848.625 updates/s. Hyperbased ends at `$CCFC`,
772 bytes below the resident `$D000` limit. No REU or streaming is required.

Madness uses selected pitch-range sample-bank variants to retain the accepted
preview's less-filtered waveforms when the complete triggered note permits
them, with whole-song banks for higher notes. Bank selection occurs only at a
retrigger. Its first 192,427 DAC values match the accepted 50-second reference;
the equivalent short build matches all 192,431. Hyperbased's first 192,427
values likewise match the accepted gain-3 preview. Four EOF-adjacent slots are
excluded from full/short prefix comparisons because a full song continues
staging its next tick while a short score stops.

The retained gain-3 setting clips 0.145% of Hyperbased's modeled output values
and 0.462% of the selected Madness output values over their complete songs.
This is a pre-existing four-bit quantization tradeoff, separate from the
lossless score codec. Later full-song passages have not received a subjective
listening verdict from the user.

The original-bank Madness codec comparison is 56,143 B to 39,729 B. The selected
45,039 B Madness program spends some of those savings on the preferred bank
variants. The dictionary itself changes no waveforms, notes or effects.

The music remains credited to its original authors: Stardust Memories by
Jester / Sanity, Hyperbased by Firefox and Tip / Phenomena, and Madness by
4-Mat / Anarchy. Exact MOD sources and checksums are retained under
`../../sources/`.

## Listen

The release manifest records completed audio-capture status and file hashes.
Full new-only C64 recordings are [Hyperbased](audio/hyperbased-c64-full.wav)
and [Madness](audio/4mats-madness-c64-full.wav). Originals remain separate under
`../more-mods/{hyperbased,4mats-madness}/original/original.wav`.
Listening files use DC removal and constant gain only. They contain no old
version segments, host-side instrument mixing, EQ, limiter or time warping.

The optional lossy loop experiment has its own [new-only C64 excerpt](loops/hyperbased/conservative/hyperbased-loop-optimized-c64-30-40s.wav)
and [separate original](loops/hyperbased/conservative/hyperbased-original-30-40s.wav).
It is not used in the selected full songs.

Exact DAC agreement proves execution and compression correctness against the
prepared score. It does not make four-bit playback identical to the original
Amiga, establish subjective fidelity of new loop candidates, or prove real
hardware/8580 performance. Foreground decoding can change sub-sample IRQ
latency, so analog WAVs need not be bit-identical to earlier captures.

## Evidence and reproduction

- [Loop search](loops/README.md), including held-note failures, negative
  controls and the corrected independent-render timing.
- [Loop plus envelope](envelopes/README.md), including all 18 points, active
  contexts and whole-song actual C64 execution of the Stardust prototype.
- [Lossless score study](score/README.md), including RLE, two-byte and one-byte
  phrase dictionaries, net program sizes and unchanged default-binary checks.
- `reachability/*/evaluation.json`: complete-score exact sample-tail analysis.
- `combined/madness/`: preferred-bank integration, exact accepted-prefix
  checks, full register execution, full DAC comparison and captured audio.
- `manifest.json`: selected program/audio hashes and completion audit.
- `score/reproducibility/summary.json`: current sources reproduce all three
  selected PRGs and named symbols byte-for-byte. A post-build module-docstring
  edit is documented there; executable source was unchanged.

The builder remains backward-compatible. Select the new lossless codec with
`pcm4_build.py --score-codec dictionary8`. The default `legacy` reproduces the
previous Stardust and Madness binaries exactly. The new codec needs 62 bytes
of code/initialization and three zero-page bytes; in these builds its code
fits existing alignment padding. Phrase data and pointer tables are included
in every reported score size. The general zlib/LZMA figures in the score study
are offline payload bounds, not implemented or playable 6502 formats.
