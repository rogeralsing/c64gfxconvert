const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

const root = '/Users/rogerjohansson/git/asynkron/c64';
const output = path.join(root, 'output/playwright');
const artifact = name => path.join(output, `border-sprites-${name}`);
const report = { errors: [], phases: [], views: [], screenshots: [] };

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => report.errors.push({ type: 'pageerror', message: error.message }));
  page.on('console', message => {
    if (message.type() === 'error') report.errors.push({ type: 'console', message: message.text() });
  });
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('edge-initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    await page.locator('#project-input').setInputFiles(artifact('project.json'));
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().vertical.enabled);
    await page.locator('#tab-restricted').click();
    await page.waitForFunction(() => ifliResult && canvas.width === 368 && canvas.height === 272);
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();

    report.phases = await page.evaluate(() => {
      const result = ensureBorderSpriteResult();
      const { layout, opaqueMask } = result;
      const edgeX = layout.coreX + 320;
      const phases = [];
      for (const phase of [0, 1]) {
        ifliFrameIndex = phase;
        renderPreview();
        const core = ifliResult.displayFrames[phase];
        const actual = context.getImageData(0, 0, canvas.width, canvas.height);
        const expected = new Uint8ClampedArray(result.pixels.data);
        const counts = { transparentRows: 0, opaqueRows: 0, visibleSpillChanges: 0,
          differences: 0, changedOutsideCoreAndFirstRightColumn: 0 };
        for (let y = 0; y < 200; y++) {
          for (let x = 0; x < 320; x++) {
            const source = (y * core.width + Math.floor(x * core.width / 320)) * 4;
            const target = ((y + layout.coreY) * layout.width + x + layout.coreX) * 4;
            expected.set(core.data.subarray(source, source + 4), target);
          }
          const target = ((y + layout.coreY) * layout.width + edgeX) * 4;
          const source = (y * core.width + core.width - 1) * 4;
          if (opaqueMask[target / 4] === 0) {
            counts.transparentRows++;
            if (phase === 1) {
              if (Array.from(expected.subarray(target, target + 4)).join(',') !==
                  Array.from(core.data.subarray(source, source + 4)).join(',')) counts.visibleSpillChanges++;
              expected.set(core.data.subarray(source, source + 4), target);
            }
          } else counts.opaqueRows++;
        }
        for (let y = 0; y < layout.height; y++) for (let x = 0; x < layout.width; x++) {
          const offset = (y * layout.width + x) * 4;
          if ([0, 1, 2, 3].some(channel => actual.data[offset + channel] !== expected[offset + channel])) counts.differences++;
          const inCore = x >= layout.coreX && x < edgeX && y >= layout.coreY && y < layout.coreY + 200;
          const firstRightColumn = x === edgeX && y >= layout.coreY && y < layout.coreY + 200;
          if (!inCore && !firstRightColumn && [0, 1, 2, 3].some(channel =>
              actual.data[offset + channel] !== result.pixels.data[offset + channel])) counts.changedOutsideCoreAndFirstRightColumn++;
        }
        const defaultComposition = composeC64BorderPreview(core, result);
        let defaultBorderDifferences = 0;
        for (let y = 0; y < 200; y++) {
          const offset = ((y + layout.coreY) * layout.width + edgeX) * 4;
          if ([0, 1, 2, 3].some(channel => defaultComposition.data[offset + channel] !== result.pixels.data[offset + channel])) {
            defaultBorderDifferences++;
          }
        }
        phases.push({ phase, ...counts, defaultBorderDifferences,
          canvas: [canvas.width, canvas.height], maskLength: opaqueMask.length });
      }
      return phases;
    });
    for (const phase of report.phases) {
      assert.ok(phase.transparentRows > 0 && phase.opaqueRows > 0, 'Source exercises both transparent and opaque sprite edge pixels');
      assert.equal(phase.differences, 0, 'Actual rendered canvas follows independent edge composition');
      assert.equal(phase.changedOutsideCoreAndFirstRightColumn, 0, 'Only first border column may receive bitmap spill');
      assert.equal(phase.defaultBorderDifferences, 0, 'Composer defaults to no spill');
      assert.deepEqual(phase.canvas, [368, 272]);
      if (phase.phase === 1) assert.ok(phase.visibleSpillChanges > 0, 'Transparent edge reveals visibly different bitmap pixels');
    }

    for (const mode of ['unrestricted', 'palette']) {
      await page.locator(`#tab-${mode}`).click();
      const view = await page.evaluate(mode => {
        ifliFrameIndex = 1;
        renderPreview();
        const actual = context.getImageData(0, 0, canvas.width, canvas.height);
        const reference = mode === 'palette' ? borderPalettePixels : borderSourcePixels;
        const layout = currentBorderLayout();
        let differences = 0;
        for (let y = 0; y < layout.height; y++) for (let x = 0; x < layout.width; x++) {
          if (x >= layout.coreX && x < layout.coreX + 320 && y >= layout.coreY && y < layout.coreY + 200) continue;
          const offset = (y * layout.width + x) * 4;
          if ([0, 1, 2, 3].some(channel => actual.data[offset + channel] !== reference.data[offset + channel])) differences++;
        }
        return { mode, differences, canvas: [canvas.width, canvas.height] };
      }, mode);
      assert.equal(view.differences, 0, 'Source/palette views retain their real border source without MCI spill');
      assert.deepEqual(view.canvas, [368, 272]);
      report.views.push(view);
    }

    await page.locator('#tab-restricted').click();
    await page.evaluate(() => { ifliFrameIndex = 0; renderPreview(); });
    await page.locator('#grid-toggle').uncheck();
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    const desktop = artifact('desktop.png');
    await page.screenshot({ path: desktop });
    report.screenshots.push(desktop);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => scrollTo(0, 0));
    const mobile = artifact('mobile.png');
    await page.screenshot({ path: mobile });
    report.screenshots.push(mobile);
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    const mobileControls = artifact('mobile-controls.png');
    await page.screenshot({ path: mobileControls });
    report.screenshots.push(mobileControls);
    report.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(report.horizontalOverflow, false);
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.failure = { message: error.message, stack: error.stack };
  } finally {
    fs.writeFileSync(artifact('edge-proof.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
})();
