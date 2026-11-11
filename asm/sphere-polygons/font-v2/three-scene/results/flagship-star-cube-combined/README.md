# Star and cube combined in one C64 player

The original star/world-lit-cube effects remain. Every flash now draws the whole40×25character source at normal size and advances2source poses per image; there is no2×zoom/crop or zoom lookup in the runtime.

Two new base effects follow the original24phases. Mode7 combines the current STAR and CUBE pose using4×4-character blocks: even parity selects STAR/purple4, odd selects CUBE/green5. Mode8 mirrors sourceTL20×12cells into24output rows: STAR fillsTL andBR(V[H[c]]); CUBE fillsTR(H[c]) andBL(V[c]). Row24 stays blank with four-pixel outer margins. Both sources use exactly the same current source pose.

The28-phase script has14base phases of501PALfields and14fast flashes of25fields, about146.914s total. Primary object changes at12and24 reset source time to1. The27→0wrap keeps the STAR clock running. Font, raw star/world-lit-cube data, lighting and H/V maps are unchanged. Two output screens and one500-byte row-pointer cache serve all nine modes; no combined output movie is stored.

## Verification

Native PAL proof passes739consecutive actual colored scanouts. Both mixed modes cover all48poses, cache object identities and physical row pointers match, and every screen character/pixel matches independent composition of the frozen source references. All14normal-size flashes retain25real fields, step2andfull-height YSCROLL3. Source resets, continuing STAR clock, palettes, checker ColorRAM parity, idle7FFFzero, front/font/source guards and zero-tail boot pass. Retained bases were sampled and their timers explicitly advanced; this is not a full147-second native timing run.

Host proof covers894images plus8independent blank-source cases, all28phase clocks, all48poses/new modes,59837IRQ injections and zero/257-byte boot copies. The new oracle also received an independent read-only review. Timing and memory receipts record content-dependent cadence; main RAM35,789bytes plus1024separate color RAM cells.

`native-contact.png` contains real mixed-mode poses9,17,33andfull-size flashes. Individual field PNGs remain in ignored build/pal-proof output. Approved lighting previews/proofs, source dependencies, frozen data/font files, the Colodore palette and all hashes are included. The lighting proof retains its original Three.js dependency path; player reconstruction below uses the frozen bytes only.

## Reproduce player

From this archive, with KickAss, VICE and py65 available:

```sh
rtk proxy /Users/rogerjohansson/.local/bin/kickass main.asm -o rebuilt.prg
rtk proxy node sources/asm/sphere-polygons/font-v2/build-span-combined-player.cjs --input inputs/scene-data --output rebuilt --data-lock inputs/scene-data/manifest.json
rtk proxy python3 sources/asm/sphere-polygons/font-v2/verify-span-combined-player.py --build rebuilt --data inputs/scene-data --output rebuilt/pal-proof
```
