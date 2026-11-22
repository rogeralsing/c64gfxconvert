"use strict";

const RIBBON_OUTSIDE_TILE = 0xffff;
const RIBBON_INDEX_PATTERN = [
  [2, 4, 6],
  [7, 5, 8],
  [14, 9, 10],
];
const DISPLAY_WIDTH = 320;
const DISPLAY_HEIGHT = 200;
const RECORD_OUTER_RADIUS = 88;
const RECORD_INNER_RADIUS = 40;
const RECORD_CENTER_LAYERS = [
  [RECORD_INNER_RADIUS, 0],
  [30, 11],
  [29, 0],
  [26, 15],
  [25, 8],
  [3, 0],
];
const RECORD_CENTER_COLORS = { 0: "#000000", 8: "#9f4815", 11: "#474747", 15: "#aeaeae" };
const FULL_TURN = 2 * Math.PI;
const TRACK_INNER_RADIUS = 26;
const TRACK_OUTER_RADIUS = 72;
const TRACK_HALF_STRAIGHT = 55;
const TRACK_STRAIGHT = TRACK_HALF_STRAIGHT * 2;
const TRACK_MID_RADIUS = (TRACK_INNER_RADIUS + TRACK_OUTER_RADIUS) / 2;
const TRACK_CAP_LENGTH = Math.PI * TRACK_MID_RADIUS;
const TRACK_LENGTH = 2 * (TRACK_STRAIGHT + TRACK_CAP_LENGTH);

function displayAxis(pixel, size, displaySize) {
  return ((pixel + 0.5) / size - 0.5) * displaySize;
}

function trackAxis(pixel, size, displaySize) {
  // Apply the native display scale first to keep exact pixel centers on lane boundaries.
  return ((pixel + 0.5) * displaySize) / size - displaySize / 2;
}

function loopTileIds(width, height, settings, halfRight, innerRadius, outerRadius, distanceAt, turnAt, axisAt = displayAxis) {
  const { along, across } = settings;
  const columns = halfRight ? along + 1 : along;
  const shift = halfRight ? 0.5 : 0;
  const tiles = new Uint16Array(width * height).fill(RIBBON_OUTSIDE_TILE);

  for (let y = 0; y < height; y += 1) {
    const dy = axisAt(y, height, DISPLAY_HEIGHT);
    for (let x = 0; x < width; x += 1) {
      const dx = axisAt(x, width, DISPLAY_WIDTH);
      const radius = distanceAt(dx, dy);
      if (radius < innerRadius || radius > outerRadius) continue;

      const radialPosition = (outerRadius - radius) / (outerRadius - innerRadius);
      const row = Math.min(across - 1, Math.floor(radialPosition * across));
      const column = Math.floor(turnAt(dx, dy) * along + shift);
      tiles[y * width + x] = row * columns + column;
    }
  }

  return tiles;
}

function recordTurn(dx, dy) {
  // At the top of the disc, reading clockwise makes text run left to right.
  const angle = Math.atan2(dx, -dy);
  return angle < 0 ? 1 + angle / FULL_TURN : angle / FULL_TURN;
}

function trackDistance(dx, dy) {
  return Math.hypot(Math.max(0, Math.abs(dx) - TRACK_HALF_STRAIGHT), dy);
}

function trackTurn(dx, dy) {
  // All rows use the center path's length so column boundaries line up.
  if (dx > TRACK_HALF_STRAIGHT) {
    const angle = Math.atan2(dx - TRACK_HALF_STRAIGHT, -dy);
    return (TRACK_STRAIGHT + angle * TRACK_MID_RADIUS) / TRACK_LENGTH;
  }
  if (dx < -TRACK_HALF_STRAIGHT) {
    const angle = Math.atan2(-dx - TRACK_HALF_STRAIGHT, dy);
    return (2 * TRACK_STRAIGHT + TRACK_CAP_LENGTH + angle * TRACK_MID_RADIUS) / TRACK_LENGTH;
  }
  const topPosition = dx + TRACK_HALF_STRAIGHT;
  return (dy < 0 ? topPosition : 2 * TRACK_STRAIGHT + TRACK_CAP_LENGTH - topPosition) / TRACK_LENGTH;
}

function trackPoint(position, radius) {
  if (position < TRACK_STRAIGHT) return [position - TRACK_HALF_STRAIGHT, -radius];
  position -= TRACK_STRAIGHT;
  if (position < TRACK_CAP_LENGTH) {
    const angle = position / TRACK_MID_RADIUS;
    return [TRACK_HALF_STRAIGHT + radius * Math.sin(angle), -radius * Math.cos(angle)];
  }
  position -= TRACK_CAP_LENGTH;
  if (position < TRACK_STRAIGHT) return [TRACK_HALF_STRAIGHT - position, radius];
  const angle = (position - TRACK_STRAIGHT) / TRACK_MID_RADIUS;
  return [-TRACK_HALF_STRAIGHT - radius * Math.sin(angle), radius * Math.cos(angle)];
}

function recordCenterIndex(x, y, width, height, backgroundIndex) {
  const dx = displayAxis(x, width, DISPLAY_WIDTH);
  const dy = displayAxis(y, height, DISPLAY_HEIGHT);
  const radius = Math.hypot(dx, dy);
  for (let layer = RECORD_CENTER_LAYERS.length - 1; layer >= 0; layer -= 1) {
    const [edge, color] = RECORD_CENTER_LAYERS[layer];
    if (radius <= edge) return color;
  }
  return backgroundIndex;
}

function drawRecord(context, width, height, { along, across }, colors, palette) {
  const scale = Math.min(width / DISPLAY_WIDTH, height / DISPLAY_HEIGHT);
  const radialStep = (RECORD_OUTER_RADIUS - RECORD_INNER_RADIUS) / across;
  const angleStep = FULL_TURN / along;
  context.save();
  context.translate(width / 2, height / 2);
  context.scale(scale, scale);
  context.globalCompositeOperation = "lighter";
  for (let row = 0; row < across; row += 1) {
    const outer = RECORD_OUTER_RADIUS - row * radialStep;
    const inner = RECORD_OUTER_RADIUS - (row + 1) * radialStep;
    for (let column = 0; column < along; column += 1) {
      const left = -Math.PI / 2 + column * angleStep;
      const right = -Math.PI / 2 + (column + 1) * angleStep;
      context.beginPath();
      context.arc(0, 0, outer, left, right);
      context.arc(0, 0, inner, right, left, true);
      context.closePath();
      context.fillStyle = ribbonPatternIndex(row, column, colors);
      context.fill();
    }
  }
  context.globalCompositeOperation = "source-over";
  for (const [radius, color] of RECORD_CENTER_LAYERS) {
    context.beginPath();
    context.arc(0, 0, radius, 0, FULL_TURN);
    context.fillStyle = palette[color] ?? RECORD_CENTER_COLORS[color];
    context.fill();
  }
  context.restore();
}

function drawTrack(context, width, height, { along, across }, colors) {
  const scale = Math.min(width / DISPLAY_WIDTH, height / DISPLAY_HEIGHT);
  const radialStep = (TRACK_OUTER_RADIUS - TRACK_INNER_RADIUS) / across;
  const steps = Math.ceil(256 / along);
  const lengthStep = TRACK_LENGTH / (along * steps);
  context.save();
  context.translate(width / 2, height / 2);
  context.scale(scale, scale);
  context.globalCompositeOperation = "lighter";
  for (let row = 0; row < across; row += 1) {
    const outer = TRACK_OUTER_RADIUS - row * radialStep;
    const inner = TRACK_OUTER_RADIUS - (row + 1) * radialStep;
    for (let column = 0; column < along; column += 1) {
      const start = column * steps;
      const end = start + steps;
      context.beginPath();
      context.moveTo(...trackPoint(start * lengthStep, outer));
      for (let i = start + 1; i <= end; i += 1) {
        context.lineTo(...trackPoint(i * lengthStep, outer));
      }
      for (let i = end; i >= start; i -= 1) {
        context.lineTo(...trackPoint(i * lengthStep, inner));
      }
      context.closePath();
      context.fillStyle = ribbonPatternIndex(row, column, colors);
      context.fill();
    }
  }
  context.restore();
}

function createRibbonGeometry({ amplitude, waves, twist, thickness }) {
  const frequency = 2 * Math.PI * waves;
  const shear = (0.84 * twist) / (frequency + 6.2);
  const halfThickness = 0.085 + 0.28 * thickness;
  const taper = 0.22 * twist;
  const waveHeight = amplitude * (0.465 - halfThickness * (1 + taper));

  function xAt(u, v) {
    const acrossPosition = 2 * v - 1;
    // The window pins both ends. The shear coefficient keeps x increasing with u.
    const window = 4 * u * (1 - u);
    return u + shear * window * (Math.sin(frequency * u + 1.25 * acrossPosition + 0.35) + 0.55 * acrossPosition);
  }

  function crossSectionAt(x) {
    const phase = frequency * x;
    return {
      center: 0.5 + waveHeight * (Math.sin(phase - 0.38) + 0.2 * Math.sin(2 * phase + 0.8)) / 1.2,
      halfThickness: halfThickness * (1 + taper * Math.sin(phase + 1.7)),
      ripple: 0.16 * twist * Math.cos(phase + 0.6),
    };
  }

  return { xAt, crossSectionAt };
}

function ribbonY({ center, halfThickness, ripple }, v) {
  return center + halfThickness * (2 * v - 1 + ripple * Math.sin(2 * Math.PI * v));
}

function ribbonV(section, y) {
  const { center, halfThickness, ripple } = section;
  let v = ((y - center) / halfThickness + 1) / 2;
  // The ripple shifts the linear inverse by at most 0.08. The slope stays positive.
  for (let step = 0; step < 5; step += 1) {
    const slope = halfThickness * (2 + 2 * Math.PI * ripple * Math.cos(2 * Math.PI * v));
    v -= (ribbonY(section, v) - y) / slope;
  }
  return v;
}

function drawRibbon(context, width, height, settings, colors, palette = []) {
  context.clearRect(0, 0, width, height);
  if (width <= 0 || height <= 0) return;
  if (settings.shape === "record") {
    drawRecord(context, width, height, settings, colors, palette);
    return;
  }
  if (settings.shape === "track") {
    drawTrack(context, width, height, settings, colors);
    return;
  }

  const { along, across, waves } = settings;
  const { xAt, crossSectionAt } = createRibbonGeometry(settings);
  const alongSteps = Math.max(2, Math.ceil((96 * waves) / along));
  const acrossSteps = Math.max(2, Math.ceil(24 / across));
  const alongSamples = along * alongSteps;
  const acrossSamples = across * acrossSteps;
  const edgePadding = 2;

  function point(path, alongIndex, acrossIndex, offset = 0, move = false) {
    const u = alongIndex / alongSamples;
    const v = acrossIndex / acrossSamples;
    const x = xAt(u, v);
    const y = height * ribbonY(crossSectionAt(x), v) + offset;

    if (move) path.moveTo(x * width, y);
    else path.lineTo(x * width, y);
  }

  function traceAlong(path, start, end, acrossIndex, offset = 0) {
    const direction = Math.sign(end - start);
    for (let i = start + direction; i !== end + direction; i += direction) {
      point(path, i, acrossIndex, offset);
    }
  }

  function traceAcross(path, alongIndex, start, end) {
    const direction = Math.sign(end - start);
    for (let i = start + direction; i !== end + direction; i += direction) {
      point(path, alongIndex, i);
    }
  }

  const paths = new Map();
  for (let row = 0; row < across; row += 1) {
    const top = row * acrossSteps;
    const bottom = top + acrossSteps;
    const topOffset = row === 0 ? -edgePadding : 0;
    const bottomOffset = row === across - 1 ? edgePadding : 0;
    const rowColors = colors[row % colors.length];

    for (let column = 0; column < along; column += 1) {
      const left = column * alongSteps;
      const right = left + alongSteps;
      const color = rowColors[column % rowColors.length];
      let path = paths.get(color);
      if (!path) {
        path = new Path2D();
        paths.set(color, path);
      }

      point(path, left, top, topOffset, true);
      traceAlong(path, left, right, top, topOffset);
      if (topOffset) point(path, right, top);
      traceAcross(path, right, top, bottom);
      if (bottomOffset) point(path, right, bottom, bottomOffset);
      traceAlong(path, right, left, bottom, bottomOffset);
      if (bottomOffset) point(path, left, bottom);
      traceAcross(path, left, bottom, top);
      path.closePath();
    }
  }

  const outline = new Path2D();
  point(outline, 0, 0, 0, true);
  traceAlong(outline, 0, alongSamples, 0);
  point(outline, alongSamples, acrossSamples);
  traceAlong(outline, alongSamples, 0, acrossSamples);
  outline.closePath();

  context.save();
  // Add the coverage of adjacent antialiased edges. Compositing the same colors
  // behind themselves fills rounding gaps without adding a seam color.
  context.globalCompositeOperation = "lighter";
  for (const [color, path] of paths) {
    context.fillStyle = color;
    context.fill(path);
  }
  context.globalCompositeOperation = "destination-over";
  context.drawImage(context.canvas, 0, 0);
  // The outer tiles extend past this mask so the contour is antialiased once.
  context.globalCompositeOperation = "destination-in";
  context.fillStyle = "#fff";
  context.fill(outline);
  context.restore();
}

function ribbonTileIds(width, height, settings, { halfRight = false } = {}) {
  if (settings.shape === "record") {
    return loopTileIds(width, height, settings, halfRight, RECORD_INNER_RADIUS, RECORD_OUTER_RADIUS, Math.hypot, recordTurn);
  }
  if (settings.shape === "track") {
    return loopTileIds(width, height, settings, halfRight, TRACK_INNER_RADIUS, TRACK_OUTER_RADIUS, trackDistance, trackTurn, trackAxis);
  }
  const { along, across } = settings;
  const columns = halfRight ? along + 1 : along;
  const shift = halfRight ? 0.5 : 0;
  const { xAt, crossSectionAt } = createRibbonGeometry(settings);
  const tiles = new Uint16Array(width * height).fill(RIBBON_OUTSIDE_TILE);

  for (let x = 0; x < width; x += 1) {
    const normalizedX = (x + 0.5) / width;
    const section = crossSectionAt(normalizedX);
    let firstY = Math.ceil(height * ribbonY(section, 0) - 0.5);

    for (let row = 0; row < across; row += 1) {
      const bottom = (row + 1) / across;
      const endY = Math.ceil(height * ribbonY(section, bottom) - 0.5);
      const tileRow = row * columns;

      for (let y = firstY; y < endY; y += 1) {
        const v = ribbonV(section, (y + 0.5) / height);

        // Shift the column boundaries in u while keeping the visible ends fixed.
        let left = 0;
        let right = columns;
        while (right - left > 1) {
          const column = Math.floor((left + right) / 2);
          if (normalizedX < xAt((column - shift) / along, v)) right = column;
          else left = column;
        }
        tiles[y * width + x] = tileRow + left;
      }

      firstY = endY;
    }
  }

  return tiles;
}

function ribbonPatternIndex(row, column, indexPattern, halfRight = false) {
  const colors = indexPattern[row % indexPattern.length];
  // The left half-column comes from the last color of the previous motif repeat.
  const motifColumn = halfRight ? column + colors.length - 1 : column;
  return colors[motifColumn % colors.length];
}

function ribbonColorIndices(width, height, settings, indexPattern, backgroundIndex = 0, { halfRight = false } = {}) {
  const columns = halfRight ? settings.along + 1 : settings.along;
  const tiles = ribbonTileIds(width, height, settings, { halfRight });
  const indices = new Uint8Array(tiles.length).fill(backgroundIndex);
  for (let pixel = 0; pixel < tiles.length; pixel += 1) {
    const tile = tiles[pixel];
    if (tile === RIBBON_OUTSIDE_TILE) {
      if (settings.shape === "record") {
        indices[pixel] = recordCenterIndex(pixel % width, Math.floor(pixel / width), width, height, backgroundIndex);
      }
      continue;
    }
    const row = Math.floor(tile / columns);
    const column = tile % columns;
    indices[pixel] = ribbonPatternIndex(row, column, indexPattern, halfRight);
  }
  return indices;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { ribbonTileIds, ribbonColorIndices, ribbonPatternIndex, RIBBON_OUTSIDE_TILE, RIBBON_INDEX_PATTERN };
}
