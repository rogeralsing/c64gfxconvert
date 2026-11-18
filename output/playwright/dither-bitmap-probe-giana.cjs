const fs = require('node:fs');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const project = '/Users/rogerjohansson/Downloads/Kontrastrik serietidningsposter med GIANA SISTERS-project (1).json';
const html = fs.readFileSync('output/playwright/dither-bitmap-probe-baseline.html', 'utf8');
const hash = bytes => crypto.createHash('sha256').update(Buffer.from(bytes)).digest('hex');
function diff(first, second) {
  let pixels = 0, even = 0, odd = 0;
  for (let offset = 0; offset < first.data.length; offset += 4) {
    if (first.data.slice(offset, offset + 4).some((v, i) => v !== second.data[offset + i])) {
      pixels++;
      Math.floor(offset / 4) % first.width % 2 ? odd++ : even++;
    }
  }
  return { pixels, even, odd };
}
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const report = { project, errors: [], snapshots: {}, comparisons: {} };
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(60000);
    page.on('pageerror', error => report.errors.push(error.message));
    await page.route('http://127.0.0.1:8768/', route => route.fulfill({ contentType: 'text/html', body: html }));
    await page.goto('http://127.0.0.1:8768/');
    await page.locator('#project-input').setInputFiles(project);
    await page.waitForFunction(() => !projectLoading && palettePixels);
    await page.locator('#tab-restricted').click();
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    const snapshots = {};
    for (const [name, pattern, dither] of [['checkers-0', 'checkers', 0], ['lines-0', 'lines', 0],
      ['checkers-100', 'checkers', 100], ['lines-100', 'lines', 100]]) {
      await page.locator('#virtual-colors').selectOption(pattern);
      await page.locator('#dither').evaluate((element, value) => {
        element.value = String(value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
      }, dither);
      const snapshot = await page.evaluate(() => {
        const image = pixels => ({ width: pixels.width, height: pixels.height, data: Array.from(pixels.data) });
        const selected = renderImageLayer(layerStack.active());
        const layout = currentBorderLayout();
        const views = ifliFrameCanvases.map(target => image(target.getContext('2d').getImageData(0, 0, target.width, target.height)));
        const canvasPhases = [0, 1].map(phase => {
          ifliFrameIndex = phase; renderPreview();
          return image(context.getImageData(layout.coreX, layout.coreY, 320, 200));
        });
        return {
          mode: graphicsMode, backgroundColorIndex, activeMode, selectedLayer: layerStack.active().name,
          values: structuredClone(layerStack.active().settings.values),
          palette: image(selected.palette), target: image(selected.target), fullTarget: image(selected.fullTarget),
          frames: ifliResult.frames.map(frame => image(frame.pixels)), views, canvasPhases,
          export: Array.from(encodeTruePaintMci(ifliResult, C64_PALETTE)),
          viewsCurrent: ifliFrameViewsResult === ifliResult,
          planPending: borderColorPending
        };
      });
      snapshots[name] = snapshot;
      report.snapshots[name] = { mode: snapshot.mode, backgroundColorIndex: snapshot.backgroundColorIndex,
        activeMode: snapshot.activeMode, selectedLayer: snapshot.selectedLayer,
        values: snapshot.values, viewsCurrent: snapshot.viewsCurrent, planPending: snapshot.planPending,
        exportSha256: hash(snapshot.export) };
      fs.writeFileSync(`output/playwright/dither-bitmap-probe-giana-${name}.mci`, Buffer.from(snapshot.export));
      console.log('captured', name);
    }
    for (const [name, firstKey, secondKey] of [
      ['pattern-0', 'lines-0', 'checkers-0'], ['pattern-100', 'lines-100', 'checkers-100'],
      ['dither-checkers', 'checkers-0', 'checkers-100'], ['dither-lines', 'lines-0', 'lines-100']
    ]) {
      const first = snapshots[firstKey], second = snapshots[secondKey];
      report.comparisons[name] = {
        palette: diff(first.palette, second.palette), target: diff(first.target, second.target),
        fullTarget: diff(first.fullTarget, second.fullTarget),
        frames: first.frames.map((frame, index) => diff(frame, second.frames[index])),
        views: first.views.map((frame, index) => diff(frame, second.views[index])),
        canvasPhases: first.canvasPhases.map((frame, index) => diff(frame, second.canvasPhases[index])),
        exportBytes: first.export.filter((value, index) => value !== second.export[index]).length
      };
      console.log(name, JSON.stringify(report.comparisons[name]));
    }
    report.passed = report.errors.length === 0;
  } catch (error) {
    report.failure = { message: error.message, stack: error.stack };
    process.exitCode = 1;
  } finally {
    fs.writeFileSync('output/playwright/dither-bitmap-probe-giana-proof.json', JSON.stringify(report, null, 2));
    await browser.close();
  }
})();
