# Native sphere implementation contract

This is a fixed-size, perspective sphere spinning around its own fixed tilted polar axis. Longitude is `U0(x,y) + spin/64`, while latitude stays fixed. It is a deliberate specialization of the direct tangent method. It must calculate screen codes on the 6510. No screen frames or frame deltas are stored.

Default geometry: 320×200, radius 94, camera distance 3.2, 12×6 checker cells, tilt 22°. Font is the existing mathematical 256-glyph bank. Pixel centers are x+0.5,y+0.5. A tile's center is x+4,y+4.

## Assets and record format

`assets/records.bin` contains one 13-byte record per active tile, in screen order:

| Offset | Field |
| --- | --- |
| 0 | screen offset low, 0..999 |
| 1 | screen offset high, 0..3 |
| 2 | flags: bit0 sparse fallback, bit1 latitude boundary, bit2 U half-normal reversed, bit3 sphere limb |
| 3 | base longitude phase, floor(U0*64)&127 |
| 4 | U scale row index, 0..31 |
| 5 | single-angle table base low (angle32 * 25), or limb remap base low when flag3 is set |
| 6 | single-angle table base high, or limb remap base high when flag3 is set |
| 7 | U half-angle base (angle8 * 9), 0..63 |
| 8 | latitude-only glyph when longitude parity is zero |
| 9 | latitude half-plane state, 0..71 |
| 10 | latitude half-plane value at tile center before offset quantization, 0 or 1 |
| 11 | latitude parity at tile center, 0 or 1 |
| 12 | U half-span in Q6 units, ceil(3.5*(abs(Ux)+abs(Uy))*64) |

`assets/probes.bin`: nine Q6 phase bytes per tile, positions [1,4,6]×[1,4,6] in glyph pixel coordinates. Phase = (floor(U0*64)&127) XOR (floor(V)&1 ?64:0). Runtime `((phase+spin)&64)!=0` is its checker value. Invalid probes are zeroed by the validity mask.

`assets/valid.bin`: two bytes per tile, a nine-bit validity mask, low then high.

`assets/scale-single.bin` and `assets/scale-pair.bin`: 32×64 bytes each. Row is the U scale, column is `(basePhase+spin)&63`. Nearest U boundary offset: if f<32, d=-f/64/|grad U|; otherwise d=(64-f)/64/|grad U|. Single output is clamp(round(d/0.5)+12,0,24). Pair output is clamp(round(d/1.25)+4,0,8). Scale representatives must be recorded in manifest. Selection of rows is derived only from the static geometry.

`assets/scale-lo.bin`, `assets/scale-hi.bin`: 32-byte row offsets (row*64), relative to each scale table.

`assets/single.bin`: 32 angles over 2π ×25 offsets at 0.5px, starting -6. The byte is the nearest fixed-font glyph for the mathematical half-plane.

`assets/xor.bin`: symmetric pair table for 72 half-plane states (8 angles over π, 9 offsets at1.25px, starting -5). Byte offset is max*(max+1)+2*min+polarity. Polarity0 represents XOR of the two half-planes; polarity1 complements it.

`assets/pair-lo.bin`, `assets/pair-hi.bin`: 72-entry row bases max*(max+1), relative to xor.bin.

`assets/inverse.bin`: exact complement glyph index for all256glyphs.

`assets/probe-lut.bin`:512-byte9-probe glyph lookup, derived only from font signatures. `assets/font.bin`:2048 bytes, C64 bit7=left.

`assets/glyph-compact.bin`: 256-byte map from the probe lookup's reachable glyph codes to 158 compact indices. `assets/limb-remap.bin`: 63 classes × 158 bytes. Each class has the same set of font glyphs contained entirely within its tiles' exact circle masks. The table chooses the closest allowed glyph to the original probe glyph. Limb records reuse fields 5/6 for `class*158`, relative to this page-aligned table. This is static font-and-geometry data, not animation data.

`assets/constants.asm`: .const SPHERE_TILE_COUNT, RECORD_SIZE=13, SPHERE_PHASE_STEP=4.

## Native tile algorithm

For every active tile, `phase=(basePhase+spin)&127`, `uParity=phase>>6`, `f=phase&63`. The global spin increments modulo128 after each completed render unless paused.

1. Sparse mode or record flag0: evaluate nine phase bytes, mask invalid points, get glyph from probe-lut. This is also the limb/pole fallback for analytic mode. For limb records (flag3), map the glyph through glyph-compact and the record's safe limb remap. Every lit pixel of the final glyph must lie inside the sphere's exact circle. Masking invalid probes alone does not constrain unsampled pixels in the glyph.
2. Otherwise, if min(f,64-f)>span: no U boundary. Use latitude-only glyph, complement when uParity=1.
3. U boundary: scale lookup gives single and pair offset indices.
4. No latitude boundary: single table at base+singleOffset gives half-plane glyph. The true center side is `f<32`, before offset quantization. Complement when `uParity XOR latitudeParity XOR centerSide` is1.
5. Latitude boundary: U pair offset is reflected (8-offset) if flags bit2. U state=halfAngleBase+pairOffset. The true center side is `(f<32) XOR bool(flags bit2)`. Polarity=`uParity XOR latitudeParity XOR UcenterSide XOR latitudeHalfCenterSide`. Pair lookup gives final glyph.

Never derive polarity from the rounded offset. A small positive distance can quantize to zero while the center remains on the negative side. Using the quantized center side would complement the entire glyph.

For each tile advance record pointer13, probe pointer9, valid pointer2 even when analytic mode does not use sparse data.

## Runtime and measurement

KickAssembler, code/data under ROM with $01=$35, no KERNAL IRQs. Color RAM is white and charset fixed. Use screen buffers $0400 and $0c00; font $2000. Code starts $3000 (BASIC SYS stub may be $0801). Use double buffering and switch $d018 only after a complete frame, at a raster boundary.

Export labels `render_start`, `render_end`, `frame_done`, `spin`, `mode`, `paused`, `frame_counter`, `front_screen_hi`. mode0=analytic, mode1=9probes. F1 may toggle mode, space pause. Never stop unrelated VICE processes.

Host assets module must export a native model returning1000screenbytes for given spin/mode, so emulator RAM can be compared byte-for-byte at frame_done. Expected images must be computed from this algorithm, not pre-recorded screenshots. The independent quality reference uses exact sphere intersections and UV functions with the same own-axis spin order.
