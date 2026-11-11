# Empirical character zoom

Run from the C64 repository with `rtk proxy node asm/sphere-polygons/font-v2/three-scene/study-char-zoom.mjs --source-cache /Users/rogerjohansson/.codex/worktrees/c64-consolidate-20261111/c64/asm/sphere-polygons/font-v2/build/char-zoom-study-contrast/render-1x --output /Users/rogerjohansson/.codex/worktrees/c64-consolidate-20261111/c64/asm/sphere-polygons/font-v2/three-scene/results/char-zoom-study-contrast`. The page consumes `study.json` and its listed packed binary files.

96 existing star poses:1–72 train;73–96 contiguous heldout. Full-view geometry is rerendered at twice the raster dimensions with the same camera and pixel/dither pitch. Each source character selects four output characters. Font and native player files stay unchanged. Source-scene hash and current tone palette are recorded in provenance; the original accepted PAL cache and baseline study are preserved.

Compare minimum-SUM learned LUT, modal quadruplet LUT, literal repeated pixels and direct target font fits. Object-only errors and outside spill are separate; char0 over a dark object is not automatically a lost feature. Direct masked fit follows the existing renderer, while unmasked direct fit is the actual per-cell Hamming lower bound. Each LUT is1024B; this is offline measurement, with no C64 player or FPS claim.

See `proof.json` for selected-source provenance, locks and serialized-byte checks.
