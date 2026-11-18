const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('/Users/rogerjohansson/.npm/_npx/31e32ef8478fbf80/node_modules/playwright');

const report = { checks: [], errors: [] };
const check = (name, value = true) => { assert.ok(value, name); report.checks.push(name); };
const svg = color => Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200"><rect width="320" height="200" fill="${color}"/></svg>`);

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
    page.on('pageerror', error => report.errors.push(error.message));
    await page.goto('http://127.0.0.1:8768/', { waitUntil: 'networkidle' });
    check('crop disabled without a source', await page.locator('#tool-crop').isDisabled());
    await page.locator('#graphics-mode-options').selectOption('bitmap');
    const upload = async (name, color) => {
      await page.locator('#image-input').setInputFiles({ name: `${name}.svg`, mimeType: 'image/svg+xml', buffer: svg(color) });
      await page.waitForFunction(() => layerStack.active().image && layerStack.active().cache && document.getElementById('preview').getAttribute('aria-busy') === 'false');
    };
    const state = () => page.evaluate(() => ({ crop: structuredClone(layerStack.active().settings.crop), source: layerStack.active().sourceDataUrl }));
    const canvas = page.locator('#source-crop-canvas');
    const open = async () => { await page.locator('#tool-crop').click(); await page.waitForFunction(() => document.getElementById('source-crop-dialog').open); };
    const apply = async () => { await page.locator('#source-crop-apply').click(); assert.equal(await page.locator('#source-crop-dialog').evaluate(el => el.open), false); };
    const point = async (x, y) => canvas.evaluate((el, p) => {
      const bounds = el.getBoundingClientRect();
      const scale = Math.min((el.clientWidth - 36) / 320, (el.clientHeight - 36) / 200);
      return { x: bounds.left + (el.clientWidth - 320 * scale) / 2 + p.x * 320 * scale,
        y: bounds.top + (el.clientHeight - 200 * scale) / 2 + p.y * 200 * scale };
    }, { x, y });
    const drag = async (from, to) => {
      const a = await point(...from), b = await point(...to);
      await page.mouse.move(a.x, a.y); await page.mouse.down();
      await page.mouse.move(b.x, b.y, { steps: 5 }); await page.mouse.up();
    };
    const pixel = (x, y) => page.evaluate(({x,y}) => {
      const el = document.getElementById('canvas');
      return [...el.getContext('2d').getImageData(Math.floor(x*el.width/320),y,1,1).data];
    }, {x,y});
    await upload('lower', '#0000ff');
    await page.locator('[data-layer-action="add"]').click();
    await upload('upper', '#ff0000');
    const original = (await state()).source;
    assert.deepEqual(await pixel(10,10), [255,0,0,255]);
    await open();
    await drag([0,0], [.25,.25]);
    await drag([1,1], [.75,.75]);
    await apply();
    const rectangle = (await state()).crop;
    assert.deepEqual(rectangle, {mode:'rectangle',points:[{x:.25,y:.25},{x:.75,y:.25},{x:.75,y:.75},{x:.25,y:.75}]});
    check('rectangle corners resize axis-aligned mask');
    assert.deepEqual(await pixel(10,10), [0,0,255,255]);
    assert.deepEqual(await pixel(160,100), [255,0,0,255]);
    check('outside crop reveals lower layer; inside retains upper');
    assert.equal((await state()).source, original);
    check('original embedded source unchanged');

    await open();
    await page.locator('#source-crop-shape').selectOption('polygon');
    await drag([.75,.25], [.65,.1]);
    await page.locator('#source-crop-cancel').click();
    assert.deepEqual((await state()).crop, rectangle);
    check('Cancel discards polygon draft');
    await open();
    await page.locator('#source-crop-reset').click();
    await page.keyboard.press('Escape');
    assert.deepEqual((await state()).crop, rectangle);
    check('Escape discards draft reset');

    await open();
    await page.locator('#source-crop-shape').selectOption('polygon');
    await drag([.75,.25], [.65,.1]);
    let edge = await point(.45,.175);
    await page.mouse.click(edge.x,edge.y);
    assert.match(await page.locator('#source-crop-status').textContent(), /of 5$/);
    check('clicking an edge adds a polygon node');
    await canvas.press('Delete');
    assert.match(await page.locator('#source-crop-status').textContent(), /of 4$/);
    await canvas.press('Insert');
    assert.match(await page.locator('#source-crop-status').textContent(), /of 5$/);
    check('Delete removes and Insert adds selected-edge node');
    const x = Number(await page.locator('#source-crop-x').inputValue());
    const y = Number(await page.locator('#source-crop-y').inputValue());
    await canvas.press('ArrowRight'); await canvas.press('Shift+ArrowDown');
    assert.equal(Number(await page.locator('#source-crop-x').inputValue()), x+1);
    assert.equal(Number(await page.locator('#source-crop-y').inputValue()), y+10);
    check('keyboard moves by one source pixel and Shift by ten');
    await canvas.press('Delete'); await canvas.press('Delete'); await canvas.press('Delete');
    assert.match(await page.locator('#source-crop-status').textContent(), /of 3$/);
    assert.equal(await page.locator('#source-crop-delete').isDisabled(), true);
    check('polygon retains at least three points');
    await apply();
    const polygon = (await state()).crop;
    assert.equal(polygon.mode, 'polygon');
    assert.equal(polygon.points.length, 3);
    check('polygon applies independently moved corners');

    await page.locator('[data-layer-action="duplicate"]').click();
    const beforeDuplicate = await page.evaluate(() => structuredClone(layerStack.layers[layerStack.layers.length-2].settings.crop));
    await open(); await canvas.press('ArrowRight'); await apply();
    assert.deepEqual(await page.evaluate(() => layerStack.layers[layerStack.layers.length-2].settings.crop), beforeDuplicate);
    assert.notDeepEqual((await state()).crop, beforeDuplicate);
    check('duplicate owns independent crop nodes');
    await page.locator('[data-layer-action="remove"]').click();

    const pending = page.waitForEvent('download');
    await page.locator('#project-save').click();
    const download = await pending;
    const projectFile = 'output/playwright/source-crop-project.json';
    await download.saveAs(projectFile);
    const saved = JSON.parse(fs.readFileSync(projectFile,'utf8'));
    assert.deepEqual(saved.layers[1].settings.crop, polygon);
    assert.equal(saved.layers[1].source.dataUrl, original);
    await open(); await page.locator('#source-crop-reset').click(); await apply();
    assert.equal((await state()).crop, null);
    assert.deepEqual(await pixel(10,10), [255,0,0,255]);
    check('Reset crop restores full original source');
    await page.locator('#project-input').setInputFiles(projectFile);
    await page.waitForFunction(() => !projectLoading && layerStack.active().settings.crop?.mode === 'polygon');
    assert.deepEqual((await state()).crop, polygon);
    assert.equal((await state()).source, original);
    check('project download/reopen preserves mask and original');

    // Restore a known center rectangle through the public crop controls for transform checks.
    await open(); await page.locator('#source-crop-reset').click();
    await drag([0,0], [.25,.25]); await drag([1,1], [.75,.75]); await apply();
    const setSlider = async (id,value) => page.locator(id).evaluate((el,value) => { el.value=String(value); el.dispatchEvent(new Event('input',{bubbles:true})); },value);
    await setSlider('#source-scale',150); await setSlider('#source-position-x',20);
    for (const mode of ['afli','fli']) {
      await page.locator('#graphics-mode-options').selectOption(mode);
      const alpha = await page.evaluate(() => {
        const image = layerStack.active().cache.source;
        return {width:image.width,outside:image.data[(100*image.width+5)*4+3],inside:image.data[(100*image.width+Math.floor(image.width/2))*4+3]};
      });
      assert.equal(alpha.width,mode==='fli'?160:320);
      assert.equal(alpha.outside,0); assert.equal(alpha.inside,255);
    }
    assert.deepEqual((await state()).crop,rectangle);
    check('source-relative mask survives scale/pan and 160/320 mode changes');
    await page.locator('#tab-palette').click();
    const paletteOutside = await page.evaluate(() => {
      const canvas=document.getElementById('canvas'), x=15,y=100,offset=(y*canvas.width+x)*4;
      return {shown:[...canvas.getContext('2d').getImageData(x,y,1,1).data],
        lower:[...layerStack.layers[0].cache.palette.data.slice(offset,offset+4)]};
    });
    assert.deepEqual(paletteOutside.shown,paletteOutside.lower);
    assert.equal(paletteOutside.shown[3],255);
    check('palette preview reveals lower mapped layer outside cropped source');
    await page.locator('#tab-restricted').click();
    const fliPending = page.waitForEvent('download');
    await page.locator('#fli-save').click();
    const fliDownload = await fliPending;
    await fliDownload.saveAs('output/playwright/source-crop-composite.fli');
    const native = fs.readFileSync('output/playwright/source-crop-composite.fli');
    const fitted = await page.evaluate(() => {
      const canvas=document.getElementById('canvas');
      return {pixels:[...fliResult.pixels.data],shown:[...canvas.getContext('2d').getImageData(0,0,160,200).data],palette:C64_PALETTE.map(color=>color.rgb)};
    });
    assert.deepEqual(fitted.shown,fitted.pixels);
    assert.equal(native.length,17666);
    for(let y=0;y<200;y++) for(let x=0;x<160;x++) {
      const tile=Math.floor(y/8)*40+Math.floor(x/4), screen=native[1282+(y%8)*1024+tile];
      const code=native[9474+tile*8+y%8]>>(6-2*(x%4))&3;
      const color=[native[2+y],screen>>4,screen&15,native[258+tile]][code],offset=(y*160+x)*4;
      assert.deepEqual(fitted.pixels.slice(offset,offset+4),[...fitted.palette[color],255]);
    }
    check('cropped composition downloads as FLI with all 32000 fitted pixels preserved');
    await page.locator('[data-layer-action="add-markers"]').click();
    check('crop disabled for tile marker layer',await page.locator('#tool-crop').isDisabled());
    await page.locator('[data-layer-action="add"]').click();
    check('crop disabled for empty image layer',await page.locator('#tool-crop').isDisabled());

    // Real artwork makes shape handles and dimmed source useful to review visually.
    await page.locator('#image-input').setInputFiles('output/playwright/talent-contrast-source.png');
    await page.waitForFunction(() => !document.getElementById('tool-crop').disabled);
    await open();
    await page.locator('#source-crop-shape').selectOption('polygon');
    await canvas.press('ArrowRight');
    await page.locator('#source-crop-x').fill('300');
    await page.locator('#source-crop-y').fill('90');
    await page.screenshot({path:'output/playwright/source-crop-editor-desktop.png'});
    for (const size of [{width:1440,height:1000},{width:390,height:844}]) {
      await page.setViewportSize(size);
      const layout = await page.locator('#source-crop-dialog').evaluate(el => {
        const r=el.getBoundingClientRect(); const canvas=el.querySelector('canvas').getBoundingClientRect();
        return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:innerWidth,height:innerHeight,
          overflow:el.scrollWidth>el.clientWidth+1,canvasWidth:canvas.width,canvasHeight:canvas.height};
      });
      assert.ok(layout.left>=0 && layout.top>=0 && layout.right<=layout.width+1 && layout.bottom<=layout.height+1);
      assert.equal(layout.overflow,false); assert.ok(layout.canvasWidth>0 && layout.canvasHeight>0);
    }
    await page.screenshot({path:'output/playwright/source-crop-editor-mobile.png'});
    check('crop editor fits desktop and 390px mobile viewport');
    assert.deepEqual(report.errors,[]);
    fs.writeFileSync('output/playwright/source-crop-proof.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally { await browser.close(); }
})().catch(error=>{ console.error(error); process.exitCode=1; });
