const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

function verifyDownload(bytes, expected) {
  assert.equal(bytes.length, 17666);
  assert.deepEqual([...bytes.subarray(0, 2)], [0, 0x3b]);
  assert.ok(bytes.subarray(2, 258).every(color => color === expected.background));
  let pixels = 0;
  for (let y = 0; y < 200; y++) {
    for (let x = 0; x < 160; x++) {
      const cell = Math.floor(y / 8) * 40 + Math.floor(x / 4);
      const screen = bytes[1282 + (y % 8) * 1024 + cell];
      const code = bytes[9474 + cell * 8 + y % 8] >> (6 - 2 * (x % 4)) & 3;
      const index = [bytes[2 + y], screen >> 4, screen & 15, bytes[258 + cell]][code];
      const offset = (y * 160 + x) * 4;
      assert.deepEqual(expected.pixels.slice(offset, offset + 4), [...expected.palette[index], 255], `pixel ${x},${y}`);
      pixels++;
    }
  }
  return pixels;
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    const save = page.getByRole('button', { name: 'Save FLI', exact: true });
    assert.equal(await save.isVisible(), true);
    assert.equal(await save.isDisabled(), true);
    for (const mode of ['ifli', 'afli', 'fli-sprites', 'bitmap']) {
      await page.locator('#graphics-mode-options').selectOption(mode);
      assert.equal(await save.isVisible(), false, mode);
    }
    await page.locator('#graphics-mode-options').selectOption('fli');
    await page.locator('#image-input').setInputFiles('output/playwright/talent-contrast-source.png');
    await page.waitForFunction(() => !document.getElementById('fli-save').disabled);
    const report = { downloads: [], errors };
    const downloadImage = async label => {
      const pending = page.waitForEvent('download');
      await save.click();
      const download = await pending;
      assert.equal(await download.failure(), null);
      assert.match(download.suggestedFilename(), /^[A-Za-z0-9_-]{1,12}\.fli$/);
      const destination = `output/playwright/fli-export-${label}.fli`;
      await download.saveAs(destination);
      const expected = await page.evaluate(() => ({
        background: fliResult.backgroundColorIndex,
        pixels: [...fliResult.pixels.data],
        palette: C64_PALETTE.map(color => color.rgb)
      }));
      const bytes = fs.readFileSync(destination);
      report.downloads.push({ label, filename: download.suggestedFilename(), bytes: bytes.length,
        background: expected.background, verifiedPixels: verifyDownload(bytes, expected) });
      return bytes;
    };
    const sourceBytes = await downloadImage('source-tab');
    for (const tab of ['palette', 'restricted']) {
      await page.locator(`#tab-${tab}`).click();
      assert.deepEqual(await downloadImage(`${tab}-tab`), sourceBytes);
    }
    const canvasMatches = await page.evaluate(() => {
      const canvas = document.getElementById('canvas');
      const pixels = canvas.getContext('2d').getImageData(0, 0, 160, 200).data;
      return pixels.every((value, index) => value === fliResult.pixels.data[index]);
    });
    assert.equal(canvasMatches, true);
    await page.getByRole('radio', { name: 'Yellow', exact: true }).locator('..').click();
    await page.locator('#c64-palette-options').selectOption('peptoette-a');
    const colored = await downloadImage('yellow-peptoette');
    assert.equal(colored[2], 7);
    assert.notDeepEqual(colored, sourceBytes);
    await page.locator('#grid-toggle').uncheck();
    await page.screenshot({ path: 'output/playwright/fli-save-preview.png' });
    assert.deepEqual(errors, []);
    report.canvasMatches = canvasMatches;
    fs.writeFileSync('output/playwright/fli-export-proof.json', JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
