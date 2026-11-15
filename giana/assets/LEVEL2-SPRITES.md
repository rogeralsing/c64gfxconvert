# Level2 actors

Rebuild with `python3 giana/tools/prepare-sprites.py --level 2` after the Level2 terrain import. All inputs are retained locally.

The 512-byte `level2-sprites.bin` contains the same four original Giana poses and two color planes per pose, area-sampled from the full 23 source rows to eight rows. Horizontal sampling, palette quantization and transparency stay the same as Level1. Rows 8–20 are transparent. The owl uses the unchanged shared Stage1 frames; this demo does not recreate Stage2 enemy types.

`level2-sprite-ground.bin` has 256 bytes and `level2-sprite-player-path.bin` has 512 bytes. The route uses real Level2 collision classes and rendered non-background pixels (code 0 is empty), eight-row opaque bodies and soles, ordinary grounded jumps, ceiling collisions and swept landings. Gravity and available launch strengths match Level1. Both current and following camera columns are checked for the actor's held frame.

The finite route is prepared through camera 472 with a terrain-supported endpoint. Runtime actor updates use 0–471 before the level transition; entries 473–511 repeat the endpoint only as unused padding. No collision or support claims cover that padding. Staged owl markers are retained only when the complete finite route remains feasible; unsafe markers use ground value 255.

`level2-sprites-import.json` records hashes, exact sampling, active-state physics and staging decisions. Level1 art, route, ground and metadata remain byte-identical.
