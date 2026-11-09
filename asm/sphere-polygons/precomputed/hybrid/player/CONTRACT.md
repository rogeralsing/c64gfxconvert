# PAL playback measurement

All players show the same64-frame checker loop from the serialized HC64 file. The font remains the original2,048-byte mathematical font. The image data contains no native code and no runtime geometry calculation is allowed or needed.

Run `node prepare-assets.cjs` from this directory once. Shared immutable assets are in `build/assets/`: checker-64.hc64, checker-64-raw.hc64, font.bin and data-layout.json. The separate `build/reference/` is verifier input only and must never be imported into a player.

HC64 global header is12bytes, followed by50bytes of row spans. First frame begins at offset62. Each frame has fillLengthLE16, edgeLengthLE16, fill payload, edge payload. The compact fill is PackBits expanding to60bytes. The edge payload begins with60raw presence-map bytes, then exact glyph codes in ascending screen order. Iterate475 selected cells in row-span order. The tail padding bits are ignored. Fill bits select glyph0 or15; edge presence overrides that value with the next glyph. The maximum edge-glyph count is below256, so an8-bit glyph index is valid.

Prefer the compact file for comparable size measurements. The raw-fill file is provided for a separately reported speed/space tradeoff. A static destination layout or offset table may be generated from the serialized metadata, but its bytes count toward the player footprint. Do not generate or embed per-frame character screens in code.

Required labels: render_start, render_end, frame_done, frame_index, frame_counter, front_screen_hi, back_screen_hi. frame_counter is16bit. At frame_done, frame_index identifies the screen that was just presented; advance the index after this label. Frame0 is presented first. After frame63, restore the first encoded frame pointer and index0.

Use bank0 hires text, white character color, black background, font$2000 and screens$0400/$0c00. Initialize both complete screen buffers, color RAM, VIC and interrupt state. Swap only at a PAL raster wrap after decoding finishes. Do not impose any extra FPS cap. All parsing, fill decoding and screen writes occur between render_start and render_end. Metadata precomputation at startup is permitted and must be described.

Each variant builds its own build/player.prg and build/main.sym. Code and emitted load data should stay outside I/O and hardware vectors. The root verifier owns VICE processes and compares all1,000 screen bytes, font bytes, VIC setup, loop wrap and actual screenshots. PAL render clocks include VIC stalls; presentation clocks include the raster wait.
