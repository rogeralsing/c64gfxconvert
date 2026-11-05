const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class ImageData {
  constructor(data, width, height) {
    if (typeof data === 'number') {
      this.width = data;
      this.height = width;
      this.data = new Uint8ClampedArray(data * width * 4);
    } else {
      this.data = data;
      this.width = width;
      this.height = height;
    }
  }
}
const context = vm.createContext({ ImageData, Uint8Array, Uint8ClampedArray, structuredClone });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../layers.js'), 'utf8'), context);
const { createC64LayerStack, compositeC64LayerPixels, compositeC64LayerSprites } = context;
const image = colors => new ImageData(Uint8ClampedArray.from(colors.flat()), colors.length, 1);

test('new and duplicated layers own independent settings while reusing the immutable image', () => {
  const defaults = { values: { brightness: 0 }, palette: { excludedIndices: [2] } };
  const stack = createC64LayerStack(defaults);
  const first = stack.active();
  first.image = { naturalWidth: 320, naturalHeight: 200 };
  stack.updateSettings({ values: { brightness: 30 }, palette: { excludedIndices: [2, 3] } });
  first.cache = { source: 'cached' };
  const copy = stack.duplicate();
  assert.equal(copy.image, first.image);
  assert.equal(copy.cache, null);
  copy.settings.palette.excludedIndices.push(4);
  copy.settings.values.brightness = -20;
  assert.equal(first.settings.values.brightness, 30);
  assert.deepEqual(Array.from(first.settings.palette.excludedIndices), [2, 3]);
  const blank = stack.add();
  assert.equal(blank.image, null);
  assert.equal(blank.settings.values.brightness, 0);
  assert.deepEqual(Array.from(blank.settings.palette.excludedIndices), [2]);
  assert.deepEqual(defaults, { values: { brightness: 0 }, palette: { excludedIndices: [2] } });
});

test('selection, ordering, deletion, and cache invalidation preserve the surviving layers', () => {
  const stack = createC64LayerStack({ values: { brightness: 0 } });
  const first = stack.active();
  const second = stack.add();
  const third = stack.add();
  stack.select(first.id);
  stack.move(1);
  assert.deepEqual(Array.from(stack.layers, layer => layer.id), [second.id, first.id, third.id]);
  assert.equal(stack.active(), first);
  stack.remove();
  assert.equal(stack.active(), third);
  assert.deepEqual(Array.from(stack.layers, layer => layer.id), [second.id, third.id]);
  for (const layer of stack.layers) layer.cache = { source: 'cached' };
  stack.invalidate();
  assert.ok(stack.layers.every(layer => layer.cache === null));
  stack.remove();
  stack.remove();
  assert.equal(stack.layers.length, 1);
  assert.equal(stack.active(), second);
  assert.throws(() => stack.select(999), /Unknown image layer/);
});

test('opening a project replaces layers with fresh identities and independent restored settings', () => {
  const stack = createC64LayerStack({ values: { brightness: 0 } });
  const previous = stack.active();
  previous.loadRequest = 1;
  const restored = [
    { name: 'Bottom', autoName: false, visible: false, image: { naturalWidth: 320 },
      fileName: 'bottom.png', sourceDataUrl: 'data:image/png;base64,AA==', settings: { values: { brightness: 40 } } },
    { name: 'Empty', autoName: true, settings: { values: { brightness: -10 } } }
  ];
  stack.replace(restored, 1);
  assert.equal(stack.layers.includes(previous), false);
  assert.equal(stack.active().name, 'Empty');
  assert.equal(stack.active().autoName, true);
  assert.ok(stack.layers.every(layer => layer.id > previous.id && layer.cache === null && layer.loadRequest === 0));
  assert.equal(stack.layers[0].visible, false);
  assert.equal(stack.layers[0].sourceDataUrl, restored[0].sourceDataUrl);
  restored[0].settings.values.brightness = 200;
  assert.equal(stack.layers[0].settings.values.brightness, 40);
  stack.select(stack.layers[0].id);
  assert.equal(stack.duplicate().sourceDataUrl, 'data:image/png;base64,AA==');
  assert.throws(() => stack.replace([], 0), /requires layers/);
  assert.equal(stack.layers.length, 3);
});

test('composition obeys paint order and straight alpha without modifying source layers', () => {
  const bottom = image([[0, 0, 255, 255], [0, 0, 255, 128], [12, 34, 56, 255]]);
  const top = image([[255, 0, 0, 255], [255, 0, 0, 128], [250, 240, 230, 0]]);
  const before = bottom.data.slice();
  const result = compositeC64LayerPixels([bottom, top], 3, 1);
  assert.deepEqual(Array.from(result.data), [255, 0, 0, 255, 170, 0, 85, 192, 12, 34, 56, 255]);
  assert.deepEqual(bottom.data, before);
  const reversed = compositeC64LayerPixels([top, bottom], 3, 1);
  assert.deepEqual(Array.from(reversed.data.subarray(0, 4)), [0, 0, 255, 255]);
});

test('single-layer and empty composites preserve hidden RGB, transparency, and dimensions', () => {
  const original = image([[11, 22, 33, 0], [44, 55, 66, 127]]);
  const result = compositeC64LayerPixels([original], 2, 1);
  assert.deepEqual(result.data, original.data);
  result.data[0] = 250;
  assert.equal(original.data[0], 11);
  assert.deepEqual(Array.from(compositeC64LayerPixels([], 2, 1).data), [0, 0, 0, 0, 0, 0, 0, 0]);
  assert.throws(() => compositeC64LayerPixels([original], 3, 1), /matching positive dimensions/);
});

test('foreground image coverage occludes lower sprite masks while transparent holes expose them', () => {
  const lower = new ImageData(320, 200);
  const upper = new ImageData(320, 200);
  const lowerMask = new Uint8Array(64000);
  const upperMask = new Uint8Array(64000);
  for (let x = 112; x <= 116; x++) lower.data[x * 4 + 3] = 255;
  lowerMask.fill(1, 112, 116);
  upper.data[112 * 4 + 3] = 128;
  upper.data[113 * 4 + 3] = 128;
  upper.data[114 * 4 + 3] = 255;
  upper.data[116 * 4 + 3] = 255;
  upperMask[116] = 1;
  const result = compositeC64LayerSprites([{ source: lower, mask: lowerMask }, { source: upper, mask: upperMask }], 1, [255, 255, 255]);
  assert.deepEqual(Array.from(result.spriteMask.subarray(112, 117)), [0, 1, 0, 1, 1]);
  assert.equal(result.spritePixelCount, 3);
  assert.deepEqual(Array.from(result.spritePixels.data.subarray(113 * 4, 114 * 4)), [255, 255, 255, 255]);
  assert.deepEqual(Array.from(lowerMask.subarray(112, 116)), [1, 1, 1, 1]);
  const single = compositeC64LayerSprites([{ source: upper, mask: upperMask }], 1, [255, 255, 255]);
  assert.deepEqual(single.spriteMask, upperMask);
});
