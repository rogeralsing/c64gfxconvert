const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const zlib = require('node:zlib');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

const root = '/Users/rogerjohansson/git/asynkron/c64';
const output = path.join(root, 'output/playwright');
const assets = path.join(root, 'images/borders');
const artifact = name => path.join(output, `cyberpunk-${name}`);
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const report = { errors: [], phases: [], screenshots: [] };

function unzip(buffer) {
  const entries = {};
  let offset = 0;
  while (buffer.readUInt32LE(offset) === 0x04034b50) {
    const method = buffer.readUInt16LE(offset + 8);
    const size = buffer.readUInt32LE(offset + 18);
    const nameLength = buffer.readUInt16LE(offset + 26);
    const extraLength = buffer.readUInt16LE(offset + 28);
    const name = buffer.subarray(offset + 30, offset + 30 + nameLength).toString();
    const start = offset + 30 + nameLength + extraLength;
    const stored = buffer.subarray(start, start + size);
    entries[name] = method === 0 ? stored : method === 8 ? zlib.inflateRawSync(stored) : null;
    assert.ok(entries[name], 'Supported ZIP compression');
    offset = start + size;
  }
  return entries;
}

(async () => {
  const projectBytes = fs.readFileSync(path.join(assets, 'Cyberpunk.json'));
  const originalCore = fs.readFileSync(path.join(assets, 'Cyberpunk.mci'));
  const originalZip = fs.readFileSync(path.join(assets, 'Cyberpunk-borders.zip'));
  const original = unzip(originalZip);
  const originalManifest = JSON.parse(original['manifest.json']);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  try {
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    fs.writeFileSync(artifact('project-initial-snapshot.yml'), await page.locator('body').ariaSnapshot());
    await page.locator('#project-input').setInputFiles(path.join(assets, 'Cyberpunk.json'));
    await page.waitForFunction(() => !projectLoading && borderSourcePixels && graphicsMode === 'mci', { timeout: 60000 });
    const loadError = await page.locator('#project-error').evaluate(element => element.hidden ? null : element.textContent);
    assert.equal(loadError, null);
    await page.locator('#tab-restricted').click();
    await page.waitForFunction(() => ifliResult && canvas.width === 368 && canvas.height === 200);
    if (await page.locator('#ifli-playback').textContent() === 'Pause') await page.locator('#ifli-playback').click();
    await page.locator('#grid-toggle').uncheck();
    report.settings = await page.evaluate(() => ({
      graphicsMode, borderSprites: borderSpriteControls.getState(), layout: currentBorderLayout(),
      backgroundColorIndex, paletteId: paletteState.id, virtualColorMode: paletteState.virtualColorMode,
      layerCount: layerStack.layers.length, imageName, canvas: [canvas.width, canvas.height]
    }));
    assert.equal(report.settings.borderSprites.vertical.enabled, false);
    assert.equal(report.settings.borderSprites.sides.enabled, true);
    assert.deepEqual(report.settings.canvas, [368, 200]);

    const generated = await page.evaluate(() => ({
      mci: Array.from(encodeTruePaintMci(ensureMulticolorInterlaceResult(), C64_PALETTE)),
      zip: Array.from(encodeC64BorderSpriteZip(ensureBorderSpriteResult()))
    }));
    const currentCore = Buffer.from(generated.mci);
    const currentZip = Buffer.from(generated.zip);
    fs.writeFileSync(artifact('current-core.mci'), currentCore);
    fs.writeFileSync(artifact('current-borders.zip'), currentZip);
    const current = unzip(currentZip);
    const currentManifest = JSON.parse(current['manifest.json']);
    const firstDifference = (first, second) => {
      for (let index = 0; index < Math.min(first.length, second.length); index++) if (first[index] !== second[index]) return index;
      return first.length === second.length ? null : Math.min(first.length, second.length);
    };
    report.exports = {
      mci: { suppliedSha256: sha(originalCore), currentSha256: sha(currentCore), bytes: currentCore.length,
        exactMatch: originalCore.equals(currentCore), firstDifference: firstDifference(originalCore, currentCore) },
      sprites: { suppliedSha256: sha(original['sprites.bin']), currentSha256: sha(current['sprites.bin']),
        bytes: current['sprites.bin'].length, exactMatch: original['sprites.bin'].equals(current['sprites.bin']),
        firstDifference: firstDifference(original['sprites.bin'], current['sprites.bin']) },
      zip: { suppliedSha256: sha(originalZip), currentSha256: sha(currentZip), exactMatch: originalZip.equals(currentZip) },
      settingsMatch: JSON.stringify(originalManifest.settings) === JSON.stringify(currentManifest.settings),
      imageMatch: JSON.stringify(originalManifest.image) === JSON.stringify(currentManifest.image),
      fieldsMatch: JSON.stringify(originalManifest.fields) === JSON.stringify(currentManifest.fields),
      spriteMetadataMatch: JSON.stringify(originalManifest.sprites) === JSON.stringify(currentManifest.sprites)
    };
    for (const phase of [0, 1]) {
      const dataUrl = await page.evaluate(phase => {
        ifliFrameIndex = phase;
        renderPreview();
        return canvas.toDataURL('image/png').split(',')[1];
      }, phase);
      const destination = artifact(`preview-phase-${phase}.png`);
      fs.writeFileSync(destination, Buffer.from(dataUrl, 'base64'));
      report.phases.push({ phase, png: destination, sha256: sha(Buffer.from(dataUrl, 'base64')) });
    }
    await page.evaluate(() => { ifliFrameIndex = 0; renderPreview(); });
    const desktop = artifact('preview-desktop.png');
    await page.screenshot({ path: desktop });
    report.screenshots.push(desktop);
    report.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(report.horizontalOverflow, false);
    assert.deepEqual(report.errors, []);
    report.assetHashesAfter = {
      project: sha(fs.readFileSync(path.join(assets, 'Cyberpunk.json'))),
      mci: sha(fs.readFileSync(path.join(assets, 'Cyberpunk.mci'))),
      zip: sha(fs.readFileSync(path.join(assets, 'Cyberpunk-borders.zip')))
    };
    assert.equal(report.assetHashesAfter.project, sha(projectBytes));
    assert.equal(report.assetHashesAfter.mci, sha(originalCore));
    assert.equal(report.assetHashesAfter.zip, sha(originalZip));
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.failure = { message: error.message, stack: error.stack };
  } finally {
    fs.writeFileSync(artifact('project-proof.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 2));
  if (!report.passed) process.exitCode = 1;
})();
