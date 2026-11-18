const fs = require('node:fs');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const requestedNative = Number(process.argv[2] ?? 15);
const suffix = requestedNative === 15 ? '' : `-${requestedNative}`;

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1100 }, deviceScaleFactor: 2 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    await page.locator('#project-input').setInputFiles('output/playwright/talent-queen-live-project.json');
    await page.waitForFunction(() => !projectLoading && layerStack.active().cache?.mapping);
    await page.locator('#tab-palette').click();
    const capture = () => page.evaluate(() => {
      const layer = layerStack.active();
      const source = layer.cache.source;
      const mapping = layer.cache.mapping;
      const colors = new Map(IFLI_VIRTUAL_PALETTE.map(color => [color.index, color]));
      const kind = Array(source.width * source.height).fill('transparent');
      const pairs = { smooth: 0, different: 0, alphaBoundary: 0, transparent: 0 };
      const output = { smooth: { solid: 0, mixture: 0 }, different: { solid: 0, mixture: 0 }, alphaBoundary: { solid: 0, mixture: 0 } };
      const solids = {};
      for (let y = 0; y < source.height; y += 2) {
        for (let x = 0; x < source.width; x++) {
          const upper = y * source.width + x;
          const lower = upper + source.width;
          const a = source.data[upper * 4 + 3];
          const b = y + 1 < source.height ? source.data[lower * 4 + 3] : 0;
          let category;
          if (!a && !b) category = 'transparent';
          else if (!a || a !== b || y + 1 >= source.height) category = 'alphaBoundary';
          else {
            const first = rgbToOklab(...source.data.slice(upper * 4, upper * 4 + 3));
            const second = rgbToOklab(...source.data.slice(lower * 4, lower * 4 + 3));
            const distance = (first.lightness - second.lightness) ** 2 + (first.a - second.a) ** 2 + (first.b - second.b) ** 2;
            category = distance > 0.03 ** 2 ? 'different' : 'smooth';
          }
          pairs[category]++;
          for (const pixel of [upper, lower]) {
            if (pixel >= kind.length || !source.data[pixel * 4 + 3]) continue;
            kind[pixel] = category;
            const color = colors.get(mapping.virtualIndices[pixel]);
            if (!color) throw Error(`Unknown mapped color at ${pixel}`);
            const solid = color.colorIndices[0] === color.colorIndices[1];
            output[category][solid ? 'solid' : 'mixture']++;
            if (solid) {
              const native = color.colorIndices[0];
              solids[native] ??= { virtualIndex: color.index, name: color.name, smooth: 0, different: 0, alphaBoundary: 0 };
              solids[native][category]++;
            }
          }
        }
      }
      return { width: source.width, height: source.height, pairs, output, solids,
        source: [...source.data], mapping: [...mapping.virtualIndices], kind,
        palette: IFLI_VIRTUAL_PALETTE.map(color => ({ index: color.index, pair: color.colorIndices, name: color.name })) };
    });
    const before = await capture();
    await page.locator('#canvas').screenshot({ path: `output/playwright/talent-queen-palette-before${suffix}.png` });
    const chosenNative = before.solids[requestedNative] ? requestedNative : before.solids[12] ? 12 : Number(Object.keys(before.solids).sort((a, b) =>
      Object.values(before.solids[b]).filter(Number.isInteger).reduce((s,n) => s+n,0) - Object.values(before.solids[a]).filter(Number.isInteger).reduce((s,n) => s+n,0))[0]);
    const chosen = before.solids[chosenNative];
    await page.locator(`.standard-palette-column [data-native-color="${chosenNative}"]`).click();
    const after = await capture();
    assert.deepEqual(before.source, after.source);
    assert.deepEqual(before.pairs, after.pairs);
    assert.deepEqual(before.kind, after.kind);
    await page.locator('#canvas').screenshot({ path: `output/playwright/talent-queen-palette-after${suffix}.png` });
    const palette = new Map(before.palette.map(color => [color.index, color]));
    const transitions = { smooth: {}, different: {}, alphaBoundary: {} };
    const changed = { smooth: 0, different: 0, alphaBoundary: 0 };
    for (let pixel = 0; pixel < before.mapping.length; pixel++) {
      if (before.mapping[pixel] !== chosen.virtualIndex) continue;
      const category = before.kind[pixel];
      const target = palette.get(after.mapping[pixel]);
      transitions[category][target.pair.join('+')] = (transitions[category][target.pair.join('+')] ?? 0) + 1;
      if (before.mapping[pixel] !== after.mapping[pixel]) changed[category]++;
    }
    const overlay = await page.evaluate(({ width, height, kind, mapping, palette }) => {
      const colors = new Map(palette.map(color => [color.index, color]));
      const overlay = document.createElement('canvas');
      overlay.width = width * 4; overlay.height = height * 4;
      const context = overlay.getContext('2d');
      for (let pixel = 0; pixel < kind.length; pixel++) {
        const color = colors.get(mapping[pixel]);
        context.fillStyle = kind[pixel] === 'transparent' ? '#171717'
          : kind[pixel] !== 'smooth' ? '#e94c43'
          : color.pair[0] === color.pair[1] ? '#efc33c' : '#42c181';
        context.fillRect(pixel % width * 4, Math.floor(pixel / width) * 4, 4, 4);
      }
      return overlay.toDataURL();
    }, before);
    fs.writeFileSync(`output/playwright/talent-queen-classification${suffix}.png`, Buffer.from(overlay.split(',')[1], 'base64'));
    const summarize = ({source,kind,mapping,palette,...result}) => result;
    const report = { before: summarize(before), disabled: { nativeIndex: chosenNative, ...chosen }, after: summarize(after),
      changed, replacementPairs: transitions, sourceUnchanged: true, pairClassificationUnchanged: true,
      sourceSha256: crypto.createHash('sha256').update(Buffer.from(before.source)).digest('hex'),
      legend: { red: 'native fallback because source vertical pair differs or alpha differs', yellow: 'smooth source pair selected a solid through Talent mapper', green: 'smooth source pair selected a mixture', dark: 'transparent' }, errors };
    fs.writeFileSync(`output/playwright/talent-queen-pair-probe${suffix}.json`, JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
