const fs = require('node:fs');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const project = '/Users/rogerjohansson/Downloads/Kontrastrik serietidningsposter med GIANA SISTERS-project (1).json';
const html = fs.readFileSync('output/playwright/dither-bitmap-probe-baseline.html', 'utf8');
const hash = values => crypto.createHash('sha256').update(Buffer.from(values)).digest('hex');
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const report = { project, errors: [], samples: {} };
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(120000);
    page.on('pageerror', error => report.errors.push(error.message));
    await page.route('http://127.0.0.1:8768/', route => route.fulfill({ contentType: 'text/html', body: html }));
    await page.goto('http://127.0.0.1:8768/');
    await page.locator('#project-input').setInputFiles(project);
    await page.waitForFunction(() => !projectLoading && ifliResult);
    async function capture(name) {
      const sample = await page.evaluate(async () => {
        const began = performance.now();
        const phases = {}, sequence = [];
        let maximumDifferences = 0, sampledFrames = 0;
        await new Promise(resolve => {
          function frame(now) {
            const phase = Number(canvas.dataset.ifliFrame), layout = currentBorderLayout();
            const actual = context.getImageData(layout.coreX, layout.coreY, 320, 200);
            const expected = ifliResult.displayFrames[phase];
            let differences = 0;
            const visible = [];
            // A shifted left-border sprite can overlay the first core column.
            for (let y = 0; y < 200; y++) for (let x = 1; x < 320; x++) {
              const offset = (y * 320 + x) * 4;
              let mismatch = false;
              for (let c = 0; c < 4; c++) {
                visible.push(actual.data[offset + c]);
                if (actual.data[offset + c] !== expected.data[offset + c]) mismatch = true;
              }
              if (mismatch) differences++;
            }
            maximumDifferences = Math.max(maximumDifferences, differences);
            if (!phases[phase]) phases[phase] = { values: visible, differences };
            sampledFrames++;
            sequence.push(phase);
            if (now - began < 1000) requestAnimationFrame(frame); else resolve();
          }
          requestAnimationFrame(frame);
        });
        return { phases, sequence, maximumDifferences, sampledFrames,
          playbackText: ifliPlayback.textContent, paused: ifliPaused, activeMode,
          hidden: document.hidden, workerPending: borderColorPending,
          planComplete: Boolean(borderColorPlan), pattern: virtualColorsSelect.value,
          dither: Number(ditherSlider.value) };
      });
      for (const phase of Object.values(sample.phases)) {
        phase.sha256 = hash(phase.values); delete phase.values;
      }
      report.samples[name] = sample;
      console.log(name, JSON.stringify(sample));
      fs.writeFileSync('output/playwright/dither-bitmap-probe-giana-playing-proof.json', JSON.stringify(report, null, 2));
    }
    await capture('initial-playing');
    await page.waitForFunction(() => borderColorPlan || borderColorError);
    await capture('initial-optimized');
    await page.locator('#virtual-colors').selectOption('lines');
    await capture('lines-pending');
    await page.waitForFunction(() => borderColorPlan || borderColorError);
    await capture('lines-optimized');
    await page.locator('#virtual-colors').selectOption('checkers');
    await page.locator('#dither').evaluate(element => {
      element.value = '100'; element.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await capture('checkers-dither100-pending');
    await page.waitForFunction(() => borderColorPlan || borderColorError);
    await capture('checkers-dither100-optimized');
    report.passed = report.errors.length === 0 && Object.values(report.samples).every(sample =>
      sample.maximumDifferences === 0 && !sample.paused && Object.keys(sample.phases).length === 2);
    console.log('passed', report.passed);
    if (!report.passed) process.exitCode = 1;
  } catch (error) {
    report.failure = { message: error.message, stack: error.stack };
    process.exitCode = 1;
  } finally {
    fs.writeFileSync('output/playwright/dither-bitmap-probe-giana-playing-proof.json', JSON.stringify(report, null, 2));
    await browser.close();
  }
})();
