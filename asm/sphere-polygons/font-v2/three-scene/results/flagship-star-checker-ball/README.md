# One C64 PRG: fast star, then checkerboard ball

The script runs STAR zoom, normal, wave, checkerboard, V mirror, H mirror, both mirrors; then the same seven effects for BALL; then repeats STAR. Each phase is501PALfields (9.9951s); all14phases total139.9315s. Each object has48animated source poses (originaloddposes1,3,…95) plus startupblank0. The star advances twice as far per source image as the previous96-pose player. Object handoffs reset local source time to1 before hidden rendering.

**W/A/S/D** pans the20×12-source-cell zoom crop. Default10,6; x0…20,y0…13. Offsets persist between objects. Both objects share the unchanged locked2048-byte font and corrected H/V maps, with separate1024-byte empirically matched zoom tables.

## Verified

The assembled host proof passes1168images, all48poses for both objects/all seven effects, crops, early history, keyboard behavior, both source-clock resets, all14timer intervals and70637IRQ injections.

The focused native PAL proof passes817consecutive actual scanouts. It covers all48fast-star zoom poses and all48ball zoom poses, four ball crop corners, all effect/object pointer selections, and both object handoffs. Every visible pixel matches independent full-screen source references; font/front/source/LUT write guards pass. Ball zoom runs its complete501physical fields without timer adjustment:247images/9.9951s=24.7121fps including the short boundary hold, with25.0623fps steady two-field cadence. Other effects were advanced through declared9-field timer injections after sample images; this is not a native140-second timing run. Physical keyboard injection is not claimed by this minimized proof.

Native sampled ball cadence is25.06fps zoom/mirrors,16.71normal,12.53wave,10.02checker. These are short samples; see timing.json. The9-field preparation margin keeps phase deadlines despite the heavier ball checker renderer.

PRG loading ends atCFDF, below the I/O gap. A1434-byte blob staged at2B00 is copied after01=35 toE000–E59A at boot. Native proof verifies all98runtime source frames and actually renders relocated ball poses46–48; no source frame crosses I/O or reserved interrupt vectors. Main RAM46,639bytes, plus separate1024four-bit color RAM cells. Two output screens and one500-byte row-pointer cache; no image history or stored140-second output movie.

`native-contact.png` contains nine real scanouts. Individual field PNGs remain only in ignored build/pal-proof output. JSON receipts and frozen input/source hashes are included.

## Reproduce

From this archive, with KickAss, VICE and py65 available:

```sh
rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm -o rebuilt.prg
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-star-ball-player.cjs --input inputs/scene-data --output rebuilt
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-star-ball-player.py --build rebuilt --data inputs/scene-data --output rebuilt/pal-proof
```
