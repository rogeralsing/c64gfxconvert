# Empirical character zoom

Run from the C64 repository with `rtk proxy node asm/sphere-polygons/font-v2/three-scene/study-char-zoom.mjs`. The page consumes `study.json` and its listed packed binary files.

96 existing star poses:1–72 train;73–96 contiguous heldout. Full-view geometry is rerendered at twice the raster dimensions with the same camera and pixel/dither pitch. Each source character selects four output characters. All source/font/player files stay unchanged.

Compare minimum-SUM learned LUT, modal quadruplet LUT, literal repeated pixels and direct target font fits. Object-only errors and outside spill are separate; char0 over a dark object is not automatically a lost feature. Direct masked fit follows the existing renderer, while unmasked direct fit is the actual per-cell Hamming lower bound. Each LUT is1024B; this is offline measurement, with no C64 player or FPS claim.

See `proof.json` for PAL-source equivalence, locks and serialized-byte checks.
