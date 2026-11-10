/**
 * Encode two multicolor phases as an uncompressed True Paint (.mci) image.
 * $9c00: screen A, bitmap A, bitmap B, screen B, then shared color RAM.
 * The 1024-byte screens and 8192-byte bitmaps retain their hardware padding;
 * the first byte after screen A's 1000 color cells stores the background.
 * https://github.com/godot64/GoDot/blob/master/loaders/l_TruePaint.a
 */
function encodeTruePaintMci(result, palette) {
  const isColorIndex = value => Number.isInteger(value) && value >= 0 && value < 16;
  const isBytes = (value, length) => ArrayBuffer.isView(value) &&
    value.BYTES_PER_ELEMENT === 1 && value.length === length;
  const colorsByRgb = new Map();
  const colorIndices = new Set();
  if (!Array.isArray(palette) || palette.length !== 16) {
    throw new Error('MCI export requires a 16-color C64 palette.');
  }
  for (const color of palette) {
    const rgb = color?.rgb;
    if (!isColorIndex(color?.index) || colorIndices.has(color.index) ||
        !Array.isArray(rgb) || rgb.length !== 3 ||
        !rgb.every(value => Number.isInteger(value) && value >= 0 && value <= 255) ||
        colorsByRgb.has(rgb.join(','))) {
      throw new Error('MCI export requires unique C64 color indices and RGB values.');
    }
    colorIndices.add(color.index);
    colorsByRgb.set(rgb.join(','), color.index);
  }
  if (!Array.isArray(result?.frames) || result.frames.length !== 2 ||
      !isColorIndex(result.backgroundColorIndex) || !isBytes(result.tileColors, 1000)) {
    throw new Error('MCI export requires two fitted frames and 1000 shared tile colors.');
  }
  if (result.tileColors.some(color => !isColorIndex(color))) {
    throw new Error('MCI tile colors must be C64 color indices.');
  }
  for (const frame of result.frames) {
    if (frame?.pixels?.width !== 160 || frame.pixels.height !== 200 ||
        !isBytes(frame.pixels.data, 160 * 200 * 4) || !isBytes(frame.rowColors, 16000)) {
      throw new Error('MCI export requires 160 × 200 frames and their fitted row colors.');
    }
  }

  const file = new Uint8Array(19434);
  file.set([0x00, 0x9c]);
  file[1002] = result.backgroundColorIndex;
  file.set(result.tileColors, 18434);
  for (let phase = 0; phase < 2; phase += 1) {
    const { pixels, rowColors } = result.frames[phase];
    const screenBase = phase === 0 ? 2 : 17410;
    const bitmapBase = phase === 0 ? 1026 : 9218;
    for (let tile = 0; tile < 1000; tile += 1) {
      const first = rowColors[tile * 16];
      const second = rowColors[tile * 16 + 1];
      if (!isColorIndex(first) || !isColorIndex(second)) {
        throw new Error('MCI row colors must be C64 color indices.');
      }
      file[screenBase + tile] = first << 4 | second;
      const allowed = [result.backgroundColorIndex, first, second, result.tileColors[tile]];
      for (let row = 0; row < 8; row += 1) {
        const rowOffset = tile * 16 + row * 2;
        if (rowColors[rowOffset] !== first || rowColors[rowOffset + 1] !== second) {
          throw new Error('MCI screen colors must stay constant across each 4 × 8 tile.');
        }
        let bits = 0;
        for (let column = 0; column < 4; column += 1) {
          const x = tile % 40 * 4 + column;
          const y = Math.floor(tile / 40) * 8 + row;
          const offset = (y * 160 + x) * 4;
          const data = pixels.data;
          const color = colorsByRgb.get(`${data[offset]},${data[offset + 1]},${data[offset + 2]}`);
          if (data[offset + 3] !== 255 || color === undefined) {
            throw new Error('MCI pixels must be opaque colors from the C64 palette.');
          }
          const code = allowed.indexOf(color);
          if (code === -1) {
            throw new Error(`MCI pixel (${x}, ${y}) in frame ${phase + 1} does not match its fitted colors.`);
          }
          bits = bits << 2 | code;
        }
        file[bitmapBase + tile * 8 + row] = bits;
      }
    }
  }
  return file;
}
