const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

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
      const excluded = new Set(layer.settings.palette.excludedIndices);
      const canvas = document.getElementById('canvas');
      const displayed = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      // Canvas stores partial-alpha pixels premultiplied; compare the same public transport,
      // rather than raw RGB that cannot all survive the browser's rounding at alpha edges.
      const referenceCanvas = document.createElement('canvas');
      referenceCanvas.width = source.width;
      referenceCanvas.height = source.height;
      const referenceContext = referenceCanvas.getContext('2d');
      referenceContext.putImageData(mapping.pixels, 0, 0);
      const reference = referenceContext.getImageData(0, 0, source.width, source.height).data;
      const kinds = Array(source.width * source.height).fill('transparent');
      const pairs = { smooth: 0, different: 0, alphaBoundary: 0, transparent: 0 };
      const output = { smooth: { solid: 0, mixture: 0 }, different: { solid: 0, mixture: 0 }, alphaBoundary: { solid: 0, mixture: 0 } };
      let pairedChoiceErrors = 0, canvasErrors = 0, alphaErrors = 0, excludedUsed = 0, individualDifferences = 0;
      for (let y = 0; y < source.height; y += 2) {
        for (let x = 0; x < source.width; x++) {
          const upper = y * source.width + x;
          const lower = upper + source.width;
          const firstAlpha = source.data[upper * 4 + 3];
          const secondAlpha = y + 1 < source.height ? source.data[lower * 4 + 3] : 0;
          let category;
          if (!firstAlpha && !secondAlpha) category = 'transparent';
          else if (!firstAlpha || firstAlpha !== secondAlpha || y + 1 >= source.height) category = 'alphaBoundary';
          else {
            const first = rgbToOklab(...source.data.slice(upper * 4, upper * 4 + 3));
            const second = rgbToOklab(...source.data.slice(lower * 4, lower * 4 + 3));
            const distance = (first.lightness - second.lightness) ** 2 + (first.a - second.a) ** 2 + (first.b - second.b) ** 2;
            category = distance > 0.03 ** 2 ? 'different' : 'smooth';
          }
          pairs[category]++;
          if (category === 'smooth' && mapping.virtualIndices[upper] !== mapping.virtualIndices[lower]) pairedChoiceErrors++;
          if (category === 'different' && mapping.virtualIndices[upper] !== mapping.virtualIndices[lower]) individualDifferences++;
          for (const pixel of [upper, lower]) {
            if (pixel >= kinds.length) continue;
            const offset = pixel * 4;
            const alpha = source.data[offset + 3];
            if (mapping.pixels.data[offset + 3] !== alpha) alphaErrors++;
            if ([0, 1, 2, 3].some(channel => displayed[offset + channel] !== reference[offset + channel])) canvasErrors++;
            if (!alpha) continue;
            kinds[pixel] = category;
            const color = colors.get(mapping.virtualIndices[pixel]);
            if (!color) throw Error(`Unknown mapped color at pixel ${pixel}`);
            if (excluded.has(color.index)) excludedUsed++;
            output[category][color.colorIndices[0] === color.colorIndices[1] ? 'solid' : 'mixture']++;
          }
        }
      }
      return { pairs, output, pairedChoiceErrors, individualDifferences, canvasErrors, alphaErrors, excludedUsed,
        canvasVisible: !canvas.hidden, mapping: [...mapping.virtualIndices], source: [...source.data], kinds,
        palette: IFLI_VIRTUAL_PALETTE.map(color => ({ index: color.index, pair: color.colorIndices })) };
    });

    const assertFrame = frame => {
      assert.equal(frame.pairedChoiceErrors, 0);
      assert.ok(frame.individualDifferences > 0, 'different source pixels retain independent choices');
      assert.equal(frame.canvasErrors, 0, 'actual C64 Palette canvas matches the mapped colors');
      assert.equal(frame.alphaErrors, 0);
      assert.equal(frame.excludedUsed, 0);
      assert.equal(frame.canvasVisible, true);
      assert.ok(frame.output.different.mixture > 0, 'differing source pairs can select Talent mixtures');
    };
    const summary = ({ mapping, source, kinds, palette, ...rest }) => rest;
    const initial = await capture();
    assertFrame(initial);
    await page.locator('#canvas').screenshot({ path: 'output/playwright/talent-full-palette-initial.png' });
    const colors = new Map(initial.palette.map(color => [color.index, color]));
    const replacements = [];
    for (const native of [12, 15]) {
      const index = initial.palette.find(color => color.pair.every(component => component === native)).index;
      const button = page.locator(`.standard-palette-column [data-native-color="${native}"]`);
      assert.equal(await button.getAttribute('aria-pressed'), 'true');
      await button.click();
      const changed = await capture();
      assertFrame(changed);
      assert.deepEqual(changed.source, initial.source);
      assert.deepEqual(changed.pairs, initial.pairs);
      const transition = { native, smooth: { mixture: 0, solid: 0 }, different: { mixture: 0, solid: 0 }, pairs: {} };
      for (let pixel = 0; pixel < initial.mapping.length; pixel++) {
        if (initial.mapping[pixel] !== index) continue;
        assert.notEqual(changed.mapping[pixel], index);
        const color = colors.get(changed.mapping[pixel]);
        const category = initial.kinds[pixel];
        transition[category][color.pair[0] === color.pair[1] ? 'solid' : 'mixture']++;
        transition.pairs[color.pair.join('+')] = (transition.pairs[color.pair.join('+')] ?? 0) + 1;
      }
      assert.ok(transition.different.mixture > 0, `disabled solid ${native} has mixed replacements for individually mapped pixels`);
      replacements.push(transition);
      await page.locator('#canvas').screenshot({ path: `output/playwright/talent-full-palette-without-${native}.png` });
      await button.click();
      assert.deepEqual((await capture()).mapping, initial.mapping);
    }

    for (let native = 0; native < 16; native++) {
      const button = page.locator(`.standard-palette-column [data-native-color="${native}"]`);
      if (await button.getAttribute('aria-pressed') === 'true') await button.click();
    }
    const mixedOnly = await capture();
    assertFrame(mixedOnly);
    assert.equal(Object.values(mixedOnly.output).reduce((sum, group) => sum + group.solid, 0), 0);
    assert.equal(Object.values(mixedOnly.output).reduce((sum, group) => sum + group.mixture, 0), 26800);
    assert.deepEqual(mixedOnly.source, initial.source);
    assert.equal(await page.locator('#error').isVisible(), false);
    await page.locator('#canvas').screenshot({ path: 'output/playwright/talent-full-palette-mixed-only.png' });
    assert.deepEqual(errors, []);
    const old = JSON.parse(fs.readFileSync('output/playwright/talent-queen-pair-probe.json', 'utf8'));
    const report = { beforeRestrictionRemoved: old.before.output, fullPalette: summary(initial), replacements,
      allSolidsDisabled: summary(mixedOnly), originalSourceSha256: crypto.createHash('sha256').update(Buffer.from(initial.source)).digest('hex'), errors };
    fs.writeFileSync('output/playwright/talent-full-palette-proof.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
