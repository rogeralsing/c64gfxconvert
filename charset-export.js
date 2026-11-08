/** Export one mixed hires/multicolor character screen and a 256-glyph VIC charset. */
function encodeC64Charset(result, settings, palette) {
  const integer = (value, min, max) => Number.isInteger(value) && value >= min && value <= max;
  const color = value => integer(value, 0, 15);
  const bytes = (value, length) => ArrayBuffer.isView(value) && value.BYTES_PER_ELEMENT === 1 &&
    value.length === length && value.every(byte => integer(byte, 0, 255));
  const background = settings?.backgroundColorIndex;
  const shared = settings?.multicolorIndices;
  if (!color(background) || !Array.isArray(shared) || shared.length !== 2 || !shared.every(color) ||
      result?.backgroundColorIndex !== background || !Array.isArray(result.multicolorIndices) ||
      result.multicolorIndices.length !== 2 || result.multicolorIndices.some((value, index) => value !== shared[index])) {
    throw new Error('Character export requires matching background and shared multicolor settings.');
  }
  if (!Array.isArray(palette) || palette.length !== 16) {
    throw new Error('Character export requires a valid indexed C64 palette.');
  }
  const colors = Array.from({ length: 16 }, (_, index) => palette.find(entry => entry?.index === index)?.rgb);
  if (colors.some(rgb => !Array.isArray(rgb) || rgb.length !== 3 || !rgb.every(value => integer(value, 0, 255)))) {
    throw new Error('Character export requires a valid indexed C64 palette.');
  }
  const pixels = result.pixels;
  if (pixels?.width !== 320 || pixels.height !== 200 || !bytes(pixels.data, 320 * 200 * 4) ||
      !bytes(result.charset, 2048) || !bytes(result.screen, 1000) || !bytes(result.colorRam, 1000) ||
      !integer(result.characterCount, 1, 256) ||
      !integer(result.unrestrictedCharacterCount, result.characterCount, 1000) ||
      !integer(result.approximatedCellCount, 0, 1000) ||
      result.screen.some(index => index >= result.characterCount) || result.colorRam.some(value => value > 15)) {
    throw new Error('Character export requires a 320 × 200 screen, at most 256 glyphs, and valid color RAM.');
  }
  for (let cell = 0; cell < 1000; cell += 1) {
    const foreground = result.colorRam[cell] & 7;
    const multicolor = (result.colorRam[cell] & 8) !== 0;
    const allocation = multicolor ? [background, shared[0], shared[1], foreground] : [background, foreground];
    for (let row = 0; row < 8; row += 1) {
      const bits = result.charset[result.screen[cell] * 8 + row];
      for (let column = 0; column < 8; column += 1) {
        const code = multicolor ? bits >> (6 - (column >> 1) * 2) & 3 : bits >> (7 - column) & 1;
        const rgb = colors[allocation[code]];
        const offset = ((Math.floor(cell / 40) * 8 + row) * 320 + cell % 40 * 8 + column) * 4;
        if (pixels.data[offset + 3] !== 255 || rgb.some((value, channel) => pixels.data[offset + channel] !== value)) {
          throw new Error('Character pixels must match the charset, screen, color RAM, and shared colors.');
        }
      }
    }
  }
  const manifest = {
    format: 'c64-multicolor-charset', version: 1,
    files: { charset: 'charset.bin', screen: 'screen.bin', colorRam: 'color-ram.bin' },
    image: { width: 320, height: 200, pixelAspectRatio: [1, 1] },
    layout: { columns: 40, rows: 25, cellWidth: 8, cellHeight: 8, bytesPerGlyph: 8,
      charsetByteLength: 2048, screenByteLength: 1000, colorRamByteLength: 1000,
      loadAddressesIncluded: false },
    characterCount: result.characterCount,
    unrestrictedCharacterCount: result.unrestrictedCharacterCount,
    approximatedCellCount: result.approximatedCellCount,
    hardware: { bitmapMode: false, extendedColorMode: false, multicolorMode: true,
      backgroundColorRegister: background, sharedMulticolorRegisters: [...shared],
      colorRamModeBit: 8, foregroundColorMask: 7,
      hiresCodes: ['background', 'foreground'],
      multicolorCodes: ['background', 'shared-1', 'shared-2', 'foreground'],
      programIncluded: false }
  };
  return encodeStoredLayerZip([
    { name: 'charset.bin', data: result.charset },
    { name: 'screen.bin', data: result.screen },
    { name: 'color-ram.bin', data: result.colorRam },
    { name: 'manifest.json', data: new TextEncoder().encode(`${JSON.stringify(manifest, null, 2)}\n`) }
  ]);
}
