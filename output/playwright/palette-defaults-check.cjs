const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const report = { errors: [] };
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
    page.on('pageerror', error => report.errors.push(error.message));
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    const state = () => page.evaluate(() => ({
      palette: paletteState.id,
      mode: paletteState.virtualColorMode,
      selectedPalette: document.getElementById('c64-palette-options').value,
      selectedMode: document.getElementById('virtual-color-mode-options').value,
      pattern: document.getElementById('virtual-colors').value,
      settings: structuredClone(layerStack.active().settings),
      enabled: IFLI_VIRTUAL_PALETTE.filter(color => !layerStack.active().settings.palette.excludedIndices.includes(color.index))
        .map(color => color.colorIndices)
    }));
    const checkDefaults = frame => {
      assert.equal(frame.palette, 'peptoette-a');
      assert.equal(frame.mode, 'talent');
      assert.equal(frame.selectedPalette, 'peptoette-a');
      assert.equal(frame.selectedMode, 'talent');
      assert.equal(frame.pattern, 'checkers');
      assert.equal(frame.settings.values['virtual-colors'], 'checkers');
      assert.deepEqual(frame.enabled.filter(pair => pair[0] === pair[1]), [[0, 0], [1, 1]]);
      assert.equal(frame.enabled.filter(pair => pair[0] !== pair[1]).length, 76);
      assert.equal(frame.settings.palette.excludedIndices.length, 14);
      assert.equal(frame.settings.palette.minLightness, 0);
      assert.equal(frame.settings.palette.maxLightness, 100);
    };
    report.startup = await state();
    checkDefaults(report.startup);
    await page.locator('#image-input').setInputFiles({ name: 'defaults.svg', mimeType: 'image/svg+xml',
      buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="#684e7b"/></svg>') });
    await page.waitForFunction(() => layerStack.active().image && layerStack.active().cache && document.getElementById('preview').getAttribute('aria-busy') === 'false');
    await page.locator('[data-inspector-panel="color-settings"]').click();
    const pressed = await page.locator('.standard-palette-column [data-native-color]').evaluateAll(buttons =>
      buttons.filter(button => button.getAttribute('aria-pressed') === 'true').map(button => Number(button.dataset.nativeColor)));
    assert.deepEqual(pressed, [0, 1]);
    await page.locator('#virtual-colors').selectOption('lines');
    await page.locator('.standard-palette-column [data-native-color="9"]').click();
    await page.locator('[data-layer-action="add"]').click();
    report.newLayer = await state();
    checkDefaults(report.newLayer);
    await page.locator('[data-inspector-panel="source-settings"]').click();
    await page.locator('#virtual-color-mode-options').selectOption('computed');
    await page.locator('#c64-palette-options').selectOption('pepto');
    await page.locator('[data-inspector-panel="color-settings"]').click();
    await page.locator('#virtual-colors').selectOption('lines');
    const existing = await state();
    const downloadReady = page.waitForEvent('download');
    await page.locator('#project-save').click();
    const download = await downloadReady;
    const savedPath = 'output/playwright/palette-defaults-existing-project.json';
    await download.saveAs(savedPath);
    const saved = JSON.parse(fs.readFileSync(savedPath, 'utf8'));
    await page.reload({ waitUntil: 'networkidle' });
    checkDefaults(await state());
    await page.locator('#project-input').setInputFiles(savedPath);
    await page.waitForFunction(() => !projectLoading && paletteState.id === 'pepto');
    report.existingProject = await state();
    assert.equal(report.existingProject.mode, 'computed');
    assert.equal(report.existingProject.pattern, 'lines');
    assert.deepEqual(report.existingProject.settings, existing.settings);
    delete saved.image.paletteId;
    delete saved.image.virtualColorMode;
    for (const layer of saved.layers) {
      layer.settings.values['virtual-colors'] = 'lines';
      layer.settings.palette = { minLevel: 0, maxLevel: 16, excludedIndices: [] };
    }
    const legacyPath = 'output/playwright/palette-defaults-legacy-project.json';
    fs.writeFileSync(legacyPath, JSON.stringify(saved));
    await page.locator('#project-input').setInputFiles(legacyPath);
    await page.waitForFunction(() => !projectLoading && paletteState.id === 'colodore');
    report.legacyProject = await state();
    assert.equal(report.legacyProject.mode, 'computed');
    assert.equal(report.legacyProject.pattern, 'lines');
    assert.deepEqual(report.legacyProject.settings.palette.excludedIndices, []);
    assert.equal(await page.locator('#project-error').isVisible(), false);
    assert.deepEqual(report.errors, []);
    report.passed = true;
    fs.writeFileSync('output/playwright/palette-defaults-proof.json', JSON.stringify(report, null, 2));
    console.log('PASS: fresh startup, 76 enabled mixtures, black/white solids only, new-layer defaults, saved project, legacy project; no browser errors.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
