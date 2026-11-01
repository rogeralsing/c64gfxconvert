/**
 * Export fitted multicolor FLI RAM planes plus a hires sprite raster mask.
 * This is an explicit versioned layer ZIP, not a standard .fli or runnable PRG.
 * Requires the shared ZIP/mask helpers in afli-sprite-export.js.
 */
function encodeFliSpriteLayers(result, palette, backgroundColorIndex) {
  const isIndex = value => Number.isInteger(value) && value >= 0 && value < 16;
  const colorsByRgb = new Map();
  const colorsByIndex = new Map();
  if (!Array.isArray(palette) || palette.length !== 16) {
    throw new Error('FLI export requires a 16-color C64 palette.');
  }
  for (const color of palette) {
    const rgb = color?.rgb;
    if (!isIndex(color?.index) || colorsByIndex.has(color.index) ||
        !Array.isArray(rgb) || rgb.length !== 3 ||
        !rgb.every(value => Number.isInteger(value) && value >= 0 && value <= 255) ||
        colorsByRgb.has(rgb.join(','))) {
      throw new Error('FLI export requires unique C64 color indices and RGB values.');
    }
    colorsByIndex.set(color.index, color);
    colorsByRgb.set(rgb.join(','), color.index);
  }
  const validImage = (image, width) => image?.width === width && image.height === 200 &&
    ArrayBuffer.isView(image.data) && image.data.BYTES_PER_ELEMENT === 1 &&
    image.data.length === width * 200 * 4;
  const fli = result?.fli;
  const mask = result?.spriteMask;
  if (!validImage(result?.pixels, 320) || !validImage(fli?.pixels, 160) ||
      fli.tileColors?.length !== 1000 || fli.rowColors?.length !== 16000 ||
      !ArrayBuffer.isView(mask) || mask.BYTES_PER_ELEMENT !== 1 || mask.length !== 64000) {
    throw new Error('FLI sprite export requires a 320 × 200 canvas, 160 × 200 FLI image, and fitted colors.');
  }
  if (!isIndex(backgroundColorIndex) || fli.backgroundColorIndex !== backgroundColorIndex) {
    throw new Error('FLI export background must match the fitted C64 background color.');
  }
  if (!isIndex(result.spriteColorIndex)) {
    throw new Error('FLI sprite export requires a C64 sprite color from 0 to 15.');
  }

  const bitmap = new Uint8Array(8000);
  const screens = new Uint8Array(8192);
  const colorRam = new Uint8Array(1000);
  for (let tile = 0; tile < 1000; tile += 1) {
    const tileColor = fli.tileColors[tile];
    if (!isIndex(tileColor)) throw new Error('FLI tile colors must be C64 color indices.');
    colorRam[tile] = tileColor;
    for (let row = 0; row < 8; row += 1) {
      const first = fli.rowColors[(tile * 8 + row) * 2];
      const second = fli.rowColors[(tile * 8 + row) * 2 + 1];
      if (!isIndex(first) || !isIndex(second)) {
        throw new Error('FLI row colors must be C64 color indices.');
      }
      screens[row * 1024 + tile] = first << 4 | second;
      const allowed = [backgroundColorIndex, first, second, tileColor];
      const tileY = Math.floor(tile / 40);
      let bits = 0;
      for (let column = 0; column < 4; column += 1) {
        const x = tile % 40 * 4 + column;
        const imageY = tileY * 8 + row;
        const offset = (imageY * 160 + x) * 4;
        const data = fli.pixels.data;
        const color = colorsByRgb.get(`${data[offset]},${data[offset + 1]},${data[offset + 2]}`);
        if (data[offset + 3] !== 255 || color === undefined) {
          throw new Error('FLI pixels must be opaque colors from the C64 palette.');
        }
        // Prefer the first matching code when BG, row, or tile colors coincide.
        const code = allowed.indexOf(color);
        if (code < 0) throw new Error(`FLI pixel (${x}, ${imageY}) does not match its fitted colors.`);
        bits = bits << 2 | code;
      }
      bitmap[tile * 8 + row] = bits;
    }
  }
  const describeColor = index => {
    const color = colorsByIndex.get(index);
    return { index, name: typeof color.name === 'string' ? color.name : `C64 color ${index}`, rgb: [...color.rgb] };
  };
  const manifest = {
    format: 'c64-fli-sprite-layers',
    version: 1,
    files: { bitmap: 'bitmap.bin', screen: 'screen.bin', colorRam: 'color-ram.bin', spriteMask: 'sprites.bin' },
    image: { width: 160, height: 200, pixelAspectRatio: [2, 1] },
    canvas: { width: 320, height: 200 },
    backgroundColor: describeColor(backgroundColorIndex),
    spriteColor: describeColor(result.spriteColorIndex),
    layout: {
      fliValidRect: { x: 112, y: 0, width: 208, height: 200 },
      spriteRect: { x: 112, y: 0, width: 192, height: 200 },
      coordinateSpace: 'canvas',
      spriteCountPerRow: 8,
      hardwareSpriteWidth: 24,
      hardwareSpriteHeight: 21
    },
    fli: {
      bitmapBytes: 8000,
      screenBytes: 8192,
      screenBankCount: 8,
      screenBankStride: 1024,
      screenUsedBytesPerBank: 1000,
      colorRamBytes: 1000,
      tileColumns: 40,
      tileRows: 25,
      tileLogicalWidth: 4,
      tileHeight: 8,
      tileOrder: 'row-major',
      bitmapByteOffset: 'tileIndex * 8 + rowWithinTile',
      screenByteOffset: 'rowWithinTile * 1024 + tileIndex',
      bitmapPixelOrder: 'most-significant-pair-first',
      pixelCodes: { '00': 'backgroundColor.index', '01': 'screen-high-nibble', '10': 'screen-low-nibble', '11': 'color-ram.bin[tileIndex]' },
      duplicateColorCode: 'first-matching-code'
    },
    mask: {
      format: 'packed-raster-mask',
      byteLength: 4800,
      bytesPerRow: 24,
      rowOrder: 'top-to-bottom',
      columnOrder: 'left-to-right',
      bitOrder: 'msb-first',
      setBit: 'sprite-color',
      clearBit: 'fli-underlay',
      hardwareFrames: false
    },
    nativePlayer: { programIncluded: false }
  };
  const utf8 = new TextEncoder();
  return encodeStoredLayerZip([
    { name: 'bitmap.bin', data: bitmap },
    { name: 'screen.bin', data: screens },
    { name: 'color-ram.bin', data: colorRam },
    { name: 'sprites.bin', data: packSpriteLayerMask(mask, 'FLI') },
    { name: 'manifest.json', data: utf8.encode(`${JSON.stringify(manifest, null, 2)}\n`) }
  ]);
}
