const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../source-crop.js'), 'utf8'), context);
const { cloneSourceCrop } = context;

test('source-relative crop masks keep independent editable vertices, including concave and crossing polygons', () => {
  assert.equal(cloneSourceCrop(), null);
  assert.equal(cloneSourceCrop(null), null);
  const masks = [
    { mode: 'rectangle', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }] },
    { mode: 'rectangle', points: [{ x: 0.1, y: 0.2 }, { x: 0.8, y: 0.2 }, { x: 0.8, y: 0.7 }, { x: 0.1, y: 0.7 }] },
    { mode: 'polygon', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 0.4, y: 0.4 }, { x: 1, y: 1 }, { x: 0, y: 1 }] },
    { mode: 'polygon', points: [{ x: 0, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }, { x: 1, y: 0 }] }
  ];
  for (const mask of masks) {
    const original = structuredClone(mask);
    const copied = cloneSourceCrop(mask);
    assert.deepEqual(JSON.parse(JSON.stringify(copied)), mask);
    copied.points[0].x = 0.3;
    copied.points.push({ x: 0.2, y: 0.2 });
    assert.deepEqual(mask, original);
  }
});

test('rejects invalid crop geometry and coordinates before accepting a new mask', () => {
  const rectangle = [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }];
  const polygon = points => ({ mode: 'polygon', points });
  for (const crop of [
    false, true, 0, 'crop', [], {},
    { mode: 'other', points: rectangle },
    polygon(null), polygon([]), polygon(rectangle.slice(0, 2)),
    polygon([...rectangle, rectangle[0]]),
    polygon([rectangle[0], rectangle[0], rectangle[2]]),
    polygon([{ x: 0, y: 0 }, { x: 0.5, y: 0.5 }, { x: 1, y: 1 }]),
    polygon(Array.from({ length: 257 }, (_, index) => ({ x: index / 257, y: index % 2 }))),
    ...[NaN, Infinity, -Infinity, -0.1, 1.01, '0.5', null, undefined].map(x =>
      polygon([{ x, y: 0 }, rectangle[1], rectangle[2]])),
    { mode: 'rectangle', points: rectangle.slice(0, 3) },
    { mode: 'rectangle', points: [...rectangle].reverse() },
    { mode: 'rectangle', points: [rectangle[0], { x: 1, y: 0.2 }, rectangle[2], rectangle[3]] }
  ]) assert.throws(() => cloneSourceCrop(crop), /[Cc]rop|[Rr]ectangle/);
});
