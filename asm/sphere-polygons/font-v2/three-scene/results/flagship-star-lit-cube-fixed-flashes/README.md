# Cube illuminated by a fixed world-space light

The cube now receives a fixed point light at(-60,65,90). Every pose recomputes vertex brightness from transformed world positions, flat face normals, Lambert response and distance attenuation. The light stays fixed while the cube rotates. Painted face gradients and material textures are removed. Source: demo-world-lit-cube-loop.mjs (SHA19e3c71fd8fe2d15b8f76f213b3eb8ea9ca33db1be4affe71f90a4937cb37f54).

The pre-font world-light proof checks96poses, all six local face normals, independent lighting values, changing brightness on each rotating face and matching loop endpoints. Grayscale/1-bit previews were visually approved before font conversion, followed by the bitmap/character comparison. These exact previews, the motion GIF, lighting proof/repro source, final data receipt and matched cube lookup are frozen under inputs/scene-data. Scene dependencies, exporter, generator and matcher sources are backed up with hashes.

The C64 renderer, font, star data, fixed-flash behavior and purple/green checker colors remain unchanged. Only cube character frames, physical frame pointers and its matched zoom lookup change. The player is still one24-phase script:501fields per base mode,25fields per fixed flash, STAR then CUBE, repeating. WASD changes the center for the next flash and never moves the current flash.

## Verification

The existing verifier was reused without edits. Native PAL proof passes616consecutive actual colored scanouts, all48source poses per object, all effects, both handoffs, all12natural25-field flashes, fixed crops, checker parity and uniform-color resets. Every pixel matches the new independent world-lit cube reference. Font/front/source/LUT/7FFF guards pass; the real zero-tail boot makes no high-memory writes. Main RAM38,349bytes plus1024separate color RAM cells. The content-dependent cadence is in timing.json.

Host proof passes1178images/63822IRQ injections and zero/257-byte boot cases. Renderer source/binary comparison and the input data-lock receipt are included. Native base timers were explicitly shortened after coverage; this is a bounded proof, not a full126-second timing run. Physical keyboard injection is outside the minimized native run.

`native-contact.png` shows real C64 scanouts, including four normal cube poses under the same palette for lighting review. All individual field PNGs remain in ignored build/pal-proof output. The exact world-light proof source retains its original Three.js dependency path; reproducing GPU previews requires that Three/WebGPU environment. Player reconstruction uses only the frozen input bytes below.

## Reproduce player

From this archive, with KickAss, VICE and py65 available:

```sh
rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm -o rebuilt.prg
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-fixed-flash-player.cjs --input inputs/scene-data --output rebuilt --data-lock inputs/scene-data/manifest.json
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-fixed-flash-player.py --build rebuilt --data inputs/scene-data --output rebuilt/pal-proof
```
