const C64_SPRITE_MATCH_MAX = 5;

/**
 * Fit AFLI beneath one front-priority monochrome sprite layer.
 * The PAL eight-sprite player exposes AFLI x112..319; its sprites cover x112..303.
 */
function createAfliSpriteImage(sourceRGB, resolvedTargets, palette, brightnessBands,
  spriteColorIndex, matchAmount, ditherAmount) {
  if (!c64SpriteImageHasSize(sourceRGB, 320) || !c64SpriteImageHasSize(resolvedTargets, 320)) {
    throw new Error('AFLI sprites require matching 320 × 200 source and target images.');
  }
  const layer = createC64SpriteLayer(sourceRGB, palette, spriteColorIndex, matchAmount, ditherAmount);
  const afli = optimizeAfliImage(resolvedTargets, palette, brightnessBands, layer.spriteMask);
  return { pixels: compositeC64SpriteLayer(afli.pixels, layer), afli, ...layer };
}

function c64SpriteImageHasSize(image, width) {
  return image?.width === width && image.height === 200 &&
    ArrayBuffer.isView(image.data) && image.data.BYTES_PER_ELEMENT === 1 &&
    image.data.length === width * 200 * 4;
}

/**
 * Shared hires sprite matching uses modified RGB, before virtual snapping.
 * Match amount 0..5 sets an Oklab distance radius of 0..2. Zero selects exact
 * visible RGB matches only. Dither 0 is a hard radius; dither 1 applies the
 * image mapper's 4×4 ordered pattern to a feather from half to 1.5× the radius.
 * Partially transparent source colors use the caller's linear-light matte,
 * defaulting to black for AFLI.
 */
function createC64SpriteLayer(sourceRGB, palette, spriteColorIndex, matchAmount, ditherAmount,
  backgroundRGB = null) {
  if (!c64SpriteImageHasSize(sourceRGB, 320)) {
    throw new Error('C64 sprites require a 320 × 200 source image.');
  }
  if (!Array.isArray(palette) || palette.length !== 16 ||
      palette.some((color, index) => color?.index !== index ||
        !Array.isArray(color.rgb) || color.rgb.length !== 3 ||
        color.rgb.some(value => !Number.isInteger(value) || value < 0 || value > 255))) {
    throw new Error('C64 sprites require an indexed 16-color C64 palette.');
  }
  if (!Number.isInteger(spriteColorIndex) || spriteColorIndex < 0 || spriteColorIndex > 15) {
    throw new Error('Choose a C64 sprite color from 0 to 15.');
  }
  if (!Number.isFinite(matchAmount) || matchAmount < 0 || matchAmount > C64_SPRITE_MATCH_MAX) {
    throw new Error(`Sprite match amount must be between 0 and ${C64_SPRITE_MATCH_MAX}.`);
  }
  if (!Number.isFinite(ditherAmount) || ditherAmount < 0 || ditherAmount > 1) {
    throw new Error('Sprite dither amount must be between 0 and 1.');
  }

  const spriteColor = palette[spriteColorIndex];
  const selectedLab = rgbToOklab(...spriteColor.rgb);
  const linearBackground = backgroundRGB?.map(srgbToLinear);
  const radius = matchAmount * 0.4;
  const thresholds = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5]
  ];
  const spriteMask = new Uint8Array(320 * 200);
  const spritePixels = new ImageData(320, 200);
  const distances = new Map();
  let spritePixelCount = 0;
  for (let y = 0; y < 200; y += 1) {
    for (let x = 112; x < 304; x += 1) {
      const pixel = y * 320 + x;
      const offset = pixel * 4;
      const alpha = sourceRGB.data[offset + 3];
      if (alpha === 0) continue;
      const rgb = sourceRGB.data.subarray(offset, offset + 3);
      const key = (rgb[0] | rgb[1] << 8 | rgb[2] << 16 | alpha << 24) >>> 0;
      if (!distances.has(key)) {
        const opacity = alpha / 255;
        const visible = alpha === 255 ? rgb : Array.from(rgb, (channel, index) => linearToSrgb(
          linearBackground ? srgbToLinear(channel) * opacity + linearBackground[index] * (1 - opacity)
            : srgbToLinear(channel) * alpha / 255
        ));
        const lab = rgbToOklab(...visible);
        distances.set(key, Math.hypot(lab.lightness - selectedLab.lightness,
          lab.a - selectedLab.a, lab.b - selectedLab.b));
      }
      const distance = distances.get(key);
      const hard = distance <= radius ? 1 : 0;
      const feather = radius > 0 ? Math.max(0, Math.min(1, 1.5 - distance / radius)) : hard;
      const coverage = hard + (feather - hard) * ditherAmount;
      const threshold = (thresholds[y % 4][x % 4] + 0.5) / 16;
      if (threshold >= coverage) continue;
      spriteMask[pixel] = 1;
      spritePixelCount += 1;
      spritePixels.data.set([...spriteColor.rgb, 255], offset);
    }
  }

  return {
    spriteMask, spritePixels, spriteColorIndex, spritePixelCount,
    matchAmount, ditherAmount
  };
}

/** Expand a multicolor bitmap's wide pixels before applying the hires sprite bits. */
function compositeC64SpriteLayer(underlay, layer) {
  const pixels = new ImageData(320, 200);
  const scale = 320 / underlay.width;
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      const pixel = y * 320 + x;
      const offset = pixel * 4;
      const data = layer.spriteMask[pixel] ? layer.spritePixels.data : underlay.data;
      const source = layer.spriteMask[pixel] ? offset : (y * underlay.width + Math.floor(x / scale)) * 4;
      pixels.data.set(data.subarray(source, source + 4), offset);
    }
  }
  return pixels;
}
