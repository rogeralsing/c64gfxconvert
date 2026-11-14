# CPU profile and exact-audio optimizations

This report describes the preserved twenty-second dual-sampler reference.
The [full-length arrangement](FULL-LENGTH.md) uses native SID programs and
decodes its compact note stream one tick ahead. Its generated CPU receipt is
separate; do not apply the percentages below to the complete song.

Profiling identified the interrupt as the largest cost. The merged changes
shorten its return paths and replace C3's per-output fractional oscillator
with compiled fixed-pitch instrument windows and an unrolled copy.
The complete SID register dump and all four listening WAVs remain
byte-identical to the pre-optimization baseline. Neither sample clock changes.

## Where the time goes

The measured interval contains **19,704,888 PAL CPU cycles**. These four
exclusive buckets account for the complete interval:

| Work | Before, cycles | Before, CPU | After, cycles | After, CPU |
| --- | ---: | ---: | ---: | ---: |
| NMI, including hardware entry and RTI | 14,271,492 | 72.426151% | 13,976,490 | 70.929051% |
| SID 3 bass/drum fill | 3,440,881 | 17.462068% | 3,440,890 | 17.462114% |
| C3 producer calls | 1,403,212 | 7.121137% | 846,017 | 4.293437% |
| Main control and busy waiting | 589,303 | 2.990644% | 1,441,491 | 7.315398% |

The source receipts are the
[baseline attribution](work/hyperbased/linus-mix/optimization-check.json)
and [current attribution](work/hyperbased/linus-mix/budget/cpu-attribution.json).
The main-control bucket includes required guards, branches and waits. It is
not a guarantee that all 7.32% can meet an arbitrary new deadline.

The profiler runs the assembled PRG unchanged in VICE. Monitor tracepoints
observe instruction starts; hardware entry, RTI and subroutine completion
costs are then accounted explicitly. NMI overlap is removed from foreground
intervals, so a cycle belongs to only one bucket.

The interval runs from the first hardware NMI entry to the last hardware NMI
entry: **156,388 intervals × 126 cycles**. Startup, including **250 prefilled
C3 ring values**, and the final non-returning shutdown path are outside it.
The bass/drum bucket includes the fill body and return; its caller's six-cycle
JSR belongs to main control. This convention matters when comparing totals.

## Interrupt costs

The baseline NMI's exclusive instruction attribution is below. These costs
are all inside the NMI bucket above, rather than additional CPU usage.
Per-interrupt averages and percentages are rounded here:

| Baseline NMI work | Average cycles/NMI | Total CPU |
| --- | ---: | ---: |
| SID 3 loads and stores | 32.000 | 25.397% |
| Hardware entry and RTI | 13.000 | 10.317% |
| CIA vector, A save and jitter synchronization | 14.625 | 11.607% |
| SID 2 loads and stores | 6.500 | 5.159% |
| Phase dispatch, progression and chaining | 10.250 | 8.135% |
| Buffer/ring cursors and boundary tests | 9.250 | 7.341% |
| Restore A and jump to RTI | 5.250 | 4.167% |
| Boundary additions | 0.173 | 0.137% |
| SID 1 commit loads and stores | 0.134 | 0.106% |
| Pending alignment/control additions | 0.075 | 0.060% |

The SID 3 prefix already consists of straight-line instructions. Its five
stores cost 20 cycles and its loads cost 12. The register-write gaps determine
the oscillator transfer. Replacing a load with a shorter instruction would
require padding to retain those same write cycles; unrolling this prefix
does not remove a loop.

The useful change is after the fixed register slots: ordinary phase returns
restore A and return directly instead of chaining through the shared tail.
Phase 0 retains its BNE boundary path so shutdown after the terminal SID 2
phase occurs at exactly the original cycles. Phases 2 and 3 use their inline BEQ boundary
paths. Full-stream comparison checks the final phase as well as ordinary ones.
Measured NMI usage falls by **1.497100 percentage points**.

## Compiled pitch and the copy LUT

The compiler expands the original instrument/step/gain waveform at the
required pitch. For elapsed output index `n`, it selects the same source
position `floor(n × step / 256)` as the original fractional model. The resulting
banks remain reusable instrument windows; they contain no combined channel
recording. There are **136 logical windows**, **135 resident nonconstant
windows**, and a shared neutral output. Eighty-five windows are reused across
multiple note instances.

The runtime keeps a 16-bit integer elapsed-output cursor. A real note trigger
resets it. Gain changes select another bank while retaining its position;
muted active spans advance it, and ended tails hold it. Original per-frame
active-prefix counts preserve sample lifetimes. Every one of the **39,097**
frequency-high values is checked against the previous source model.

This trades flexibility for CPU time: a new pitch or gain needs a derived bank.
The current phrase has no held-pitch changes. The fractional source model is
compiler intermediate data, with no fractional DSP in the native output loop.

The copy body repeats this four-instruction sequence:

```asm
    lda (c3_source_pointer),y
    sta $0600,x
    iny
    inx
```

It costs 14 cycles per value, or 15 when the source read crosses a page. X wraps
within the 256-byte ring; Y tracks the current source frame. Thirty-two copies
are laid out consecutively. A **66-byte low/high address LUT** chooses the
suffix that emits exactly 1–32 values, removing per-value counter updates and
loop branches. Short tails neither read nor write padded values. Ended neutral
spans use their separate 16-value unroll or a bounded short loop.

Both 16- and 32-value copy candidates were measured independently. The selected
candidate's producer kernels, including neutral paths, average **15.29
cycles/value** with setup and JSR/RTS costs. The complete producer, manager and
active background guards cost more:

| Complete C3 stream cost | Before | Merged result |
| --- | ---: | ---: |
| Foreground cycles, including background control | 1,490,691 | 910,652 |
| Cycles per output value | 38.1280 | 23.2921 |

That is a **38.91% reduction** for this complete C3 cost. The isolated COPY32
candidate saved 38.75%; the final return-path change also changes background
control costs. These totals cover all 39,097 ring values, including prefill,
and include active background guards. They have a different scope from the
exclusive playback-only C3 bucket in the first table. Idle waits and the final
exit into each wait are excluded from the producer-control total.

## RAM and deadline results

| Measurement | Before | Merged result |
| --- | ---: | ---: |
| C3 resident waveform bytes | 13,199 | 14,146 |
| Instrument data, score and tables | 41,841 | 41,316 |
| Startup code copied into zero page | 199 bytes | 139 bytes |
| Conservative RAM budget, including stack | 49,903 bytes | 49,843 bytes |
| Standalone PRG | 48,138 bytes | 48,138 bytes |
| Minimum SID 3 foreground deadline margin | 543 cycles | 1,006 cycles |
| Longest producer call, including manager | 622 cycles | 560 cycles |
| Longest complete NMI | 125 cycles | 125 cycles |
| Minimum pointer-commit margin | 13 cycles | 13 cycles |
| Minimum C3 write-to-read margin | 63,577 cycles | 82,225 cycles |
| Maximum occupied C3 ring entries | 250 of 256 | 250 of 256 |

The fixed-pitch waves add 947 bytes. Two 137-entry pointer tables add 40 bytes,
while removing the unused C3 index/field tables saves 1,512 bytes. The net
resident-data saving is **525 bytes**. The copied zero-page code shrinks by
60 bytes because the old fractional producer kernel is gone. PRG size includes
its memory layout and gaps, so it does not shrink by the resident-data delta.

These memory figures apply only to the measured twenty-second phrase. Fixed
instrument/pitch/gain variants can grow with additional instruments and effects;
the result does not prove that a complete song fits. Measure that growth before
extending the player, and keep sampling within the agreed CPU/memory limits.

The new minimum producer lead is **83.46 ms** at the PAL clock. These are
complete-phrase measurements with the display disabled. Screen-on playback
and physical SID hardware remain unverified.

## Correctness and reproduction

Use the single command in [README.md](README.md). Its
[verification receipt](work/hyperbased/linus-mix/verification.json) contains
strict streams for the mix, each physical stem and the muted control; causal
ring checks; CPU measurements; and independent VICE audio captures.
The all-muted capture matches a static-SID control.

The merged PRG changes, but the entire SID register dump and all four listening
WAVs match the optimization baseline byte for byte. The older accepted stem
comparison and its small existing capture differences remain documented in
[DUAL-SAMPLER.md](DUAL-SAMPLER.md). No gain, sample-rate, alignment, EQ or host
mixing change is used to obtain the optimization comparison.
