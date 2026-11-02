/** Pack the standard Mufflon NUFLI layout; all offsets below exclude its load header. */
function encodeNufli(result) {
  const sizes = { bitmap: 8000, screenColors: 4000, spriteBits: 3600,
    bugHiresBits: 600, bugMulticolorBits: 600, bugColors: 400, registerUpdates: 606 };
  for (const [key, size] of Object.entries(sizes)) {
    const data = result?.[key];
    if (!ArrayBuffer.isView(data) || data.BYTES_PER_ELEMENT !== 1 || data.length !== size) {
      throw new Error(`NUFLI export requires ${size} fitted ${key} bytes.`);
    }
  }
  if (result.bugColors.some(color => color > 15) || result.registerUpdates.subarray(0, 6).some(color => color > 15)) {
    throw new Error('NUFLI initial colors must be C64 palette indices.');
  }
  const yUpdates = new Set();
  for (let row = 1; row <= 100; row += 1) {
    for (let slot = 0; slot < 6; slot += 1) {
      const command = result.registerUpdates[row * 6 + slot];
      const type = command >> 4;
      if (![0, 1, 5, 6, 7, 14].includes(type) ||
          ([5, 6, 7, 14].includes(type) && slot === 0)) {
        throw new Error('NUFLI register update has an unsupported command or timing slot.');
      }
      if (type === 1) {
        if (row < 0x3e || row > 0x52 || (command & 1) !== 1 || yUpdates.has(command)) {
          throw new Error('NUFLI sprite Y updates must occur once each inside the split window.');
        }
        yUpdates.add(command);
      }
    }
  }
  if (yUpdates.size !== 8) throw new Error('NUFLI export requires all eight sprite Y updates.');
  const file = new Uint8Array(0x5a02);
  file.set([0x00, 0x20]);
  const data = file.subarray(2);
  const tables = C64_NUFLI_DATA;
  const updateOffsets = [0x400, 0x480, 0x800, 0x880, 0xc00, 0xc80];
  for (let row = 0; row <= 100; row += 1) {
    for (let slot = 0; slot < 6; slot += 1) data[updateOffsets[slot] + row] = result.registerUpdates[row * 6 + slot];
  }
  data.set(result.bitmap.subarray(0, 0x1400), 0x4000);
  data.set(result.bitmap.subarray(0x1400), 0x1400);
  for (let row = 0; row < 100; row += 1) {
    data.set(result.screenColors.subarray(row * 40, row * 40 + 40), tables.nuifli_scram[row]);
  }
  let spriteRow = 5;
  for (let y = 0; y < 200; y += 1) {
    for (let byte = 0; byte < 18; byte += 1) {
      const within = (spriteRow + byte % 3) & 63;
      const address = byte >= 15 && y < 128
        ? 0x5400 + (((y >> 1) & 7) ^ 7) * 64 + within
        : tables.nuifli_spram[y >> 1] + within + Math.floor(byte / 3) * 64;
      data[address] = result.spriteBits[y * 18 + byte];
    }
    for (let byte = 0; byte < 3; byte += 1) {
      const within = (spriteRow + byte) & 63;
      data[tables.flibug_hires_spram[y >> 1] + within] = result.bugHiresBits[y * 3 + byte];
      data[tables.flibug_multi_spram[y >> 1] + within] = result.bugMulticolorBits[y * 3 + byte];
    }
    if ((y & 1) === 0) spriteRow += 3;
    if (spriteRow > 63) spriteRow &= 63;
    else if (spriteRow === 63) spriteRow = 0;
  }
  const pointerOffsets = [0x3f8, 0x7f8, 0xbf8, 0xff8, 0x23f8, 0x27f8,
    0x2bf8, 0x2ff8, 0x33f8, 0x37f8, 0x3bf8, 0x3ff8];
  pointerOffsets.forEach((offset, bank) => data.set(tables.nuifli_sprite_pointers.subarray(bank * 8, bank * 8 + 8), offset));
  const [hires, first, second, third] = result.bugColors;
  data[0x1ff7] = hires;
  data[0x1ff1] = first;
  // Multicolor bits 10 use the sprite's own color; 11 use shared $d026.
  data[0x1ff6] = second;
  data[0x1ff0] = third;
  [0x1000, 0x1300, 0x1fc0, 0x1f40, 0x23c0, 0x27c0, 0x2bc0].forEach((offset, index) => {
    data.set(tables[`nuifli_displayer_code${index + 1}`], offset);
  });
  return file;
}

/** Add a BASIC SYS 12288 launcher so VICE and a real C64 can start with RUN. */
function encodeNufliPrg(result) {
  const nuf = encodeNufli(result);
  const program = new Uint8Array(2 + 0x7a00 - 0x0801);
  program.set([0x01, 0x08, 0x0d, 0x08, 0x0a, 0x00, 0x9e, 0x20,
    0x31, 0x32, 0x32, 0x38, 0x38, 0x00, 0x00, 0x00]);
  program.set(nuf.subarray(2), 2 + 0x2000 - 0x0801);
  return program;
}
