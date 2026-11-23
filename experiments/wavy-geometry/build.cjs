"use strict";

const { mkdtempSync, mkdirSync, copyFileSync, readFileSync, rmSync, writeFileSync } = require("node:fs");
const { join, resolve } = require("node:path");
const { tmpdir } = require("node:os");
const { execFileSync } = require("node:child_process");
const engine = join(__dirname, "../wavy-scroll-shapes");
const { buildScrollPhase } = require(join(engine, "generate-four-line-bitmap.cjs"));
const { prepareRows } = require(join(engine, "generate-four-line-scroll.cjs"));
const { RIBBON_OUTSIDE_TILE, RIBBON_INDEX_PATTERN } = require(join(engine, "ribbon.js"));

const width = 160;
const height = 200;
const columns = 64;
const tunnelDepthColumns = 24;
const rows = 16;
const leftGuard = 12;
const shapes = {
  spiral: { title: "Spiralband", fields: 4 },
  disc: { title: "Lutad skiva", fields: 3 },
  tunnel: { title: "Tunnel", fields: 3 },
};
const files = ["bitmap.bin", "owners.bin", "target-tiles.bin"];

function samplePhase(sample, halfRight, visibleColumns) {
  const indices = new Uint8Array(width * height);
  const tiles = new Uint16Array(width * height).fill(RIBBON_OUTSIDE_TILE);
  const stride = columns + Number(halfRight);
  for (let y = 0; y < height; y += 1) {
    for (let x = leftGuard; x < width; x += 1) {
      const uv = sample(x * 2 + 1, y + 0.5);
      if (!uv) continue;
      const [u, v] = uv;
      if (!(u >= 0 && u <= 1 && v >= 0 && v <= 1)) {
        throw new Error(`Geometry returned invalid tape coordinates at ${x}, ${y}`);
      }
      const row = Math.min(rows - 1, Math.floor(v * rows));
      const column = Math.min(visibleColumns + Number(halfRight) - 1,
        Math.floor(u * visibleColumns + (halfRight ? 0.5 : 0)));
      const pixel = y * width + x;
      tiles[pixel] = row * stride + column;
      indices[pixel] = 1;
    }
  }
  return { indices, tiles, leftGuard };
}

function buildShape(out, shape, colorsPath, colors) {
  const { createGeometry } = require(join(__dirname, `${shape}.js`));
  const sample = createGeometry({ width: width * 2, height });
  const settings = { along: columns, across: rows, shape };
  // Keep the tape period and lookup stride while projecting fewer depth cells.
  const visibleColumns = shape === "tunnel" ? tunnelDepthColumns : columns;
  for (const [phase, halfRight] of [["phase-a", false], ["phase-b", true]]) {
    buildScrollPhase(join(out, phase), settings, "none", colors, halfRight, undefined, rows,
      samplePhase(sample, halfRight, visibleColumns));
  }
  execFileSync(process.execPath, [join(engine, "generate-four-line-scroll.cjs"),
    out, colorsPath, "--step", "0.5", "--fields-per-step", String(shapes[shape].fields)], { stdio: "inherit" });

  const work = mkdtempSync(join(tmpdir(), "wavy-geometry-"));
  try {
    const source = join(work, "four-line-scroll-player.asm");
    copyFileSync(join(engine, "four-line-scroll-player.asm"), source);
    copyFileSync(join(out, "four-line-scroll-generated.asm"), join(work, "four-line-scroll-generated.asm"));
    execFileSync(process.env.KICKASS || "kickass", [source,
      `:bitmapA=${join(out, "phase-a/bitmap.bin")}`,
      `:bitmapB=${join(out, "phase-b/bitmap.bin")}`,
      `:rowColors=${join(out, "row-colors-lz.bin")}`,
      "-odir", out, "-o", join(out, "wave-four-line-scroll.prg")], { stdio: "inherit" });
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

function buildPreview(out, colors) {
  const palette = readFileSync(join(__dirname, "../../palettes/colodore.vpl"), "utf8")
    .split(/\r?\n/).map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => line.split(/\s+/).slice(0, 3).map((hex) => parseInt(hex, 16)));
  const data = {
    width, height, columns, rows, palette,
    pattern: RIBBON_INDEX_PATTERN,
    colors: colors.toString("base64"),
    shapes: Object.entries(shapes).map(([id, settings]) => ({
      id, ...settings,
      phases: ["phase-a", "phase-b"].map((phase) =>
        files.map((file) => readFileSync(join(out, id, phase, file)).toString("base64"))),
    })),
  };
  const html = readFileSync(join(__dirname, "preview.html"), "utf8")
    .replace("/* DATA */", () => JSON.stringify(data))
    .replace("/* PLAYER */", () => readFileSync(join(__dirname, "preview.js"), "utf8"));
  writeFileSync(join(out, "index.html"), html);
}

function main() {
  const [destination, shape, ...rest] = process.argv.slice(2);
  if (!destination || rest.length || (shape && !Object.hasOwn(shapes, shape))) {
    throw new Error("Usage: node build.cjs <output-directory> [spiral|disc|tunnel]");
  }
  const out = resolve(destination);
  const colorsPath = join(engine, "demo/y-sine-colors.bin");
  const colors = prepareRows(colorsPath, rows, columns);
  mkdirSync(out, { recursive: true });
  for (const id of shape ? [shape] : Object.keys(shapes)) {
    console.log(shapes[id].title);
    buildShape(join(out, id), id, colorsPath, colors);
  }
  if (!shape) buildPreview(out, colors);
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
