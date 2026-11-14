const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync('output/playwright/palette-components-initial.yml', await page.locator('body').ariaSnapshot());
    await page.locator('#image-input').setInputFiles('output/playwright/talent-contrast-source.png');
    await page.waitForFunction(() => layerStack.active().image && layerStack.active().cache);
    await page.locator('#c64-palette-options').selectOption('peptoette-a');
    await page.locator('#virtual-color-mode-options').selectOption('talent');
    await page.locator('#virtual-colors').selectOption('checkers');
    await page.locator('#tab-palette').click();
    const standard = page.locator('.standard-palette-column');
    assert.deepEqual(await standard.locator('[data-native-color]').evaluateAll(buttons => buttons.map(button => Number(button.dataset.nativeColor))), Array.from({ length: 16 }, (_, index) => index));
    const mixture = page.locator('.virtual-palette-mixes [data-virtual-color="ifli-1-10"]').first();
    await mixture.scrollIntoViewIfNeeded();
    const chips = await mixture.evaluate(button => {
      const face = button.querySelector('.virtual-palette-color').getBoundingClientRect();
      const strip = button.querySelector('.virtual-palette-components').getBoundingClientRect();
      return { below: strip.top >= face.bottom - 1, colors: Array.from(button.querySelectorAll('.virtual-palette-component'), chip => ({ index: Number(chip.dataset.colorIndex), rgb: getComputedStyle(chip).backgroundColor })) };
    });
    assert.equal(chips.below, true);
    assert.deepEqual(chips.colors, [{ index: 1, rgb: 'rgb(255, 255, 255)' }, { index: 10, rgb: 'rgb(167, 111, 111)' }]);
    const countBrown = () => page.evaluate(() => {
      const mapping = layerStack.active().cache.mapping;
      const brown = IFLI_VIRTUAL_PALETTE.find(color => color.colorIndices.join('-') === '9-9').index;
      const brownMix = IFLI_VIRTUAL_PALETTE.find(color => color.colorIndices.join('-') === '0-9').index;
      const canvas = document.getElementById('canvas');
      const displayed = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      const rgb = C64_PALETTE[9].rgb;
      let canvasSolid = 0;
      for (let offset = 0; offset < displayed.length; offset += 4) {
        if (displayed[offset + 3] && rgb.every((channel, index) => displayed[offset + index] === channel)) canvasSolid += 1;
      }
      return { solid: Array.from(mapping.virtualIndices).filter(index => index === brown).length,
        mixture: Array.from(mapping.virtualIndices).filter(index => index === brownMix).length, canvasSolid };
    });
    const before = await countBrown();
    assert.ok(before.solid > 0);
    await standard.locator('[data-native-color="9"]').click();
    const after = await countBrown();
    assert.equal(after.solid, 0);
    assert.equal(after.canvasSolid, 0);
    assert.ok(after.mixture > 0);
    assert.ok((await page.locator('[data-virtual-color="ifli-9-9"]').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-pressed')))).every(value => value === 'false'));
    const layout = await page.evaluate(() => {
      const column = document.querySelector('.standard-palette-column');
      const mixes = document.querySelector('.virtual-palette-mixes');
      const before = column.getBoundingClientRect().left;
      mixes.scrollLeft = mixes.scrollWidth;
      return { fixed: Math.abs(column.getBoundingClientRect().left - before) < 1, scrolled: mixes.scrollLeft > 0 };
    });
    assert.deepEqual(layout, { fixed: true, scrolled: true });
    await page.evaluate(() => { document.querySelector('.virtual-palette-mixes').scrollLeft = 0; });
    await page.locator('#virtual-palette').screenshot({ path: 'output/playwright/palette-components-talent.png' });
    for (let index = 0; index < 16; index += 1) {
      const button = standard.locator(`[data-native-color="${index}"]`);
      if (await button.getAttribute('aria-pressed') === 'true') await button.click();
    }
    assert.equal(await page.locator('#palette-mapping-error').isVisible(), true);
    assert.match(await page.locator('#palette-mapping-error').innerText(), /enabled solid color/);
    assert.equal(await page.locator('#canvas').isVisible(), false);
    await standard.locator('[data-native-color="9"]').click();
    assert.equal(await page.locator('#palette-mapping-error').isVisible(), false);
    assert.equal(await page.locator('#canvas').isVisible(), true);
    for (let index = 0; index < 16; index += 1) {
      const button = standard.locator(`[data-native-color="${index}"]`);
      if (await button.getAttribute('aria-pressed') === 'false') await button.click();
    }
    await page.locator('#c64-palette-options').selectOption('pepto');
    const peptoChips = await page.locator('.virtual-palette-mixes [data-virtual-color="ifli-1-10"]').first().locator('.virtual-palette-component').evaluateAll(elements => elements.map(element => getComputedStyle(element).backgroundColor));
    assert.deepEqual(peptoChips, ['rgb(255, 255, 255)', 'rgb(154, 103, 89)']);
    await page.locator('#virtual-color-mode-options').selectOption('computed');
    assert.equal(await page.locator('.standard-palette-column [data-native-color]').count(), 16);
    assert.equal(await page.locator('.virtual-palette-row').count(), 17);
    assert.equal(await page.locator('.virtual-palette-mixes [data-virtual-color="ifli-0-6"] .virtual-palette-component').count(), 2);
    await page.locator('#virtual-palette').screenshot({ path: 'output/playwright/palette-components-computed.png' });
    assert.deepEqual(pageErrors, []);
    const report = { standardColors: 16, chips, before, after, scrolling: layout, noSolidErrorAndRecovery: true, peptoChips, computedRows: 17, pageErrors };
    fs.writeFileSync('output/playwright/palette-components-proof.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
