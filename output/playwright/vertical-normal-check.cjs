const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

const root = '/Users/rogerjohansson/git/asynkron/c64';
const artifact = name => path.join(root, 'output/playwright', `vertical-normal-${name}`);
const report = { errors: [], cases: [] };
function unzip(bytes) {
  const entries = {};
  for (let offset = 0; bytes.readUInt32LE(offset) === 0x04034b50;) {
    assert.equal(bytes.readUInt16LE(offset + 8), 0);
    const size = bytes.readUInt32LE(offset + 18), length = bytes.readUInt16LE(offset + 26);
    const start = offset + 30 + length + bytes.readUInt16LE(offset + 28);
    entries[bytes.subarray(offset + 30, offset + 30 + length).toString()] = bytes.subarray(start, start + size);
    offset = start + size;
  }
  return entries;
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    await page.locator('#project-input').setInputFiles(artifact('project.json'));
    await page.waitForFunction(() => !projectLoading && ifliResult && canvas.width === 368 && canvas.height === 272);
    assert.equal(await page.locator('#project-error').evaluate(element => element.hidden ? null : element.textContent), null);
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    for (const mode of ['hires', 'multicolor']) {
      await page.locator('#border-vertical-mode').selectOption(mode);
      await page.waitForFunction(mode => ensureBorderSpriteResult()?.config.vertical.mode === mode, mode);
      const downloadEvent = page.waitForEvent('download');
      await page.locator('#save-border-sprites').click();
      const download = await downloadEvent;
      await download.saveAs(artifact(`${mode}.zip`));
      const zip = unzip(fs.readFileSync(artifact(`${mode}.zip`)));
      const manifest = JSON.parse(zip['manifest.json']);
      assert.equal(manifest.sprites.length, 104);
      assert.equal(zip['sprites.bin'].length, 6656);
      const vertical = manifest.sprites.filter(sprite => ['top', 'bottom'].includes(sprite.group));
      assert.equal(vertical.length, 64);
      assert.ok(vertical.every(sprite => !sprite.yExpanded && sprite.xExpanded && sprite.displayHeight === 21 &&
        sprite.rowHeights.every(height => height === 1)));
      for (const phase of [0, 1]) {
        for (const group of ['top', 'bottom']) {
          const sprites = vertical.filter(sprite => sprite.field === phase && sprite.group === group);
          assert.deepEqual([...new Set(sprites.map(sprite => sprite.band))], [0, 1]);
          assert.equal(sprites.filter(sprite => sprite.band === 0).length, 8);
          assert.equal(sprites.filter(sprite => sprite.band === 1).length, 8);
        }
        const actual = await page.evaluate(phase => {
          ifliFrameIndex = phase;
          renderPreview();
          return { rgba: Array.from(context.getImageData(0, 0, canvas.width, canvas.height).data),
            palette: C64_PALETTE.map(color => color.rgb), png: canvas.toDataURL('image/png').split(',')[1] };
        }, phase);
        const expected = new Uint8ClampedArray(368 * 272 * 4);
        for (let offset = 0; offset < expected.length; offset += 4) expected.set([...actual.palette[0], 255], offset);
        for (const sprite of manifest.sprites.filter(sprite => sprite.field === phase)) {
          const colors = sprite.multicolor ? [0, ...[manifest.settings.multicolorIndices[0], sprite.colorIndex,
            manifest.settings.multicolorIndices[1]]] : [0, sprite.colorIndex];
          for (let y = 0; y < 21; y++) for (let x = 0; x < sprite.displayWidth; x++) {
            const px = sprite.x + x, py = sprite.y + y;
            if (px < 0 || px >= 368 || py < 0 || py >= 272 || px < sprite.clip.x ||
                px >= sprite.clip.x + sprite.clip.width || py < sprite.clip.y || py >= sprite.clip.y + sprite.clip.height) continue;
            const bit = Math.floor(x / (sprite.xExpanded ? 2 : 1));
            const value = zip['sprites.bin'][sprite.byteOffset + y * 3 + Math.floor(bit / 8)];
            const code = sprite.multicolor ? value >> (6 - 2 * Math.floor(bit % 8 / 2)) & 3 : value >> (7 - bit % 8) & 1;
            expected.set([...actual.palette[colors[code]], 255], (py * 368 + px) * 4);
          }
        }
        let differences = 0, sourceDifferences = 0;
        for (let y = 0; y < 272; y++) for (let x = 0; x < 368; x++) {
          const offset = (y * 368 + x) * 4;
          if ([0, 1, 2, 3].some(channel => actual.rgba[offset + channel] !== expected[offset + channel])) differences++;
          const border = y < 35 || y >= 235 || x < 24 || x >= 344;
          const shiftedBitmapEdge = phase === 1 && x === 344 && y >= 35 && y < 235;
          if (border && x >= phase && !shiftedBitmapEdge) {
            const rgb = actual.palette[y % 2 === 0 ? 3 : 0];
            if (rgb.some((channel, index) => actual.rgba[offset + index] !== channel)) sourceDifferences++;
          }
        }
        assert.equal(differences, 0, `${mode} field${phase}: canvas matches independently decoded export`);
        assert.equal(sourceDifferences, 0, `${mode} field${phase}: every original single-raster stripe survives`);
        const rowChanges = (first, end) => {
          let count = 0;
          for (let y = first + 1; y < end; y++) {
            const current = (y * 368 + 100) * 4, previous = ((y - 1) * 368 + 100) * 4;
            if ([0, 1, 2].some(channel => actual.rgba[current + channel] !== actual.rgba[previous + channel])) count++;
          }
          return count;
        };
        const topRowChanges = rowChanges(0, 35), bottomRowChanges = rowChanges(235, 272);
        assert.equal(topRowChanges, 34);
        assert.equal(bottomRowChanges, 36);
        fs.writeFileSync(artifact(`${mode}-phase-${phase}.png`), Buffer.from(actual.png, 'base64'));
        report.cases.push({ mode, phase, nativePixelDifferences: differences, sourcePixelDifferences: sourceDifferences,
          topRowChanges, bottomRowChanges, spritesPerField: 52 });
      }
    }
    await page.screenshot({ path: artifact('desktop.png') });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
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
