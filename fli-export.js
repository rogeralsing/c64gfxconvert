/**
 * Encode a fitted 160 × 200 FLI image as an uncompressed FLIGraph .fli file.
 * Load address $3b00; 256 scanline backgrounds, 1024 Color RAM bytes, eight
 * 1024-byte screen banks, and an 8192-byte bitmap follow the two-byte header.
 * This 17666-byte variant retains the selected background. The FLI-Designer
 * variant assumes black instead. RECOIL accepts both variants as .fli files.
 * https://github.com/pfusik/recoil/blob/b51a8569f941680ebcd9c78d3917ed96694bcdcc/recoil.fu#L11086-L11099
 * https://github.com/pfusik/recoil/blob/b51a8569f941680ebcd9c78d3917ed96694bcdcc/recoil.fu#L21891-L21893
 * https://github.com/godot64/GoDot/blob/90c8c5c05a6683edb76a82efd8d3cff6f4713c3d/loaders/l_FLIGraph.a
 */
function encodeFli(result, palette) {
  const isColorIndex = value => Number.isInteger(value) && value >= 0 && value < 16;
  const colorsByRgb = new Map();
  const colorIndices = new Set();
  if (!Array.isArray(palette) || palette.length !== 16) {
    throw new Error('FLI export requires a 16-color C64 palette.');
  }
  for (const color of palette) {
    const rgb = color?.rgb;
    if (!isColorIndex(color?.index) || colorIndices.has(color.index) ||
        !Array.isArray(rgb) || rgb.length !== 3 ||
        !rgb.every(value => Number.isInteger(value) && value >= 0 && value <= 255) ||
        colorsByRgb.has(rgb.join(','))) {
      throw new Error('FLI export requires unique C64 color indices and RGB values.');
    }
    colorIndices.add(color.index);
    colorsByRgb.set(rgb.join(','), color.index);
  }

  const pixels = result?.pixels;
  const rowColors = result?.rowColors;
  const tileColors = result?.tileColors;
  if (pixels?.width !== 160 || pixels.height !== 200 ||
      !ArrayBuffer.isView(pixels.data) || pixels.data.BYTES_PER_ELEMENT !== 1 ||
      pixels.data.length !== 160 * 200 * 4 || rowColors?.length !== 16000 ||
      tileColors?.length !== 1000) {
    throw new Error('FLI export requires a 160 × 200 image and its fitted tile and row colors.');
  }
  if (!isColorIndex(result.backgroundColorIndex)) {
    throw new Error('FLI export requires a C64 background color from 0 to 15.');
  }

  const file = new Uint8Array(17666);
  file.set([0x00, 0x3b]);
  // $3b00 backgrounds, $3c00 Color RAM, $4000 screens, $6000 bitmap.
  file.fill(result.backgroundColorIndex, 2, 0x102);
  const data = pixels.data;
  for (let tile = 0; tile < 1000; tile += 1) {
    const tileColor = tileColors[tile];
    if (!isColorIndex(tileColor)) throw new Error('FLI tile colors must be C64 color indices.');
    file[0x102 + tile] = tileColor;
    for (let row = 0; row < 8; row += 1) {
      const rowOffset = (tile * 8 + row) * 2;
      const first = rowColors[rowOffset];
      const second = rowColors[rowOffset + 1];
      if (!isColorIndex(first) || !isColorIndex(second)) {
        throw new Error('FLI row colors must be C64 color indices.');
      }
      file[0x502 + row * 1024 + tile] = first << 4 | second;
      const allowed = [result.backgroundColorIndex, first, second, tileColor];
      const y = Math.floor(tile / 40) * 8 + row;
      let bits = 0;
      for (let column = 0; column < 4; column += 1) {
        const x = tile % 40 * 4 + column;
        const offset = (y * 160 + x) * 4;
        const color = colorsByRgb.get(`${data[offset]},${data[offset + 1]},${data[offset + 2]}`);
        if (data[offset + 3] !== 255 || color === undefined) {
          throw new Error('FLI pixels must be opaque colors from the C64 palette.');
        }
        // Prefer the first code when fitted background, row, or tile colors coincide.
        const code = allowed.indexOf(color);
        if (code < 0) throw new Error(`FLI pixel (${x}, ${y}) does not match its fitted colors.`);
        bits = bits << 2 | code;
      }
      file[0x2502 + tile * 8 + row] = bits;
    }
  }
  // Color RAM/screen gaps and the 192-byte bitmap tail remain zero-filled.
  return file;
}
