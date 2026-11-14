const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../tile-markers.js'), 'utf8'), context);

function editorFixture(display = { width: 320, height: 200 }) {
  class Canvas extends EventTarget {
    captured = new Set();
    getBoundingClientRect() { return { left: 20, top: 10, right: 660, bottom: 410, width: 640, height: 400 }; }
    setPointerCapture(id) { this.captured.add(id); }
    hasPointerCapture(id) { return this.captured.has(id); }
    releasePointerCapture(id) { this.captured.delete(id); }
  }
  const canvas = new Canvas();
  const layer = { type: 'tile-markers', visible: true, markers: { color: '#ffcc00', tiles: Array(1000).fill(0) } };
  const stack = { layers: [layer], active: () => stack.layers[0] };
  const editor = context.createC64TileMarkerEditor({ canvas, overlay: {}, stack, getDisplaySize: () => display,
    onChange() {} });
  function pointer(type, x, y, props = {}) {
    const event = new Event(type, { cancelable: true });
    Object.assign(event, { clientX: 20 + x * 640 / display.width, clientY: 10 + y * 400 / display.height,
      pointerId: 1, button: 0, isPrimary: true, ...props });
    canvas.dispatchEvent(event);
    return event;
  }
  return { canvas, layer, stack, editor, pointer };
}

test('drag strokes fill skipped tiles and keep one on/off value when revisiting cells', () => {
  const { layer, pointer } = editorFixture();
  pointer('pointerdown', 1, 1);
  pointer('pointermove', 33, 1);
  pointer('pointermove', 9, 1);
  pointer('pointerup', 9, 1);
  assert.deepEqual(layer.markers.tiles.slice(0, 6), [1, 1, 1, 1, 1, 0]);
  pointer('pointerdown', 17, 1);
  pointer('pointermove', 33, 1);
  pointer('pointerup', 33, 1);
  assert.deepEqual(layer.markers.tiles.slice(0, 6), [1, 1, 0, 0, 0, 0]);
});

test('outside movement does not paint borders or connect a line across reentry', () => {
  const { layer, pointer, canvas } = editorFixture();
  pointer('pointerdown', 1, 1);
  pointer('pointermove', -20, 25);
  pointer('pointermove', 25, 25);
  pointer('pointercancel', 25, 25);
  pointer('pointermove', 80, 25);
  assert.deepEqual(layer.markers.tiles.flatMap((value, index) => value ? [index] : []), [0, 123]);
  assert.equal(canvas.hasPointerCapture(1), false);
});

test('hidden layers, other pointers, and cancelled strokes cannot change tile annotations', () => {
  const { layer, pointer, editor, canvas } = editorFixture();
  layer.visible = false;
  pointer('pointerdown', 1, 1);
  layer.visible = true;
  pointer('pointerdown', 1, 1, { button: 2 });
  pointer('pointerdown', 1, 1, { isPrimary: false });
  assert.equal(layer.markers.tiles.some(Boolean), false);
  const start = pointer('pointerdown', 319, 199);
  assert.equal(start.defaultPrevented, true);
  pointer('pointermove', 1, 1, { pointerId: 2 });
  editor.finish();
  pointer('pointermove', 1, 1);
  assert.equal(canvas.hasPointerCapture(1), false);
  assert.equal(layer.markers.tiles[999], 1);
  assert.equal(layer.markers.tiles.filter(Boolean).length, 1);
});

test('tile hit testing stays eight display pixels wide when the preview shows a smaller sprite grid', () => {
  const { layer, pointer } = editorFixture({ width: 48, height: 42 });
  pointer('pointerdown', 17, 9);
  pointer('pointerup', 17, 9);
  assert.equal(layer.markers.tiles[42], 1);
  assert.equal(layer.markers.tiles.filter(Boolean).length, 1);
});
