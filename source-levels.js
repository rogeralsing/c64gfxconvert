/** Shared input-levels transfer curve, applied equally to the source RGB channels. */
function createSourceLevelsLookup({ blackPoint = 0, whitePoint = 255, gamma = 1 } = {}) {
  if (!Number.isInteger(blackPoint) || !Number.isInteger(whitePoint) ||
      blackPoint < 0 || whitePoint > 255 || blackPoint >= whitePoint ||
      !Number.isFinite(gamma) || gamma <= 0) {
    throw new RangeError('Source levels require 0 <= black < white <= 255 and positive gamma.');
  }
  const lookup = new Uint8ClampedArray(256);
  for (let value = 0; value < 256; value += 1) {
    const normalized = Math.max(0, Math.min(1, (value - blackPoint) / (whitePoint - blackPoint)));
    lookup[value] = 255 * normalized ** (1 / gamma);
  }
  return lookup;
}

/** Stretch input levels and adjust midtones without changing alpha or the source. */
function applySourceLevels(source, { blackPoint = 0, whitePoint = 255, gamma = 1 } = {}) {
  const lookup = createSourceLevelsLookup({ blackPoint, whitePoint, gamma });
  if (blackPoint === 0 && whitePoint === 255 && gamma === 1) return source;
  const adjusted = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  for (let offset = 0; offset < adjusted.data.length; offset += 4) {
    if (adjusted.data[offset + 3] === 0) continue;
    for (let channel = 0; channel < 3; channel += 1) {
      adjusted.data[offset + channel] = lookup[adjusted.data[offset + channel]];
    }
  }
  return adjusted;
}
