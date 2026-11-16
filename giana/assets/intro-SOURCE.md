# Original Giana opening-sequence sprites

The opening sequence uses the original small Giana, the original electrical
transformation graphic, and the original striped beach ball. The accepted punk
Giana atlas remains separate and unchanged.

## Source identity

The retained source slices come from directory file `1` of the verified
[original C64 disk](https://github.com/Zibri/The-Great-Giana-Sisters-C64-D64/blob/f99e2b9477badce359ad068d7b3f5f981082a73c/The%20Great%20Giana%20Sisters%20ORIGINAL.d64).
The complete PRG contains 63,443 bytes, loads at `$0820`, and has SHA-256
`0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880`.

| Retained input | Original addresses | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `original-intro-small-walk.bin` | `$A080..$A37F` | 768 | `169267a5a7cecd5132dd4c509a8c462bbe558208e927d278bdf8a479e1526833` |
| `original-intro-small-jump.bin` | `$A680..$A73F` | 192 | `192d22864c0dd217bfbf8cb801e501c5e5beb25518285a743f805c348dd726b3` |
| `original-intro-electric.bin` | `$D740..$D7FF` | 192 | `46e6c9cc8c90f92d2a933f7fe9d5d6915a958bb020c038fabbab4ea7aabf3066` |
| `original-intro-ball.bin` | `$EE40..$EE7F`, then `$F000..$F03F` | 128 | `0832cc04daeff9213d23124e9ec3bcc5a3f442ccd61e9ed528ad85de5377d00d` |

The original player swaps its active `$CC00..$D5FF` sprite bank with
`$A080..$AA7F` at power-up. The unmodified PRG stores the normal artwork in the
latter bank, identified by its byte `$A083 = 3`; its `$CC03` byte differs.
The [ported original sprite-bank routines](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/state.rs)
document the same test and exchange at `$14DC` and `$1474`.

Small Giana uses walking triplets `$30/$31/$32` and `$36/$37/$38`, plus the
right-facing jumping triplet `$48/$49/$4A`, from the normal bank. Their layer
colors are 7, 6 and 1; the first two layers are multicolor and the third hires.
Layer Y offsets are 0, 1 and 2. The electrical pose is the fixed triplet
`$5D/$5E/$5F`, with three hires layers colored 7, 1 and 7. Each source image is
composited in original sprite-priority order before reduction.

The ball is original type 11, whose descriptor starts at `$3126`. It alternates
sprite pointers `$B9/$C0` with individual color 7 and shared colors 10 and 2.
The first Stage 1 dynamic pickup record at `$3D64` contains `(48,10,11)`.
The original [enemy loader](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/enemy.rs)
selects the pickup type through `$3032 + powerupState`.

## Reduction and atlas

The existing `prepare-sprites.py` area-vote and hardware-packing helpers provide
the reduction. Four original horizontal pixels contribute to each output
multicolor pixel. Small Giana's complete 23-row composite becomes eight rows;
the electrical pose becomes ten. The ball's five transparent top rows are
discarded, and all sixteen remaining rows contribute to its six-row canvas.
Player coverage uses a 20% threshold and the ball uses 50%.

Small Giana retains yellow hair, blue clothing, skin and red. Her white source
details approximate skin color, matching the accepted punk sprite's palette.
The electrical pose retains yellow and white on two planes. All three original
ball colors survive in both reduced poses.

`intro-sprites.bin` contains exactly ten standard 64-byte sprite planes:

| Relative plane | Contents | Individual color | Canvas height |
| ---: | --- | ---: | ---: |
| 0–1 | Small walk pose 0, base and blue | 7, 6 | 8 |
| 2–3 | Small walk pose 2, base and blue | 7, 6 | 8 |
| 4–5 | Small jump, base and blue | 7, 6 | 8 |
| 6–7 | Electrical pose, yellow and white | 7, 1 | 10 |
| 8 | Beach ball `$B9` | 7 | 6 |
| 9 | Beach ball `$C0` | 7 | 6 |

All output planes use multicolor mode, code 0 transparency, and shared colors
10 and 2. Unused canvas bytes and byte 63 are zero. `intro-sprites.asm` exports
the relative indices, colors, heights, and `introSpriteFrames` labels. Its
640-byte source atlas can reside outside VIC-visible RAM because the existing
actor renderer copies selected planes into its VIC-visible working buffers.
`intro-import.json` records source spans, output hashes, bounding boxes, and
5,040 independently decoded physical output pixels. The preview places the
original art above each reduced pose.

## First-platform geometry

The original Stage 1 first platform occupies character columns 40–57 and rows
10–11. Its top is at source Y 80, or reduced Y 32. The first power-up brick
occupies columns 46–48 and rows 3–4, with marker `$F2` at column 47, row 3.
The original used-brick graphic contains `$4C/$4D/$4E` on its upper row and
`$4F/$50/$51` below. These are map coordinates, independent of the TV camera
and fixed perspective projection.

## Offline rebuild

```sh
python3 giana/tools/prepare-intro.py
```

To repeat extraction from the exact original PRG:

```sh
python3 giana/tools/prepare-intro.py --program giana/build/original-file1.prg
```

The original game graphics are by Manfred Trenz for Rainbow Arts and retain
their original ownership.
