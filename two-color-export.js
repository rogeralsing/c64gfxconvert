/**
 * Art Studio hires: $2000 load address, 8000 bitmap bytes, 1000 screen bytes,
 * border color, then six zero bytes. Bitmap bit 1 selects the high nibble.
 * https://github.com/elysium64/c64img/blob/master/c64img/hires.py#L113-L122
 * https://github.com/pfusik/recoil/blob/7b4d11e159639a4b415ccc1d630edbed513cf5f3/recoil.fu#L10108-L10114
 */
function encodeTwoColorHiresArt(result, palette) {
  const pixels = result?.pixels;
  const indices = result?.colorIndices;
  if (pixels?.width !== 320 || pixels.height !== 200 ||
      !ArrayBuffer.isView(pixels.data) || pixels.data.BYTES_PER_ELEMENT !== 1 ||
      pixels.data.length !== 320 * 200 * 4) {
    throw new Error('Two-color hires export requires a 320 × 200 image.');
  }
  if (!Array.isArray(indices) || indices.length !== 2 ||
      !indices.every(index => Number.isInteger(index) && index >= 0 && index < 16) ||
      !Array.isArray(palette) || palette.length !== 16) {
    throw new Error('Two-color hires export requires two C64 palette colors.');
  }
  const colors = indices.map(index => palette.find(color => color?.index === index)?.rgb);
  if (colors.some(rgb => !Array.isArray(rgb) || rgb.length !== 3 ||
      !rgb.every(value => Number.isInteger(value) && value >= 0 && value <= 255))) {
    throw new Error('Two-color hires export requires valid palette RGB values.');
  }
  const file = new Uint8Array(9009);
  file.set([0x00, 0x20]);
  file.fill(indices[1] << 4 | indices[0], 8002, 9002);
  file[9002] = indices[0];
  for (let pixel = 0; pixel < 64000; pixel += 1) {
    const offset = pixel * 4;
    const shadow = colors[0].every((value, channel) => pixels.data[offset + channel] === value);
    const highlight = colors[1].every((value, channel) => pixels.data[offset + channel] === value);
    if (pixels.data[offset + 3] !== 255 || (!shadow && !highlight)) {
      throw new Error('Two-color hires pixels must be opaque and match the selected colors.');
    }
    if (shadow) continue;
    const x = pixel % 320;
    const y = Math.floor(pixel / 320);
    file[2 + (y >> 3) * 320 + (x >> 3) * 8 + (y & 7)] |= 128 >> (x & 7);
  }
  return file;
}
