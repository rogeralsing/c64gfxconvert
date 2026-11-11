# Colored base effects with half-second zoom flashes

One C64 PRG runs normal, wave, checkerboard, V mirror, H mirror and both mirrors for STAR, then BALL, repeating. Every base phase lasts501PALfields (9.9951s), followed by a25-field zoom flash (0.4988s). All24phases total125.9263s. Base source advance is1 of48poses; flashes advance2. The ball uses the stronger compound X/Z/Y rotation and its own matched zoom lookup. Font and star source are unchanged.

Flash framing adds dx=round(3sin(2πp/25)),dy=round(2sin(4πp/25)) source cells to the WASD center, then clamps x0…20,y0…13. WASD changes the center in every mode; base images stay unchanged. Each phase cycles through BG/border15,FG11; BG/border10,FG4; BG/border13,FG5. Color RAM is uniformly filled only during phase commits in the border.

## Evidence

Native PAL proof passed673consecutive actual colored scanouts. All12flashes ran their full25real fields with no timer injection. Every pixel matched the independent raw-frame/font/Colodore reference; side borders matched background, all1024ColorRAM cells matched foreground, and all three palettes passed. Both objects covered all48source poses; both object handoffs reset to source1. Flash step2 wrapping, field-driven sine latches, all four crop clamp bounds and the relocated high-memory source frames passed. Font/front/source/LUT/7FFF write guards passed.

Palette fills took5573wall cycles and ended at raster35, before visible raster51. Flashes contained11–12distinct images each. Maximum held image was6fields. Base phase timers were explicitly advanced after coverage; this is a bounded native proof, not a full126-second timing run. The assembled host proof covers all24phase clocks, preparation budgets, input and geometry across1178images and71254IRQ injections. Physical keyboard injection is outside this minimized native run.

The PRG loads belowD000. A1897-byte tail is staged below the font and copied toE000 at boot. No source frame crosses7FFF, the D000I/O gap or reserved vectors;7FFF stays zero for colored YSCROLL7 idle margins. Native boot verifies all98physical source frames.

`native-contact.png` contains nine actual PAL scanouts. Individual field PNGs remain only in ignored build/pal-proof output. `native-verification.json`, `host-proof.json`, `timing.json`, `memory.json` and hash receipts contain the detailed evidence.

## Reproduce

From this archive, with KickAss, VICE and py65 available:

```sh
rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm -o rebuilt.prg
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-flash-player.cjs --input inputs/scene-data --output rebuilt
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-flash-player.py --build rebuilt --data inputs/scene-data --output rebuilt/pal-proof
```
