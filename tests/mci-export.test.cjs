const assert = require('node:assert/strict');
const test = require('node:test');
const { ImageData, palette, bands, createContext, image, setPixel } = require('./fixtures/sprite-images.cjs');
const context = createContext(['fli.js', 'mci-export.js']);
const { encodeTruePaintMci } = context;

function fixture() {
  const backgroundColorIndex = 6;
  const available = palette.filter(color => color.index !== backgroundColorIndex).map(color => color.index);
  const result = {
    backgroundColorIndex,
    tileColors: new Uint8Array(1000),
    frames: Array.from({ length: 2 }, () => ({
      pixels: new ImageData(160, 200), rowColors: new Uint8Array(16000)
    }))
  };
  for (let tile = 0; tile < 1000; tile += 1) {
    result.tileColors[tile] = available[(tile + 4) % 15];
    for (let phase = 0; phase < 2; phase += 1) {
      const frame = result.frames[phase];
      const colors = [backgroundColorIndex, available[(tile + phase * 2) % 15],
        available[(tile + phase * 2 + 1) % 15], result.tileColors[tile]];
      for (let row = 0; row < 8; row += 1) {
        frame.rowColors.set(colors.slice(1, 3), tile * 16 + row * 2);
        for (let column = 0; column < 4; column += 1) {
          setPixel(frame.pixels, tile % 40 * 4 + column, Math.floor(tile / 40) * 8 + row,
            palette[colors[(tile + row + column + phase) % 4]].rgb);
        }
      }
    }
  }
  return result;
}

function decodeTruePaint(file, phase) {
  const loadAddress = file[0] | file[1] << 8;
  const at = address => file[2 + address - loadAddress];
  const decoded = new Uint8ClampedArray(160 * 200 * 4);
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 160; x += 1) {
      const tile = Math.floor(y / 8) * 40 + Math.floor(x / 4);
      const screen = at((phase === 0 ? 0x9c00 : 0xe000) + tile);
      const bits = at((phase === 0 ? 0xa000 : 0xc000) + tile * 8 + y % 8);
      const code = bits >> (6 - x % 4 * 2) & 3;
      const color = [at(0x9fe8), screen >> 4, screen & 15, at(0xe400 + tile) & 15][code];
      decoded.set([...palette[color].rgb, 255], (y * 160 + x) * 4);
    }
  }
  return decoded;
}

test('True Paint export preserves both phases in the native address layout with shared color RAM', () => {
  const result = fixture();
  const before = result.frames.map(frame => frame.pixels.data.slice());
  const file = encodeTruePaintMci(result, [...palette].reverse());
  assert.equal(file.length, 19434);
  assert.deepEqual(Array.from(file.slice(0, 2)), [0x00, 0x9c]);
  // Literal addresses and offsets follow the external True Paint format.
  for (const [offset, expected] of [
    [2, 0x01], [1001, 0xab], [1002, 6], [1026, 0x1b], [1033, 0xc6],
    [9218, 0x6c], [17410, 0x23], [18409, 0xcd], [18434, 4], [19433, 14]
  ]) assert.equal(file[offset], expected, `byte ${offset}`);
  assert.ok(file.slice(1003, 1026).every(value => value === 0));
  assert.ok(file.slice(9026, 9218).every(value => value === 0));
  assert.ok(file.slice(17218, 17410).every(value => value === 0));
  for (let phase = 0; phase < 2; phase += 1) {
    assert.deepEqual(decodeTruePaint(file, phase), result.frames[phase].pixels.data);
    assert.deepEqual(result.frames[phase].pixels.data, before[phase]);
  }
});

test('True Paint export retains the fitted composition when MCI must reduce each source phase palette', () => {
  const phases = [image(palette[6].rgb, 160), image(palette[6].rgb, 160)];
  phases.forEach((pixels, phase) => {
    for (let y = 0; y < 8; y += 1) {
      for (let x = 0; x < 4; x += 1) {
        setPixel(pixels, x, y, palette[(y * 4 + x + phase * 5) % 16].rgb);
      }
    }
    setPixel(pixels, 159, 199, palette[phase === 0 ? 13 : 2].rgb);
  });
  const result = context.optimizeMciImages(...phases, palette, bands, 6);
  const file = encodeTruePaintMci(result, palette);
  for (let phase = 0; phase < 2; phase += 1) {
    assert.notDeepEqual(result.frames[phase].pixels.data, phases[phase].data);
    assert.deepEqual(decodeTruePaint(file, phase), result.frames[phase].pixels.data);
  }
});

test('True Paint export rejects invalid geometry, palette values, pixels, and FLI-only color changes', () => {
  for (const [mutate, message] of [
    [result => { result.frames.pop(); }, /two fitted frames/],
    [result => { result.frames[0].pixels.width = 320; }, /160 × 200/],
    [result => { result.frames[1].pixels.data = new Uint8ClampedArray(4); }, /160 × 200/],
    [result => { result.backgroundColorIndex = 16; }, /two fitted frames/],
    [result => { result.tileColors = new Uint8Array(999); }, /shared tile colors/],
    [result => { result.tileColors[999] = 16; }, /tile colors/],
    [result => { result.frames[1].rowColors = new Uint8Array(2); }, /fitted row colors/],
    [result => { result.frames[0].rowColors[0] = 16; }, /row colors/],
    [result => { result.frames[1].rowColors[15999] = 16; }, /constant/],
    [result => { result.frames[0].rowColors[2] = 5; }, /constant/],
    [result => { result.frames[0].pixels.data[3] = 254; }, /opaque colors/],
    [result => { setPixel(result.frames[0].pixels, 0, 0, [12, 34, 56]); }, /opaque colors/],
    [result => { setPixel(result.frames[1].pixels, 159, 199, palette[5].rgb); }, /fitted colors/]
  ]) {
    const result = fixture();
    mutate(result);
    assert.throws(() => encodeTruePaintMci(result, palette), message);
  }
  for (const change of [
    colors => colors.pop(),
    colors => { colors[15] = { ...colors[15], index: 0 }; },
    colors => { colors[15] = { ...colors[15], rgb: colors[0].rgb }; },
    colors => { colors[15] = { ...colors[15], rgb: [256, 0, 0] }; }
  ]) {
    const colors = palette.map(color => ({ ...color }));
    change(colors);
    assert.throws(() => encodeTruePaintMci(fixture(), colors), /palette|unique C64/);
  }
});
