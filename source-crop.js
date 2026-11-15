/** Copy a source-relative crop mask without changing the original image or its placement. */
function cloneSourceCrop(crop = null) {
  if (crop === null) return null;
  const points = crop?.points;
  const coordinate = value => Number.isFinite(value) && value >= 0 && value <= 1;
  if (!['rectangle', 'polygon'].includes(crop?.mode) || !Array.isArray(points) ||
      points.length < 3 || points.length > 256 ||
      points.some(point => !point || !coordinate(point.x) || !coordinate(point.y))) {
    throw new Error('Crop requires a rectangle or polygon with 3 to 256 source-relative points.');
  }
  if (points.some((point, index) => {
    const next = points[(index + 1) % points.length];
    return point.x === next.x && point.y === next.y;
  })) throw new Error('Crop edges must join different points.');

  const [first, second] = points;
  const noncollinear = points.some(point =>
    (second.x - first.x) * (point.y - first.y) !==
      (second.y - first.y) * (point.x - first.x));
  if (!noncollinear) throw new Error('Crop must enclose an area.');
  if (crop.mode === 'rectangle') {
    const [topLeft, topRight, bottomRight, bottomLeft] = points;
    if (points.length !== 4 || topLeft.x >= topRight.x || topLeft.y >= bottomLeft.y ||
        topLeft.y !== topRight.y || topRight.x !== bottomRight.x ||
        bottomRight.y !== bottomLeft.y || bottomLeft.x !== topLeft.x) {
      throw new Error('Rectangle crop requires four ordered axis-aligned corners.');
    }
  }
  return { mode: crop.mode, points: points.map(({ x, y }) => ({ x, y })) };
}

/** Clip the caller's saved drawing context before source sampling and color conversion. */
function applySourceCrop(context, placement, crop) {
  const mask = cloneSourceCrop(crop);
  if (!mask) return;
  context.beginPath();
  mask.points.forEach((point, index) => {
    const x = placement.x + point.x * placement.width;
    const y = placement.y + point.y * placement.height;
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.closePath();
  // Independent handles can cross; the same even-odd region is used by the editor.
  context.clip('evenodd');
}
