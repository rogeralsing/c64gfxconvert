# Original tiny Giana and Stage 1 owl

These sprites use original C64 graphics, reduced to match the terrain scale.
No character pixels are hand-drawn. The first slice contains four right-walking
Giana poses and the two walking poses of the Stage 1 horned owl.

## Original data

Source: [`The Great Giana Sisters ORIGINAL.d64`](https://github.com/Zibri/The-Great-Giana-Sisters-C64-D64/blob/f99e2b9477badce359ad068d7b3f5f981082a73c/The%20Great%20Giana%20Sisters%20ORIGINAL.d64),
directory file `1`, loaded at `$0820`. Its 63,443-byte PRG has SHA-256
`0f1a720961fa52102fcfd52e46e40df07e5e307328ad087d55cc00506f904880`,
matching the [native port's original-program manifest](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-extract/src/lib.rs).
Only the required graphics slices are retained here:

| File | Original addresses | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `original-sprites-giana.bin` | `$CC00..$CEFF` | 768 | `00cc787a7bed3d67516782d9eb2816088844317a714d2e27d5c8e45beafc2944` |
| `original-sprites-owl.bin` | `$E480..$E4FF` | 128 | `a7852467282ae17687868613b1000f3392ba571519dee0b0aa258e24de5606c3` |
| `original-sprites-collision.bin` | `$9C20..$9D1F` | 256 | `667526cbc31e27d88d7e5871b646f96ff904d5b76b81494f29e425f41083b22b` |

The original [walking sequencer](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/player_move.rs)
selects Giana pointer triplets `$30/$31/$32`, `$33/$34/$35`, `$36/$37/$38`, and
`$39/$3A/$3B`. The three original layers share X and use Y offsets 0, 1, and 2.
They are composited in hardware priority order before reduction. The first two
layers are multicolor, with individual colors yellow `$7` and blue `$6`; the
third is hires white `$1`. Shared colors at `$9D20/$9D21` are skin `$A` and red `$2`.

The owl is original enemy type 5, with its record at `$30C0`. Its native walking
pointers are `$92/$93`, its individual color is white `$1`, and its shared colors
are the same skin/red pair. These values match the
[original enemy loader and animation cycle](https://github.com/kvnshroom/giana-sisters-native/blob/0cf76724e9ca1d18e84d749e3d10de416efa1544/crates/giana-core/src/enemy.rs).
The first ground-walking owl in Stage 1 is triggered at original map column 75.
The earlier object-list entry at column 48 selects a rolling eye; the owl is not
claimed to be the first enemy of every kind.

## Reduction and hardware format

Horizontal scale is 1/2 and vertical scale is 2/5, matching the terrain axes.
Area voting operates on the original colored pixels. Giana retains cells with
at least 20% foreground coverage; the owl uses 50% coverage to preserve its horns
and face at this size. Palette choices use RGB distance in the retained Peptoette
A palette. Giana's white highlights approximate skin `$A`; yellow hair, blue
clothing, skin, and red remain separate colors. The owl retains its native colors.

Each pose occupies standard 24×21 hardware sprite storage, with transparent
padding and a zero final padding byte. Code 0 is always transparent. Giana's
visible image is 12×10 physical pixels. The owl uses a 12×9 canvas with an actual
12×8 visible rectangle at Y 1–8. All four Giana poses and both owl poses remain
distinct after reduction.

Giana uses two hardware planes at the same coordinates. The base plane contains
skin in code 1, yellow in code 2, and red in code 3. Its overlay contains only
blue in code 2; all other overlay pixels are transparent. The owl uses one plane,
with skin in code 1, white in code 2, and red in code 3. Shared multicolors are
`SPRITE_MC0 = 10` and `SPRITE_MC1 = 2`.

`sprites.bin` contains ten 64-byte planes in this order:

```text
Giana0 base, Giana0 blue, Giana1 base, Giana1 blue,
Giana2 base, Giana2 blue, Giana3 base, Giana3 blue, Owl0, Owl1
```

`sprites.asm` exports the frame counts, plane counts, strides, offsets, colors,
canvas dimensions, and `tinySpriteFrames`/`tinySpriteFramesEnd` labels. The
640-byte atlas is immutable. At the reserved `$0C00` placement it ends at `$0E7F`;
three separate 64-byte working buffers fit after it through `$0F3F`.

## Demonstration movement

`sprite-ground.bin` contains one ground-top Y for each of the original 256 map
character columns. The owl uses this compact table. The preparer starts at row
19 and walks up the contiguous solid stack, using original collision
classifications `$01` and `$80`. An empty bottom cell produces `$FF`. The output
coordinate is `(16 * top_row + 2) // 5`. Green bushes remain decoration.

`sprite-player-path.bin` contains 512 foot-Y values, one per multicolor-pixel
camera step. A step lasts four PAL frames. Giana stays at screen X 10 with a
six-multicolor-pixel width. Her route uses every solid map layer, including
floating platforms, roofs, and ceilings. A pixel blocks movement only when its
original character is solid and its reduced terrain pixel is not sky code 1.
The exact perspective source-row mapping is applied separately at every pixel
of the sprite, including the region boundary crossing her body.

A finite offline search advances projected foot position and vertical velocity
in half-pixel units. Gravity adds half a pixel per step squared; grounded-only
launches range from 1.5 to 5 pixels per step, and falling speed stops at 5 pixels
per step. The search prefers supported walking and penalizes airtime, vertical
travel, takeoffs, and stronger launches. A descending body lands at the first
crossed sole support. An ascending body stops below a ceiling and then falls.
States outside the visible TV area are rejected rather than clamping a jump's
apex. There is no midair jump restart or forced periodic hop.

Collision uses the actual opaque pixels of each animated pose, including both
Giana planes. Owl encounters use their exact animated opaque pixels too. A
brief, genuinely supported owl-head landing can be followed by a new jump.
The actor must remain clear of the current terrain and the next camera image
that appears before its next update; vertical sweeps use the current image.

The resulting path stands on the floating platform at projected foot Y 32 for
all camera steps 80–100. The longest unsupported physical run is 15 steps.
Half-pixel ballistic apices can round to four identical displayed Y positions;
there are no long clamped plateaus. All 512 states remain visible and the final
foot closes onto the initial Y 54. This finite demonstration route is not an
implementation of the original game's control or physics engine.

The owl's world center is `(step & ~63) + 43`; it hides when ground is `$FF` or
numerically below Y 28. Its placement and the sprite art stay unchanged. Ground
and path data remain outside `sprites.asm` and the VIC-visible atlas allocation.
Their hashes, collision inputs, physical state sequence, support classification,
and chosen launches are recorded in `sprites-import.json`.

## Offline rebuild

From the repository root:

```sh
python3 giana/tools/prepare-sprites.py
```

To repeat extraction from the verified original PRG as well:

```sh
python3 giana/tools/prepare-sprites.py --program /path/to/original-file1.prg
```

The preparer verifies source hashes, decodes all 5,040 physical pixels of the ten
stored planes, and checks all 2,016 physical pixels of Giana's recombined poses.
The blue overlay contains only transparent/code-2 pixels, and every Giana pose
retains blue pixels. `sprites-import.json` records frame indices, source slices,
palettes, bounding boxes, approximations, and output hashes. `sprites-preview.png`
shows original art above its reduced counterpart when Pillow is installed.

Original game graphics are by Manfred Trenz for Rainbow Arts and retain their
original ownership.
