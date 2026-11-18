const fs = require('node:fs');
const vm = require('node:vm');
const { createContext, ImageData } = require('../../tests/fixtures/sprite-images.cjs');
const runtime = createContext(['ifli.js', 'talent-palette.js', 'talent-neighbors.js', 'talent-mapping.js', 'palettes.js', 'source-interlace.js']);
const html = fs.readFileSync('index.html', 'utf8');
const noise = html.slice(html.indexOf('    function applyRgbNoise('), html.indexOf('    function mapToC64Palette('));
vm.runInContext(noise, runtime);
const palette = runtime.createC64PaletteState('peptoette-a', 'talent');
const byIndex = new Map(palette.virtualPalette.map(color => [color.index, color]));
const source = new ImageData(160, 200);
for (let pixel = 0; pixel < 32000; pixel++) source.data.set([248, 152, 106, 255], pixel * 4);

function measure(image) {
  let similar = 0, detail = 0;
  let minimum = Infinity, maximum = 0;
  for (let y = 0; y < image.height; y += 2) {
    for (let x = 0; x < image.width; x++) {
      const upper = (y * image.width + x) * 4;
      const lower = upper + image.width * 4;
      const first = runtime.rgbToOklab(...image.data.slice(upper, upper + 3));
      const second = runtime.rgbToOklab(...image.data.slice(lower, lower + 3));
      const distance = Math.hypot(first.lightness - second.lightness, first.a - second.a, first.b - second.b);
      if (distance <= 0.03) similar++; else detail++;
      minimum = Math.min(minimum, distance); maximum = Math.max(maximum, distance);
    }
  }
  const mapped = runtime.mapToTalentVirtualPalette(image, palette.virtualPalette, { minLightness: 0, maxLightness: 100 }, 1);
  let solidPixels = 0, mixedPixels = 0;
  const choices = new Map();
  for (const index of mapped.virtualIndices) {
    const color = byIndex.get(index);
    if (color.colorIndices[0] === color.colorIndices[1]) solidPixels++; else mixedPixels++;
    const name = color.colorIndices.join('+');
    choices.set(name, (choices.get(name) ?? 0) + 1);
  }
  return { similarPairs: similar, detailPairs: detail, minimumDistance: minimum, maximumDistance: maximum,
    solidPixels, mixedPixels, choices: Object.fromEntries(choices) };
}
const report = [{ effects: 'none', ...measure(source) }];
for (const amount of [-0.05, -0.1, -0.2, 0.05, 0.1, 0.2, 0.5]) {
  report.push({ effects: 'interlace', amount, ...measure(runtime.applyInterlace(source, amount)) });
}
for (const amount of [0.01, 0.05, 0.1, 0.2, 0.5]) {
  report.push({ effects: 'rgb-noise', amount, ...measure(runtime.applyRgbNoise(source, amount)) });
}
fs.writeFileSync('output/playwright/talent-detail-probe.json', JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
