"use strict";

const { readFileSync, statSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");

const usage = "Usage: node generate-demo-colors.cjs <chargen.bin> <font16.json> <output.bin>";
const rows = 16;
const rowBytes = 1000;
const wrapBytes = 63;
const period = rowBytes - wrapBytes;
const glyphSize = 16;
const black = 0;
const white = 1;
const darkBlue = 6;
const lightBlue = 14;
const darkGray = 11;
const mediumGray = 12;
const lightGray = 15;
const gradientColors = [0, 9, 2, 4, 12, 10, 15, 7, 1, 13, 3, 14, 12, 4, 11, 6];
const intro = "*** COMMODORE 64 ***";
const caption = "ASYNKRON PRESENTS";
const graphicsPath = join(__dirname, "demo", "font-scroll-colors.bin");
// Keep the five game graphics from the original tape.
const graphicsSourceStart = 148;
const graphicsSourceEnd = 239;
const introStart = 16;
const fadeStart = introStart + intro.length * glyphSize + 16;
const fadeWidth = 64;
const graphicsStart = fadeStart + fadeWidth + 8;
const gradientStart = graphicsStart + graphicsSourceEnd - graphicsSourceStart + 9;
const gradientStep = 7;
const gradientWidth = (gradientColors.length - 1) * gradientStep + 4;
const gradientTop = 4;
const captionStart = gradientStart + gradientWidth + 16;

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

function antialiasGlyph(mask) {
  const inkAt = (x, y) => x >= 0 && x < glyphSize && y >= 0 && y < glyphSize
    && (mask[y] & (0x8000 >> x)) !== 0;

  return mask.map((_, y) => Uint8Array.from({ length: glyphSize }, (_, x) => {
    const ink = inkAt(x, y);
    let corners = 0;
    // A change at a corner requires all three surrounding pixels to agree.
    // Straight edges and the centers of strokes keep their original color.
    for (const dy of [-1, 1]) {
      for (const dx of [-1, 1]) {
        corners += Number(inkAt(x + dx, y) !== ink
          && inkAt(x, y + dy) !== ink
          && inkAt(x + dx, y + dy) !== ink);
      }
    }
    if (ink) return corners > 0 ? lightGray : white;
    if (corners === 0) return black;
    return corners === 1 ? darkGray : mediumGray;
  }));
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
    glyphs.set(character, antialiasGlyph(mask.map((line) => Number.parseInt(line, 16))));
  }
  return glyphs;
}

function drawGradientRow(colors, base, row) {
  const thresholds = bayer[row - gradientTop];
  if (!thresholds) return;

  for (let x = 0; x < gradientWidth; x += 1) {
    const stop = Math.floor(x / gradientStep);
    const blend = x % gradientStep;
    const useNext = stop + 1 < gradientColors.length && thresholds[x & 7] * gradientStep < blend * 64;
    colors[base + gradientStart + x] = gradientColors[stop + Number(useNext)];
  }
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
    drawGradientRow(colors, base, row);
    for (const [index, character] of Array.from(caption).entries()) {
      const start = base + captionStart + index * glyphSize;
      colors.set(font.get(character)[row], start);
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
