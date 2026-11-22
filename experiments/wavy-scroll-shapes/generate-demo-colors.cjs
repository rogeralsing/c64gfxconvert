"use strict";

const { readFileSync, statSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");

const usage = "Usage: node generate-demo-colors.cjs <chargen.bin> <font16.json> <output.bin>";
const rows = 16;
const rowBytes = 1000;
const wrapBytes = 63;
const period = rowBytes - wrapBytes;
const glyphSize = 16;
const darkBlue = 6;
const lightBlue = 14;
const intro = "*** COMMODORE 64 ***";
const caption = "ASYNKRON PRESENTS";
const graphicsPath = join(__dirname, "demo", "font-scroll-colors.bin");
// The original tape contains this same group of game graphics and color patterns twice.
const graphicsSourceStart = 148;
const graphicsSourceEnd = 357;
const introStart = 16;
const fadeStart = introStart + intro.length * glyphSize + 16;
const fadeWidth = 64;
const graphicsStart = fadeStart + fadeWidth + 8;
const captionStart = graphicsStart + graphicsSourceEnd - graphicsSourceStart + 16;

const bayer = [
  [0, 48, 12, 60, 3, 51, 15, 63],
  [32, 16, 44, 28, 35, 19, 47, 31],
  [8, 56, 4, 52, 11, 59, 7, 55],
  [40, 24, 36, 20, 43, 27, 39, 23],
  [2, 50, 14, 62, 1, 49, 13, 61],
  [34, 18, 46, 30, 33, 17, 45, 29],
  [10, 58, 6, 54, 9, 57, 5, 53],
  [42, 26, 38, 22, 41, 25, 37, 21],
];

function readRom(path) {
  const rom = readFileSync(path);
  const space = 32 * 8;
  const reversedSpace = (32 + 128) * 8;
  if (rom.length !== 4096 ||
      !rom.subarray(space, space + 8).every((byte) => byte === 0) ||
      !rom.subarray(reversedSpace, reversedSpace + 8).every((byte) => byte === 255)) {
    throw new Error("Expected a C64 character ROM with the uppercase and graphics set first.");
  }
  return rom;
}

function readFont(path) {
  const data = JSON.parse(readFileSync(path, "utf8"));
  const glyphs = new Map();
  for (const character of new Set(caption)) {
    const mask = data?.[character];
    if (!Array.isArray(mask) || mask.length !== glyphSize ||
        !mask.every((line) => typeof line === "string" && /^[0-9a-f]{4}$/i.test(line))) {
      throw new Error(`Expected 16 four-digit hex rows for ${JSON.stringify(character)} in the 16×16 font.`);
    }
    glyphs.set(character, mask.map((line) => Number.parseInt(line, 16)));
  }
  return glyphs;
}

function render(rom, font, graphics) {
  if (graphics.length !== rows * rowBytes || graphics.some((color) => color > 15)) {
    throw new Error("Expected the original 16 × 1000 C64 palette-index color tape.");
  }
  if (captionStart + caption.length * glyphSize > period) {
    throw new Error("Scroll sequence exceeds its 937-column loop.");
  }
  const colors = Buffer.alloc(rows * rowBytes);

  for (let row = 0; row < rows; row += 1) {
    const base = row * rowBytes;
    colors.fill(darkBlue, base, base + fadeStart);
    for (const [index, character] of Array.from(intro).entries()) {
      const ascii = character.charCodeAt(0);
      const code = ascii >= 0x41 ? ascii - 0x40 : ascii;
      const bits = rom[code * 8 + (row >> 1)];
      const start = base + introStart + index * glyphSize;
      for (let x = 0; x < 8; x += 1) {
        if (bits & (0x80 >> x)) colors.fill(lightBlue, start + 2 * x, start + 2 * x + 2);
      }
    }
    for (let x = 0; x < fadeWidth; x += 1) {
      if (bayer[row & 7][x & 7] < fadeWidth - x - 1) {
        colors[base + fadeStart + x] = darkBlue;
      }
    }
    graphics.copy(colors, base + graphicsStart, base + graphicsSourceStart, base + graphicsSourceEnd);
    for (const [index, character] of Array.from(caption).entries()) {
      const mask = font.get(character)[row];
      const start = base + captionStart + index * glyphSize;
      for (let x = 0; x < glyphSize; x += 1) {
        if (mask & (0x8000 >> x)) colors[start + x] = lightBlue;
      }
    }
    colors.copy(colors, base + period, base, base + wrapBytes);
  }
  return colors;
}

function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && ["-h", "--help"].includes(args[0])) {
    console.log(usage);
    return;
  }
  if (args.length !== 3) throw new Error(usage);
  const [romPath, fontPath, outputPath] = args;
  const destination = statSync(outputPath, { throwIfNoEntry: false });
  if (destination && [romPath, fontPath, graphicsPath].some((path) => {
    const source = statSync(path);
    return destination.dev === source.dev && destination.ino === source.ino;
  })) {
    throw new Error("Choose an output path separate from the input files.");
  }
  writeFileSync(outputPath, render(readRom(romPath), readFont(fontPath), readFileSync(graphicsPath)));
  console.log(`Wrote ${rows} × ${rowBytes} color bytes to ${outputPath}.`);
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
