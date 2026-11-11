'use strict';

// Embed two consecutive native character screens and their actual font.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  const option = process.argv[i];
  assert(['--input', '--output', '--frame'].includes(option), 'Unknown option: ' + option);
  assert(process.argv[i + 1], 'Missing value: ' + option);
  options[option] = process.argv[i + 1];
}
const input = path.resolve(options['--input'] || path.join(__dirname, '../build/three-scene-dithered-star/characters'));
const output = path.resolve(options['--output'] || path.join(input, '../frame-diff.html'));
const metadata = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json')));
const screens = fs.readFileSync(path.join(input, 'reference.frames'));
const font = fs.readFileSync(path.join(input, 'font.bin'));
const first = Number(options['--frame'] || 1);
assert(Number.isInteger(first) && first >= 0 && first + 1 < metadata.frameCount, 'Choose a frame with a following image.');
assert.equal(metadata.frameBytes, 1000);
assert.equal(screens.length, metadata.frameCount * 1000);
assert.equal(font.length, 2048);
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
assert.equal(hash(screens), metadata.hashes.screens);
assert.equal(hash(font), metadata.hashes.font);
const frames = [first, first + 1].map(index => Array.from(screens.subarray(index * 1000, (index + 1) * 1000)));
const popcount = byte => byte.toString(2).replaceAll('0', '').length;
const changed = [];
let added = 0, cleared = 0, replaced = 0, changedPixels = 0;
for (let position = 0; position < 1000; position++) {
  const before = frames[0][position], after = frames[1][position];
  if (before === after) continue;
  let pixels = 0;
  for (let row = 0; row < 8; row++) pixels += popcount(font[before * 8 + row] ^ font[after * 8 + row]);
  changed.push({position, x: position % 40, y: Math.floor(position / 40), before, after, pixels});
  changedPixels += pixels;
  if (before === metadata.emptyGlyph) added++;
  else if (after === metadata.emptyGlyph) cleared++;
  else replaced++;
}
const data = {title: metadata.title, width: 40, height: 25, frameIndices: [first, first + 1],
  fps: metadata.fps, frames, font: Array.from(font), changed,
  statistics: {changed: changed.length, unchanged: 1000 - changed.length, added, cleared, replaced, changedPixels},
  hashes: {screens: hash(screens), font: hash(font), frames: frames.map(frame => hash(Buffer.from(frame)))}};
const template = fs.readFileSync(path.join(__dirname, 'frame-diff-template.html'), 'utf8');
assert.equal(template.split('__FRAME_DIFF_DATA__').length, 2);
fs.mkdirSync(path.dirname(output), {recursive: true});
fs.writeFileSync(output, template.replace('__FRAME_DIFF_DATA__', JSON.stringify(data).replaceAll('<', '\\u003c')));
console.log(JSON.stringify({output, frames: data.frameIndices, ...data.statistics, hashes: data.hashes}, null, 2));
