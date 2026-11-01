# AFLI hardware-sprite validation

Only the new `afli-sprite-viewer/validation/` files belong to this validation lane.
The existing renderer, player, captures, and user VICE processes stay untouched.

The baseline is the original `images/face-afl.afl`, decoded at all 320×200 source
pixels without a mask or overlay. Its file hash, palette and decoded-index hash
are recorded in `baseline-metadata.json`. The expected images are explicitly
source decodes, not emulator captures.

## Acceptance fixed before implementation

- Retain original source x112..319 over **all 200 rows**: 208×200 = 41,600 pixels.
- Overlay eight unexpanded, monochrome 24×21 hardware sprites, white index1,
  starting at source x112,136,160,184,208,232,256,280. Their combined field ends
  at source x303; x304..319 always displays the original AFLI.
- Hardware sprite X starts are136,160,184,208,232,256,280,304; X-MSB mask is `$e0`.
- The declared checker is4×3 blocks: each of the three bytes in local rowr is
  `$f0` when `floor(r/3)` is even, `$0f` otherwise;21 rows plus one padding byte.
- The builder's corrected proposed startup is Y register31 (visible raster32..52),
  prewritten to52 for visible raster53..73; subsequent Y values are73,94,115,… .
  If the AFLI starts at raster48, source row0 therefore sees local sprite row16,
  and source reuse boundaries are5,26,47,…194. Actual raster alignment and the
  complete write schedule still require the builder's receipt/trace before
  finalizing the composite oracle.
- The image's left112 pixels are outside the valid hardware image area. This
  explicit tradeoff does **not** permit dropping a top or bottom source row.
- A 50% checker row gives96 white pixels across eight sprites. Full200-row
  coverage must therefore yield19,200 opaque overlay positions and22,400
  preserved source positions, including transparent checker holes.

## Independent pixel oracle

Build the expected composite from the original decoded C64 indices and the
frozen intended checker function, positions, color and multiplex schedule.
Do not build expectations from a failed capture or from unexpected sprite RAM.
At opaque checker positions require white index1; everywhere else in the
208×200 area require the exact original source index. The bitmap image beneath
opaque checker pixels must also remain unchanged in RAM.

One21-row bitmap reused at+21 resets its vertical checker phase. In particular,
the last row of one reuse and first row of the next can have identical parity.
Declare whether this local reset or a continuous global checker is intended;
one shared pointer implies the former unless the bitmap is deliberately changed.
With the declared pre-image startup and an R48 image origin, check boundaries
4/5,25/26,…,193/194 and the last partial reuse through199. These are source
coordinates, not local sprite rows20/21.

Use the previously established VICE RGB-to-C64-index calibration as a fixed
mapping. Do not rename colors per capture to hide errors. Preserve original
384×272 PNGs. A single global image origin may be established from the declared
kernel geometry; per-row shifts, rescaling or Y cropping are not acceptance fixes.
Label expected composites and actual VICE captures separately.

## Hardware and memory evidence

Validate both VIC banks against the original image with only the builder's
declared left mask and reserved pointer-table updates. Source screen entries in
the valid26 character columns and all corresponding bitmap bytes must match,
including data hidden behind opaque sprites. Sprite pointer tables occupy
unused screen-page tails; validate those separately rather than treating them
as ordinary source screen bytes.

The proposed pointer `$fd` addresses `$7f40` and `$ff40`. Check the declared
63-byte pattern plus padding, all eight sprite pointers in all eight matrices
in both banks, eight enable bits, monochrome mode, expansion, sprite foreground
priority, white colors, X/MSB values, and every scheduled Y reuse. Register
snapshots from one instant alone cannot prove all200 rows; supplement them with
the declared raster write trace or equivalent diagnostics across the schedule.
Bank B's bootstrap copy ends at `$ffa3` (16,292 bytes). Validate that complete
payload plus the installed NMI/IRQ vectors; unrelated power-on tail bytes
`$ffa4..$fff9` and `$fffc..$fffd` are not image or sprite data and have no required
zero value. Bank A is fully initialized and can be compared across all16KB.
The pinned first-stage IRQ handler installs low byte`$e5`; active-image IRQ
vectors are therefore`$0ee5`, while the rearmed first-stage vector is`$0ec3`.
A code symbol named`row100` is an observation checkpoint, not a guarantee that
its first instruction executes on VIC raster100. Record the actual raster and
cycle from the monitor, require the exact symbol PC inside the active image,
and derive the expected live Y registers from the preceding code-row updates.

## Trial2 bottom-clear acceptance

The original Trial1 pass remains historical image/overlay evidence. Trial2 adds
an independent requirement before capture: raw PNG rectangle `[0,232,384,272)`
must be RGBblack at every one of15,360 positions in every sample. All previous
41,600 image pixels, source RAM, sprite data and repeated-frame checks remain.
Do not move the image origin or crop any Y rows to obtain a pass. Show the full
384×272 raw frame, enlarged only with nearest-neighbor rendering, so both the
graphics and hardware sprites being cleared below source row199 are visible.
Run `verify-capture.py --require-black-bottom` for Trial2 and later cleanup runs.

## Bounded stability proof

After the kernel is ready, capture at least three distinct advancing PAL frames,
with monitor execution resumed between captures. Record frame/raster progress
and include both bank phases if the kernel switches banks. Every capture must
match the same frozen41,600-pixel oracle, with matching image/index hashes and
the same geometry. Check source rows0,1,4,5,7,8,25,26,193,194,199 explicitly in diagnostics.
Preserve RAM dumps, resource settings, monitor logs and raw captures. Describe
the result as bounded repeated-frame evidence, not a proof of indefinite uptime.

The builder's receipt declares the checker bytes, intended image origin,
screen/bitmap layout, pointer padding, priority/expansion flags and Y-write
schedule; root's timing trace must confirm the alignment before the composite
oracle is finalized. A failed run must not shrink
the accepted208×200 source area or alter the intended checker pattern.
