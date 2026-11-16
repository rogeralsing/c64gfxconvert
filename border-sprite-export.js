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
  const colorPlan = result.colorPlan;
  const normalVertical = config.vertical.enabled && config.vertical.xExpanded === false;
  if (normalVertical && (!colorPlan || !Array.isArray(colorPlan.verticalPositions) ||
      colorPlan.verticalPositions.length !== 32 || colorPlan.verticalPositions.some((x, index, positions) =>
        !Number.isInteger(x) || x < 0 || x > layout.width - 24 ||
        index % 8 !== 0 && x < positions[index - 1] + 24))) {
    throw new Error('Normal-width border export requires a completed nonoverlapping placement plan.');
  }
  if ((config.optimizeColors || normalVertical) && (!colorPlan || !Array.isArray(colorPlan.colorIndices) ||
      colorPlan.colorIndices.length !== count || colorPlan.colorIndices.some(index => !Number.isInteger(index) || index < 0 || index > 15) ||
      colorPlan.spriteCount !== count ||
      colorPlan.phaseCount !== frames.length || colorPlan.backgroundColorIndex !== backgroundColorIndex ||
      JSON.stringify(colorPlan.multicolorIndices) !== JSON.stringify(config.multicolorIndices) ||
      !['virtual-surface-oklab-sse', 'native-pixel-oklab-sse'].includes(colorPlan.metric) ||
      !Number.isFinite(colorPlan.baselineError) || colorPlan.baselineError < 0 ||
      !Number.isFinite(colorPlan.optimizedError) || colorPlan.optimizedError < 0 ||
      colorPlan.optimizedError > colorPlan.baselineError + 1e-9 ||
      !Number.isFinite(colorPlan.improvementPercent) || colorPlan.improvementPercent < 0 || colorPlan.improvementPercent > 100)) {
    throw new Error('Optimized border export requires a valid completed color plan.');
  }
  const binary = new Uint8Array(frames.length * count * 64);
  const sprites = frames.flatMap((frame, phase) => {
    if (frame?.width !== layout.width || frame.height !== layout.height || frame.backgroundColorIndex !== backgroundColorIndex ||
        JSON.stringify(normalizeC64BorderSprites(frame.config)) !== JSON.stringify(config) ||
        !Array.isArray(frame.sprites) || frame.sprites.length !== count ||
        interlaced && (frame.phase !== phase || frame.offsetX !== phase) ||
        normalVertical && [0, 8, 16, 24].some(start =>
          new Set(frame.sprites.slice(start, start + 8).map(sprite => sprite.hardwareSlot)).size !== 8)) {
      throw new Error('Border sprite fields require matching colors, geometry and phase offsets.');
    }
    return frame.sprites.map((sprite, index) => {
      const vertical = sprite.group === 'top' || sprite.group === 'bottom';
      const group = vertical ? config.vertical : config.sides;
      const first = frames[0].sprites[index];
      const xExpanded = vertical && config.vertical.xExpanded !== false;
      const invalidNormalPlacement = normalVertical && (index < 32
        ? !vertical || sprite.group !== (index < 16 ? 'top' : 'bottom') || sprite.band !== Math.floor(index % 16 / 8) ||
          sprite.x !== colorPlan.verticalPositions[index] + phase ||
          sprite.y !== (index < 16 ? -7 : layout.coreY + 200) + sprite.band * 21 ||
          sprite.clip?.x !== phase || sprite.clip?.y !== (index < 16 ? 0 : layout.coreY + 200) ||
          sprite.clip?.width !== layout.width || sprite.clip?.height !== (index < 16 ? layout.top : layout.bottom)
        : vertical);
      if (sprite.index !== index || !Number.isInteger(sprite.hardwareSlot) || sprite.hardwareSlot < 0 || sprite.hardwareSlot > 7 ||
          !ArrayBuffer.isView(sprite.data) || sprite.data.BYTES_PER_ELEMENT !== 1 || sprite.data.length !== 64 || sprite.data[63] !== 0 ||
          !['top', 'bottom', 'left', 'right'].includes(sprite.group) || !group.enabled ||
          sprite.mode !== group.mode || !Number.isInteger(sprite.colorIndex) || sprite.colorIndex < 0 || sprite.colorIndex > 15 ||
          sprite.colorIndex !== (config.optimizeColors ? colorPlan.colorIndices[index] : group.colorIndex) ||
          normalVertical && sprite.colorIndex !== colorPlan.colorIndices[index] ||
          sprite.multicolor !== (group.mode === 'multicolor') ||
          sprite.xExpanded !== xExpanded || sprite.yExpanded !== false || sprite.displayWidth !== (xExpanded ? 48 : 24) ||
          invalidNormalPlacement ||
          !Number.isInteger(sprite.x) || !Number.isInteger(sprite.y) ||
          sprite.vicX !== sprite.x + 24 - layout.coreX || sprite.vicY !== sprite.y + 50 - layout.coreY ||
          vertical && (!Number.isInteger(sprite.band) || sprite.band < 0 || sprite.band > 1 || sprite.vicYRegister !== (sprite.vicY & 0xff)) ||
          !Array.isArray(sprite.rowHeights) || sprite.rowHeights.length !== 21 || sprite.rowHeights.some(value => value !== 1) ||
          sprite.rowHeights.reduce((sum, value) => sum + value, 0) !== sprite.displayHeight ||
          interlaced && (sprite.x !== first.x + phase || sprite.y !== first.y ||
            sprite.clip?.x !== first.clip?.x + phase || sprite.colorIndex !== first.colorIndex)) {
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
    ...(config.optimizeColors ? { colorOptimization: {
      method: 'global-shared-pair', metric: colorPlan.metric, phaseColorsTied: true,
      baselineError: colorPlan.baselineError, optimizedError: colorPlan.optimizedError,
      improvementPercent: colorPlan.improvementPercent,
      ...(normalVertical ? { jointPlacement: true } : {})
    } } : {}),
    ...(normalVertical ? { placementOptimization: {
      method: 'ordered-nonoverlapping-windows', reference: 'full-resolution-mapped-image',
      metric: colorPlan.metric, phasePositionsTied: true, spritesPerBand: 8, spriteWidth: 24,
      verticalPositions: [...colorPlan.verticalPositions],
      uncoveredPixels: 'shared-background', jointColorOptimization: config.optimizeColors === true,
      baselineError: colorPlan.baselineError, optimizedError: colorPlan.optimizedError,
      improvementPercent: colorPlan.improvementPercent
    } } : {}),
    data: { bytesPerSprite: 64, imageBytesPerSprite: 63, paddingByte: 0, bitOrder: 'msb-first',
      multicolorCodes: ['transparent', 'shared-1', 'sprite-color', 'shared-2'] },
    hardware: { videoStandard: 'PAL', programIncluded: false,
      borderOpeningRequired: true, rasterMultiplexingRequired: true, behindBitmapMask: 0,
      sharedMulticolorRegisters: [...config.multicolorIndices], backgroundColorRegister: backgroundColorIndex,
      ...(config.optimizeColors ? { individualSpriteColors: true } : {}),
      spritePositionOrigin: config.vertical.enabled
        ? 'VIC X coordinates and full PAL DMA-start raster; vertical sprites also record the eight-bit vicYRegister value.'
        : 'VIC register coordinates; viewport positions are also recorded per frame',
      transparency: 'Code zero shows the background beneath the sprite, using $D021 in the open border.',
      sideBandHeight: 21, sideBandCountPerSide: 10,
      maximumSideSpritesAtOnce: config.sides.enabled ? 4 : 0,
      ...(config.vertical.enabled ? { verticalBandHeight: 21, verticalBandCountPerBorder: 2,
        maximumVerticalSpritesAtOnce: 8,
        verticalBandRetrigger: normalVertical
          ? 'Reuse eight normal-width, normal-height sprites at PAL rasters 8/29 above and 250/271 below. Each band has optimized X positions. A raster player must schedule X and $D010 writes with Y, pointer and color handoffs; the fixed X-expanded handoff schedule cannot be reused.'
          : 'Reuse all eight X-expanded, normal-height sprites at PAL rasters 8/29 above and 250/271 below. Prepare Y coordinates and switch data pointers between bands; raster 271 uses Y register 15 after the first lower band has started.' } : {}),
      lastSideBand: 'Spare slots 5 and 6 start ten transparent rows early, followed by eleven visible rows. Their normal 21-line DMA ends at the bitmap boundary before the lower border reuses all slots.',
      clipping: 'Top and bottom extend beyond the viewport. The final side frames have ten transparent leading rows and eleven visible rows within the central bitmap height.' },
    sprites
  };
  return encodeStoredLayerZip([
    { name: 'sprites.bin', data: binary },
    { name: 'manifest.json', data: new TextEncoder().encode(`${JSON.stringify(manifest, null, 2)}\n`) }
  ]);
}
