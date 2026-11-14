# Cream of the Earth — complete three-voice arrangement

The PRG and four WAV files cover the entire original timeline, 4:01.92.
They play 12,096 source ticks on an unexpanded C64. This extends the preserved
26.88-second reference rather than replacing it.

- [Full mix](all.wav)
- [SID1](sid-1.wav)
- [SID2](sid-2.wav)
- [SID3: Linus-style sampling](sid-3.wav)
- [Runnable PRG](player.prg)
- [Verification, CPU, memory and audio receipts](verification.json)
- [Every omitted source passage](coverage.json)
- [Approved passage within the full actual recording](audio-reference-check.json)
- [Clean rebuild](rebuild-check.json)

## What plays

SID1 follows original C3. SID2 follows C4 and also plays C1's pulse part during
the explicitly allocated introduction. SID3 reads C2's reused sample banks;
before C2 starts, it also plays C1's geioilsound introduction. C1 is omitted
outside that allocation. Silent gaps in another allocated track are not filled
automatically.

Later instrument changes are included: geioilsound, polysynth, clap and the
major/minor/sus4 chord samples have explicit programs or reused PCM banks.
Chord synthesis uses 50 Hz arpeggios instead of simultaneous chord partials.
Ordinary SID source volumes use the approved continuous-envelope on/off policy,
so their nonzero volume slides are simplified. PCM gain changes retain their
separate banks or native gain lookup tables. The new lookup gains differ from
the floating-point source quantization by at most one eight-bit code.

## Playback and memory

The C64 advances a persistent fractional Q8 cursor through reusable banks.
Four held pitch changes preserve that cursor and its fraction. Gain changes
also preserve position. This replaces per-pitch expansion, which would have
needed 58,280 bytes before other assets. No flattened song waveform is stored.

PCM banks including silence and guards use 16,896 bytes. Gain lookup pages use
5,888 bytes. The compressed control score uses 7,622 bytes with a separate
4,096-byte decoder history. The disk-loadable PRG is 51,201 bytes, including
address gaps and its startup loader. The loader starts in visible RAM at
`$C000`, banks ROM out and restores the original high code before playback.

The native clock is 126 PAL cycles per value, about 7,819.43 values/s. Master
volume stays constant during music; samples never use `$D418` amplitudes.
Screen blanking is intentional. Use PAL, reSID, MOS8580 + digiboost and
resampling method 2.

## Actual verification

All five output/mute variants check every one of 1,891,676 sample values and
prefixes, all ordinary SID register values, the complete tick count and exact
shutdown. They finish with zero late buffers. Full true-drive D64 autostart
passes; 53,272 native RAM bytes match before original entry. All five PRGs
reproduce byte for byte from a clean temporary build.

Full CPU tracing measures a maximum 118-cycle NMI, minimum foreground margin
931 cycles and 2,303 cycles before the consuming hardware NMI. The all-muted
producer and an independently static SID control differ by zero PCM16 LSB.
These measurements do not establish capacity for another sample lane.

Each WAV is an independent full-workload VICE capture: mono 22,050 Hz,
5,334,336 frames, 241.92 seconds, common gain 8. Processing is limited to a
native-clock crop, DC removal and that constant gain. No host mixing, EQ,
alignment, limiting or dynamics are used.

The approved original interval 17.92–44.80 is checked at its fixed native-clock
position within the complete recording. All 135 windows pass: RMS ratios
0.9895–1.0136 and minimum spectral cosine 0.9870. The rest of the song has
digital proof and the disclosed instrument approximations; it has not received
separate listening approval. The short Cream PRG/WAVs, Hyperbased and immutable
references remain unchanged.

Build from the repository root:

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --full
```
