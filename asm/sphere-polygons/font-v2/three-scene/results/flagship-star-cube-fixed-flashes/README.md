# Star and gradient cube with fixed zoom flashes

One C64 PRG runs normal, wave, checkerboard, V mirror, H mirror and both mirrors for STAR, then CUBE, repeating. Each base phase lasts501PALfields (9.9951s), followed by a25-field fixed-crop zoom flash (0.4988s). The24-phase script totals125.9263s. Flashes advance2 of48source poses per image; base phases advance1. The cube uses the approved gradient-dithered scene and its own matched zoom lookup. Font and star source remain unchanged.

Each flash captures the WASD center once on entry and adds its fixed offset. The crop stays fixed for the entire flash, even when WASD changes the center; that new center is used by the next flash. Default center10,6; bounds x0…20,y0…13. The six offsets repeat for both objects: (0,0),(-3,-2),(2,0),(-1,2),(3,-1),(-2,1). There is no sinusoidal movement.

Checker mode colors the same4×4-character blocks as source phases A/B: purple4 for even parity, green5 for odd. All1024ColorRAM cells, including24unused cells, follow that rule. Other phases restore uniform foreground. Background and border retain the three global palette pairs.

## Evidence

Native PAL proof passed616consecutive actual colored scanouts. All12flashes retained their25real fields and exactly one crop each. Manual-center changes made during every flash left the active crop unchanged and affected the following entry. All48poses/object, both object handoffs, all crop bounds, exact Colodore pixels, side borders, checker ColorRAM parity and uniform-color restoration passed. Font/front/source/LUT/7FFF write guards passed.

Checker fills took5173wall cycles and ended at raster29; uniform fills5582cycles/raster35, both before visible51. The zero-byte high-copy branch was protected by a native E000–FFF9 store guard and made no writes; all98physical source frames matched after boot. No high payload is needed. Main RAM38,205bytes plus separate1024four-bit color cells.

The host proof covers1178images/63679IRQ injections, all24phase clocks and input cases. Additional actual-ASM boot fixtures cover zero bytes (39CPUcycles/nohighwrites) and257bytes (12385cycles/exactcopy/nooutsidewrites). These receipts are included. Native base phase timers were explicitly advanced after coverage; this is not a full126-second native playback run. Physical keyboard injection is outside this minimized proof.

`native-contact.png` contains nine real scanouts. Individual field PNGs remain in ignored build/pal-proof output. Detailed JSON receipts, source/input hashes and the Colodore palette are included.

## Reproduce

From this archive, with KickAss, VICE and py65 available:

```sh
rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm -o rebuilt.prg
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-fixed-flash-player.cjs --input inputs/scene-data --output rebuilt
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-fixed-flash-player.py --build rebuilt --data inputs/scene-data --output rebuilt/pal-proof
```
