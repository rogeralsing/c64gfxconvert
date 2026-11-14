# Hyperbased arrangement: 3:00

The user selected the musical ending at exactly three minutes. The active
arrangement therefore plays the first 9,000 ticks, with 180-second listening
WAVs. The pinned MOD's complete 16,692-tick traversal is still validated before
selecting that interval. Do not restore its 333.84-second ending automatically.
The target remains an unexpanded PAL C64 with MOS8580 + digiboost in VICE.
The preserved twenty-second reference is a separate, unchanged artifact.

## Build

From the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --full
```

Use `--assemble-only` to assemble without running VICE. Omitting `--full`
rebuilds the preserved twenty-second arrangement. There is one public build
entry point; the helpers are not alternative music players.

## Representation

Two ordinary SID voices run reusable native instrument programs. A third voice
uses the Linus-style oscillator sample-and-hold technique at 126 PAL cycles per
value, approximately 7,819.43 Hz. The C64 adds a software triangle oscillator to
one reused PCM stream before sending the result to this voice. Master volume
remains constant throughout playback.

The physical roles change with musical passages. Original orchestral attacks
remain reused instrument samples. All active source parts have assigned
outputs in the selected three-minute interval. The later third-lead section
and instrument22 effect are outside the chosen ending.

Each source instrument has a reusable declaration under
`native_instruments/hyperbased_full/`. `full-length-sid.asm` executes the ordinary
SID programs. An exact frequency dictionary and chord-tone tables preserve
the selected pitches without storing per-tick PWM/register automation.

PCM gain uses native full, half, quarter and silent kernels. Silent playback
continues advancing the sample cursor. Instrument ends, loop wraps and triangle
phase are computed on C64. Only unread one-shot tails are removed: the selected
interval saves 3,903 bytes without changing any of its 1,407,497 intended mixed
input values. The complete SID3 input stream matches the previous longer
arrangement's prefix exactly. SID1's approved envelope behavior is repaired
as described below; other channel data and banks remain unchanged.

## Memory and scheduling

Reusable PCM banks including guards occupy 16,320 bytes; nine triangle volume
tables occupy 2,304 bytes. The linked compressed control stream currently uses
11,733 bytes, with a separate 4,096-byte history. The native score decoder uses
1,708 bytes; the selected SID programs and tables use 1,375 bytes. Count runtime code, buffers,
stack, alignment and all reserved address ranges as well; the generated memory
ledger records the actual layout.

The disk-loadable PRG is 51,201 bytes and includes unused address gaps. It does
not require external RAM, bank-switched instrument storage or a host process
during playback. BASIC/KERNAL are mapped out at startup while I/O remains mapped
in. The assembled native image still spans 62,816 file bytes; it is retained as
`native.prg` in build output, not delivered as the ordinary-load player.

`prg_loader.py` packages the native image without changing instruments, notes,
timing code or playback addresses. A 189-byte loader and 3,423-byte high-code
payload occupy unused `$58C0..$66DB` during startup. The disk file ends at
`$CFFF`, so KERNAL LOAD never writes its padding to active I/O registers. After
banking ROM out, the loader copies the high code to `$F000..$FD5E`, clears the
`$E000..$EFFF` decoder history, restores the original three entry bytes and jumps
to the original `$080E` entry. No music is synthesized by the loader.

Control decoding runs one tick ahead of the mixer. This is necessary: the
initial longer arrangement produced correct sample values but completed 621
buffers late. Decoding ahead removed those late completions. Current native
SID state and trigger flags remain separate from future decoded note state.

The generated CPU receipt measures the complete selected interval and separates
interrupts, native synthesis/mixing, note decoding and main control. Its wait
bucket is not uniformly available time for another sampler. Do not reuse the
longer version's percentages or minimum margins as measurements of this build.

For the current 9,000 ticks, NMI uses 61.1957%, synthesis/mixing 30.5092%, score
decoding 2.8212%, and control/waiting 5.4739%. Minimum foreground slack is 347
cycles, with the fill returning at least 883 cycles before the consuming
hardware NMI entry. Maximum NMI time remains 118 cycles.

## Musical limits

This is an arrangement, not an exact Amiga replay. Ordinary SID timbres,
arpeggiated chords and software triangle bass are approximations. PCM volume
maps to four declared gain levels. Some percussion uses native SID programs.

There are no active source-part allocation omissions before the selected end.
The longer version's C3 instrument22 and percussion omissions occur after this
interval. The generated `coverage.json` records the selected interval only;
`instruments/routing.json` keeps its routing timeline. Assigned parts and
correct pitches do not establish identical Amiga timbres.

The first 1,000 source-C2 frequency/control triples retain the accepted melody.
Its accepted sustain and continuous-GATE policy must also survive TEST rests;
matching frequency/CONTROL values alone previously hid a silent envelope.
The real SID1 recording now passes all 122 reference passages before delivery.
See [the regression and narrow repair](SID1-REGRESSION.md).
The full arrangement's routing, ordinary-voice instruments and startup differ
from the bounded reference; its WAV is not claimed byte-identical to that
reference. Listening approval remains separate from digital correctness.

## Verification and recording

The builder verifies all native sample prefixes and values, ordinary SID
registers, source-tick count, constant master volume and exact shutdown. It
traces every complete buffer before its consuming hardware activation. CPU
profiling separates NMI time, native instrument/mix work, prefetched decoding
and main-loop control without counting interrupt time twice.

The complete PRG must run through VICE's default true-drive disk autostart
mode2. The previous mode1-only check used direct RAM injection and missed the
flat image's writes through I/O during LOAD. Mode0 virtual-filesystem traps also
load the old flat image successfully, so that mode alone does not cover this
regression. `verify_prg_startup.py` checks restored native RAM before original
entry, then continues without manual LOAD, SYS or an addressed monitor jump.
It supports mode2 and a faster supplementary mode0 check. Allow sufficient
startup time for the serial disk load before counting musical playback.
Mix and physical SID
stems are independently recorded with the same producer workload, native time
origin and listening gain. The all-muted run is compared with an independently
static SID control. Audio processing is limited to native-clock cropping,
DC removal and one shared constant gain. No host mixing, EQ or timing alignment
is used.

Each output WAV contains exactly 3,969,000 frames at 22,050 Hz. Keep listening
gain 3.6308204724132565 from the longer version. The PRG stops on the nearest
126-cycle sample boundary for its 9,000 ticks; do not add a host fade to mask
the player's ending.

Muted ordinary voices keep TEST set and GATE clear (`$18`), with zero frequency
and sustain. Keeping GATE set (`$19`) while replaying native gate retriggers
produced audible envelope/DC transients despite zero sustain. The static-mute
comparison catches this fault; correct sample bytes alone do not establish
clean stem isolation.

See the generated `verification.json` for the result of the current build.
Physical SID fidelity and screen-on operation remain unverified.
