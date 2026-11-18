const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const root = '/Users/rogerjohansson/git/asynkron/c64';
const artifact = name => path.join(root, 'output/playwright', `pattern-toggle-${name}`);
const project = path.join(root, 'batman/assets/batman.json');
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const changes = (first, second) => {
  assert.equal(first.length, second.length);
  let result = 0;
  for (let offset = 0; offset < first.length; offset += 4) {
    if ([0, 1, 2, 3].some(channel => first[offset + channel] !== second[offset + channel])) result++;
  }
  return result;
};
function decode(file, format, palette) {
  const pixels = new Uint8ClampedArray(160 * 200 * 4);
  assert.equal(file.length, format === 'fli' ? 17666 : 10003);
  for (let y = 0; y < 200; y++) for (let x = 0; x < 160; x++) {
    const cell = Math.floor(y / 8) * 40 + Math.floor(x / 4);
    const bitmap = file[(format === 'fli' ? 0x2502 : 2) + cell * 8 + y % 8];
    const code = bitmap >> (6 - 2 * (x % 4)) & 3;
    const screen = file[format === 'fli' ? 0x502 + (y % 8) * 1024 + cell : 8002 + cell];
    const indices = [file[format === 'fli' ? 2 : 10002], screen >> 4, screen & 15,
      file[(format === 'fli' ? 0x102 : 9002) + cell]];
    pixels.set([...palette[indices[code]], 255], (y * 160 + x) * 4);
  }
  return pixels;
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const report = { errors: [], baseline: [], fixed: [], dither: [] };
  const originalHash = hash(fs.readFileSync(project));
  async function open(baseline) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
    page.setDefaultTimeout(45000);
    page.on('pageerror', error => report.errors.push(error.message));
    if (baseline) {
      const body = fs.readFileSync(path.join(root, 'output/playwright/dither-bitmap-probe-baseline.html'));
      await page.route('http://127.0.0.1:8768/', route => route.fulfill({ contentType: 'text/html', body }));
    }
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    await page.locator('#project-input').setInputFiles(project);
    await page.waitForFunction(() => !projectLoading && palettePixels);
    await page.locator('#tab-palette').click();
    await page.locator('#grid-toggle').uncheck();
    return page;
  }
  async function snapshot(page) {
    return page.evaluate(() => {
      const fitted = fliResult.fli ?? fliResult;
      return { target: Array.from(getRestrictedTarget().data), native: Array.from(fitted.pixels.data),
        palette: Array.from(palettePixels.data), width: fitted.pixels.width,
        colors: C64_PALETTE.map(color => color.rgb), pattern: layerStack.active().settings.values['virtual-colors'] };
    });
  }
  async function save(page, selector, name) {
    const pending = page.waitForEvent('download');
    await page.locator(selector).click();
    const download = await pending;
    await download.saveAs(artifact(name));
    return fs.readFileSync(artifact(name));
  }
  try {
    for (const baseline of [true, false]) {
      const page = await open(baseline);
      try {
        for (const mode of ['fli', 'bitmap', 'fli-sprites']) {
          const borderCases = mode === 'fli-sprites' ? [false] : [false, true];
          for (const borders of borderCases) {
            await page.locator('#tab-palette').click();
            await page.locator('#graphics-mode-options').selectOption(mode);
            if (mode !== 'fli-sprites') {
              await page.locator('#border-vertical-enabled').setChecked(borders);
              await page.locator('#border-sides-enabled').setChecked(borders);
            }
            const outputs = [], files = [];
            for (const pattern of ['lines', 'checkers']) {
              await page.locator('#virtual-colors').selectOption(pattern);
              await page.locator('#tab-restricted').click();
              outputs.push(await snapshot(page));
              if (!baseline && mode !== 'fli-sprites') {
                const format = mode === 'fli' ? 'fli' : 'koa';
                const file = await save(page, mode === 'fli' ? '#fli-save' : '#multicolor-save',
                  `${mode}-${borders ? 'borders' : 'core'}-${pattern}.${format}`);
                files.push(file);
                assert.equal(changes(decode(file, mode === 'fli' ? 'fli' : 'koala', outputs.at(-1).colors),
                  outputs.at(-1).native), 0, 'actual download independently decodes to the fitted core');
              }
            }
            const entry = { mode, borders, targetChanges: changes(outputs[0].target, outputs[1].target),
              bitmapChanges: changes(outputs[0].native, outputs[1].native),
              paletteChanges: changes(outputs[0].palette, outputs[1].palette) };
            assert.equal(entry.paletteChanges, 0, 'retained virtual RGB choices stay independent of component pattern');
            if (baseline) assert.equal(entry.targetChanges, 0, 'pre-fix bitmap aliases checkers to lines');
            else {
              assert.ok(entry.targetChanges > 0, `${mode}: bitmap target reacts to pattern change`);
              assert.ok(entry.bitmapChanges > 0, `${mode}: actual bitmap reacts to pattern change`);
              if (files.length) {
                assert.notEqual(hash(files[0]), hash(files[1]), 'real exports reflect the selected pattern');
                entry.exportHashes = files.map(hash);
                entry.decodedPixelDifferences = 0;
              }
            }
            report[baseline ? 'baseline' : 'fixed'].push(entry);
            console.log(`${baseline ? 'baseline' : 'fixed'} ${mode} borders=${borders}: ${entry.bitmapChanges} changed bitmap pixels`);
            if (!baseline && mode === 'bitmap' && !borders) {
              await page.screenshot({ path: artifact('bitmap-checkers.png') });
              await page.locator('#virtual-colors').selectOption('lines');
              await page.screenshot({ path: artifact('bitmap-lines.png') });
            }
          }
        }
        if (!baseline) {
          for (const mode of ['fli', 'bitmap', 'fli-sprites']) {
            await page.locator('#tab-palette').click();
            await page.locator('#graphics-mode-options').selectOption(mode);
            await page.locator('#virtual-colors').selectOption('checkers');
            await page.locator('#tab-restricted').click();
            const outputs = [], files = [];
            for (const value of [0, 100]) {
              await page.locator('#dither').fill(String(value));
              await page.locator('#dither').dispatchEvent('input');
              outputs.push(await snapshot(page));
              if (mode !== 'fli-sprites') files.push(await save(page, mode === 'fli' ? '#fli-save' : '#multicolor-save',
                `${mode}-dither-${value}.${mode === 'fli' ? 'fli' : 'koa'}`));
            }
            const entry = { mode, targetChanges: changes(outputs[0].target, outputs[1].target),
              bitmapChanges: changes(outputs[0].native, outputs[1].native) };
            assert.ok(entry.bitmapChanges > 0, `${mode}: Dither modifies the actual bitmap`);
            if (files.length) {
              assert.notEqual(hash(files[0]), hash(files[1]));
              files.forEach((file, index) => assert.equal(changes(decode(file, mode === 'fli' ? 'fli' : 'koala',
                outputs[index].colors), outputs[index].native), 0));
              entry.decodedPixelDifferences = 0;
            }
            report.dither.push(entry);
          }
        }
      } finally { await page.close(); }
    }
    assert.equal(hash(fs.readFileSync(project)), originalHash);
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.failure = { message: error.message, stack: error.stack };
  } finally {
    fs.writeFileSync(artifact('proof.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
})();
