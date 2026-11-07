/**
 * Koala Painter: $6000 load address, 8000 bitmap bytes, 1000 screen bytes,
 * 1000 color RAM bytes, then the shared background color.
 * Pixel codes 00/01/10/11 select background/screen high/screen low/color RAM.
 * https://github.com/elysium64/c64img/blob/master/c64img/multi.py
 */
function encodeMulticolorBitmapKoala(result, palette) {
  const pixels = result?.pixels;
  const tileColors = result?.tileColors;
  const background = result?.backgroundColorIndex;
  if (pixels?.width !== 160 || pixels.height !== 200 ||
      !ArrayBuffer.isView(pixels.data) || pixels.data.BYTES_PER_ELEMENT !== 1 ||
      pixels.data.length !== 160 * 200 * 4) {
    throw new Error('Multicolor bitmap export requires a 160 × 200 image.');
  }
  if (!Number.isInteger(background) || background < 0 || background >= 16 ||
      !ArrayBuffer.isView(tileColors) || tileColors.BYTES_PER_ELEMENT !== 1 ||
      tileColors.length !== 3000 || tileColors.some(index => index < 0 || index >= 16) ||
      !Array.isArray(palette) || palette.length !== 16) {
    throw new Error('Multicolor bitmap export requires a C64 background and three colors per tile.');
  }
  const colors = Array.from({ length: 16 }, (_, index) => palette.find(color => color?.index === index)?.rgb);
  if (colors.some(rgb => !Array.isArray(rgb) || rgb.length !== 3 ||
      !rgb.every(value => Number.isInteger(value) && value >= 0 && value <= 255))) {
    throw new Error('Multicolor bitmap export requires valid palette RGB values.');
  }

  const file = new Uint8Array(10003);
  file.set([0x00, 0x60]);
  file[10002] = background;
  for (let tile = 0; tile < 1000; tile += 1) {
    const [first, second, third] = tileColors.subarray(tile * 3, tile * 3 + 3);
    file[8002 + tile] = first << 4 | second;
    file[9002 + tile] = third;
    const allocated = [background, first, second, third].map(index => colors[index]);
    for (let row = 0; row < 8; row += 1) {
      let bits = 0;
      for (let column = 0; column < 4; column += 1) {
        const x = tile % 40 * 4 + column;
        const y = Math.floor(tile / 40) * 8 + row;
        const offset = (y * 160 + x) * 4;
        const code = allocated.findIndex(rgb =>
          rgb.every((value, channel) => pixels.data[offset + channel] === value));
        if (pixels.data[offset + 3] !== 255 || code === -1) {
          throw new Error('Multicolor bitmap pixels must be opaque and match the allocated tile colors.');
        }
        bits |= code << (6 - column * 2);
      }
      file[2 + tile * 8 + row] = bits;
    }
  }
  return file;
}
