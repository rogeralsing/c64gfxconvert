/** Read the preset's display inset; unrecognized legacy layout modes stay full width. */
function getC64ImageLeftInset(mode) {
  return C64_GRAPHICS_MODES.some(preset => preset.id === mode) ? getC64GraphicsMode(mode).leftInset : 0;
}

/** Fit, scale, and pan the source in display pixels without changing its aspect ratio. */
function getC64ImagePlacement(sourceWidth, sourceHeight, mode, transform = {}) {
  if (!Number.isFinite(sourceWidth) || sourceWidth <= 0 ||
      !Number.isFinite(sourceHeight) || sourceHeight <= 0) {
    throw new Error('Source image dimensions must be positive finite numbers.');
  }
  const { scale = 1, offsetX = 0, offsetY = 0 } = transform;
  if (!Number.isFinite(scale) || scale <= 0) {
    throw new Error('Image scale must be a positive finite number.');
  }
  if (!Number.isFinite(offsetX) || !Number.isFinite(offsetY)) {
    throw new Error('Image offsets must be finite numbers.');
  }
  const canvasWidth = 320;
  const canvasHeight = 200;
  const leftInset = getC64ImageLeftInset(mode);
  const availableWidth = canvasWidth - leftInset;
  const aspectRatio = sourceWidth / sourceHeight;
  const width = Math.min(availableWidth, canvasHeight * aspectRatio) * scale;
  const height = Math.min(canvasHeight, availableWidth / aspectRatio) * scale;
  return {
    x: leftInset + (availableWidth - width) / 2 + offsetX,
    y: (canvasHeight - height) / 2 + offsetY,
    width,
    height,
    leftInset,
    availableWidth,
    canvasWidth,
    canvasHeight
  };
}
