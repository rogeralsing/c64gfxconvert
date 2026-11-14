# Original Level 1 music

`music-source.sid` is an unchanged, self-contained copy of
`../../experiments/mod-hybrid/sources/sid-examples/hvsc/Great_Giana_Sisters.sid`.
Its SHA-256 is
`014764e6ee11df4b458c6b30e235ea639d702bd56766a87b5e90d4737558b1c8`.
The music is by Chris Hülsbeck for the original C64 game.
Archive source: [HVSC's original SID file](https://www.hvsc.c64.org/download/C64Music/MUSICIANS/H/Huelsbeck_Chris/Great_Giana_Sisters.sid),
credited in its header as © 1987 Time Warp.

`prepare-music.py` reads the RSID header and embedded load word, then extracts
the complete 7,709-byte native player/score block stored at `$71E3..$8FFF` in
the SID payload. Its runtime addresses are the original `$41C0..$5FDC`.
The block is copied without changing any bytes. `music-original.bin` has SHA-256
`09ed883e8991e224604eda00b1ff3c7219f815f4e0de4b033ecd1d2fb5bf3c4c`.

Those bytes were independently compared with the same range of the original
game's directory file `1`, PRG SHA-256
`0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880`.
The retained SID is sufficient for subsequent offline rebuilds; the cached game
PRG and disk image are not build dependencies.

## Level selection and calls

The original stage-start code at `$0AA3` executes `LDY $20; LDA $1529,Y; JSR $150C`.
Stage 1 reads `$152A = $01`. The request wrapper clears carry and calls `$41C9`.
This is internal music cue 1, corresponding to the retained SID's subtune 3.
The selection is also documented by the pinned native port's
[stage setup](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/state.rs)
and [original driver translation](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/sound_driver.rs).

The reference initialization sequence is `LDA #1; CLC; JSR $41C9`. The selector
enters `$49E6` and invokes the driver's initialization routine internally.
The standalone initialization vector `$41C3` points to `$4346`; it is exported
for completeness and does not require a second call before selecting cue 1.
Each normal PAL music tick calls `$41C0`, which jumps to `$439E`. The original
game performs this call at `$13E4`.

The entire native score module remains present, with its original score-driven
looping. The import does not select a timed excerpt, synthesize a replacement,
or convert the tune into recorded PCM. Audio loop duration is established by
the separate native/reference playback verification.

## Memory contract

`music.asm` emits the raw module at its caller's current address and asserts
the original `$41C0` base and 7,709-byte length. It includes constants and data
only; startup calls, memory banking, and tick scheduling belong to the scene.
The driver uses zero page `$A4..$B3` for normal cue-1 playback; `$A4..$B9` is
reserved conservatively.

Cue 1 reads `$4AB1 = 0` during selection and stores it in `$41EC` at `$4A21`.
This disables the optional sampler paths through `$AE00`, `$AFxx`, and CIA2
timer registers. Initialization still reads `$AC00/$AD00` into unused sampler
variables `$B4/$B5`; those values do not affect cue-1 SID playback.

Rebuild without network access:

```sh
python3 giana/tools/prepare-music.py
```

`music-import.json` records source identity, extraction offset, hashes, entry
points, cue mapping, and the full-module byte count.
