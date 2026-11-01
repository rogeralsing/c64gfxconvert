/**
 * Encode a fitted 320 × 200 AFLI image as an uncompressed AFLI-editor .afl file.
 * Load address $4000; eight 1024-byte screen banks precede the hires bitmap.
 * RECOIL requires 16385 bytes: the final unused bitmap padding byte is omitted.
 * GoDot's loader reads the same eight banks and 8000 active bitmap bytes.
 * https://github.com/pfusik/recoil/blob/7b4d11e159639a4b415ccc1d630edbed513cf5f3/recoil.fu#L10712-L10718
 * https://github.com/godot64/GoDot/blob/90c8c5c05a6683edb76a82efd8d3cff6f4713c3d/loaders/l_AFLI.a#L58-L181
 */
function encodeAfli(result, palette) {
  const isColorIndex = value => Number.isInteger(value) && value >= 0 && value < 16;
  const colorsByRgb = new Map();
  const colorIndices = new Set();
  if (!Array.isArray(palette) || palette.length !== 16) {
    throw new Error('AFLI export requires a 16-color C64 palette.');
  }
  for (const color of palette) {
    const rgb = color?.rgb;
    if (!isColorIndex(color?.index) || colorIndices.has(color.index) ||
        !Array.isArray(rgb) || rgb.length !== 3 ||
        !rgb.every(value => Number.isInteger(value) && value >= 0 && value <= 255) ||
        colorsByRgb.has(rgb.join(','))) {
      throw new Error('AFLI export requires unique C64 color indices and RGB values.');
    }
    colorIndices.add(color.index);
    colorsByRgb.set(rgb.join(','), color.index);
  }
  const pixels = result?.pixels;
  const rowColors = result?.rowColors;
  if (pixels?.width !== 320 || pixels.height !== 200 ||
      !ArrayBuffer.isView(pixels.data) || pixels.data.BYTES_PER_ELEMENT !== 1 ||
      pixels.data.length !== 320 * 200 * 4 || rowColors?.length !== 16000) {
    throw new Error('AFLI export requires a 320 × 200 image and its fitted row colors.');
  }

  const file = new Uint8Array(16385);
  file.set([0x00, 0x40]);
  const data = pixels.data;
  for (let y = 0; y < 200; y += 1) {
    const row = y & 7;
    for (let column = 0; column < 40; column += 1) {
      const tile = (y >> 3) * 40 + column;
      const rowOffset = (tile * 8 + row) * 2;
      const first = rowColors[rowOffset];
      const second = rowColors[rowOffset + 1];
      if (!isColorIndex(first) || !isColorIndex(second)) {
        throw new Error('AFLI row colors must be C64 color indices.');
      }
      // Hires bit 1 uses the high nibble; bit 0 uses the low nibble.
      file[2 + row * 1024 + tile] = first << 4 | second;
      let bits = 0;
      for (let pixel = 0; pixel < 8; pixel += 1) {
        const x = column * 8 + pixel;
        const offset = (y * 320 + x) * 4;
        const color = colorsByRgb.get(`${data[offset]},${data[offset + 1]},${data[offset + 2]}`);
        if (data[offset + 3] !== 255 || color === undefined) {
          throw new Error('AFLI pixels must be opaque colors from the C64 palette.');
        }
        if (color !== first && color !== second) {
          throw new Error(`AFLI pixel (${x}, ${y}) does not match its fitted colors.`);
        }
        bits = bits << 1 | Number(color === first);
      }
      file[0x2002 + tile * 8 + row] = bits;
    }
  }
  // The 24-byte screen-bank gaps and 191-byte bitmap tail remain zero-filled.
  return file;
}
