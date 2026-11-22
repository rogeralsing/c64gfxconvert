"use strict";

const { readFileSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");
const { parseArgs } = require("node:util");
const { RIBBON_INDEX_PATTERN } = require("./ribbon.js");
const { compileRasterPlan, instructionCycles } = require("./pack-four-line-raster.cjs");

const rowBytes = 1000;
const cells = 1000;
const fixedBlack = 0xff00;
const packedRowAddress = 0xe000;
const usage = "Usage: node generate-four-line-scroll.cjs <asset-directory> [row-colors.bin] [--step 0.5|1.5] [--foreground]";

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

function operand(ref, high, lookup, lowTable = "waveLutLow") {
  if (ref >= fixedBlack) return immediate((ref & 15) << (high ? 4 : 0));
  // The player writes the even and odd colors into separate halves of each LUT row.
  const { width, half, shift } = lookup;
  const row = Math.floor(ref / width);
  const column = ref % width + shift;
  const index = row * 2 * half + (column >> 1) + (column & 1) * half;
  return `${high ? "waveLutHigh" : lowTable} + ${index}`;
}

function emitWrites(cellsByValue, address, load) {
  const code = [];
  for (const [value, destinations] of cellsByValue.entries()) {
    code.push(...load(value));
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

function compilePhase(planes, phase, lookup) {
  const groups = new Set();
  for (const [cell, { used, refs }] of planes.entries()) {
    if ((used[1] & 2 && refs[0] !== refs[2]) || (used[1] & 4 && refs[1] !== refs[3])) {
      groups.add(Math.floor(cell / 40));
    }
  }

  const top = new Map();
  const bottom = new Map();
  const color = new Map();
  for (const [cell, { used, refs }] of planes.entries()) {
    const split = groups.has(Math.floor(cell / 40));
    if (split && cell % 40 < 3 && (used[1] & ~1)) {
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
  return {
    groups: [...groups],
    writers: {
      [`ScreenTop${phase}`]: emitWrites(top, `screenTop${phase}`, (pair) => loadPair(pair, lookup)),
      [`ScreenBottom${phase}`]: emitWrites(bottom, `screenBottom${phase}`, (pair) => loadPair(pair, lookup)),
      [`Color${phase}`]: emitWrites(color, "colorRam", (ref) => [
        `lda ${operand(ref, false, lookup, phase === "B" ? "waveLutColorB" : "waveLutLow")}`,
      ]),
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
  const { positionals: [out, source, ...rest], values: { foreground, step } } = parseArgs({
    allowPositionals: true,
    options: { foreground: { type: "boolean" }, step: { type: "string", default: "1.5" } },
  });
  if (!out || rest.length || !["0.5", "1.5"].includes(step)) throw new Error(usage);
  // Phase B already moves the geometry half a column relative to phase A.
  // A(n), B(n+1), A(n+3) give 1.5 columns on both transitions.
  const stepHalfColumns = step === "1.5" ? 3 : 1;
  const bOffset = (stepHalfColumns - 1) / 2;
  const { columns, radialRows: rows } = JSON.parse(readFileSync(join(out, "phase-a", "fit.json"), "utf8"));
  const lookupSize = rows * (columns + 1);
  const lookup = { width: columns + 1, half: Math.floor((columns + 1 + bOffset) / 2) + 1 };
  const a = compilePhase(readPhase(out, "A", lookupSize), "A", { ...lookup, shift: 0 });
  const b = compilePhase(readPhase(out, "B", lookupSize), "B", { ...lookup, shift: bOffset });
  const plan = compileRasterPlan(a, b, !foreground);
  const assembly = [
    "// Generated by generate-four-line-scroll.cjs.",
    `.const columnsA = ${columns}`,
    `.const rowCount = ${rows}`,
    `.const scrollColumnsPerPair = ${stepHalfColumns}`,
    `.const scrollBOffset = ${bOffset}`,
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
  const packed = Buffer.alloc(raw.length / 2);
  for (let offset = 0; offset < packed.length; offset++) packed[offset] = raw[offset * 2] | (raw[offset * 2 + 1] << 4);
  if (packedRowAddress + packed.length > 0xfffa) throw new Error("The player can store up to 16 color rows.");
  const packedLz = compressRows(packed);
  writeFileSync(join(out, "row-colors.bin"), raw);
  writeFileSync(join(out, "row-colors-lz.bin"), packedLz);
  writeFileSync(join(out, "four-line-scroll-generated.asm"), assembly.join("\n"));
  const report = { mode: plan.report ? "raster" : "foreground", stepHalfColumns, ...plan.report };
  writeFileSync(join(out, "raster-plan.json"), `${JSON.stringify(report, null, 2)}\n`);
  if (plan.report) {
    console.log(`Packed screen updates into ${plan.constants.rasterMapFieldsA} fields during A and ${plan.constants.rasterMapFieldsB} fields during B.`);
  }
  console.log(`Late fetches per field: A=${a.groups.length}, B=${b.groups.length}.`);
  console.log(`Scroll step: ${step} columns per update.`);
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
