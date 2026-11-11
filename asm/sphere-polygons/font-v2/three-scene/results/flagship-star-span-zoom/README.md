# Seven-effect C64 player with character zoom

One PRG starts with the new zoom for review, then runs normal, wave, checkerboard, vertical mirror, horizontal mirror and both mirrors before returning to zoom. Each phase lasts501PALfields (9.9951s); the full script is69.9657s. The original97-frame raw film and locked font are unchanged. Zoom adds a1024-byte learned1-to4-character lookup, stored as four256-byte runtime pages.

During zoom, **W/A/S/D** pans the20×12-source-cell crop. Default offset10,6; limits x0…20,y0…13. Output40×24cells is centered with four black pixel rows above and below. Crop requests are latched per hidden frame before the atomic lower-border flip.

Native PAL proof passed506consecutive actual scanouts: the complete501-field zoom phase, all96default-crop poses, four corner offsets, then three normal images. Every visible pixel matched the independent original-film/LUT oracle. Font, raw film, index, lookup and front-screen write guards passed. Zoom runs two fields per image (25.0623fps); including the short boundary hold,249images/9.9951s=24.9122fps. Maximum hold was5fields (0.09975s).

The host proof also covers all seven mode timers/order,480zoom crop/pose cases, CIA keyboard matrix/clamping/repeat, input ignored outside zoom, and153307interrupt injections. The minimized native proof sets requested offsets through the monitor; it does not claim physical keyboard injection. Modes0–5 retain the accepted suite renderers; their full native cycle is archived in the sibling flagship-star-span-suite result.

`native-contact.png` and six small PNGs are actual PAL scanouts. All506individual captures remain in the ignored build/pal-proof directory, outside this archive.

## Reproduce

From this archive, with KickAss, PAL VICE and py65 installed:

```sh
rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm -o rebuilt.prg
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-zoom-player.cjs --input inputs/raw-film --reference reference.frames --output rebuilt
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-zoom-player.py --build rebuilt --output rebuilt/pal-proof
```

`native-verification.json`, `host-proof.json`, `timing.json`, `memory.json` and `sha256.json` contain the receipts. Main RAM33,918bytes; separate color RAM1024four-bit cells. Two output screens, one500-byte row-pointer cache, no frame history or previous-screen copy.
