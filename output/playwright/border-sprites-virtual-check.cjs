const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

const root = '/Users/rogerjohansson/git/asynkron/c64';
const output = path.join(root, 'output/playwright');
const artifact = name => path.join(output, `border-sprites-virtual-${name}`);
const report = { cases: [], errors: [], screenshots: [] };

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  const color = async (name, value) => page.locator(`input[name="${name}"][value="${value}"]`).check({ force: true });
  async function selectLegalVirtualColors(excludeMixed = false) {
    await page.evaluate(excludeMixed => {
      const excludedIndices = IFLI_VIRTUAL_PALETTE.filter(color =>
        color.colorIndices.some(index => index !== 0 && index !== 6) ||
        excludeMixed && color.colorIndices[0] !== color.colorIndices[1]).map(color => color.index);
      virtualPaletteView.setSettings({ minLevel: 0, maxLevel: 16, minLightness: 0, maxLightness: 100, excludedIndices });
      const dither = document.getElementById('dither');
      dither.value = '0';
      dither.dispatchEvent(new Event('input', { bubbles: true }));
      updatePalettePreview();
    }, excludeMixed);
  }
  async function inspect(name) {
    const result = await page.evaluate(name => {
      const result = ensureBorderSpriteResult();
      const frame = result.frames[0];
      const left = frame.sprites.filter(sprite => sprite.group === 'left');
      const codes = new Set();
      for (const sprite of left) {
        const multicolor = sprite.mode === 'multicolor';
        let y = sprite.y;
        for (let row = 0; row < 21; row++) {
          if (y >= sprite.clip.y && y < sprite.clip.y + sprite.clip.height) {
            for (let column = 0; column < (multicolor ? 12 : 24); column++) {
              const bit = column * (multicolor ? 2 : 1);
              codes.add(sprite.data[row * 3 + (bit >> 3)] >> ((multicolor ? 6 : 7) - bit % 8) & (multicolor ? 3 : 1));
            }
          }
          y += sprite.rowHeights[row];
        }
      }
      const palette = frame.palettePixels;
      const sideIndex = ((frame.layout.coreY + 10) * frame.width + 10) * 4;
      const coreIndex = (10 * palettePixels.width + 10) * 4;
      const pair = IFLI_VIRTUAL_PALETTE.find(color => color.colorIndices.includes(0) && color.colorIndices.includes(6));
      return { name, codes: [...codes].sort(), mode: paletteState.virtualColorMode,
        spriteMode: frame.config.sides.mode, paletteSide: palette ? Array.from(palette.data.slice(sideIndex, sideIndex + 3)) : null,
        paletteCore: Array.from(palettePixels.data.slice(coreIndex, coreIndex + 3)), virtualRGB: pair.rgb.map(Math.round),
        fields: result.frames.length, canvas: [canvas.width, canvas.height] };
    }, name);
    report.cases.push(result);
    return result;
  }
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    await page.locator('#graphics-mode-options').selectOption('mci');
    await page.locator('#border-vertical-enabled').check();
    await page.locator('#border-sides-enabled').check();
    await color('background-color', 0);
    await color('border-vertical-color', 6);
    await color('border-sides-color', 6);

    for (const virtualMode of ['talent', 'computed']) {
      await page.locator('#virtual-color-mode-options').selectOption(virtualMode);
      const fixture = await page.evaluate(() => {
        const pair = IFLI_VIRTUAL_PALETTE.find(color => color.colorIndices.includes(0) && color.colorIndices.includes(6));
        const image = document.createElement('canvas');
        image.width = 368; image.height = 272;
        const context = image.getContext('2d');
        context.fillStyle = `rgb(${pair.rgb.join(',')})`;
        context.fillRect(0, 0, image.width, image.height);
        return image.toDataURL('image/png').split(',')[1];
      });
      await page.locator('#image-input').setInputFiles({ name: `${virtualMode}-black-blue.png`, mimeType: 'image/png', buffer: Buffer.from(fixture, 'base64') });
      await page.waitForFunction(() => unrestrictedPixels && !projectLoading);
      await selectLegalVirtualColors();
      for (const pattern of ['checkers', 'lines']) {
        await page.locator('#virtual-colors').selectOption(pattern);
        for (const spriteMode of ['hires', 'multicolor']) {
          await page.locator('#border-vertical-mode').selectOption(spriteMode);
          await page.locator('#border-sides-mode').selectOption(spriteMode);
          if (spriteMode === 'multicolor') {
            await color('border-multi-1', 0);
            await color('border-multi-2', 6);
          }
          await page.locator('#tab-restricted').click();
          if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
          const result = await inspect(`${virtualMode}/${pattern}/${spriteMode}`);
          assert.ok(result.codes.includes(0) && result.codes.some(code => code !== 0), 'Virtual tone must pack both background and foreground');
          assert.deepEqual(result.paletteSide, result.virtualRGB, 'Border palette preview retains the actual selected virtual RGB');
          assert.deepEqual(result.paletteCore, result.virtualRGB, 'Bitmap uses the same virtual RGB');
          assert.deepEqual(result.canvas, [368, 272]);
          assert.equal(result.fields, 2);
          await page.locator('#tab-palette').click();
          const displayed = await page.evaluate(() => Array.from(context.getImageData(10, currentBorderLayout().coreY + 10, 1, 1).data.slice(0, 3)));
          assert.deepEqual(displayed, result.virtualRGB, 'Visible palette tab must include the border virtual color');
        }
      }
      await page.locator('#border-vertical-mode').selectOption('hires');
      await page.locator('#border-sides-mode').selectOption('hires');
      await page.locator('#virtual-colors').selectOption('checkers');
      await selectLegalVirtualColors(true);
      const disabled = await inspect(`${virtualMode}/mixed-disabled`);
      assert.equal(disabled.codes.length, 1, 'Disabled mixed entry must not reappear as a virtual pattern at zero dither');
      await selectLegalVirtualColors();
      await page.locator('#virtual-colors').selectOption('off');
      const off = await inspect(`${virtualMode}/off`);
      assert.equal(off.codes.length, 1, 'Off retains the original solid-only sprite fit');
    }

    await page.locator('#project-input').setInputFiles(path.join(output, 'border-sprites-project.json'));
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().vertical.enabled);
    await color('background-color', 0);
    await color('border-sides-color', 6);
    await page.locator('#border-sides-mode').selectOption('hires');
    await page.locator('#tab-restricted').click();
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    await page.locator('#grid-toggle').uncheck();
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    await page.screenshot({ path: artifact('desktop.png') });
    report.screenshots.push(artifact('desktop.png'));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    await page.screenshot({ path: artifact('mobile.png') });
    report.screenshots.push(artifact('mobile.png'));
    report.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(report.horizontalOverflow, false);
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
