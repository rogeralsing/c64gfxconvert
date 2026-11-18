const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const root = '/Users/rogerjohansson/git/asynkron/c64';
const source = process.env.C64_BORDER_PROJECT || '/Users/rogerjohansson/Downloads/Kontrastrik serietidningsposter med GIANA SISTERS-project (1).json';
const prefix = process.env.C64_BORDER_PROOF_NAME || 'normal-border-placement';
const artifact = name => path.join(root, 'output/playwright', `${prefix}-${name}`);
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const report = { errors: [], fields: [] };

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
  page.setDefaultTimeout(240000);
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  const original = hash(fs.readFileSync(source));
  async function download(selector, name) {
    const pending = page.waitForEvent('download');
    await page.locator(selector).click();
    const value = await pending;
    await value.saveAs(artifact(name));
    return fs.readFileSync(artifact(name));
  }
  async function waitPlan() {
    await page.waitForFunction(() => borderColorPlan !== null || borderColorError !== null);
    assert.equal(await page.evaluate(() => borderColorError), null);
    const plan = await page.evaluate(() => borderColorPlan);
    assert.equal(plan.verticalPositions.length, 32);
    assert.ok(Number.isFinite(plan.baselineError) && Number.isFinite(plan.optimizedError));
    assert.ok(plan.optimizedError <= plan.baselineError + 1e-8);
    for (let band = 0; band < 4; band++) for (let slot = 0; slot < 8; slot++) {
      const x = plan.verticalPositions[band * 8 + slot];
      assert.ok(Number.isInteger(x) && x >= 0 && x <= 344);
      if (slot) assert.ok(x >= plan.verticalPositions[band * 8 + slot - 1] + 24);
    }
    assert.equal(await page.locator('#save-border-sprites').isDisabled(), false);
    return plan;
  }
  async function decodeFields(zipBytes, mci, label) {
    const entries = unzip(zipBytes), manifest = JSON.parse(entries['manifest.json']);
    assert.equal(manifest.settings.vertical.xExpanded, false);
    assert.equal(manifest.sprites.length, 104);
    for (const phase of [0, 1]) {
      const image = await page.evaluate(phase => {
        ifliFrameIndex = phase;
        renderPreview();
        return { pixels: Array.from(context.getImageData(0, 0, canvas.width, canvas.height).data),
          palette: C64_PALETTE.map(color => color.rgb), png: canvas.toDataURL().split(',')[1] };
      }, phase);
      const bg = manifest.hardware.backgroundColorRegister;
      const expected = new Uint8ClampedArray(368 * 272 * 4);
      for (let offset = 0; offset < expected.length; offset += 4) expected.set([...image.palette[bg], 255], offset);
      for (let y = 0; y < 200; y++) for (let x = 0; x < 160; x++) {
        const cell = Math.floor(y / 8) * 40 + Math.floor(x / 4);
        const bits = mci[(phase ? 9218 : 1026) + cell * 8 + y % 8];
        const code = bits >> (6 - 2 * (x % 4)) & 3;
        const screen = mci[(phase ? 17410 : 2) + cell];
        const color = [mci[1002], screen >> 4, screen & 15, mci[18434 + cell]][code];
        for (const half of [0, 1]) expected.set([...image.palette[color], 255],
          ((y + 35) * 368 + 24 + x * 2 + phase + half) * 4);
      }
      for (const sprite of manifest.sprites.filter(sprite => sprite.field === phase)) {
        assert.equal(sprite.xExpanded, false);
        assert.equal(sprite.displayWidth, 24);
        assert.equal(sprite.yExpanded, false);
        const colors = sprite.multicolor
          ? [bg, manifest.hardware.sharedMulticolorRegisters[0], sprite.colorIndex, manifest.hardware.sharedMulticolorRegisters[1]]
          : [bg, sprite.colorIndex];
        for (let y = 0; y < 21; y++) for (let x = 0; x < 24; x++) {
          const px = sprite.x + x, py = sprite.y + y;
          if (px < 0 || px >= 368 || py < 0 || py >= 272 || px < sprite.clip.x || px >= sprite.clip.x + sprite.clip.width ||
              py < sprite.clip.y || py >= sprite.clip.y + sprite.clip.height) continue;
          const value = entries['sprites.bin'][sprite.byteOffset + y * 3 + Math.floor(x / 8)];
          const code = sprite.multicolor ? value >> (6 - 2 * Math.floor(x % 8 / 2)) & 3 : value >> (7 - x % 8) & 1;
          if (code) expected.set([...image.palette[colors[code]], 255], (py * 368 + px) * 4);
        }
      }
      let differentPixels = 0;
      for (let offset = 0; offset < expected.length; offset += 4) {
        if ([0, 1, 2, 3].some(channel => expected[offset + channel] !== image.pixels[offset + channel])) differentPixels++;
      }
      assert.equal(differentPixels, 0, `${label}, field ${phase}: independent export decoding`);
      fs.writeFileSync(artifact(`${label}-field-${phase}.png`), Buffer.from(image.png, 'base64'));
      report.fields.push({ label, phase, differentPixels });
    }
    return manifest;
  }
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    await page.locator('#project-input').setInputFiles(source);
    await page.waitForFunction(() => !projectLoading && ifliResult);
    await page.locator('#border-optimize-colors').uncheck();
    if (process.env.C64_BORDER_BACKGROUND !== undefined) {
      await page.locator(`#background-palette input[value="${process.env.C64_BORDER_BACKGROUND}"]`).check({ force: true });
    }
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    const expanded = await download('#save-border-sprites', 'expanded.zip');
    const core = await download('#mci-save', 'core-before.mci');
    const mapped = await page.evaluate(() => Array.from(borderPalettePixels.data));
    await page.locator('#border-vertical-width').selectOption('normal');
    assert.equal(await page.locator('#save-border-sprites').isDisabled(), true);
    report.responsiveFrames = await page.evaluate(async () => {
      const start = performance.now(); let frames = 0;
      await new Promise(resolve => {
        function frame() { frames++; performance.now() - start < 500 ? requestAnimationFrame(frame) : resolve(); }
        requestAnimationFrame(frame);
      });
      return frames;
    });
    assert.ok(report.responsiveFrames > 5);
    report.manualPlan = await waitPlan();
    assert.equal(await page.locator('#border-optimize-colors').isChecked(), false);
    assert.deepEqual(await page.evaluate(() => Array.from(borderPalettePixels.data)), mapped);
    assert.ok((await download('#mci-save', 'core-normal.mci')).equals(core), 'normal placement preserves the complete MCI bitmap');
    const normal = await download('#save-border-sprites', 'manual.zip');
    await decodeFields(normal, core, 'manual');
    await download('#project-save', 'project.json');
    const saved = JSON.parse(fs.readFileSync(artifact('project.json')));
    assert.equal(saved.image.borderSprites.vertical.xExpanded, false);
    await page.screenshot({ path: artifact('desktop.png') });
    await page.locator('#border-vertical-mode').selectOption('hires');
    report.hiresPlan = await waitPlan();
    await decodeFields(await download('#save-border-sprites', 'hires.zip'), core, 'hires');
    assert.ok((await download('#mci-save', 'core-hires.mci')).equals(core));
    await page.locator('#border-vertical-mode').selectOption('multicolor');
    await waitPlan();
    await page.locator('#border-optimize-colors').check();
    await page.waitForFunction(() => borderColorWorker !== null || borderColorError !== null);
    await page.locator('#border-vertical-width').selectOption('expanded');
    await page.locator('#border-optimize-colors').uncheck();
    assert.equal(await page.evaluate(() => borderColorWorker === null && !borderColorPending && borderColorPlan === null), true);
    assert.ok((await download('#save-border-sprites', 'expanded-restored.zip')).equals(expanded), 'expanded mode is restored byte for byte');
    await page.locator('#border-vertical-width').selectOption('normal');
    await page.locator('#border-optimize-colors').check();
    report.automaticPlan = await waitPlan();
    assert.deepEqual(await page.evaluate(() => Array.from(borderPalettePixels.data)), mapped);
    assert.ok((await download('#mci-save', 'core-automatic.mci')).equals(core));
    await decodeFields(await download('#save-border-sprites', 'automatic.zip'), core, 'automatic');
    await download('#project-save', 'automatic-project.json');
    await page.screenshot({ path: artifact('automatic-desktop.png') });
    await page.locator('#project-input').setInputFiles(artifact('project.json'));
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().vertical.xExpanded === false);
    assert.equal(await page.locator('#border-vertical-width').inputValue(), 'normal');
    await waitPlan();
    assert.ok((await download('#save-border-sprites', 'manual-reloaded.zip')).equals(normal));
    assert.equal(hash(fs.readFileSync(source)), original);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.setViewportSize({ width: 520, height: 900 });
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
