/** Interpolate editable tone points smoothly without overshooting either endpoint of a segment. */
function createSourceCurveLookup(curvePoints = [{ input: 0, output: 0 }, { input: 255, output: 255 }]) {
  if (!Array.isArray(curvePoints) || curvePoints.length < 2 || curvePoints.length > 256 ||
      curvePoints[0]?.input !== 0 || curvePoints.at(-1)?.input !== 255 ||
      Array.from(curvePoints).some((point, index) => !point ||
        !Number.isInteger(point.input) || !Number.isInteger(point.output) ||
        point.input < 0 || point.input > 255 || point.output < 0 || point.output > 255 ||
        index > 0 && point.input <= curvePoints[index - 1].input)) {
    throw new RangeError('Source curve requires increasing integer input points from 0 to 255 and output values from 0 to 255.');
  }

  const spans = curvePoints.slice(1).map((point, index) => point.input - curvePoints[index].input);
  const slopes = curvePoints.slice(1).map((point, index) =>
    (point.output - curvePoints[index].output) / spans[index]);
  const tangents = [slopes[0]];
  for (let index = 1; index < curvePoints.length - 1; index += 1) {
    const previous = slopes[index - 1];
    const next = slopes[index];
    const firstWeight = 2 * spans[index] + spans[index - 1];
    const secondWeight = spans[index] + 2 * spans[index - 1];
    tangents.push(previous * next <= 0 ? 0
      : (firstWeight + secondWeight) / (firstWeight / previous + secondWeight / next));
  }
  tangents.push(slopes.at(-1));

  const lookup = new Uint8ClampedArray(256);
  let segment = 0;
  for (let value = 0; value < 256; value += 1) {
    while (segment < curvePoints.length - 2 && value > curvePoints[segment + 1].input) segment += 1;
    const first = curvePoints[segment];
    const second = curvePoints[segment + 1];
    const span = spans[segment];
    const position = (value - first.input) / span;
    const squared = position * position;
    const cubed = squared * position;
    const output = (2 * cubed - 3 * squared + 1) * first.output +
      (cubed - 2 * squared + position) * span * tangents[segment] +
      (-2 * cubed + 3 * squared) * second.output +
      (cubed - squared) * span * tangents[segment + 1];
    lookup[value] = Math.max(Math.min(first.output, second.output),
      Math.min(Math.max(first.output, second.output), output));
  }
  return lookup;
}

/** Shared input-levels transfer curve, applied equally to the source RGB channels. */
function createSourceLevelsLookup({ blackPoint = 0, whitePoint = 255, gamma = 1, curvePoints } = {}) {
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
  if (curvePoints !== undefined) {
    const curve = createSourceCurveLookup(curvePoints);
    for (let value = 0; value < 256; value += 1) lookup[value] = curve[lookup[value]];
  }
  return lookup;
}

/** Stretch input levels and adjust midtones without changing alpha or the source. */
function applySourceLevels(source, { blackPoint = 0, whitePoint = 255, gamma = 1, curvePoints } = {}) {
  const lookup = createSourceLevelsLookup({ blackPoint, whitePoint, gamma, curvePoints });
  if (lookup.every((output, input) => output === input)) return source;
  const adjusted = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  for (let offset = 0; offset < adjusted.data.length; offset += 4) {
    if (adjusted.data[offset + 3] === 0) continue;
    for (let channel = 0; channel < 3; channel += 1) {
      adjusted.data[offset + channel] = lookup[adjusted.data[offset + channel]];
    }
  }
  return adjusted;
}
