const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync('output/playwright/talent-pairs-initial.yml', await page.locator('body').ariaSnapshot());
    await page.locator('#image-input').setInputFiles('output/playwright/talent-contrast-source.png');
    await page.waitForFunction(() => layerStack.active().image && layerStack.active().cache);
    await page.locator('#c64-palette-options').selectOption('peptoette-a');
    await page.locator('#virtual-color-mode-options').selectOption('talent');
    await page.locator('#virtual-colors').selectOption('checkers');
    await page.locator('#tab-palette').click();
    await page.locator('#grid-toggle').uncheck();
    const proof = await page.evaluate(() => {
      const { source, mapping } = layerStack.active().cache;
      const byIndex = new Map(IFLI_VIRTUAL_PALETTE.map(color => [color.index, color]));
      const resolved = resolveVirtualPaletteColors(mapping, IFLI_VIRTUAL_PALETTE, C64_PALETTE, 'checkers');
      const errors = { pairedChoice: 0, detailIsNative: 0, resolvedDetail: 0, transparent: 0, canvas: 0 };
      const counts = { surfacePairs: 0, detailPairs: 0, surfaceMixtures: 0, detailPixels: 0 };
      const displayed = document.getElementById('canvas').getContext('2d').getImageData(0, 0, source.width, source.height);
      for (let y = 0; y < source.height; y += 2) {
        for (let x = 0; x < source.width; x += 1) {
          const upper = y * source.width + x, lower = upper + source.width;
          const a = source.data[upper * 4 + 3], b = y + 1 < source.height ? source.data[lower * 4 + 3] : 0;
          const first = rgbToOklab(...source.data.slice(upper * 4, upper * 4 + 3));
          const second = y + 1 < source.height ? rgbToOklab(...source.data.slice(lower * 4, lower * 4 + 3)) : null;
          const similar = a > 0 && a === b && second && Math.hypot(first.lightness - second.lightness, first.a - second.a, first.b - second.b) <= 0.03;
          if (similar) {
            counts.surfacePairs += 1;
            if (mapping.virtualIndices[upper] !== mapping.virtualIndices[lower]) errors.pairedChoice += 1;
            for (let channel = 0; channel < 3; channel += 1) {
              if (mapping.pixels.data[upper * 4 + channel] !== mapping.pixels.data[lower * 4 + channel]) errors.pairedChoice += 1;
            }
            const color = byIndex.get(mapping.virtualIndices[upper]);
            if (color.colorIndices[0] !== color.colorIndices[1]) counts.surfaceMixtures += 1;
          } else {
            if (a || b) counts.detailPairs += 1;
            for (const pixel of y + 1 < source.height ? [upper, lower] : [upper]) {
              const offset = pixel * 4;
              if (!source.data[offset + 3]) {
                if (mapping.virtualIndices[pixel] !== 255) errors.transparent += 1;
                for (let channel = 0; channel < 4; channel += 1) if (mapping.pixels.data[offset + channel] !== source.data[offset + channel]) errors.transparent += 1;
                continue;
              }
              counts.detailPixels += 1;
              const color = byIndex.get(mapping.virtualIndices[pixel]);
              if (color.colorIndices[0] !== color.colorIndices[1]) errors.detailIsNative += 1;
              const native = C64_PALETTE[color.colorIndices[0]].rgb;
              for (let channel = 0; channel < 3; channel += 1) if (resolved.data[offset + channel] !== native[channel]) errors.resolvedDetail += 1;
            }
          }
        }
      }
      for (let offset = 0; offset < source.data.length; offset += 4) {
        if (source.data[offset + 3] !== 255) continue;
        for (let channel = 0; channel < 4; channel += 1) if (displayed.data[offset + channel] !== mapping.pixels.data[offset + channel]) errors.canvas += 1;
      }
      return { image: imageName, preview: activeMode, base: paletteState.id, counts, errors };
    });
    assert.ok(proof.counts.surfacePairs > 0 && proof.counts.surfaceMixtures > 0 && proof.counts.detailPairs > 0);
    assert.deepEqual(Object.values(proof.errors), [0, 0, 0, 0, 0]);
    await page.locator('#canvas').screenshot({ path: 'output/playwright/talent-vertical-pairs.png' });
    assert.deepEqual(pageErrors, []);
    fs.writeFileSync('output/playwright/talent-pair-proof.json', JSON.stringify({ ...proof, pageErrors }, null, 2));
    console.log(JSON.stringify({ ...proof, pageErrors }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
