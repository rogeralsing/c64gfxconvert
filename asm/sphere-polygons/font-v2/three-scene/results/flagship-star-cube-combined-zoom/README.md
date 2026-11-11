# Normal-speed animation with fixed2xzoom flashes

Source time advances **exactly1stored frame per presented image in every mode**, including flash entry, every internal zoom frame and flash exit. There is no frame skipping. Object changes reset local time to1; the same-STAR script wrap keeps time running.

Mode6is a spatial2xzoom again: a fixed20×12-source-cell crop is expanded through the STAR or world-lit CUBE's own learned lookup into40×24characters. YSCROLL7centers192pixels with four-pixel outer margins; row24 is blank. The crop is latched once per25-field flash and uses the manualWASDcenter plus the fixed14-entry offset pattern. The raw movies, font and source lighting are unchanged.

The two mixed modes are preserved: mode7 selects synchronous STAR/purple4andCUBE/green5in4×4-character blocks; mode8 putsSTARinTL/BRandCUBEinTR/BLwiththeacceptedH/Vlookups. The28-phase script still uses501-field bases and25-field flashes.

## Verification

Native PAL proof passes547actual colored scanouts. The serial+1contract is checked on every entry, internal frame, exit and wrap; all14flashes run25real fields. Both objects cover all48poses at default crop10,6. Retained mixed output, both object handoffs, fixed framing, foreground/background colors, font/source/front/lookup guards and zero-tail boot pass. Source time was never injected.

For bounded coverage, only base timers and manual centers were adjusted: centers compensated each existing offset to keep crop10,6, and base timing aligned six flash windows per object to cover all48poses. The last STAR flashes sample ordinary offsets, including7,4. The prior accepted lit-zoom native proof and current host proof cover representative cube corner offsets; their renderer helpers are unchanged. This is not a full147-second native playback run and no GUI keys or existing emulator were touched.

Host proof passes1278images/72618IRQ injections,494zoom pose/corner cases, all28normal-rate phase transitions, fixed entries, mixed regressions and actual zero/257-byte boot copies. Independent read-only review approved the new oracle and coverage alignment. Main RAM38,605bytes plus1024separate color RAM cells. Content-dependent cadence is in timing.json.

`native-contact.png` contains real normal/2xzoom pairs at the same stored pose plus retained mixes. Individual field PNGs remain in ignored build/pal-proof output. The approved lighting previews/proofs, exact frozen inputs, scene/source dependencies, Colodore palette and all hashes are included; GPU proof sources retain their original Three/WebGPU dependency environment.

## Reproduce player

From this archive, with KickAss, VICE and py65 available:

```sh
rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm -o rebuilt.prg
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-combined-zoom-player.cjs --input inputs/scene-data --output rebuilt --data-lock inputs/scene-data/manifest.json
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-combined-zoom-player.py --build rebuilt --data inputs/scene-data --output rebuilt/pal-proof
```
