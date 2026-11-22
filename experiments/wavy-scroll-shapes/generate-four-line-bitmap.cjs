"use strict";

const { mkdirSync, readFileSync, writeFileSync } = require("node:fs");
const { join, resolve } = require("node:path");
const { createContext, runInContext } = require("node:vm");
const { fitScrollBitmap } = require("./four-line-scroll-fit.cjs");
const { prepareRows } = require("./generate-four-line-scroll.cjs");
const { optimizeSlots } = require("./optimize-four-line-slots.cjs");
const { ribbonColorIndices, ribbonTileIds, RIBBON_INDEX_PATTERN, RIBBON_OUTSIDE_TILE } = require("./ribbon.js");

const width = 160;
const height = 200;
const background = 0;
const usage = "Usage: node generate-four-line-bitmap.cjs <output-directory> [columns=64] [rows=16] [record|track|ribbon] [none|rows|columns|both|checker] [--scroll [row-colors.bin]] [--split-plan split-plan.json] [--active-rows count]";

class ImageData {
  constructor(width, height) {
    this.width = width;
    this.height = height;
    this.data = new Uint8ClampedArray(width * height * 4);
  }
}

function loadFitter() {
  const context = createContext({ ImageData });
  const root = resolve(__dirname, "../..");
  // Load the converter's classic scripts in the same order as the web harness.
  for (const name of ["color-math", "ifli", "talent-palette", "talent-neighbors", "talent-mapping", "palettes", "fli"]) {
    const path = join(root, `${name}.js`);
    runInContext(readFileSync(path, "utf8"), context, { filename: path });
  }
  const path = join(__dirname, "four-line-bitmap.js");
  runInContext(readFileSync(path, "utf8"), context, { filename: path });
  return runInContext("({ createC64PaletteState, optimizeMulticolorBitmapImage, optimizeFourLineBitmapImage })", context);
}

function countExact(source, fitted) {
  let exact = 0;
  for (let offset = 0; offset < source.data.length; offset += 4) {
    if (source.data[offset] === fitted.data[offset] &&
        source.data[offset + 1] === fitted.data[offset + 1] &&
        source.data[offset + 2] === fitted.data[offset + 2]) exact++;
  }
  return exact;
}

function addGutters(colors, tiles, sampleWidth, along, mode) {
  const rows = mode === "rows" || mode === "both";
  const columns = mode === "columns" || mode === "both";
  for (let pixel = 0; pixel < tiles.length; pixel += 1) {
    const tile = tiles[pixel];
    if (tile === RIBBON_OUTSIDE_TILE) continue;
    const above = pixel < sampleWidth ? RIBBON_OUTSIDE_TILE : tiles[pixel - sampleWidth];
    const left = pixel % sampleWidth === 0 ? RIBBON_OUTSIDE_TILE : tiles[pixel - 1];
    const rowBoundary = rows && above !== RIBBON_OUTSIDE_TILE &&
      Math.floor(above / along) !== Math.floor(tile / along);
    const columnBoundary = columns && left !== RIBBON_OUTSIDE_TILE && left % along !== tile % along;
    if (rowBoundary || columnBoundary) colors[pixel] = background;
  }
}

function measureOwnership(tiles, indices, bitmap) {
  const counts = { coloredBandPixels: 0, occupiedCells: 0, conflictedCells: 0, aliasedPixels: 0, unmappedPixels: 0 };
  const sampledTiles = new Set(tiles);
  sampledTiles.delete(RIBBON_OUTSIDE_TILE);
  const visibleTiles = new Set();
  for (let cell = 0; cell < 1000; cell += 1) {
    const x = (cell % 40) * 4;
    const y = Math.floor(cell / 40) * 8;
    const [top, bottom] = [new Set(), new Set()];
    const slots = Array.from({ length: 5 }, () => new Map());
    for (let row = 0; row < 8; row += 1) {
      const half = Math.floor(row / 4);
      const owners = half === 0 ? top : bottom;
      const bits = bitmap[cell * 8 + row];
      for (let column = 0; column < 4; column += 1) {
        const offset = (y + row) * width + x + column;
        const tile = tiles[offset];
        const code = (bits >> (6 - column * 2)) & 3;
        if (tile === RIBBON_OUTSIDE_TILE || indices[offset] === background) continue;
        counts.coloredBandPixels += 1;
        visibleTiles.add(tile);
        owners.add(tile);
        if (code === 0) {
          counts.unmappedPixels += 1;
          continue;
        }
        const candidates = slots[code === 3 ? 4 : half * 2 + code - 1];
        candidates.set(tile, (candidates.get(tile) ?? 0) + 1);
      }
    }
    if (top.size || bottom.size) counts.occupiedCells += 1;
    // When both halves fill all three slots, at least one owner must
    // belong to both halves so Color RAM can carry that common owner.
    if (top.size > 3 || bottom.size > 3 ||
        (top.size === 3 && bottom.size === 3 && ![...top].some((tile) => bottom.has(tile)))) {
      counts.conflictedCells += 1;
    }
    for (const slot of slots) {
      const pixels = [...slot.values()];
      if (pixels.length === 0) continue;
      counts.aliasedPixels += pixels.reduce((sum, count) => sum + count, 0) - Math.max(...pixels);
    }
  }
  return { ...counts, visibleTiles: visibleTiles.size, hiddenTiles: sampledTiles.size - visibleTiles.size };
}

function samplePhase(settings, gutters, halfRight = false) {
  const { along, shape } = settings;
  // The late fetch can miss the first three character cells. Scale the full
  // wavelength into the usable area, so the guard does not hide any tiles.
  const leftGuard = shape === "ribbon" ? 12 : 0;
  const sampleWidth = width - leftGuard;
  const samples = ribbonColorIndices(sampleWidth, height, settings, RIBBON_INDEX_PATTERN, background, { halfRight });
  const sampleTiles = ribbonTileIds(sampleWidth, height, settings, { halfRight });
  if (gutters === "checker") {
    for (let y = 0; y < height; y += 1) {
      for (let x = (y + leftGuard + 1) % 2; x < sampleWidth; x += 2) {
        samples[y * sampleWidth + x] = background;
      }
    }
  } else if (gutters !== "none") {
    addGutters(samples, sampleTiles, sampleWidth, along + Number(halfRight), gutters);
  }
  const indices = new Uint8Array(width * height).fill(background);
  const tiles = new Uint16Array(width * height).fill(RIBBON_OUTSIDE_TILE);
  for (let y = 0; y < height; y += 1) {
    indices.set(samples.subarray(y * sampleWidth, (y + 1) * sampleWidth), y * width + leftGuard);
    tiles.set(sampleTiles.subarray(y * sampleWidth, (y + 1) * sampleWidth), y * width + leftGuard);
  }
  return { indices, tiles, leftGuard };
}

function buildStatic(out, settings, gutters, fitter) {
  const { along, across, shape } = settings;
  const { palette, brightnessBands, colorGroups, optimizeMulticolorBitmapImage, optimizeFourLineBitmapImage } = fitter;
  const { indices, tiles, leftGuard } = samplePhase(settings, gutters);
  const source = new ImageData(width, height);
  for (const [pixel, index] of indices.entries()) {
    const offset = pixel * 4;
    source.data.set(palette[index].rgb, offset);
    source.data[offset + 3] = 255;
  }
  const normal = optimizeMulticolorBitmapImage(source, palette, brightnessBands, background, { colorGroups });
  const fitted = optimizeFourLineBitmapImage(source, palette, brightnessBands, background, { colorGroups });
  const changedByBottomMatrix = fitted.screenBottom.reduce((count, value, cell) => {
    const top = fitted.screenTop[cell];
    for (const bits of fitted.bitmap.subarray(cell * 8 + 4, cell * 8 + 8)) {
      for (const shift of [6, 4, 2, 0]) {
        const code = (bits >> shift) & 3;
        if ((code === 1 && value >> 4 !== top >> 4) || (code === 2 && (value & 15) !== (top & 15))) count++;
      }
    }
    return count;
  }, 0);
  const report = {
    shape,
    gutters,
    columns: along,
    radialRows: across,
    leftGuardDisplayPixels: leftGuard * 2,
    logicalPixels: width * height,
    ordinaryMulticolorExact: countExact(source, normal.pixels),
    fourLineExact: countExact(source, fitted.pixels),
    pixelsUsingDifferentBottomScreenColor: changedByBottomMatrix,
    ownership: measureOwnership(tiles, indices, fitted.bitmap),
  };
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, "bitmap.bin"), fitted.bitmap);
  writeFileSync(join(out, "screen-top.bin"), fitted.screenTop);
  writeFileSync(join(out, "screen-bottom.bin"), fitted.screenBottom);
  writeFileSync(join(out, "color-ram.bin"), fitted.colorRam);
  writeFileSync(join(out, "fit.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`${along} × ${across}: ${report.fourLineExact}/${report.logicalPixels} exact pixels (${report.ordinaryMulticolorExact} with one screen matrix).`);
  console.log(`The lower-half matrix changes ${changedByBottomMatrix} logical pixels.`);
}

function buildScrollPhase(out, settings, gutters, rowColors, halfRight, splits, activeRows) {
  const { along, across, shape } = settings;
  const { indices, tiles, leftGuard } = samplePhase(settings, gutters, halfRight);
  const phaseColumns = along + Number(halfRight);
  const stride = along + 1;
  const targets = Uint16Array.from(tiles, (tile, pixel) => {
    if (indices[pixel] === background || tile === RIBBON_OUTSIDE_TILE) return 0xff00 | indices[pixel];
    return Math.floor(tile / phaseColumns) * stride + tile % phaseColumns;
  });
  const fitted = fitScrollBitmap(targets, { columns: along, rows: across, rowColors, splits, activeRows });
  const { bitmap, owners, slotChanges, mappingCycles } = optimizeSlots(fitted.bitmap, fitted.owners, splits);

  const targetData = Buffer.alloc(targets.length * 2);
  for (const [pixel, reference] of targets.entries()) targetData.writeUInt16LE(reference, pixel * 2);
  const screenTop = Buffer.alloc(1000);
  const screenBottom = Buffer.alloc(1000);
  const colorRam = Buffer.alloc(1000);
  const initialColor = (reference) => {
    if (reference >= 0xff00) return reference & 15;
    const row = Math.floor(reference / stride);
    return row < activeRows ? rowColors[row * 1000 + reference % stride] : background;
  };
  let ownerChanges = 0;
  for (let cell = 0; cell < 1000; cell++) {
    const cellRow = Math.floor(cell / 40);
    const split = (splits?.[cellRow] ?? 4) || 8;
    const references = Array.from({ length: 5 }, (_, slot) => owners.readUInt16LE(cell * 10 + slot * 2));
    const colors = references.map(initialColor);
    screenTop[cell] = colors[0] << 4 | colors[1];
    screenBottom[cell] = colors[2] << 4 | colors[3];
    colorRam[cell] = colors[4];
    for (let row = 0; row < 8; row++) {
      const pixel = (cellRow * 8 + row) * width + (cell % 40) * 4;
      const bits = bitmap[cell * 8 + row];
      for (let column = 0; column < 4; column++) {
        const code = (bits >> (6 - 2 * column)) & 3;
        const slot = code === 3 ? 4 : Number(row >= split) * 2 + code - 1;
        const reference = code === 0 ? 0xff00 : references[slot];
        if (reference !== targets[pixel + column]) ownerChanges++;
      }
    }
  }
  const report = {
    shape,
    gutters,
    columns: along,
    radialRows: across,
    leftGuardDisplayPixels: leftGuard * 2,
    logicalPixels: width * height,
    changedOwnerPixels: ownerChanges,
    ...(splits && { splits }),
    ...(activeRows !== across && { activeRows }),
    slotChanges,
    mappingCycles,
  };
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, "bitmap.bin"), bitmap);
  writeFileSync(join(out, "screen-top.bin"), screenTop);
  writeFileSync(join(out, "screen-bottom.bin"), screenBottom);
  writeFileSync(join(out, "color-ram.bin"), colorRam);
  writeFileSync(join(out, "owners.bin"), owners);
  writeFileSync(join(out, "target-tiles.bin"), targetData);
  writeFileSync(join(out, "fit.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`Phase ${halfRight ? "B" : "A"}: ${ownerChanges} logical pixels use a different tile owner.`);
  console.log(`Slot changes: ${slotChanges.before} to ${slotChanges.after}. Mapping cycles before raster packing: ${mappingCycles.before} to ${mappingCycles.after}.`);
}

function readSplitPlan(path) {
  const plan = JSON.parse(readFileSync(path, "utf8"));
  for (const phase of ["phaseA", "phaseB"]) {
    const splits = plan?.[phase];
    if (!Array.isArray(splits) || splits.length !== 25 ||
        splits.some((split, row) => !Number.isInteger(split) || split < 0 || split > (row === 24 ? 4 : 7))) {
      throw new Error(`Split plan ${phase} must contain 25 cuts from 0 to 7, with at most 4 on the last row.`);
    }
  }
  return plan;
}

function main() {
  const args = process.argv.slice(2);
  const splitPlanIndex = args.indexOf("--split-plan");
  const [, splitPlanPath] = splitPlanIndex >= 0 ? args.splice(splitPlanIndex, 2) : [];
  const activeRowsIndex = args.indexOf("--active-rows");
  const [, activeRowsArg] = activeRowsIndex >= 0 ? args.splice(activeRowsIndex, 2) : [];
  const scrollIndex = args.indexOf("--scroll");
  const scroll = scrollIndex >= 0;
  const [, rowColorPath, ...extraScrollArgs] = scroll ? args.splice(scrollIndex) : [];
  const [destination, columns = "64", rows = "16", shape = "record", gutters = "none", ...rest] = args;
  if ((destination === "--help" || destination === "-h") && !rest.length) {
    console.log(usage);
    return;
  }
  const along = Number(columns);
  const across = Number(rows);
  const activeRows = activeRowsIndex >= 0 ? Number(activeRowsArg) : across;
  if (!destination || rest.length || extraScrollArgs.length || (splitPlanIndex >= 0 && (!scroll || !splitPlanPath)) ||
      (activeRowsIndex >= 0 && (!scroll || !Number.isInteger(activeRows) || activeRows < 1 || activeRows > across)) ||
      !["record", "track", "ribbon"].includes(shape) ||
      !["none", "rows", "columns", "both", "checker"].includes(gutters) || !Number.isInteger(along) || along < 1 || along > 80 ||
      !Number.isInteger(across) || across < 1 || across > 32) throw new Error(usage);

  const thickness = shape === "ribbon" && activeRows < across ? 0.7 : 0.57;
  const settings = { shape, along, across, amplitude: 0.72, waves: 1.15, twist: 0.8, thickness };
  const out = resolve(destination);
  if (scroll) {
    const rowColors = prepareRows(rowColorPath, activeRows, along);
    const splitPlan = splitPlanPath ? readSplitPlan(splitPlanPath) : undefined;
    buildScrollPhase(join(out, "phase-a"), settings, gutters, rowColors, false, splitPlan?.phaseA, activeRows);
    buildScrollPhase(join(out, "phase-b"), settings, gutters, rowColors, true, splitPlan?.phaseB, activeRows);
    writeFileSync(join(out, "row-colors.bin"), rowColors);
    return;
  }

  const fitter = loadFitter();
  const { palette, brightnessBands } = fitter.createC64PaletteState("colodore");
  const colorGroups = palette.map(({ index }) => index + RIBBON_INDEX_PATTERN[0].length);
  for (const row of RIBBON_INDEX_PATTERN) {
    for (const [column, color] of row.entries()) colorGroups[color] = column;
  }
  buildStatic(out, settings, gutters, { ...fitter, palette, brightnessBands, colorGroups });
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
