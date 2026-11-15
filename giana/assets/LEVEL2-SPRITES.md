# Level2 actors

Rebuild with `python3 giana/tools/prepare-sprites.py --level 2` after the Level2 terrain import. All inputs are retained locally.

The 512-byte `level2-sprites.bin` contains the same four original Giana poses and two color planes per pose, area-sampled from the full 23 source rows to eight rows. Horizontal sampling, palette quantization and transparency stay the same as Level1. Rows 8–20 are transparent. The owl uses the unchanged shared Stage1 frames. Original crab, slinky and bee poses come from the separate 896-byte `level2-enemies.bin`; see `level2-enemies-SOURCE.md` for extraction and sampling details.

`level2-sprite-player-path.bin` has 512 bytes. The route uses real Level2 collision classes and rendered non-background pixels (code 0 is empty), eight-row opaque bodies and soles, ordinary grounded jumps, ceiling collisions and swept landings. Gravity and available launch strengths match Level1. Both current and following camera columns are checked for the actor's held frame. All eight enemies participate through their exact animated opaque pixels, including genuine head support. The 256-byte `level2-sprite-ground.bin` remains an offline reference for the initial foot anchor; it is not loaded into the demo.

The finite route is prepared through camera 472 with a terrain-supported endpoint. Runtime actor updates use 0–471 before the level transition; entries 473–511 repeat the endpoint only as unused padding. No collision or support claims cover that padding. Among the 473 prepared states, 363 have terrain support, four have enemy support and 106 are airborne according to the route's position/velocity state. Runtime uses 362 terrain-supported states, four enemy-supported states and 106 airborne states. There is no opaque body/solid overlap or midair jump restart.

## Enemy movement

All eight original enemy records are retained: one owl, two crabs, four slinkies and one bee. The two type-11 entries are powerups and are outside this enemy pass. There are at most two enemies visible together. Each complete visible lifetime stays assigned to the same hardware slot.

The graphics and spawn records are original; movement is a deliberate approximation. Each enemy starts from its original column group, settles before TV entry, and patrols within two multicolor pixels of its settled center. Native source speed is retained: one source pixel per PAL update for walkers, two for the bee, with four updates per camera step. Animation advances every seven updates and uses the original left/right pose sets. Walkers turn against their rendered solid-pixel bodies, use actual sole support, and sweep downward when support ends. Slinky animation changes its height while retaining foot contact; there is no imposed bouncing cycle.

The vertically compressed map needs small explicit placement adjustments. Original record 0 (owl) settles three multicolor pixels left onto the lower floor. Record 2 (first slinky) settles two right onto the nearest supported ledge; that ledge is above its scaled source hint. Record 5 (second slinky) settles one right to avoid a one-pixel support pocket. Record 9 (bee) settles six left so Giana can traverse the final cavern. The other records retain their original horizontal anchors. The bee uses the lowest clear horizontal flight lane found from its source hint, at unprojected top Y 13. This is not the original enemy AI.

All visible walker states have real sole support except one transition state for record 5 at camera 277. That state moves between supports at the perspective seam; it is not a sustained flat hover. Every enemy body remains clear of both held camera phases.

Two sets of `level2-enemyN-x.bin`, `level2-enemyN-y.bin` and `level2-enemyN-frame.bin` contain 512 bytes per channel, 3,072 bytes total. X is signed in multicolor pixels, Y is the already projected sprite top within the TV, and frame `$FF` hides the slot. The runtime clips visible pixels at either TV edge. Data beyond the finite level endpoint is inactive.

`level2-sprites-import.json` records hashes, sampling, active-state physics, per-enemy states, settling offsets, stable slots and schedule hashes. Level1 art, route, ground and metadata remain byte-identical.
