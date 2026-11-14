async page => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const root = '/Users/rogerjohansson/git/asynkron/c64';
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.reload();
  await page.getByRole('button', { name: 'New tile marker layer', exact: true }).click();
  let bounds = await page.locator('#canvas').boundingBox();
  const point = (x, y) => ({ x: bounds.x + (x + 0.5) * bounds.width / 40,
    y: bounds.y + (y + 0.5) * bounds.height / 25 });
  const drag = async (x1, y1, x2, y2) => {
    const from = point(x1, y1), to = point(x2, y2);
    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(to.x, to.y);
    await page.mouse.up();
  };
  await drag(4, 3, 14, 3);
  assert(await page.evaluate(() => layerStack.active().markers.tiles.reduce((a,b)=>a+b,0)) === 11,
    'Fast drag must fill every crossed tile');
  await drag(4, 3, 9, 3);
  assert(await page.evaluate(() => layerStack.active().markers.tiles.reduce((a,b)=>a+b,0)) === 5,
    'Drag from an enabled tile must erase the whole stroke');
  await page.locator('#tile-marker-color').fill('#00aaff');
  const blank = await page.evaluate(() => ({
    type:layerStack.active().type, settings:layerStack.active().settings,
    panels:['source-settings','adjustment-settings','color-settings'].map(id=>document.getElementById(id).hidden),
    color:layerStack.active().markers.color,
    on:[...document.getElementById('tile-marker-overlay').getContext('2d').getImageData(14*8+1,3*8+1,1,1).data],
    off:[...document.getElementById('tile-marker-overlay').getContext('2d').getImageData(4*8+1,3*8+1,1,1).data]
  }));
  assert(blank.settings === null && blank.panels.every(Boolean), 'Marker layer must hide image settings');
  assert(blank.color === '#00aaff' && blank.on[3] === 102 && blank.off[3] === 0, 'Overlay color/alpha mismatch');
  await page.getByRole('combobox', {name:'C64 palette',exact:true}).selectOption('pepto');
  await page.getByRole('combobox', {name:'Virtual color mode',exact:true}).selectOption('talent');
  await page.getByRole('combobox', {name:'Virtual color mode',exact:true}).selectOption('computed');
  await page.locator('#image-input').setInputFiles(root + '/assets/images/c64-studio-background-layer.png');
  await page.waitForFunction(() => Boolean(unrestrictedPixels));
  assert(await page.evaluate(() => layerStack.active().type) === 'image', 'Opening image on marker must create image layer');
  await page.getByRole('combobox', {name:'Graphics format',exact:true}).selectOption('hires-2color');
  await page.getByRole('button', {name:'Select Tile markers 2',exact:true}).click();
  bounds = await page.locator('#canvas').boundingBox();
  const imageBefore = await page.locator('#canvas').evaluate(canvas => canvas.toDataURL());
  await drag(17, 8, 25, 8);
  assert(imageBefore === await page.locator('#canvas').evaluate(canvas => canvas.toDataURL()), 'Markers must not alter image pixels');
  const saveNative = async name => {
    const ready = page.waitForEvent('download');
    await page.getByRole('button',{name:'Save Hires',exact:true}).click();
    await (await ready).saveAs(root + '/output/playwright/' + name);
  };
  await saveNative('landing-marker-visible.art');
  await page.getByRole('button', {name:'Show Tile markers 2',exact:true}).click();
  assert(await page.locator('#tile-marker-overlay').isHidden(), 'Hidden marker must hide overlay');
  await saveNative('landing-marker-hidden.art');
  await page.getByRole('button', {name:'Show Tile markers 2',exact:true}).click();
  const expected = await page.evaluate(() => JSON.stringify(layerStack.active().markers));
  const ready = page.waitForEvent('download');
  await page.getByRole('button',{name:'Save project',exact:true}).click();
  const projectPath = root + '/output/playwright/landing-tile-marker-roundtrip.json';
  await (await ready).saveAs(projectPath);
  await page.reload();
  await page.locator('#project-input').setInputFiles(projectPath);
  await page.waitForFunction(() => layerStack.active().type === 'tile-markers');
  assert(await page.evaluate(() => JSON.stringify(layerStack.active().markers)) === expected,
    'Cold project open must preserve tile states and overlay color');
  assert(await page.locator('#tile-marker-color').inputValue() === '#00aaff', 'Restored color control mismatch');
  await page.screenshot({path:root + '/output/playwright/landing-tile-markers-desktop.png'});
  await page.getByRole('button',{name:'Duplicate layer',exact:true}).click();
  await page.getByRole('button',{name:'Move layer down',exact:true}).click();
  await page.getByRole('button',{name:'Move layer up',exact:true}).click();
  await page.getByRole('button',{name:'Delete layer',exact:true}).click();
  await page.getByRole('button',{name:'Select c64-studio-background-layer',exact:true}).click();
  assert(await page.evaluate(() => ["source-settings","adjustment-settings"].every(id=>!document.getElementById(id).hidden)), "Image settings must reappear after selecting image");
  const beforePan = await page.evaluate(() => ({x:sourcePositionX.valueAsNumber,y:sourcePositionY.valueAsNumber}));
  bounds = await page.locator('#canvas').boundingBox();
  await drag(20,12,22,13);
  const afterPan = await page.evaluate(() => ({x:sourcePositionX.valueAsNumber,y:sourcePositionY.valueAsNumber}));
  assert(beforePan.x !== afterPan.x && beforePan.y !== afterPan.y,'Image panning must still work');
  await page.getByRole('button',{name:'Select Tile markers 2',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:root + '/output/playwright/landing-tile-markers-mobile.png',fullPage:true});
  assert(errors.length === 0, 'Browser errors: ' + errors.join(', '));
  console.log(JSON.stringify({blank, restored:true, imagePixelsUnchanged:true, imagePan:true, errors}));
}
