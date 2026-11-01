/**
 * FLI Virtual with one front-priority hires sprite layer. The target bitmap is
 * 160 × 200, while matching and composition retain all 320 source columns.
 * The sprite matcher is shared with AFLI Virtual + Sprites.
 */
function createFliSpriteImage(sourceRGB, resolvedTargets, palette, brightnessBands,
  backgroundColorIndex, spriteColorIndex, matchAmount, ditherAmount) {
  if (!c64SpriteImageHasSize(sourceRGB, 320) || !c64SpriteImageHasSize(resolvedTargets, 160)) {
    throw new Error('FLI sprites require a 320 × 200 RGB source and a 160 × 200 target image.');
  }
  if (!Number.isInteger(backgroundColorIndex) || backgroundColorIndex < 0 || backgroundColorIndex > 15) {
    throw new Error('Choose a valid C64 background color.');
  }
  const layer = createC64SpriteLayer(sourceRGB, palette, spriteColorIndex, matchAmount, ditherAmount,
    palette?.[backgroundColorIndex]?.rgb);
  const fli = optimizeFliImage(resolvedTargets, palette, brightnessBands, backgroundColorIndex, layer.spriteMask);
  return { pixels: compositeC64SpriteLayer(fli.pixels, layer), fli, ...layer };
}
