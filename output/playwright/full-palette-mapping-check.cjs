const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const root = '/Users/rogerjohansson/git/asynkron/c64';
const artifact = name => path.join(root, 'output/playwright', `full-palette-mapping-${name}`);
const sha256 = data => crypto.createHash('sha256').update(data).digest('hex');
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
  page.setDefaultTimeout(180000);
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  const sourcePath = path.join(root, 'batman/assets/batman.json');
  const original = sha256(fs.readFileSync(sourcePath));
  async function download(selector, name) {
    const pending = page.waitForEvent('download');
    await page.locator(selector).click();
    const value = await pending, destination = artifact(name);
    await value.saveAs(destination);
    return fs.readFileSync(destination);
  }
  async function paletteData() {
    await page.locator('#tab-palette').click();
    return page.evaluate(() => ({ width: canvas.width, height: canvas.height,
      pixels: Array.from(context.getImageData(0, 0, canvas.width, canvas.height).data) }));
  }
  async function compareFullMapping(name) {
    const comparison = await page.evaluate(() => {
      const layout = currentBorderLayout();
      const layers = layerStack.layers.filter(layer => layer.visible && layer.image);
      const mapped = layers.map(layer => {
        const rendered = renderImageLayer(layer);
        const input = layout.enabled ? rendered.borderSource : rendered.source;
        const virtual = mapC64VirtualColors(input, {
          virtualPalette: IFLI_VIRTUAL_PALETTE, virtualColorMode: paletteState.virtualColorMode,
          palette: C64_PALETTE, brightnessBands: C64_BRIGHTNESS_BANDS,
          paletteSettings: layer.settings.palette, pattern: layer.settings.values['virtual-colors'],
          dither: layer.settings.values.dither / 100,
          originX: -layout.coreX, originY: -layout.coreY
        });
        return virtual?.mapping.pixels ?? mapToC64Palette(input, layer.settings.values.dither / 100);
      });
      const expected = compositeC64LayerPixels(mapped, layout.width, layout.height);
      const actual = context.getImageData(0, 0, canvas.width, canvas.height);
      let differentPixels = 0, differentBorderPixels = 0, fullResolutionDetails = 0;
      if (expected.width !== actual.width || expected.height !== actual.height) {
        return { dimensions: [actual.width, actual.height], expectedDimensions: [expected.width, expected.height],
          differentPixels: -1, differentBorderPixels: -1 };
      }
      for (let y = 0; y < expected.height; y++) for (let x = 0; x < expected.width; x++) {
        const offset = (y * expected.width + x) * 4;
        const border = x < layout.coreX || x >= layout.coreX + 320 || y < layout.coreY || y >= layout.coreY + 200;
        if ([0, 1, 2, 3].some(channel => expected.data[offset + channel] !== actual.data[offset + channel])) {
          differentPixels++; if (border) differentBorderPixels++;
        }
        if (border && x % 4 !== 0 && x > 0 && [0, 1, 2].some(channel =>
          expected.data[offset + channel] !== expected.data[offset - 4 + channel])) fullResolutionDetails++;
      }
      return { dimensions: [actual.width, actual.height], differentPixels, differentBorderPixels, fullResolutionDetails };
    });
    assert.equal(comparison.differentPixels, 0, `${name}: Palette preview equals independent full-resolution document mapping`);
    assert.equal(comparison.differentBorderPixels, 0, `${name}: border pixels retain global mapping`);
    assert.ok(comparison.fullResolutionDetails > 100, `${name}: fixture contains detail below expanded sprite-cell width`);
    report.cases.push({ name, ...comparison });
  }
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    await page.locator('#project-input').setInputFiles(sourcePath);
    await page.waitForFunction(() => !projectLoading && ifliResult);
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    await page.locator('#grid-toggle').uncheck();
    const before = await paletteData();
    assert.deepEqual([before.width, before.height], [368, 272]);
    await compareFullMapping('MCI full-image palette');
    await page.screenshot({ path: artifact('palette-desktop.png') });
    await page.locator('#tab-restricted').click();
    const fitComparison = await page.evaluate(() => {
      const layout = currentBorderLayout(), settings = borderSpriteControls.getState();
      const layers = layerStack.layers.filter(layer => layer.visible && layer.image);
      const mappedLayers = layers.map(layer => {
        const input = renderImageLayer(layer).borderSource;
        const mapped = mapC64VirtualColors(input, {
          virtualPalette: IFLI_VIRTUAL_PALETTE, virtualColorMode: paletteState.virtualColorMode,
          palette: C64_PALETTE, brightnessBands: C64_BRIGHTNESS_BANDS,
          paletteSettings: layer.settings.palette, pattern: layer.settings.values['virtual-colors'],
          dither: layer.settings.values.dither / 100, originX: -layout.coreX, originY: -layout.coreY
        });
        return { source: mapped?.mapping.pixels ?? mapToC64Palette(input, layer.settings.values.dither / 100),
          pattern: layer.settings.values['virtual-colors'], paletteSettings: layer.settings.palette,
          dither: layer.settings.values.dither / 100 };
      });
      const rawLayers = layers.map((layer, index) => ({ ...mappedLayers[index], source: renderImageLayer(layer).borderSource }));
      const fit = inputs => convertC64BorderSprites(
        compositeC64LayerPixels(inputs.map(layer => layer.source), layout.width, layout.height), C64_PALETTE,
        settings, backgroundColorIndex, true,
        { virtualPalette: IFLI_VIRTUAL_PALETTE, virtualColorMode: paletteState.virtualColorMode,
          brightnessBands: C64_BRIGHTNESS_BANDS, layers: inputs });
      const mapped = fit(mappedLayers), raw = fit(rawLayers), actual = ensureBorderSpriteResult();
      const bytes = result => result.frames.flatMap(frame => frame.sprites.flatMap(sprite => Array.from(sprite.data)));
      const same = (left, right) => left.length === right.length && left.every((value, index) => value === right[index]);
      return { matchesMappedInput: same(bytes(mapped), bytes(actual)), differsFromRaw: !same(bytes(mapped), bytes(raw)) };
    });
    assert.equal(fitComparison.differsFromRaw, true, 'border fixture distinguishes mapping before hardware fitting');
    assert.equal(fitComparison.matchesMappedInput, true, 'border export fits the globally mapped image');
    report.borderMappedInput = fitComparison;
    const manualBefore = await download('#save-border-sprites', 'manual-before.zip');
    await page.locator('#tab-palette').click();
    await page.locator('#border-sides-color-palette input[value="2"]').check({ force: true });
    await page.locator('#border-vertical-color-palette input[value="2"]').check({ force: true });
    await page.locator('#border-multi-1-palette input[value="7"]').check({ force: true });
    await page.locator('#border-multi-2-palette input[value="8"]').check({ force: true });
    assert.deepEqual(await paletteData(), before, 'hardware color changes must not remap the Palette tab');
    await page.locator('#border-vertical-mode').selectOption('hires');
    await page.locator('#border-sides-mode').selectOption('hires');
    assert.deepEqual(await paletteData(), before, 'hardware resolution changes must not resample the Palette tab');
    await compareFullMapping('Palette after hardware color and resolution changes');
    await page.locator('#tab-restricted').click();
    const manualAfter = await download('#save-border-sprites', 'manual-after.zip');
    assert.notEqual(sha256(manualBefore), sha256(manualAfter), 'actual sprite exports reflect hardware changes');
    report.hardwareIndependentPalette = true;

    await page.locator('#border-vertical-mode').selectOption('multicolor');
    await page.locator('#border-sides-mode').selectOption('multicolor');
    await page.locator('#tab-palette').click();
    await page.locator('#border-optimize-colors').check();
    await page.waitForFunction(() => borderColorPending || borderColorPlan !== null || borderColorError !== null);
    assert.equal(await page.locator('#save-border-sprites').isDisabled(), true);
    assert.deepEqual(await paletteData(), before, 'pending optimization must not change the Palette tab');
    await page.waitForFunction(() => borderColorPlan !== null || borderColorError !== null);
    assert.equal(await page.evaluate(() => borderColorError), null);
    assert.deepEqual(await paletteData(), before, 'completed optimization must not change the Palette tab');
    report.optimizedPaletteIndependent = true;
    report.plan = await page.evaluate(() => borderColorPlan);
    await page.locator('#tab-restricted').click();
    const optimizedZip = await download('#save-border-sprites', 'optimized-sprites.zip');
    const coreMci = await download('#mci-save', 'core.mci');
    const atlas = unzip(optimizedZip), manifest = JSON.parse(atlas['manifest.json']);
    report.fields = [];
    for (const phase of [0, 1]) {
      const image = await page.evaluate(phase => {
        ifliFrameIndex = phase; renderPreview();
        return { pixels: Array.from(context.getImageData(0, 0, canvas.width, canvas.height).data),
          palette: C64_PALETTE.map(color => color.rgb), png: canvas.toDataURL().split(',')[1] };
      }, phase);
      const expected = new Uint8ClampedArray(368 * 272 * 4);
      for (let offset = 0; offset < expected.length; offset += 4) expected.set([...image.palette[0], 255], offset);
      for (let y = 0; y < 200; y++) for (let x = 0; x < 160; x++) {
        const cell = Math.floor(y / 8) * 40 + Math.floor(x / 4);
        const bits = coreMci[(phase ? 9218 : 1026) + cell * 8 + y % 8];
        const code = bits >> (6 - 2 * (x % 4)) & 3;
        const screen = coreMci[(phase ? 17410 : 2) + cell];
        const color = [coreMci[1002], screen >> 4, screen & 15, coreMci[18434 + cell]][code];
        for (const half of [0, 1]) {
          const targetX = 24 + x * 2 + phase + half;
          if (targetX < 368) expected.set([...image.palette[color], 255], ((y + 35) * 368 + targetX) * 4);
        }
      }
      for (const sprite of manifest.sprites.filter(sprite => sprite.field === phase)) {
        const colors = [0, manifest.hardware.sharedMulticolorRegisters[0], sprite.colorIndex,
          manifest.hardware.sharedMulticolorRegisters[1]];
        for (let y = 0; y < 21; y++) for (let x = 0; x < sprite.displayWidth; x++) {
          const px = sprite.x + x, py = sprite.y + y;
          if (px < 0 || px >= 368 || py < 0 || py >= 272 || px < sprite.clip.x || px >= sprite.clip.x + sprite.clip.width ||
              py < sprite.clip.y || py >= sprite.clip.y + sprite.clip.height) continue;
          const bit = Math.floor(x / (sprite.xExpanded ? 2 : 1));
          const value = atlas['sprites.bin'][sprite.byteOffset + y * 3 + Math.floor(bit / 8)];
          const code = value >> (6 - 2 * Math.floor(bit % 8 / 2)) & 3;
          if (code) expected.set([...image.palette[colors[code]], 255], (py * 368 + px) * 4);
        }
      }
      let differentPixels = 0;
      for (let offset = 0; offset < expected.length; offset += 4) {
        if ([0, 1, 2, 3].some(channel => expected[offset + channel] !== image.pixels[offset + channel])) differentPixels++;
      }
      assert.equal(differentPixels, 0, `MCI field ${phase} matches independently decoded real downloads`);
      fs.writeFileSync(artifact(`restricted-phase-${phase}.png`), Buffer.from(image.png, 'base64'));
      report.fields.push({ phase, differentPixels });
    }
    await page.locator('#border-optimize-colors').uncheck();
    await page.locator('#graphics-mode-options').selectOption('bitmap');
    await page.locator('#tab-palette').click();
    await compareFullMapping('Multicolor bitmap full-image palette');
    assert.deepEqual(await paletteData(), before, 'switching MCI to bitmap must preserve physical palette resolution');
    assert.equal(await page.evaluate(() => documentTargetPixels.width), 160, 'only the hardware target uses wide-pixel sampling');
    report.bitmapFullResolution = true;

    for (const format of ['charset', 'sprites', 'sprites-hires']) {
      await page.locator('#graphics-mode-options').selectOption(format);
      await page.locator('#tab-restricted').click();
      const comparison = await page.evaluate(() => {
        const same = (left, right) => left.length === right.length && left.every((value, index) => value === right[index]);
        const fit = input => isCharsetMode()
          ? createC64CharsetImage(input, C64_PALETTE, { backgroundColorIndex, multicolorIndices: charsetControls.getState(),
              similarityThreshold: charsetControls.getSimilarityThreshold() })
          : createC64SpriteGridImage(input, C64_PALETTE, { ...spriteGridControls.getState(), backgroundColorIndex,
              overlay: Boolean(currentGraphicsMode().hiresOverlay) });
        const mapped = fit(getRestrictedTarget()), raw = fit(unrestrictedPixels);
        return { expectedDimensions: [mapped.pixels.width, mapped.pixels.height],
          actualDimensions: [fliResult.pixels.width, fliResult.pixels.height],
          differsFromRaw: !same(mapped.pixels.data, raw.pixels.data),
          matchesMappedInput: same(mapped.pixels.data, fliResult.pixels.data),
          targetDiffersFromRaw: !same(getRestrictedTarget().data, unrestrictedPixels.data) };
      });
      assert.equal(comparison.targetDiffersFromRaw, true, `${format}: fixture has a meaningful mapping`);
      assert.equal(comparison.differsFromRaw, true, `${format}: mapping changes hardware output`);
      assert.equal(comparison.matchesMappedInput, true, `${format}: hardware fits the mapped target`);
      report.cases.push({ name: `${format} derives from mapped target`, ...comparison });
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.equal(sha256(fs.readFileSync(sourcePath)), original, 'original project remains unchanged');
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
