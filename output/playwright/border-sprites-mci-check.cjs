const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

const root = '/Users/rogerjohansson/git/asynkron/c64';
const output = path.join(root, 'output/playwright');
const artifact = name => path.join(output, `border-sprites-mci-${name}`);
const report = { errors: [], phases: [], screenshots: [] };

function unzipStored(buffer) {
  const entries = {};
  let offset = 0;
  while (buffer.readUInt32LE(offset) === 0x04034b50) {
    assert.equal(buffer.readUInt16LE(offset + 8), 0);
    const size = buffer.readUInt32LE(offset + 18);
    const nameLength = buffer.readUInt16LE(offset + 26);
    const extraLength = buffer.readUInt16LE(offset + 28);
    const name = buffer.subarray(offset + 30, offset + 30 + nameLength).toString();
    const start = offset + 30 + nameLength + extraLength;
    entries[name] = buffer.subarray(start, start + size);
    offset = start + size;
  }
  return entries;
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  async function download(button, name) {
    const pending = page.waitForEvent('download');
    await page.locator(button).click();
    const file = await pending;
    await file.saveAs(artifact(name));
    return fs.readFileSync(artifact(name));
  }
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    await page.locator('#project-input').setInputFiles(path.join(output, 'border-sprites-project.json'));
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().vertical.enabled);
    await page.locator('#tab-restricted').click();
    await page.waitForFunction(() => ifliResult && canvas.width === 368 && canvas.height === 272);
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();

    report.phases = await page.evaluate(() => {
      const conversion = ensureBorderSpriteResult();
      if (!conversion.interlaced || conversion.frames.length !== 2) throw new Error('MCI requires two sprite fields');
      const [first, second] = conversion.frames;
      let differingBytes = 0;
      for (let index = 0; index < first.sprites.length; index++) {
        const a = first.sprites[index], b = second.sprites[index];
        if (b.x !== a.x + 1 || b.vicX !== a.vicX + 1 || b.clip.x !== a.clip.x + 1 || b.y !== a.y) {
          throw new Error('Sprite coordinates must follow the one-pixel MCI phase offset');
        }
        for (let byte = 0; byte < 64; byte++) if (a.data[byte] !== b.data[byte]) differingBytes++;
      }
      if (!differingBytes) throw new Error('Real source must produce separately fitted sprite fields');
      return conversion.frames.map((field, phase) => {
        ifliFrameIndex = phase;
        renderPreview();
        const { layout } = field;
        const core = ifliResult.displayFrames[phase];
        const actual = context.getImageData(0, 0, canvas.width, canvas.height);
        const expected = new Uint8ClampedArray(layout.width * layout.height * 4);
        const mask = new Uint8Array(layout.width * layout.height);
        const bg = C64_PALETTE[backgroundColorIndex].rgb;
        for (let offset = 0; offset < expected.length; offset += 4) expected.set([...bg, 255], offset);
        for (let y = 0; y < 200; y++) for (let x = 0; x < 320; x++) {
          const source = (y * core.width + x) * 4;
          const target = ((y + layout.coreY) * layout.width + x + layout.coreX) * 4;
          expected.set(core.data.subarray(source, source + 4), target);
        }
        if (phase === 1) for (let y = 0; y < 200; y++) {
          const source = (y * core.width + core.width - 1) * 4;
          const target = ((y + layout.coreY) * layout.width + layout.coreX + 320) * 4;
          expected.set(core.data.subarray(source, source + 4), target);
        }
        for (const sprite of field.sprites) {
          const mc = sprite.mode === 'multicolor';
          const colors = mc ? [backgroundColorIndex, field.config.multicolorIndices[0],
            sprite.colorIndex, field.config.multicolorIndices[1]] : [backgroundColorIndex, sprite.colorIndex];
          const cellWidth = (mc ? 2 : 1) * (sprite.xExpanded ? 2 : 1);
          let top = sprite.y;
          for (let row = 0; row < 21; row++) {
            for (let cell = 0; cell < (mc ? 12 : 24); cell++) {
              const bit = cell * (mc ? 2 : 1);
              const code = sprite.data[row * 3 + (bit >> 3)] >> ((mc ? 6 : 7) - bit % 8) & (mc ? 3 : 1);
              if (code) for (let yy = top; yy < top + sprite.rowHeights[row]; yy++) {
                for (let xx = sprite.x + cell * cellWidth; xx < sprite.x + (cell + 1) * cellWidth; xx++) {
                  if (xx < 0 || yy < 0 || xx >= layout.width || yy >= layout.height ||
                      xx < sprite.clip.x || xx >= sprite.clip.x + sprite.clip.width ||
                      yy < sprite.clip.y || yy >= sprite.clip.y + sprite.clip.height) continue;
                  const target = yy * layout.width + xx;
                  expected.set([...C64_PALETTE[colors[code]].rgb, 255], target * 4);
                  mask[target] = 1;
                }
              }
            }
            top += sprite.rowHeights[row];
          }
        }
        let differences = 0, maskDifferences = 0, leftOverlayRows = 0;
        for (let index = 0; index < mask.length; index++) {
          if (mask[index] !== field.opaqueMask[index]) maskDifferences++;
          if ([0, 1, 2, 3].some(channel => actual.data[index * 4 + channel] !== expected[index * 4 + channel])) differences++;
        }
        for (let y = 0; y < 200; y++) if (mask[(y + layout.coreY) * layout.width + layout.coreX]) leftOverlayRows++;
        const side = field.sprites.filter(sprite => ['left', 'right'].includes(sprite.group));
        if (side.length !== 20 || side.some(sprite => sprite.yExpanded || sprite.rowHeights.some(height => height !== 1))) {
          throw new Error('Every side sprite must retain normal vertical resolution');
        }
        for (const sprite of side.filter(sprite => sprite.band === 9)) {
          if (sprite.vicY !== 229 || sprite.data.subarray(0, 30).some(Boolean) || ![5, 6].includes(sprite.hardwareSlot)) {
            throw new Error('Final side strip must use the padded spare pair');
          }
        }
        return { phase, offsetX: field.offsetX, spriteCount: field.sprites.length, differingBytes,
          differences, maskDifferences, leftOverlayRows, canvas: [canvas.width, canvas.height] };
      });
    });
    for (const field of report.phases) {
      assert.equal(field.differences, 0);
      assert.equal(field.maskDifferences, 0);
      assert.equal(field.spriteCount, 36);
      assert.deepEqual(field.canvas, [368, 272]);
    }
    assert.ok(report.phases[1].leftOverlayRows > 0, 'Second field exercises sprite priority over the left bitmap edge');
    assert.equal(await page.locator('#border-interlace-help').isVisible(), true);
    const zip = unzipStored(await download('#save-border-sprites', 'export.zip'));
    const manifest = JSON.parse(zip['manifest.json']);
    assert.equal(zip['sprites.bin'].length, 4608);
    assert.equal(manifest.interlaced, true);
    assert.equal(manifest.fields.length, 2);
    assert.deepEqual(manifest.fields.map(field => field.offsetX), [0, 1]);
    assert.equal(manifest.sprites.length, 72);
    report.export = { nativeBytes: zip['sprites.bin'].length, frames: manifest.sprites.length,
      fields: manifest.fields, filename: artifact('export.zip') };
    const mci = await download('#mci-save', 'core.mci');
    assert.equal(mci.length, 19434);
    report.coreMciBytes = mci.length;

    await page.evaluate(() => { ifliFrameIndex = 0; renderPreview(); });
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    await page.screenshot({ path: artifact('desktop.png') });
    report.screenshots.push(artifact('desktop.png'));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    await page.screenshot({ path: artifact('mobile.png') });
    report.screenshots.push(artifact('mobile.png'));
    report.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(report.horizontalOverflow, false);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('#graphics-mode-options').selectOption('bitmap');
    await page.waitForFunction(() => graphicsMode === 'bitmap' && !ensureBorderSpriteResult().interlaced);
    assert.equal(await page.locator('#border-interlace-help').isVisible(), false);
    const plainZip = unzipStored(await download('#save-border-sprites', 'plain-export.zip'));
    const plain = JSON.parse(plainZip['manifest.json']);
    assert.equal(plainZip['sprites.bin'].length, 2304);
    assert.equal(plain.fields, undefined);
    assert.equal(plain.sprites.length, 36);
    report.plainExport = { nativeBytes: plainZip['sprites.bin'].length, frames: plain.sprites.length };
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
