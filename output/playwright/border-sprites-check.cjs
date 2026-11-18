const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

const root = '/Users/rogerjohansson/git/asynkron/c64';
const output = path.join(root, 'output/playwright');
const report = { errors: [], checks: [], screenshots: [] };
const artifact = name => path.join(output, `border-sprites-${name}`);

function readStoredZip(buffer) {
  const entries = {};
  let offset = 0;
  while (buffer.readUInt32LE(offset) === 0x04034b50) {
    assert.equal(buffer.readUInt16LE(offset + 8), 0, 'ZIP uses stored data');
    const size = buffer.readUInt32LE(offset + 18);
    const nameLength = buffer.readUInt16LE(offset + 26);
    const extraLength = buffer.readUInt16LE(offset + 28);
    const name = buffer.subarray(offset + 30, offset + 30 + nameLength).toString();
    const data = offset + 30 + nameLength + extraLength;
    entries[name] = buffer.subarray(data, data + size);
    offset = data + size;
  }
  return entries;
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  page.on('pageerror', error => report.errors.push({ type: 'pageerror', message: error.message }));
  page.on('console', message => {
    if (message.type() === 'error') report.errors.push({ type: 'console', message: message.text() });
  });
  const check = (name, data) => { report.checks.push({ name, ...data }); };
  const state = () => page.evaluate(() => ({
    config: borderSpriteControls.getState(),
    layout: currentBorderLayout(),
    canvas: { width: canvas.width, height: canvas.height },
    mode: graphicsMode, preview: activeMode, backgroundColorIndex,
    fieldsetDisabled: document.getElementById('border-sprite-controls').disabled,
    multicolorVisible: !document.getElementById('border-multicolor-settings').hidden,
    sourcePosition: [Number(sourcePositionX.value), Number(sourcePositionY.value)],
    activeLayer: layerStack.layers.indexOf(layerStack.active()),
    layerCount: layerStack.layers.length
  }));
  const layout = async (width, height) => {
    const current = await state();
    assert.deepEqual([current.layout.width, current.layout.height], [width, height]);
    assert.deepEqual([current.canvas.width, current.canvas.height], [width, height]);
    return current;
  };
  const swatch = async (prefix, index) => page.locator(`#${prefix}-palette label:has(input[value="${index}"])`).click();
  const download = async (selector, name) => {
    const ready = page.waitForEvent('download');
    await page.locator(selector).click();
    const file = await ready;
    const destination = artifact(name);
    await file.saveAs(destination);
    return { destination, name: file.suggestedFilename(), bytes: fs.statSync(destination).size };
  };
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    const initial = await state();
    assert.equal(initial.config.vertical.enabled, false);
    assert.equal(initial.config.sides.enabled, false);
    assert.equal(await page.locator('#border-vertical-mode').isDisabled(), true);
    assert.equal(await page.locator('#border-sides-mode').isDisabled(), true);
    assert.equal(initial.multicolorVisible, false);
    check('default off', initial);

    await page.locator('#graphics-mode-options').selectOption('mci');
    await page.locator('#image-input').setInputFiles(path.join(root, 'giana/assets/mci-phase-0.png'));
    await page.waitForFunction(() => layerStack.active().image && !loadingLayers.size && !projectLoading);
    await page.locator('#source-scale').evaluate(input => {
      input.value = '118'; input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await page.locator('#border-vertical-enabled').check();
    check('vertical only', await layout(320, 272));
    await page.locator('#border-vertical-enabled').uncheck();
    await page.locator('#border-sides-enabled').check();
    check('sides only', await layout(368, 200));
    await page.locator('#border-vertical-enabled').check();
    check('all borders', await layout(368, 272));

    await swatch('border-vertical-color', 7);
    await swatch('border-sides-color', 5);
    await page.locator('#border-vertical-mode').selectOption('multicolor');
    assert.equal((await state()).multicolorVisible, true);
    await swatch('border-multi-1', 2);
    await swatch('border-multi-2', 14);
    await swatch('background', 9);
    const configured = await state();
    assert.deepEqual(configured.config, { vertical: { enabled: true, mode: 'multicolor', colorIndex: 7 },
      sides: { enabled: true, mode: 'hires', colorIndex: 5 }, multicolorIndices: [2, 14] });
    assert.equal(configured.backgroundColorIndex, 9);
    await page.locator('#border-vertical-mode').selectOption('hires');
    assert.equal((await state()).multicolorVisible, false);
    await page.locator('#border-sides-mode').selectOption('multicolor');
    assert.equal((await state()).multicolorVisible, true);
    await page.locator('#border-vertical-mode').selectOption('multicolor');
    await page.locator('#border-sides-mode').selectOption('hires');
    check('independent modes and global colors', await state());

    await page.locator('#tab-palette').click();
    check('palette preview includes borders', await layout(368, 272));
    await page.locator('#tab-restricted').click();
    await page.waitForFunction(() => ifliResult && canvas.width === 368 && canvas.height === 272);
    const pixels = await page.evaluate(() => {
      const converted = ensureBorderSpriteResult();
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
      const { coreX, coreY, coreWidth, coreHeight } = currentBorderLayout();
      const zones = { top: [0, 0, pixels.width, coreY], bottom: [0, coreY + coreHeight, pixels.width, pixels.height],
        left: [0, coreY, coreX, coreY + coreHeight], right: [coreX + coreWidth, coreY, pixels.width, coreY + coreHeight] };
      const counts = {};
      for (const [name, box] of Object.entries(zones)) {
        const indices = name === 'left' || name === 'right' ? [backgroundColorIndex, 5] : [backgroundColorIndex, 2, 7, 14];
        const allowed = indices.map(index => C64_PALETTE[index].rgb.join(','));
        let foreground = 0, invalid = 0;
        const background = C64_PALETTE[backgroundColorIndex].rgb.join(',');
        for (let y = box[1]; y < box[3]; y++) for (let x = box[0]; x < box[2]; x++) {
          const offset = (y * pixels.width + x) * 4;
          const rgb = Array.from(pixels.data.slice(offset, offset + 3)).join(',');
          if (!allowed.includes(rgb)) invalid++;
          if (rgb !== background) foreground++;
        }
        counts[name] = { foreground, invalid };
      }
      return { counts, sprites: converted.sprites.length, core: [coreX, coreY, coreWidth, coreHeight] };
    });
    for (const counts of Object.values(pixels.counts)) {
      assert.ok(counts.foreground > 0, 'Each border contains actual image content');
      assert.equal(counts.invalid, 0, 'Border pixels use configured sprite colors');
    }
    assert.equal(pixels.sprites, 26);
    const alternating = await page.evaluate(async () => {
      const frames = [];
      for (let index = 0; index < 18; index++) {
        await new Promise(resolve => requestAnimationFrame(resolve));
        frames.push({ phase: canvas.dataset.ifliFrame, width: canvas.width, height: canvas.height });
      }
      return frames;
    });
    assert.deepEqual([...new Set(alternating.map(frame => frame.phase))].sort(), ['0', '1']);
    assert.ok(alternating.every(frame => frame.width === 368 && frame.height === 272));
    check('restricted pixels and alternating padded frames', { ...pixels, alternating });

    report.spriteDownload = await download('#save-border-sprites', 'export.zip');
    const entries = readStoredZip(fs.readFileSync(report.spriteDownload.destination));
    const manifest = JSON.parse(entries['manifest.json']);
    assert.equal(entries['sprites.bin'].length, 26 * 64);
    assert.deepEqual(manifest.settings, configured.config);
    assert.equal(manifest.hardware.backgroundColorRegister, 9);
    assert.equal(manifest.image.width, 368);
    assert.equal(manifest.image.height, 272);
    assert.equal(manifest.sprites.length, 26);
    report.spriteDownload.manifest = manifest;
    report.mciDownload = await download('#mci-save', 'core.mci');
    assert.equal(report.mciDownload.bytes, 19434);

    await page.locator('#tab-unrestricted').click();
    const beforePan = await state();
    const bounds = await page.locator('#canvas').boundingBox();
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await page.mouse.down();
    await page.mouse.move(bounds.x + bounds.width / 2 + 24, bounds.y + bounds.height / 2 + 12, { steps: 3 });
    await page.mouse.up();
    const afterPan = await state();
    assert.notDeepEqual(afterPan.sourcePosition, beforePan.sourcePosition);
    await layout(368, 272);
    check('source panning retains border geometry', { before: beforePan.sourcePosition, after: afterPan.sourcePosition });
    await page.locator('#source-crop').click();
    assert.equal(await page.locator('#source-crop-dialog').isVisible(), true);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal(await page.locator('#source-crop-dialog').isVisible(), false);
    const beforeLayer = await state();
    await page.locator('[data-layer-action="add"]').click();
    assert.deepEqual((await state()).config, beforeLayer.config);
    await page.locator('.layer-select').first().click();
    assert.deepEqual((await state()).config, beforeLayer.config);
    check('settings stay global across layer selection', { layers: (await state()).layerCount, config: (await state()).config });

    const retained = (await state()).config;
    for (const mode of ['sprites', 'sprites-hires', 'fli-sprites', 'afli-sprites', 'nufli', 'pafli']) {
      await page.locator('#graphics-mode-options').selectOption(mode);
      const unsupported = await state();
      assert.equal(unsupported.fieldsetDisabled, true, mode);
      assert.deepEqual(unsupported.config, retained, mode);
      assert.equal(unsupported.layout.enabled, false, mode);
      check('unsupported mode retains settings', { mode, config: unsupported.config });
    }
    await page.locator('#graphics-mode-options').selectOption('mci');
    assert.deepEqual((await state()).config, retained);
    assert.equal((await state()).fieldsetDisabled, false);

    report.projectDownload = await download('#project-save', 'project.json');
    const saved = JSON.parse(fs.readFileSync(report.projectDownload.destination, 'utf8'));
    assert.deepEqual(saved.image.borderSprites, retained);
    assert.equal(saved.image.backgroundColorIndex, 9);
    await page.locator('#border-vertical-enabled').uncheck();
    await page.locator('#border-sides-enabled').uncheck();
    await page.locator('#project-input').setInputFiles(report.projectDownload.destination);
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().vertical.enabled);
    assert.deepEqual((await state()).config, retained);
    check('saved project reopens global settings', await state());
    delete saved.image.borderSprites;
    const legacy = artifact('legacy-project.json');
    fs.writeFileSync(legacy, JSON.stringify(saved));
    await page.locator('#project-input').setInputFiles(legacy);
    await page.waitForFunction(() => !projectLoading && !borderSpriteControls.getState().vertical.enabled);
    const legacyState = await state();
    assert.equal(legacyState.config.sides.enabled, false);
    assert.deepEqual([legacyState.layout.width, legacyState.layout.height], [320, 200]);
    check('legacy project resets border settings', legacyState);
    await page.locator('#project-input').setInputFiles(report.projectDownload.destination);
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().vertical.enabled);
    await page.locator('#tab-restricted').click();
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    await page.locator('#grid-toggle').uncheck();

    const measure = () => page.evaluate(() => {
      const sidebar = document.querySelector('.config-sidebar').getBoundingClientRect();
      const controls = document.getElementById('border-sprite-settings').getBoundingClientRect();
      return { viewport: [innerWidth, innerHeight], documentWidth: document.documentElement.scrollWidth,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
        borderControlsFitSidebar: controls.left >= sidebar.left && controls.right <= sidebar.right + 1,
        canvas: [canvas.width, canvas.height] };
    });
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    report.desktop = await measure();
    assert.equal(report.desktop.horizontalOverflow, false);
    assert.equal(report.desktop.borderControlsFitSidebar, true);
    const desktop = artifact('desktop.png');
    await page.screenshot({ path: desktop });
    report.screenshots.push(desktop);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => scrollTo(0, 0));
    report.mobile = await measure();
    assert.equal(report.mobile.horizontalOverflow, false);
    assert.equal(report.mobile.borderControlsFitSidebar, true);
    const mobile = artifact('mobile.png');
    await page.screenshot({ path: mobile });
    report.screenshots.push(mobile);
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    const mobileControls = artifact('mobile-controls.png');
    await page.screenshot({ path: mobileControls });
    report.screenshots.push(mobileControls);
    fs.writeFileSync(artifact('final-snapshot.yml'), await page.locator('body').ariaSnapshot());
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.failure = { message: error.message, stack: error.stack };
  } finally {
    fs.writeFileSync(artifact('proof.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify({ passed: report.passed, checks: report.checks.length, failure: report.failure,
    errors: report.errors, screenshots: report.screenshots, proof: artifact('proof.json') }, null, 2));
  if (!report.passed) process.exitCode = 1;
})();
