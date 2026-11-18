const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');
const root = '/Users/rogerjohansson/git/asynkron/c64';
const artifact = name => path.join(root, `output/playwright/border-sprites-${name}`);
const report = { errors: [], downloads: {}, screenshots: [] };

function unzip(buffer) {
  const entries = {};
  for (let offset = 0; buffer.readUInt32LE(offset) === 0x04034b50;) {
    assert.equal(buffer.readUInt16LE(offset + 8), 0);
    const size = buffer.readUInt32LE(offset + 18), nameLength = buffer.readUInt16LE(offset + 26);
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
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('normal-side-initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    await page.locator('#project-input').setInputFiles(artifact('project.json'));
    await page.waitForFunction(() => !projectLoading && borderSpriteControls.getState().vertical.enabled);
    await page.locator('#tab-restricted').click();
    await page.waitForFunction(() => ifliResult && canvas.width === 368 && canvas.height === 272);
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();

    report.geometry = await page.evaluate(() => {
      const result = ensureBorderSpriteResult();
      const side = result.sprites.filter(sprite => ['left', 'right'].includes(sprite.group));
      let pixelDifferences = 0, pixelsDecoded = 0;
      for (const sprite of side) {
        for (let row = 0; row < 21; row++) for (let column = 0; column < 24; column++) {
          const x = sprite.x + column, y = sprite.y + row;
          if (x < sprite.clip.x || x >= sprite.clip.x + sprite.clip.width ||
              y < sprite.clip.y || y >= sprite.clip.y + sprite.clip.height) continue;
          const byte = sprite.data[row * 3 + Math.floor(column / 8)];
          const code = sprite.multicolor ? byte >> (6 - 2 * Math.floor(column % 8 / 2)) & 3
            : byte >> (7 - column % 8) & 1;
          const colors = sprite.multicolor ? [result.backgroundColorIndex, result.config.multicolorIndices[0],
            sprite.colorIndex, result.config.multicolorIndices[1]] : [result.backgroundColorIndex, sprite.colorIndex];
          const expected = C64_PALETTE[colors[code]].rgb;
          const offset = (y * result.width + x) * 4;
          if (expected.some((channel, index) => result.pixels.data[offset + index] !== channel)) pixelDifferences++;
          pixelsDecoded++;
        }
      }
      return { config: result.config, layout: result.layout, totalFrames: result.sprites.length,
        sideFrames: side.map(({ data, ...metadata }) => ({ ...metadata, prefixBytes: Array.from(data.slice(0, 30)),
          padding: data[63] })), pixelDifferences, pixelsDecoded };
    });
    assert.equal(report.geometry.totalFrames, 36);
    assert.equal(report.geometry.sideFrames.length, 20);
    assert.equal(report.geometry.pixelDifferences, 0);
    assert.equal(report.geometry.pixelsDecoded, 200 * 24 * 2);
    for (const group of ['left', 'right']) {
      const sprites = report.geometry.sideFrames.filter(sprite => sprite.group === group);
      assert.equal(sprites.length, 10);
      sprites.forEach((sprite, band) => {
        assert.equal(sprite.yExpanded, false);
        assert.equal(sprite.displayHeight, 21);
        assert.deepEqual(sprite.rowHeights, Array(21).fill(1));
        assert.equal(sprite.y, report.geometry.layout.coreY + (band === 9 ? 179 : band * 21));
        assert.equal(sprite.hardwareSlot, (group === 'left' ? 3 : 4) + (band === 9 ? 2 : 0));
        assert.equal(sprite.padding, 0);
        if (band === 9) {
          assert.equal(sprite.vicY, 229);
          assert.equal(sprite.clip.y, report.geometry.layout.coreY + 189);
          assert.equal(sprite.clip.height, 11);
          assert.deepEqual(sprite.prefixBytes, Array(30).fill(0));
        }
      });
    }

    report.phases = await page.evaluate(() => {
      const result = ensureBorderSpriteResult(), layout = result.layout;
      const edge = layout.coreX + 320;
      return [0, 1].map(phase => {
        ifliFrameIndex = phase;
        renderPreview();
        const core = ifliResult.displayFrames[phase], actual = context.getImageData(0, 0, canvas.width, canvas.height);
        const expected = new Uint8ClampedArray(result.pixels.data);
        let transparentRows = 0, opaqueRows = 0, visibleSpill = 0;
        for (let y = 0; y < 200; y++) {
          for (let x = 0; x < 320; x++) {
            const source = (y * core.width + Math.floor(x * core.width / 320)) * 4;
            expected.set(core.data.subarray(source, source + 4), ((y + layout.coreY) * layout.width + x + layout.coreX) * 4);
          }
          const pixel = (y + layout.coreY) * layout.width + edge, source = (y * core.width + core.width - 1) * 4;
          if (result.opaqueMask[pixel] === 0) {
            transparentRows++;
            if (phase === 1) {
              if ([0, 1, 2, 3].some(channel => expected[pixel * 4 + channel] !== core.data[source + channel])) visibleSpill++;
              expected.set(core.data.subarray(source, source + 4), pixel * 4);
            }
          } else opaqueRows++;
        }
        let differences = 0, outsideChanges = 0;
        for (let y = 0; y < layout.height; y++) for (let x = 0; x < layout.width; x++) {
          const offset = (y * layout.width + x) * 4;
          if ([0, 1, 2, 3].some(channel => actual.data[offset + channel] !== expected[offset + channel])) differences++;
          const coreOrEdge = x >= layout.coreX && x <= edge && y >= layout.coreY && y < layout.coreY + 200;
          if (!coreOrEdge && [0, 1, 2, 3].some(channel => actual.data[offset + channel] !== result.pixels.data[offset + channel])) outsideChanges++;
        }
        return { phase, transparentRows, opaqueRows, visibleSpill, differences, outsideChanges, canvas: [canvas.width, canvas.height] };
      });
    });
    for (const phase of report.phases) {
      assert.equal(phase.differences, 0);
      assert.equal(phase.outsideChanges, 0);
      assert.ok(phase.transparentRows > 0 && phase.opaqueRows > 0);
      assert.deepEqual(phase.canvas, [368, 272]);
      if (phase.phase === 1) assert.ok(phase.visibleSpill > 0);
    }

    for (const [selector, key, filename] of [['#save-border-sprites', 'sprites', 'normal-side-export.zip'],
      ['#mci-save', 'mci', 'normal-side-core.mci']]) {
      const ready = page.waitForEvent('download');
      await page.locator(selector).click();
      const download = await ready, destination = artifact(filename);
      await download.saveAs(destination);
      report.downloads[key] = { path: destination, name: download.suggestedFilename(), bytes: fs.statSync(destination).size };
    }
    const entries = unzip(fs.readFileSync(report.downloads.sprites.path));
    const manifest = JSON.parse(entries['manifest.json']);
    assert.equal(entries['sprites.bin'].length, 2304);
    assert.equal(manifest.sprites.length, 36);
    assert.equal(manifest.hardware.sideBandHeight, 21);
    assert.equal(manifest.hardware.sideBandCountPerSide, 10);
    assert.equal(manifest.hardware.maximumSideSpritesAtOnce, 4);
    assert.deepEqual(manifest.settings, report.geometry.config);
    for (const sprite of manifest.sprites.filter(sprite => ['left', 'right'].includes(sprite.group))) {
      assert.equal(sprite.yExpanded, false);
      assert.equal(sprite.displayHeight, 21);
    }
    assert.equal(report.downloads.mci.bytes, 19434);
    report.downloads.sprites.nativeBytes = entries['sprites.bin'].length;
    report.downloads.sprites.frames = manifest.sprites.length;

    await page.evaluate(() => { ifliFrameIndex = 0; renderPreview(); });
    await page.locator('#grid-toggle').uncheck();
    await page.locator('#border-sprites-heading').evaluate(element => {
      const sidebar = document.querySelector('.config-sidebar');
      sidebar.scrollTop += element.getBoundingClientRect().top - sidebar.getBoundingClientRect().top - 48;
    });
    const desktop = artifact('desktop.png');
    await page.screenshot({ path: desktop });
    report.screenshots.push(desktop);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => scrollTo(0, 0));
    const mobile = artifact('mobile.png');
    await page.screenshot({ path: mobile });
    report.screenshots.push(mobile);
    await page.locator('#border-sprites-heading').scrollIntoViewIfNeeded();
    const mobileControls = artifact('mobile-controls.png');
    await page.screenshot({ path: mobileControls });
    report.screenshots.push(mobileControls);
    report.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(report.horizontalOverflow, false);
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.failure = { message: error.message, stack: error.stack };
  } finally {
    fs.writeFileSync(artifact('normal-side-proof.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify({ passed: report.passed, phases: report.phases, downloads: report.downloads,
    errors: report.errors, failure: report.failure, proof: artifact('normal-side-proof.json') }, null, 2));
  if (!report.passed) process.exitCode = 1;
})();
