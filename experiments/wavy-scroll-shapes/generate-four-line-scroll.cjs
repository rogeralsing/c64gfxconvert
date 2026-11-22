"use strict";

const { readFileSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");
const { parseArgs } = require("node:util");
const { RIBBON_INDEX_PATTERN } = require("./ribbon.js");
const { compileRasterPlan, instructionCycles } = require("./pack-four-line-raster.cjs");

const rowBytes = 1000;
// At the end of the stream, phase B's extra column and nibble alignment can
// make the lookup fetch two more packed bytes than fit in the base row.
const packedRowBytes = rowBytes / 2 + 2;
const cells = 1000;
const cellsPerRow = 40;
const fixedBlack = 0xff00;
const packedRowAddress = 0xe000;
const usage = "Usage: node generate-four-line-scroll.cjs <asset-directory> [row-colors.bin] [--step 0.5|1.5] [--fields-per-step 3|4] [--foreground]";

function readPhase(out, name, lookupSize) {
  const path = join(out, `phase-${name.toLowerCase()}`);
  const bitmap = readFileSync(join(path, "bitmap.bin"));
  const owners = readFileSync(join(path, "owners.bin"));
  if (bitmap.length !== cells * 8 || owners.length !== cells * 10) {
    throw new Error(`Invalid bitmap or owner table for phase ${name}.`);
  }
  const planes = [];
  for (let cell = 0; cell < cells; cell++) {
    const used = [0, 0];
    for (let row = 0; row < 8; row++) {
      const byte = bitmap[cell * 8 + row];
      for (let shift = 0; shift < 8; shift += 2) used[row >> 2] |= 1 << ((byte >> shift) & 3);
    }
    const refs = Array.from({ length: 5 }, (_, slot) => owners.readUInt16LE(cell * 10 + slot * 2));
    for (const ref of refs) {
      if (ref >= lookupSize && (ref < fixedBlack || ref > fixedBlack + 15)) {
        throw new Error(`Invalid owner reference for phase ${name} at cell ${cell}.`);
      }
    }
    planes.push({ used, refs });
  }
  return planes;
}

function immediate(value) {
  return `#$${value.toString(16).padStart(2, "0")}`;
}

function lookupIndex(ref, lookup) {
  // The player writes the even and odd colors into separate halves of each LUT row.
  const { width, half, shift } = lookup;
  const row = Math.floor(ref / width);
  const column = ref % width + shift;
  return row * 2 * half + (column >> 1) + (column & 1) * half;
}

function operand(ref, high, lookup, lowTable = "waveLutLow") {
  if (ref >= fixedBlack) return immediate((ref & 15) << (high ? 4 : 0));
  return `${high ? "waveLutHigh" : lowTable} + ${lookupIndex(ref, lookup)}`;
}

function emitWrites(cellsByValue, address, load) {
  const code = [];
  for (const [value, destinations] of cellsByValue.entries()) {
    code.push(...load(value, destinations));
    for (const cell of destinations) code.push(`sta ${address} + ${cell}`);
  }
  return code;
}

function addDestination(writes, value, cell) {
  if (!writes.has(value)) writes.set(value, []);
  writes.get(value).push(cell);
}

function loadPair(pair, lookup) {
  const high = pair >>> 16;
  const low = pair & 0xffff;
  if (high >= fixedBlack && low >= fixedBlack) return [`lda ${immediate(((high & 15) << 4) | (low & 15))}`];
  if (high === fixedBlack) return [`lda ${operand(low, false, lookup)}`];
  if (low === fixedBlack) return [`lda ${operand(high, true, lookup)}`];
  return [`lda ${operand(high, true, lookup)}`, `ora ${operand(low, false, lookup)}`];
}

function collectPhase(planes, phase) {
  const groups = new Set();
  for (const [cell, { used, refs }] of planes.entries()) {
    if ((used[1] & 2 && refs[0] !== refs[2]) || (used[1] & 4 && refs[1] !== refs[3])) {
      groups.add(Math.floor(cell / cellsPerRow));
    }
  }

  const top = new Map();
  const bottom = new Map();
  const color = new Map();
  for (const [cell, { used, refs }] of planes.entries()) {
    const split = groups.has(Math.floor(cell / cellsPerRow));
    if (split && cell % cellsPerRow < 3 && (used[1] & ~1)) {
      throw new Error(`Phase ${phase} must leave the first three cells clear on late fetches.`);
    }
    const topCodes = split ? used[0] : used[0] | used[1];
    const bottomCodes = split ? used[1] : 0;
    const topHigh = topCodes & 2 ? refs[0] : fixedBlack;
    const topLow = topCodes & 4 ? refs[1] : fixedBlack;
    const bottomHigh = bottomCodes & 2 ? refs[2] : fixedBlack;
    const bottomLow = bottomCodes & 4 ? refs[3] : fixedBlack;
    // Both matrices start cleared and each phase always writes to its own bank.
    if (topHigh !== fixedBlack || topLow !== fixedBlack) addDestination(top, topHigh * 0x10000 + topLow, cell);
    if (bottomHigh !== fixedBlack || bottomLow !== fixedBlack) addDestination(bottom, bottomHigh * 0x10000 + bottomLow, cell);
    if ((used[0] | used[1]) & 8) addDestination(color, refs[4], cell);
  }
  return { groups: [...groups], top, bottom, color };
}

function previousRef(ref, { width, shift }) {
  if (ref >= fixedBlack) return ref;
  // The trailing column can fall beyond A's available columns. Keep it
  // distinct from the first column of the following wave row.
  return ref % width + shift < width ? ref + shift : -1;
}

function previousScreenSources(previous) {
  const pairs = new Map();
  const lows = new Map();
  for (const [address, writes] of [["screenTopA", previous.top], ["screenBottomA", previous.bottom]]) {
    for (const [pair, locations] of writes) {
      for (const cell of locations) {
        const source = { address, cell };
        addDestination(pairs, pair, source);
        addDestination(lows, pair & 0xffff, source);
      }
    }
  }
  return { pairs, lows };
}

function findRightNeighbor(sources, destinations) {
  return sources.find(({ cell }) => cell % cellsPerRow !== 0 && destinations.includes(cell - 1));
}

function loadScreenByte({ address, cell }) {
  return `lda ${address} + ${cell}`;
}

function reuseScreenLoads(pairs, lookup, metrics) {
  return (pair, destinations) => {
    const load = loadPair(pair, lookup);
    if (load.length === 1) return load;
    const high = previousRef(pair >>> 16, lookup);
    const low = previousRef(pair & 0xffff, lookup);
    if (high < 0 || low < 0) return load;
    const sources = pairs.get(high * 0x10000 + low);
    if (!sources) return load;

    // A remains displayed while we build B. Pick the previous image's
    // right neighbor wherever that byte can supply this group of stores.
    const rightNeighbor = findRightNeighbor(sources, destinations);
    const replacement = loadScreenByte(rightNeighbor ?? sources[0]);
    metrics.groups++;
    if (rightNeighbor) metrics.rightNeighborGroups++;
    metrics.stores += destinations.length;
    metrics.mappingCyclesSaved += load.reduce((total, line) => total + instructionCycles(line), 0)
      - instructionCycles(replacement);
    return [replacement];
  };
}

function omitUnchangedColorWrites(color, previous, lookup, metrics) {
  const previousAt = new Map();
  for (const [ref, destinations] of previous) {
    for (const cell of destinations) previousAt.set(cell, ref);
  }
  const changed = new Map();
  for (const [ref, destinations] of color) {
    const priorRef = previousRef(ref, lookup);
    const writes = destinations.filter((cell) => previousAt.get(cell) !== priorRef);
    const skipped = destinations.length - writes.length;
    metrics.storesSkipped += skipped;
    metrics.mappingCyclesSaved += skipped * 4;
    if (writes.length) changed.set(ref, writes);
    else metrics.mappingCyclesSaved += instructionCycles(`lda ${operand(ref, false, lookup, "waveLutColorB")}`);
  }
  return changed;
}

function denseCopyCycles(size, load, branch) {
  const pages = Math.floor(size / 256);
  const tail = size % 256;
  return (pages ? 1 + 256 * ((load + 5) * pages + 2 + branch) : 0)
    + (tail ? 1 + tail * (load + 5 + 2 + 2 + branch) : 0);
}

function colorBackup(indexes, denseSize) {
  const sorted = [...indexes].sort((a, b) => a - b);
  const slots = new Map();
  const groups = [];
  for (const [slot, index] of sorted.entries()) {
    const page = index >> 8;
    const last = groups.at(-1);
    if (last?.page !== page || last.count === 128) groups.push({ page, start: slot, count: 0 });
    groups.at(-1).count++;
    slots.set(index, slot);
  }
  // Compare a worst-case sparse loop against the cheapest dense copy.
  // Each sparse entry occupies one index byte and one destination byte.
  const sparseCycles = sorted.length * 21 + groups.length * 2;
  const sparse = sparseCycles < denseCopyCycles(denseSize, 4, 3)
    && 2 * sorted.length + 14 * groups.length <= denseSize;
  return {
    sparse,
    size: sparse ? sorted.length : denseSize,
    worstCaseCycles: sparse ? sparseCycles : denseCopyCycles(denseSize, 5, 4),
    slots,
    groups: sparse ? groups : [],
    indices: sparse ? sorted.map((index) => index & 255) : [],
  };
}

function planColorB(writes, lows, lookup, metrics) {
  const loads = new Map();
  const toCopy = new Set();
  for (const [ref, destinations] of writes) {
    if (ref >= fixedBlack) continue;
    const sources = lows.get(previousRef(ref, lookup));
    if (!sources) {
      toCopy.add(lookupIndex(ref, lookup));
      continue;
    }
    // A screen byte already has the needed low nibble. Color RAM discards
    // the high nibble, so using the displayed matrix needs no mask.
    loads.set(ref, loadScreenByte(findRightNeighbor(sources, destinations) ?? sources[0]));
    metrics.screenLoadGroups++;
    metrics.screenLoadStores += destinations.length;
  }
  const backup = colorBackup(toCopy, lookup.rows * 2 * lookup.half);
  metrics.backupBytes = backup.size;
  metrics.backupWorstCaseCycles = backup.worstCaseCycles;
  return {
    backup,
    load(ref) {
      if (loads.has(ref)) return loads.get(ref);
      if (ref < fixedBlack && backup.sparse) return `lda waveLutColorB + ${backup.slots.get(lookupIndex(ref, lookup))}`;
      return `lda ${operand(ref, false, lookup, "waveLutColorB")}`;
    },
  };
}

function emitSparseColorBCopy({ groups, indices }) {
  const copy = groups.flatMap(({ page, start, count }) => [
    `    ldx #${count - 1}`,
    "!copy:",
    `    ldy colorBIndices + ${start},x`,
    `    lda waveLutLow + ${page * 256},y`,
    `    sta waveLutColorB + ${start},x`,
    "    dex",
    "    bpl !copy-",
  ]);
  const table = [];
  for (let start = 0; start < indices.length; start += 16) {
    table.push(`    .byte ${indices.slice(start, start + 16).join(", ")}`);
  }
  return [".macro PreserveSparseColorB() {", ...copy, "}",
    ".macro EmitSparseColorBIndices() {", ...table, "}"];
}

function compilePhase({ groups, top, bottom, color }, phase, lookup, previous) {
  const reuse = {
    screenRam: { groups: 0, rightNeighborGroups: 0, stores: 0, mappingCyclesSaved: 0 },
    colorRam: { storesSkipped: 0, mappingCyclesSaved: 0, screenLoadGroups: 0, screenLoadStores: 0 },
  };
  const sources = previous ? previousScreenSources(previous) : null;
  const load = sources
    ? reuseScreenLoads(sources.pairs, lookup, reuse.screenRam)
    : (pair) => loadPair(pair, lookup);
  const colorWrites = previous
    ? omitUnchangedColorWrites(color, previous.color, lookup, reuse.colorRam)
    : color;
  const colorB = sources ? planColorB(colorWrites, sources.lows, lookup, reuse.colorRam) : null;
  const colorLoad = colorB ? colorB.load : (ref) => `lda ${operand(ref, false, lookup)}`;
  return {
    groups,
    reuse,
    backup: colorB?.backup,
    writers: {
      [`ScreenTop${phase}`]: emitWrites(top, `screenTop${phase}`, load),
      [`ScreenBottom${phase}`]: emitWrites(bottom, `screenBottom${phase}`, load),
      [`Color${phase}`]: emitWrites(colorWrites, "colorRam", (ref) => [colorLoad(ref)]),
    },
  };
}

function prepareRows(source, rows, columns) {
  const period = rowBytes + 1 - columns;
  const data = source ? readFileSync(source) : Buffer.alloc(rows * rowBytes);
  if (data.length !== rows * rowBytes || data.some((color) => color > 15)) {
    throw new Error(`Expected ${rows} rows of ${rowBytes} C64 palette indices.`);
  }
  for (let row = 0; row < rows; row++) {
    const base = row * rowBytes;
    const pattern = RIBBON_INDEX_PATTERN[row % RIBBON_INDEX_PATTERN.length];
    if (!source) {
      for (let column = 0; column < rowBytes; column++) data[base + column] = pattern[(column % period) % pattern.length];
    }
    if (!data.subarray(base + period, base + rowBytes).equals(data.subarray(base, base + columns - 1))) {
      throw new Error(`Row ${row + 1} must end with a copy of its first ${columns - 1} colors.`);
    }
  }
  return data;
}

function compressRows(data) {
  const tokens = [];
  const positions = new Map();
  let literal = [];
  const keyAt = (offset) => data[offset] * 65536 + data[offset + 1] * 256 + data[offset + 2];
  const flush = () => {
    if (literal.length === 0) return;
    tokens.push(literal.length, ...literal);
    literal = [];
  };

  let cursor = 0;
  while (cursor < data.length) {
    const limit = Math.min(130, data.length - cursor);
    const candidates = limit >= 3 ? positions.get(keyAt(cursor)) ?? [] : [];
    let bestMatch = 0;
    let bestLength = 0;
    for (let index = candidates.length - 1; index >= 0; index--) {
      const start = candidates[index];
      let length = 3;
      while (length < limit && data[start + length] === data[cursor + length]) length++;
      if (length > bestLength) {
        bestLength = length;
        bestMatch = start;
      }
      if (length === limit) break;
    }

    // The loader copies back-references forward, including overlapping runs.
    if (bestLength >= 3) {
      flush();
      const address = packedRowAddress + bestMatch;
      tokens.push(125 + bestLength, address & 255, address >> 8);
    } else {
      literal.push(data[cursor]);
      if (literal.length === 127) flush();
    }
    const end = cursor + Math.max(1, bestLength);
    for (; cursor < end; cursor++) {
      if (cursor + 2 >= data.length) continue;
      const key = keyAt(cursor);
      if (!positions.has(key)) positions.set(key, []);
      positions.get(key).push(cursor);
    }
  }
  flush();
  return Buffer.from([...tokens, 0]);
}

function main() {
  const { positionals: [out, source, ...rest], values: { foreground, step, "fields-per-step": fields } } = parseArgs({
    allowPositionals: true,
    options: {
      foreground: { type: "boolean" },
      step: { type: "string", default: "1.5" },
      "fields-per-step": { type: "string", default: "4" },
    },
  });
  if (!out || rest.length || !["0.5", "1.5"].includes(step) || !["3", "4"].includes(fields)) {
    throw new Error(usage);
  }
  const fieldsPerAdvance = Number(fields);
  // Phase B already moves the geometry half a column relative to phase A.
  // A(n), B(n+1), A(n+3) give 1.5 columns on both transitions.
  const stepHalfColumns = step === "1.5" ? 3 : 1;
  const bOffset = (stepHalfColumns - 1) / 2;
  const { columns, radialRows: rows } = JSON.parse(readFileSync(join(out, "phase-a", "fit.json"), "utf8"));
  const lookupSize = rows * (columns + 1);
  const lookup = { width: columns + 1, half: Math.floor((columns + 1 + bOffset) / 2) + 1, rows };
  const previous = collectPhase(readPhase(out, "A", lookupSize), "A");
  const a = compilePhase(previous, "A", { ...lookup, shift: 0 });
  const b = compilePhase(collectPhase(readPhase(out, "B", lookupSize), "B"), "B",
    { ...lookup, shift: bOffset }, previous);
  const plan = compileRasterPlan(a, b, !foreground);
  const assembly = [
    "// Generated by generate-four-line-scroll.cjs.",
    `.const columnsA = ${columns}`,
    `.const rowCount = ${rows}`,
    `.const packedRowBytes = ${packedRowBytes}`,
    `.const fieldsPerAdvance = ${fieldsPerAdvance}`,
    `.const scrollColumnsPerPair = ${stepHalfColumns}`,
    `.const scrollBOffset = ${bOffset}`,
    `.const sparseColorBLookup = ${b.backup.sparse}`,
    `.const colorBLookupSize = ${b.backup.size}`,
    ...emitSparseColorBCopy(b.backup),
    ".var phaseAGroups = List()",
    ...a.groups.map((group) => `.eval phaseAGroups.add(${group})`),
    ".var phaseBGroups = List()",
    ...b.groups.map((group) => `.eval phaseBGroups.add(${group})`),
    ...Object.entries(plan.constants).map(([name, value]) => `.const ${name} = ${value}`),
    ".macro EmitRasterPlanTables() {",
    ...plan.tables.map((line) => `    ${line}`),
    "}",
    ".macro CallPackedScreenA() {",
    ...plan.startupCalls.map((line) => `    ${line}`),
    "}",
    "",
  ];
  for (const [name, code] of Object.entries({ ...a.writers, ...b.writers })) {
    const cycles = code.reduce((sum, line) => sum + instructionCycles(line), 0);
    const metric = name[0].toLowerCase() + name.slice(1, -1) + "Cycles" + name.at(-1);
    const instructions = plan.writers[name] ?? code;
    assembly.push(`.const ${metric} = ${cycles}`, `.macro Write${name}() {`,
      ...instructions.map((line) => `    ${line}`), "}", "");
    console.log(`${name}: ${cycles} mapping cycles`);
  }
  const raw = prepareRows(source, rows, columns);
  const period = rowBytes + 1 - columns;
  const packed = Buffer.alloc(rows * packedRowBytes);
  if (packedRowAddress + packed.length > 0xfffa) throw new Error("The player can store up to 16 color rows.");
  for (let row = 0; row < rows; row++) {
    for (let offset = 0; offset < packedRowBytes; offset++) {
      const low = raw[row * rowBytes + (offset * 2) % period];
      const high = raw[row * rowBytes + (offset * 2 + 1) % period];
      packed[row * packedRowBytes + offset] = low | (high << 4);
    }
  }
  const packedLz = compressRows(packed);
  writeFileSync(join(out, "row-colors.bin"), raw);
  writeFileSync(join(out, "row-colors-lz.bin"), packedLz);
  writeFileSync(join(out, "four-line-scroll-generated.asm"), assembly.join("\n"));
  const report = { mode: plan.report ? "raster" : "foreground", stepHalfColumns, fieldsPerAdvance, reuse: b.reuse, ...plan.report };
  writeFileSync(join(out, "raster-plan.json"), `${JSON.stringify(report, null, 2)}\n`);
  if (plan.report) {
    console.log(`Packed screen updates into ${plan.constants.rasterMapFieldsA} fields during A and ${plan.constants.rasterMapFieldsB} fields during B.`);
  }
  console.log(`Late fetches per field: A=${a.groups.length}, B=${b.groups.length}.`);
  console.log(`Scroll step: ${step} columns every ${fieldsPerAdvance} PAL fields.`);
  console.log(`Packed color rows: ${packedLz.length} compressed bytes.`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

module.exports = { prepareRows };
