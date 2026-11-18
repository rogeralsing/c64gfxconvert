const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const root = '/Users/rogerjohansson/git/asynkron/c64';
const artifact = name => path.join(root, 'output/playwright', `border-color-optimization-${name}`);
const asset = name => path.join(root, 'batman/assets', name);
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const report = { errors: [], downloads: {}, fields: [], workersStarted: 0 };

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
  page.setDefaultTimeout(180000);
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  page.on('worker', () => report.workersStarted++);
  const originals = Object.fromEntries(['batman.json', 'batman.mci', 'batman-sprites.zip'].map(name =>
    [name, hash(fs.readFileSync(asset(name)))]));
  async function download(selector, destination) {
    const pending = page.waitForEvent('download');
    await page.locator(selector).click();
    const downloaded = await pending;
    if (destination.startsWith(asset('')) && fs.existsSync(destination)) {
      const checked = artifact(`rechecked-${path.basename(destination)}`);
      await downloaded.saveAs(checked);
      assert.ok(fs.readFileSync(checked).equals(fs.readFileSync(destination)), 'optimized assets stay deterministic');
    } else await downloaded.saveAs(destination);
  }
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    await page.locator('#project-input').setInputFiles(asset('batman.json'));
    await page.waitForFunction(() => !projectLoading && ifliResult && canvas.width === 368 && canvas.height === 272);
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    await page.locator('#grid-toggle').uncheck();
    await download('#save-border-sprites', artifact('manual.zip'));
    assert.ok(fs.readFileSync(artifact('manual.zip')).equals(fs.readFileSync(asset('batman-sprites.zip'))),
      'manual export stays byte-identical');
    await page.locator('#tab-unrestricted').click();
    const rawPreview = await page.evaluate(() => canvas.toDataURL());
    await page.locator('#border-optimize-colors').check();
    await page.waitForFunction(() => borderColorWorker !== null || borderColorError !== null);
    assert.equal(await page.evaluate(() => borderColorError), null);
    assert.equal(await page.locator('#save-border-sprites').isDisabled(), true);
    report.animationFramesDuringSearch = await page.evaluate(async () => {
      const began = performance.now(); let frames = 0;
      await new Promise(resolve => {
        function frame() { frames++; if (performance.now() - began < 500) requestAnimationFrame(frame); else resolve(); }
        requestAnimationFrame(frame);
      });
      return frames;
    });
    assert.ok(report.animationFramesDuringSearch > 5, 'editor remains responsive during the worker search');
    await page.locator('#grid-toggle').check();
    await page.locator('#grid-toggle').uncheck();
    const canceledGeneration = await page.evaluate(() => borderColorGeneration);
    await page.locator('#border-optimize-colors').uncheck();
    const canceled = await page.evaluate(() => ({ generation: borderColorGeneration, pending: borderColorPending,
      worker: borderColorWorker !== null, plan: borderColorPlan }));
    assert.ok(canceled.generation > canceledGeneration);
    assert.equal(canceled.pending, false); assert.equal(canceled.worker, false); assert.equal(canceled.plan, null);
    assert.equal(await page.locator('#save-border-sprites').isDisabled(), false);
    await download('#save-border-sprites', artifact('manual-after-cancel.zip'));
    assert.ok(fs.readFileSync(artifact('manual-after-cancel.zip')).equals(fs.readFileSync(asset('batman-sprites.zip'))));
    await page.locator('#border-optimize-colors').check();
    const began = Date.now();
    await page.waitForFunction(() => borderColorPlan !== null || borderColorError !== null);
    assert.equal(await page.evaluate(() => borderColorError), null);
    report.searchSeconds = (Date.now() - began) / 1000;
    report.plan = await page.evaluate(() => borderColorPlan);
    assert.ok(report.plan.optimizedError <= report.plan.baselineError);
    assert.ok(report.plan.improvementPercent > 15);
    assert.equal(report.plan.colorIndices.length, 52);
    assert.equal(report.plan.phaseCount, 2);
    assert.equal(await page.evaluate(() => activeMode), 'unrestricted');
    assert.equal(await page.evaluate(() => canvas.toDataURL()), rawPreview,
      'automatic search leaves the Unrestricted source preview unchanged');
    assert.equal(await page.locator('#save-border-sprites').isDisabled(), false);
    report.unrestrictedSearchPassed = true;
    await page.locator('#tab-restricted').click();
    await download('#save-border-sprites', asset('batman-optimized-sprites.zip'));
    await download('#project-save', asset('batman-optimized.json'));
    await download('#mci-save', artifact('core.mci'));
    assert.ok(fs.readFileSync(artifact('core.mci')).equals(fs.readFileSync(asset('batman.mci'))), 'core bitmap stays unchanged');
    const saved = JSON.parse(fs.readFileSync(asset('batman-optimized.json')));
    assert.equal(saved.image.borderSprites.optimizeColors, true);
    assert.deepEqual(saved.image.borderSprites.multicolorIndices, [6, 1], 'manual choices stay saved for mode switching');
    const archive = unzip(fs.readFileSync(asset('batman-optimized-sprites.zip')));
    const bitmap = fs.readFileSync(artifact('core.mci'));
    const manifest = JSON.parse(archive['manifest.json']);
    assert.equal(manifest.settings.optimizeColors, true);
    assert.deepEqual(manifest.hardware.sharedMulticolorRegisters, report.plan.multicolorIndices);
    assert.equal(manifest.sprites.length, 104);
    assert.ok(new Set(manifest.sprites.map(sprite => sprite.colorIndex)).size > 1);
    for (let i = 0; i < 52; i++) {
      assert.equal(manifest.sprites[i].colorIndex, report.plan.colorIndices[i]);
      assert.equal(manifest.sprites[i + 52].colorIndex, report.plan.colorIndices[i]);
    }
    for (const phase of [0, 1]) {
      const image = await page.evaluate(phase => {
        ifliFrameIndex = phase; renderPreview();
        return { pixels: Array.from(context.getImageData(0, 0, canvas.width, canvas.height).data),
          palette: C64_PALETTE.map(color => color.rgb),
          png: canvas.toDataURL('image/png').split(',')[1] };
      }, phase);
      const expected = new Uint8ClampedArray(368 * 272 * 4);
      for (let offset = 0; offset < expected.length; offset += 4) expected.set([...image.palette[0], 255], offset);
      for (let y = 0; y < 200; y++) for (let x = 0; x < 160; x++) {
        const cell = Math.floor(y / 8) * 40 + Math.floor(x / 4);
        const bits = bitmap[(phase ? 9218 : 1026) + cell * 8 + y % 8];
        const code = bits >> (6 - 2 * (x % 4)) & 3;
        const screen = bitmap[(phase ? 17410 : 2) + cell];
        const color = [bitmap[1002], screen >> 4, screen & 15, bitmap[18434 + cell]][code];
        for (const half of [0, 1]) {
          const targetX = 24 + x * 2 + phase + half;
          if (targetX < 368) expected.set([...image.palette[color], 255], ((y + 35) * 368 + targetX) * 4);
        }
      }
      for (const sprite of manifest.sprites.filter(sprite => sprite.field === phase)) {
        const colors = [0, ...[manifest.hardware.sharedMulticolorRegisters[0], sprite.colorIndex,
          manifest.hardware.sharedMulticolorRegisters[1]]];
        for (let y = 0; y < 21; y++) for (let x = 0; x < sprite.displayWidth; x++) {
          const px = sprite.x + x, py = sprite.y + y;
          if (px < 0 || px >= 368 || py < 0 || py >= 272 || px < sprite.clip.x || px >= sprite.clip.x + sprite.clip.width ||
              py < sprite.clip.y || py >= sprite.clip.y + sprite.clip.height) continue;
          const bit = Math.floor(x / (sprite.xExpanded ? 2 : 1));
          const value = archive['sprites.bin'][sprite.byteOffset + y * 3 + Math.floor(bit / 8)];
          const code = value >> (6 - 2 * Math.floor(bit % 8 / 2)) & 3;
          if (code) expected.set([...image.palette[colors[code]], 255], (py * 368 + px) * 4);
        }
      }
      let differences = 0;
      for (let offset = 0; offset < expected.length; offset += 4) {
        if ([0, 1, 2, 3].some(channel => expected[offset + channel] !== image.pixels[offset + channel])) differences++;
      }
      assert.equal(differences, 0, `field${phase} canvas matches independent MCI and sprite decoding`);
      fs.writeFileSync(artifact(`phase-${phase}.png`), Buffer.from(image.png, 'base64'));
      report.fields.push({ phase, pixelDifferences: differences });
    }
    await page.evaluate(() => { ifliFrameIndex = 0; renderPreview(); });
    await page.screenshot({ path: artifact('desktop.png') });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.locator('#project-input').setInputFiles(asset('batman-optimized.json'));
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().optimizeColors === true);
    assert.equal(await page.locator('#border-optimize-colors').isChecked(), true);
    await page.locator('#border-optimize-colors').uncheck();
    assert.equal(await page.evaluate(() => borderColorWorker === null && !borderColorPending), true);
    for (const [name, value] of Object.entries(originals)) assert.equal(hash(fs.readFileSync(asset(name))), value);
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.passed = false; report.failure = { message: error.message, stack: error.stack };
  } finally {
    fs.writeFileSync(artifact('proof.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
})();
