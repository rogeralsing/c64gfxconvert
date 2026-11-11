# One C64 player, all six effects

A single PRG runs normal → wave → checkerboard → V only → H only → both quadrants, then repeats. Each mode occupies **501 PAL fields / 9.9951 seconds**. The complete cycle is **59.9706 seconds**. The source-image clock continues across every transition and into the next cycle.

Native PAL VICE passed **all 3,007 consecutive actual scanouts**, including the first normal image after the full repeat, and **1,331 displayed images**. Every field matched the independent source reference; all mode timers and transitions were checked. The shared cache matched 56,350 raw-row pointers, including re-entry after mirror modes. Original mirror source halves stayed unchanged. H-only preserved all 25 source rows, including 29 checked nonzero bottom-row cells. Forced refresh was disabled. No writes reached the visible front, font, raw movie, frame index or lookups.

| Mode | Effect | Actual images in cycle | Mean FPS including boundary hold |
| --- | --- | ---: | ---: |
| 0 | Normal | 249 | 24.91 |
| 1 | Wave | 167 | 16.71 |
| 2 | Checkerboard | 167 | 16.71 |
| 3 | V only | 249 | 24.91 |
| 4 | H only | 249 | 24.91 |
| 5 | Both quadrants | 249 | 24.91 |

Normal/wave/checkerboard and H-only use all 25 rows with YSCROLL 3. V-only and both-quadrants use a centered 24-row canvas with YSCROLL 7 and four black pixels above/below. V-only keeps the full-width top half unchanged; H-only keeps the full-height left half unchanged. Both-quadrants uses `H[c]`, `V[c]`, and `V[H[c]]`. The longest visible hold was **5 fields / 0.0998 seconds**.

The original raw film is still **23,076 B**, the locked font **2,048 B**, corrected H/V lookups **512 B**, and shared row-pointer cache **500 B**. The player uses **two 1,024 B output buffers** and **32,382 B of ordinary main RAM**. Color RAM is a separate 1,024 four-bit cells. It renders directly from X/length/raw rows; no minute-long output movie or image history is stored.

- `player.prg`, `main.sym`: the accepted combined player and symbols.
- `native-six-mode-contact.png`: actual screenshots of all six effects at matching source pose 6, with correct PAL proportions.
- `native-verification.json`, `native-monitor.log.gz`: complete scanout/state proof. All 3,007 individual PNG captures remain in the ignored build output, outside this compact archive.
- `independent-lookup-policy.json`, `host-proof.json`: reused corrected texture policy and separate assembled-CPU evidence.
- `memory.json`, `timing.json`, `source-hashes.json`, `sha256.json`: accounting, per-mode cadence and provenance.
- `sources/`: exact native sources, generated assembly inputs and the previously validated independent reference helpers.
- `inputs/raw-film/`: unchanged raw-film builder inputs.

Rebuild and verify from this archive directory:

```sh
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-suite-player.cjs --input inputs/raw-film --reference reference.frames --output /tmp/c64-span-suite-rebuild
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-suite-player.py --build /tmp/c64-span-suite-rebuild --output /tmp/c64-span-suite-proof
```

KickAss, Python/py65, Pillow and VICE 3.10 are needed for assembly, CPU and native proof. All previous accepted players and archives remain separate and unchanged. This archive includes the actual six-mode contact and every native capture; no additional video export was needed for acceptance.

PRG SHA256: `81986daea4faa18254200fa82af01a1f302de07a8490fe1d2ebf0386992999cc`.
Font SHA256: `1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1`.
Raw rows SHA256: `cbd68a6607da7e175f587e58c1d738fe321146d3ca9414d4eba05c46f0c9c719`.
