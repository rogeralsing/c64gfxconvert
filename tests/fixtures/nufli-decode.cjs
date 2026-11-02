/** Independent file-address decoder, following RECOIL's documented NUF layout.
 * https://github.com/pfusik/recoil/blob/master/recoil.fu (DecodeNuf)
 * Uses screen-page sprite pointers, not the exporter's packing address tables.
 */
function decodeNufli(file) {
  if (file.length !== 23042 || file[0] !== 0 || file[1] !== 32) throw new Error('Invalid NUF file');
  const pixels = new Uint8Array(64000);
  const colors = [file[0x1ff9], 0, 0, 0, 0, 0, 0, file[0x1ff3], file[0x1ff8], file[0x1ff2]];
  const table = slot => 0x402 + ((slot & 6) << 9) + ((slot & 1) << 7);
  for (let slot = 0; slot < 6; slot += 1) colors[slot + 1] = file[table(slot)];
  for (let y = 0; y < 200; y += 1) {
    if (y > 0) {
      for (let slot = 0; slot < 6; slot += 1) {
        const command = file[table(slot) + ((y + 1) >> 1)];
        const type = command >> 4;
        if (type === 0 && (y & 1)) colors[slot + 1] = command & 15;
        if ((y & 1) === (slot === 0 ? 1 : 0)) {
          const destination = { 5: 7, 6: 9, 7: 0, 14: 8 }[type];
          if (destination !== undefined) colors[destination] = command & 15;
        }
      }
    }
    const page = y < 128 ? 0x2002 + (((~y >> 1) & 7) << 10)
      : 2 + ((((y >> 1) + (y >= 168 ? 1 : 0)) & 3) << 10);
    for (let x = 0; x < 320; x += 1) {
      const column = x >> 3;
      const cell = (y & ~7) * 5 + column;
      const attributes = column < 3 && (y & 6) !== 0 ? 255 : file[page + cell];
      const bitmap = file[(y < 128 ? 0x4002 : 2) + cell * 8 + (y & 7)];
      let color = attributes & 15;
      if (bitmap & (128 >> (x & 7))) color = attributes >> 4;
      else if (column < 39) {
        const sprite = Math.floor((3 + column) / 6);
        const byteInSprite = (((y + 47) >> 1) * 3 + (y < 123 ? 0 : y < 165 ? 1 : 2)) & 63;
        const spriteX = column < 3 ? x : ((x - 24) >> 1) % 24;
        const pointer = 128 - ((y & 128) << 1) + file[page + 0x3f8 + sprite];
        const byte = file[2 + pointer * 64 + ((byteInSprite + (spriteX >> 3)) & 63)];
        if (byte & (128 >> (spriteX & 7))) color = colors[sprite];
        else if (column < 3) {
          const multiPointer = 128 - ((y & 128) << 1) + file[page + 0x3ff];
          const multi = file[2 + multiPointer * 64 + ((byteInSprite + column) & 63)];
          const code = (multi >> (6 - (x & 6))) & 3;
          if (code) color = colors[6 + code];
        }
      }
      pixels[y * 320 + x] = color;
    }
  }
  return pixels;
}
module.exports = { decodeNufli };
