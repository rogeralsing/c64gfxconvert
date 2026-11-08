/** Export native 64-byte VIC sprite frames with their shared colors and grid layout. */
function encodeC64SpriteGrid(result, settings) {
  const color = value => Number.isInteger(value) && value >= 0 && value <= 15;
  const colors = (value, count) => Array.isArray(value) && value.length === count && value.every(color);
  const { columns, rows, backgroundColorIndex, multicolorIndices, spriteColorIndices,
    overlayColorIndices, overlay } = settings || {};
  const cells = columns * rows;
  if (!Number.isInteger(columns) || !Number.isInteger(rows) || columns < 1 || rows < 1 ||
      columns > 8 || rows > 8 || typeof overlay !== 'boolean' || cells * (overlay ? 2 : 1) > 8 ||
      !color(backgroundColorIndex) || !colors(multicolorIndices, 2) || !colors(spriteColorIndices, 8) ||
      !colors(overlayColorIndices, 8)) {
    throw new Error('Sprite export requires a valid grid of at most eight sprites and C64 colors.');
  }
  const width = columns * 24;
  const height = rows * 21;
  const count = cells * (overlay ? 2 : 1);
  const pixels = result?.pixels;
  if (pixels?.width !== width || pixels.height !== height || !ArrayBuffer.isView(pixels.data) ||
      pixels.data.BYTES_PER_ELEMENT !== 1 || pixels.data.length !== width * height * 4 ||
      !Array.isArray(result.sprites) || result.sprites.length !== count) {
    throw new Error('Sprite export requires matching grid pixels and hardware frames.');
  }
  const binary = new Uint8Array(count * 64);
  let multicolorMask = 0;
  const sprites = result.sprites.map((sprite, index) => {
    const cell = index % cells;
    const multicolor = !overlay || index >= cells;
    const colorIndex = (multicolor ? spriteColorIndices : overlayColorIndices)[cell];
    if (sprite.index !== index || sprite.column !== cell % columns || sprite.row !== Math.floor(cell / columns) ||
        sprite.multicolor !== multicolor || sprite.colorIndex !== colorIndex ||
        !ArrayBuffer.isView(sprite.data) || sprite.data.BYTES_PER_ELEMENT !== 1 || sprite.data.length !== 64 ||
        sprite.data[63] !== 0) {
      throw new Error('Sprite frames must use hardware slot order, matching colors, and 63 bytes plus zero padding.');
    }
    binary.set(sprite.data, index * 64);
    if (multicolor) multicolorMask |= 1 << index;
    return { index, column: sprite.column, row: sprite.row, x: sprite.column * 24, y: sprite.row * 21,
      colorIndex, multicolor, byteOffset: index * 64, byteLength: 64 };
  });
  const manifest = {
    format: 'c64-sprite-grid', version: 1,
    files: { sprites: 'sprites.bin' },
    image: { width, height, pixelAspectRatio: [1, 1] },
    grid: { columns, rows, cellWidth: 24, cellHeight: 21, overlay },
    backgroundColorIndex, multicolorIndices: [...multicolorIndices],
    data: { bytesPerSprite: 64, imageBytesPerSprite: 63, paddingByte: 0, bitOrder: 'msb-first',
      multicolorCodes: ['transparent', 'shared-1', 'sprite-color', 'shared-2'] },
    hardware: {
      spriteEnableMask: (1 << count) - 1,
      multicolorEnableMask: multicolorMask,
      xExpansionMask: 0, yExpansionMask: 0, behindBitmapMask: 0,
      backgroundColorRegister: backgroundColorIndex,
      sharedMulticolorRegisters: [...multicolorIndices],
      spriteColorRegisters: sprites.map(sprite => sprite.colorIndex),
      positionOrigin: 'relative-to-grid',
      priority: 'lower sprite index is in front',
      programIncluded: false
    },
    sprites
  };
  return encodeStoredLayerZip([
    { name: 'sprites.bin', data: binary },
    { name: 'manifest.json', data: new TextEncoder().encode(`${JSON.stringify(manifest, null, 2)}\n`) }
  ]);
}
