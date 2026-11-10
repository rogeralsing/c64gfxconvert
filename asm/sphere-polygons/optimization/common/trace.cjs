'use strict';
// Frozen full-render outputs, not precomputed delta inputs for the kernels.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const base = path.resolve(__dirname, '../..');
const { createModel } = require(path.join(base, 'native-model.cjs'));
const frames = Number(process.argv[2] || 64);
if (!Number.isInteger(frames) || frames < 4 || frames > 256) throw Error('Frames must be 4..256.');
const model = createModel(), cases = [];
function add(group, mesh, yaw, pitch, roll) {
  const f = model.frame(mesh, yaw, pitch, roll), bytes = a => Buffer.from(a).toString('base64');
  cases.push({ id: cases.length, group, model: mesh, yaw, pitch, roll,
    projectedX: bytes(f.geometry.projectedX), projectedY: bytes(f.geometry.projectedY),
    coverage: bytes(f.coverage), screen: bytes(f.screen) });
}
for (const mesh of [0, 1]) for (let i = 0; i < frames; i++) add(`animation-${mesh}`, mesh, (2*i)&255, (24+i)&255, i&255);
for (const mesh of [0, 1]) {
  for (const pose of [[0,0,0],[0,0,0],[0,0,64],[37,61,93],[37,61,93],[255,255,255],[128,64,192],[0,24,0]]) add('jumps-pauses', mesh, ...pose);
  for (const [dy,dp,dr] of [[2,0,0],[0,1,0],[0,0,1]]) for (let i=0;i<4;i++) add('single-axis', mesh, (37+dy*i)&255,(61+dp*i)&255,(93+dr*i)&255);
}
for (let i=0;i<8;i++) add('model-switch', i&1, 37,61,93);
const inputs = Object.fromEntries(['main.asm','raster.asm','geometry.asm','geometry.cjs','native-model.cjs','assets/font.bin','assets/glyph-lut.bin'].map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(base,name))).digest('hex')]));
process.stdout.write(JSON.stringify({ frames, scope:'Live projected geometry and frozen full-render output; native kernels must construct all spans themselves.', inputs, cases }));
