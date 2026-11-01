/**
 * Encode fitted IFLI frames as an uncompressed Fun Painter II (.fp2) file.
 * Layout follows GoDot's s_FunPaintII saver: two screen/bitmap sets and one
 * shared Color RAM. The 160 × 200 backing includes the usual left FLI bug area.
 * https://github.com/godot64/GoDot/blob/master/savers/s_FunPaintII.a
 */
function encodeFunPaintIfli(result, palette) {
  const isColorIndex = value => Number.isInteger(value) && value >= 0 && value < 16;
  const colorsByRgb = new Map();
  const colorIndices = new Set();
  if (!Array.isArray(palette) || palette.length !== 16) {
    throw new Error('IFLI export requires a 16-color C64 palette.');
  }
  for (const color of palette) {
    const rgb = color?.rgb;
    if (!isColorIndex(color?.index) || colorIndices.has(color.index) ||
        !Array.isArray(rgb) || rgb.length !== 3 ||
        !rgb.every(value => Number.isInteger(value) && value >= 0 && value <= 255) ||
        colorsByRgb.has(rgb.join(','))) {
      throw new Error('IFLI export requires unique C64 color indices and RGB values.');
    }
    colorIndices.add(color.index);
    colorsByRgb.set(rgb.join(','), color.index);
  }

  if (!Array.isArray(result?.frames) || result.frames.length !== 2 ||
      !isColorIndex(result.backgroundColorIndex) || result.tileColors?.length !== 1000) {
    throw new Error('IFLI export requires two fitted frames and 1000 shared tile colors.');
  }
  for (const frame of result.frames) {
    if (frame?.pixels?.width !== 160 || frame.pixels.height !== 200 ||
        !ArrayBuffer.isView(frame.pixels.data) || frame.pixels.data.BYTES_PER_ELEMENT !== 1 ||
        frame.pixels.data.length !== 160 * 200 * 4 || frame.rowColors?.length !== 16000) {
      throw new Error('IFLI export requires 160 × 200 frames and their fitted row colors.');
    }
  }

  const file = new Uint8Array(33694);
  file.set([0xf0, 0x3f]);
  const signature = 'FUNPAINT (MT) ';
  for (let index = 0; index < signature.length; index += 1) {
    file[index + 2] = signature.charCodeAt(index);
  }
  file[16] = 0; // Uncompressed data; the escape byte is unused in this mode.
  file[17] = 0xad;

  for (let tile = 0; tile < 1000; tile += 1) {
    const color = result.tileColors[tile];
    if (!isColorIndex(color)) throw new Error('IFLI tile colors must be C64 color indices.');
    file[16402 + tile] = color;
  }
  // The player uses these tails for its shared scanline background sequence.
  file.fill(result.backgroundColorIndex, 16210, 16402);
  file.fill(result.backgroundColorIndex, 33594, 33694);

  for (let phase = 0; phase < 2; phase += 1) {
    const { pixels, rowColors } = result.frames[phase];
    const screenBase = phase === 0 ? 18 : 17402;
    const bitmapBase = phase === 0 ? 8210 : 25594;
    for (let y = 0; y < 200; y += 1) {
      const row = y & 7;
      for (let column = 0; column < 40; column += 1) {
        const tile = (y >> 3) * 40 + column;
        const rowOffset = tile * 16 + row * 2;
        const first = rowColors[rowOffset];
        const second = rowColors[rowOffset + 1];
        if (!isColorIndex(first) || !isColorIndex(second)) {
          throw new Error('IFLI row colors must be C64 color indices.');
        }
        file[screenBase + row * 1024 + tile] = first << 4 | second;
        const allowed = [result.backgroundColorIndex, first, second, result.tileColors[tile]];
        let bits = 0;
        for (let pixel = 0; pixel < 4; pixel += 1) {
          const x = column * 4 + pixel;
          const offset = (y * 160 + x) * 4;
          const data = pixels.data;
          const color = colorsByRgb.get(`${data[offset]},${data[offset + 1]},${data[offset + 2]}`);
          if (data[offset + 3] !== 255 || color === undefined) {
            throw new Error('IFLI pixels must be opaque colors from the C64 palette.');
          }
          const code = allowed.indexOf(color);
          if (code < 0) {
            throw new Error(`IFLI pixel (${x}, ${y}) in frame ${phase + 1} does not match its fitted colors.`);
          }
          bits = bits << 2 | code;
        }
        file[bitmapBase + tile * 8 + row] = bits;
      }
    }
  }
  return file;
}
