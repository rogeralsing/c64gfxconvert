# Hyperbased: full-length work within stock C64 limits

This is the historical budget and experiment plan. The native note decoder,
instrument programs and complete arrangement are now implemented; see
[the full-length implementation notes](../../../FULL-LENGTH.md) and the current
build's verification receipt. The measurements below retain their original
diagnostic scope.

Hyperbased stays active. [Druid 2 on piano is queued](../../../REPERTOIRE.md).
The canonical twenty-second player and its accepted reference files remain
unchanged. This directory contains control-data measurements and a deliberately
incomplete technical diagnostic, not a new full-song port.

## Representation and voice choices

Choose the representation per instrument and musical passage. Prefer reusable
SID instrument programs when they preserve the part's character. Keep distinctive
samples, especially orchestral attacks, when synthesis does not match. Bass and
drums may use SID, periodic waveform tables or original samples; none is mandatory
solely because of its tracker channel.

The starting physical allocation is two ordinary SID voices plus one Linus-style
sample-and-hold voice with a specialized software mixer. This follows the general
division described in [Platform Hopping](https://linusakesson.net/music/platform-hopping/index.php),
but it does not establish that arbitrary MOD sample combinations fit. Two fully
general pitched sample channels are substantially more expensive than a periodic
bass waveform plus fixed-pitch percussion.

Store each instrument or small pitch family once, with separate notes, effects
and loop metadata. Do not create gain/phase/time-specific audio windows for the
whole timeline. Do not add GeoRAM to make the result fit.

## Full-song control data: measured

The pinned source has 45 patterns, 64 orders and 16,692 twenty-millisecond ticks,
covering 333.84 seconds. Its original waves total 137,766 bytes.

The [data-only score experiment](../../../studies/score_events.py) preserves
all 66,768 normalized channel states: 4,844 real triggers, 5,513 pitch changes,
volume changes, repeat targets and any offset/DMA markers. Exact integer volume
ramps replace 15,314 individual gain updates.

| Representation | Bytes |
| --- | ---: |
| Delta/event/wait commands with volume ramps | 54,464 |
| Bounded LZSS stream, including header | 14,618 |
| Required LZSS history | 4,096 |
| Stream plus history | 18,714 |

Both control decoding and LZSS roundtrip exactly in the host measurement. The
largest decoded event frame is 27 bytes. The native C64 streaming decoder is
not implemented or timed yet. These numbers exclude instruments and player code.
See [score-budget.json](score-budget.json). Offline zlib/LZMA sizes in that report
are comparisons only, not available C64 decoders.

## One-sampler engine: actual VICE proof

The [diagnostic](native-probe/verification.json) runs the accepted first twenty
seconds of C1 software bass and C4 drums through SID3. It computes bass phase and
drum position natively; it does not store triangle run programs or C3 pitch/gain
waveform variants. The six triangle volume tables occupy 1,536 bytes, replacing
9,472 bytes of phase-dependent triangle RLE.

| Measured item | Result |
| --- | ---: |
| Exact SID3 values/prefixes | 156,389 |
| Sample interval | 126 PAL cycles |
| Exact SID1 writes | 3,000 |
| Buffer misses | 0 |
| NMI CPU | 61.19% |
| Bass/drum preparation CPU | 27.61% |
| Main control and busy waiting | 11.20% |
| Maximum NMI | 117 cycles |
| Minimum foreground buffer margin | 1,986 cycles |
| Triangle and drum waveform assets | 6,960 bytes |
| Temporary uncompressed diagnostic score | 13,000 bytes |
| Diagnostic PRG | 29,719 bytes |

The residual is not uniformly free CPU. The compact note decoder and more SID
instrument processing must be measured with the mixer. The calibrated startup
matches the reference epoch; no host alignment is used. A clean rebuild produces
the same PRG bytes.

**Original C3 is intentionally absent.** SID2 executes silent ordinary TEST
states to measure its register-update path. The actual
[diagnostic WAV](native-probe/diagnostic.wav) therefore is not a replacement
Hyperbased mix. The [PRG](native-probe/player.prg) is a mechanical budget proof,
not a complete arrangement or a demonstration of two generic PCM streams.

## Instrument-memory estimates

One filtered base bank per instrument at the high-rate sample clock gives these
nominal allocations, with native pitch/gain handling afterward:

| Candidate pool | Waveform bytes |
| --- | ---: |
| Drums 2/3/4/5/6/9/10 | 5,006 |
| Above plus bass8 and orch-hit11 | 8,852 |
| Above plus lead23 and drop22 | 12,110 |
| Above plus all special one-shots17–21 | 19,590 |

These estimates choose a decimation factor from each instrument's fastest used
pitch. They exclude alignment, interpolation guards and metadata. A single
global filter can dull lower notes. The simple eight-bit fractional-step model
also produces bass8 pitch errors from -13.80 to +10.08 cents. These banks are
therefore allocation estimates, not listening-equivalent instrument assets.
Use higher precision or a small number of pitch families where needed.

For the basic bass8/drums/orchestra pool, a shared exact gain table for 53 used
volumes adds 13,568 bytes. The basic waves, that gain table, full-song stream and
history total 41,134 bytes before code, buffers, SID programs and alignment.
This is a starting ledger, not proof that the final arrangement fits.

Do not use one strategy for every instrument. Bass8 has 46 period values and
180 audible held-pitch changes; all pitched copies would occupy about 125,375
bytes before gains. Fixed-pitch percussion has few pitch choices and can use
cheap integer cursors. Rare slow drum hits also need care: blindly upsampling
them creates long banks. Small pitch families, a slow native cursor or a suitable
SID percussion program are alternatives that require listening/CPU checks.

## Candidate musical allocation

This is a test plan rather than an approved arrangement:

- Early phrases: ordinary SID for C2 lead/chords and a suitable C1 bass sound;
  sampled C3 orchestral attacks/bass and C4 drums share the PCM path when its
  specialized kernels fit. Keep orch-hit11 sampled unless a richer SID program
  passes a complete-phrase comparison; do not restore the rejected flute.
- Later leads14/23/24: build SID programs with waveform/PW/envelope changes and
  compare whole phrases against the original channels.
- Around 181.10–247.28 seconds, three lead lines plus bass compete. Measure the selected
  sample combination and report any necessary omitted part.
- Around 247.28–283.68 seconds, C1 becomes bass and C2 percussion while C3/C4 become
  chord/lead parts. The physical allocation must change with these roles.
- Special one-shots17–21 may keep their original samples, with another suitable
  part moving to SID temporarily. Do not assume tracker C4 is always percussion.

## Work required before claiming full length

1. Implement and time the native streaming note decoder and exact volume ramps.
2. Audition instrument programs and retained samples one instrument/phrase at a
   time; preserve the approved reference separately.
3. Implement only the needed sample cursors, ends, loops, gains and pitch effects.
   Test dense overlapping passages rather than extrapolating this diagnostic.
4. Link all selected banks, note data, history, code and buffers within actual
   stock-C64 address ranges. Count lookup tables and alignment too.
5. Run the complete timeline in VICE and deliver the mix plus isolated physical
   SID stems. Verify clocks, native mixing, buffer causality and constant master
   volume. Record every omitted passage and distinguish fidelity from correctness.
