/** Raw native frames and PAL multiplexing metadata; no raster player is included. */
function encodeC64BorderSpriteZip(result) {
  const config = normalizeC64BorderSprites(result?.config);
  const backgroundColorIndex = result?.backgroundColorIndex;
  const layout = getC64BorderLayout(config);
  const count = (config.vertical.enabled ? 32 : 0) + (config.sides.enabled ? 20 : 0);
  const interlaced = result?.interlaced === true;
  const frames = interlaced ? result.frames : [result];
  if (!count || !Number.isInteger(backgroundColorIndex) || backgroundColorIndex < 0 || backgroundColorIndex > 15 ||
      result?.width !== layout.width || result.height !== layout.height ||
      !Array.isArray(result.sprites) || result.sprites.length !== count ||
      !Array.isArray(frames) || frames.length !== (interlaced ? 2 : 1)) {
    throw new Error('Border sprite export requires enabled borders and matching converted frames.');
  }
  const binary = new Uint8Array(frames.length * count * 64);
  const sprites = frames.flatMap((frame, phase) => {
    if (frame?.width !== layout.width || frame.height !== layout.height || frame.backgroundColorIndex !== backgroundColorIndex ||
        JSON.stringify(normalizeC64BorderSprites(frame.config)) !== JSON.stringify(config) ||
        !Array.isArray(frame.sprites) || frame.sprites.length !== count ||
        interlaced && (frame.phase !== phase || frame.offsetX !== phase)) {
      throw new Error('Border sprite fields require matching colors, geometry and phase offsets.');
    }
    return frame.sprites.map((sprite, index) => {
      const vertical = sprite.group === 'top' || sprite.group === 'bottom';
      const group = vertical ? config.vertical : config.sides;
      const first = frames[0].sprites[index];
      if (sprite.index !== index || !Number.isInteger(sprite.hardwareSlot) || sprite.hardwareSlot < 0 || sprite.hardwareSlot > 7 ||
          !ArrayBuffer.isView(sprite.data) || sprite.data.BYTES_PER_ELEMENT !== 1 || sprite.data.length !== 64 || sprite.data[63] !== 0 ||
          !['top', 'bottom', 'left', 'right'].includes(sprite.group) || !group.enabled ||
          sprite.mode !== group.mode || sprite.colorIndex !== group.colorIndex || sprite.multicolor !== (group.mode === 'multicolor') ||
          sprite.xExpanded !== vertical || sprite.yExpanded !== false || sprite.displayWidth !== (vertical ? 48 : 24) ||
          !Number.isInteger(sprite.x) || !Number.isInteger(sprite.y) ||
          sprite.vicX !== sprite.x + 24 - layout.coreX || sprite.vicY !== sprite.y + 50 - layout.coreY ||
          vertical && (!Number.isInteger(sprite.band) || sprite.band < 0 || sprite.band > 1 || sprite.vicYRegister !== (sprite.vicY & 0xff)) ||
          !Array.isArray(sprite.rowHeights) || sprite.rowHeights.length !== 21 || sprite.rowHeights.some(value => value !== 1) ||
          sprite.rowHeights.reduce((sum, value) => sum + value, 0) !== sprite.displayHeight ||
          interlaced && (sprite.x !== first.x + phase || sprite.y !== first.y ||
            sprite.clip?.x !== first.clip?.x + phase)) {
        throw new Error('Border sprite frames require native 63-byte data, zero padding and PAL placement metadata.');
      }
      const globalIndex = phase * count + index;
      binary.set(sprite.data, globalIndex * 64);
      const { data, ...metadata } = sprite;
      return { ...metadata, ...(interlaced ? { index: globalIndex, field: phase } : {}),
        byteOffset: globalIndex * 64, byteLength: 64 };
    });
  });
  const manifest = {
    format: 'c64-border-sprites', version: 1,
    ...(interlaced ? { interlaced: true, fields: frames.map((frame, phase) => ({
      phase, offsetX: frame.offsetX, spriteOffset: phase * count, spriteCount: count,
      byteOffset: phase * count * 64, byteLength: count * 64
    })) } : {}),
    files: { sprites: 'sprites.bin' },
    image: { width: layout.width, height: layout.height, pixelAspectRatio: [1, 1],
      core: { x: layout.coreX, y: layout.coreY, width: 320, height: 200 } },
    settings: config,
    data: { bytesPerSprite: 64, imageBytesPerSprite: 63, paddingByte: 0, bitOrder: 'msb-first',
      multicolorCodes: ['transparent', 'shared-1', 'sprite-color', 'shared-2'] },
    hardware: { videoStandard: 'PAL', programIncluded: false,
      borderOpeningRequired: true, rasterMultiplexingRequired: true, behindBitmapMask: 0,
      sharedMulticolorRegisters: [...config.multicolorIndices], backgroundColorRegister: backgroundColorIndex,
      spritePositionOrigin: config.vertical.enabled
        ? 'VIC X coordinates and full PAL DMA-start raster; vertical sprites also record the eight-bit vicYRegister value.'
        : 'VIC register coordinates; viewport positions are also recorded per frame',
      transparency: 'Code zero shows the background beneath the sprite, using $D021 in the open border.',
      sideBandHeight: 21, sideBandCountPerSide: 10,
      maximumSideSpritesAtOnce: config.sides.enabled ? 4 : 0,
      ...(config.vertical.enabled ? { verticalBandHeight: 21, verticalBandCountPerBorder: 2,
        maximumVerticalSpritesAtOnce: 8,
        verticalBandRetrigger: 'Reuse all eight X-expanded, normal-height sprites at PAL rasters 8/29 above and 250/271 below. Prepare Y coordinates and switch data pointers between bands; raster 271 uses Y register 15 after the first lower band has started.' } : {}),
      lastSideBand: 'Spare slots 5 and 6 start ten transparent rows early, followed by eleven visible rows. Their normal 21-line DMA ends at the bitmap boundary before the lower border reuses all slots.',
      clipping: 'Top and bottom extend beyond the viewport. The final side frames have ten transparent leading rows and eleven visible rows within the central bitmap height.' },
    sprites
  };
  return encodeStoredLayerZip([
    { name: 'sprites.bin', data: binary },
    { name: 'manifest.json', data: new TextEncoder().encode(`${JSON.stringify(manifest, null, 2)}\n`) }
  ]);
}
