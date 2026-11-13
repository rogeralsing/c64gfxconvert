/** Apply one-logical-pixel interlace lines before source palette conversion. */
function applyInterlace(source, amount, {
  spacing = 2, direction = 'horizontal', pixelWidth = 1, phase = 1
} = {}) {
  if (!Number.isFinite(amount) || amount < -1 || amount > 1 ||
      !Number.isInteger(spacing) || spacing < 1 || spacing > 32 ||
      !['horizontal', 'diagonal-up', 'diagonal-down'].includes(direction) ||
      ![1, 2].includes(pixelWidth) || !Number.isInteger(phase)) {
    throw new RangeError('Interlace requires strength -1–1, spacing 1–32, a supported direction, and logical pixel width 1 or 2.');
  }
  if (amount === 0) return source;

  const intermediate = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  const pixels = intermediate.data;
  const target = amount < 0 ? 0 : 255;
  const strength = Math.abs(amount);

  // Lift alternate logical rows toward white; preserve the source and alpha.
  // Negative amounts darken those rows toward black instead.
  for (let y = 0; y < source.height; y += 1) {
    for (let x = 0; x < source.width; x += 1) {
      const logicalX = Math.floor(x / pixelWidth);
      const position = direction === 'diagonal-up' ? y + logicalX
        : direction === 'diagonal-down' ? y - logicalX : y;
      if (((position - phase) % spacing + spacing) % spacing !== 0) continue;
      const offset = (y * source.width + x) * 4;
      if (pixels[offset + 3] === 0) continue;

      for (let channel = 0; channel < 3; channel += 1) {
        pixels[offset + channel] += (target - pixels[offset + channel]) * strength;
      }
    }
  }
  return intermediate;
}
