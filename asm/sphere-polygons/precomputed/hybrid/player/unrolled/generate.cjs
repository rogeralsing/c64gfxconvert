'use strict';
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const here = __dirname, output = path.join(here, 'build');
const source = fs.readFileSync(path.join(here, '../build/assets/checker-64.hc64'));
if (source.subarray(0, 4).toString() !== 'HC64' || source[4] !== 1 || source[5] !== 40 || source[6] !== 25 || source[9] !== 2 || source[10] !== 1 || source[11] !== 5) throw Error('Unsupported shared HC64 player asset');
const indices = [];
for (let row = 0; row < 25; row++) {
  const first = source[12 + row * 2], count = source[13 + row * 2];
  if (first + count > 40) throw Error('Invalid row metadata');
  for (let column = first; column < first + count; column++) indices.push(row * 40 + column);
}
if (indices.length !== 475) throw Error('Expected the declared 475-cell layout');
const frames = source.readUInt16LE(7);
const fillDecoder = require('../../fill.cjs').codecs.find(codec => codec.name === 'wildcard-packbits').decode;
let read = 62, maxGlyphs = 0, maxFillBytes = 0;
for (let frame = 0; frame < frames; frame++) {
  const fill = source.readUInt16LE(read), edge = source.readUInt16LE(read + 2);
  maxGlyphs = Math.max(maxGlyphs, edge - 60); maxFillBytes = Math.max(maxFillBytes, fill);
  if (edge < 60 || edge - 60 >= 256 || fill >= 256) throw Error('Asset exceeds byte-index bounds');
  fillDecoder(source.subarray(read + 4, read + 4 + fill), 475);
  let mappedGlyphs = 0;
  for (let cell = 0; cell < 475; cell++) mappedGlyphs += (source[read + 4 + fill + (cell >>> 3)] >>> (7 - (cell & 7))) & 1;
  if (mappedGlyphs !== edge - 60) throw Error('Edge-map count differs from glyph payload length');
  read += 4 + fill + edge;
}
if (read !== source.length || frames !== 64) throw Error('Invalid 64-frame asset length');
fs.mkdirSync(output, { recursive: true });
fs.writeFileSync(path.join(output, 'constants.asm'), `.const ACTIVE_CELLS = ${indices.length}\n.const FILL_BYTES = 60\n.const EDGE_MAP_BYTES = 60\n.const FIRST_FRAME_OFFSET = 62\n.const FRAME_COUNT = ${frames}\n`);
const tables = [];
for (let bit = 0; bit < 8; bit++) {
  tables.push(`fill_bit_${bit}:`);
  for (let first = 0; first < 256; first += 32) tables.push('    .byte ' + Array.from({ length: 32 }, (_, i) => ((first + i) & (128 >>> bit)) ? 15 : 0).join(','));
}
fs.writeFileSync(path.join(output, 'tables.asm'), tables.join('\n') + '\n');
const code = ['// Destinations come only from the HC64 row-span metadata; no frame glyph is embedded.'];
for (const [name, base] of [['a', 0x0400], ['b', 0x0c00]]) {
  code.push(`expand_${name}:`);
  for (let first = 0; first < indices.length; first += 8) {
    code.push(`    ldx fill_scratch+${first >>> 3}`);
    for (let bit = 0; bit < 8 && first + bit < indices.length; bit++) {
      const address = '$' + (base + indices[first + bit]).toString(16).padStart(4, '0');
      code.push(`    lda fill_bit_${bit},x`, `    sta ${address}`);
    }
  }
  code.push('    ldy #0');
  for (let first = 0; first < indices.length; first += 8) {
    code.push(`    ldx edge_scratch+${first >>> 3}`);
    for (let bit = 0; bit < 8 && first + bit < indices.length; bit++) {
      const address = '$' + (base + indices[first + bit]).toString(16).padStart(4, '0');
      code.push('    txa', `    and #${128 >>> bit}`, '    beq !skip+', '    lda (glyph_ptr),y', `    sta ${address}`, '    iny', '!skip:');
    }
  }
  code.push('    rts');
}
fs.writeFileSync(path.join(output, 'routines.asm'), code.join('\n') + '\n');
const report = { source: '../build/assets/checker-64.hc64', sourceBytes: source.length,
  sourceSha256: crypto.createHash('sha256').update(source).digest('hex'), frames, activeCells: indices.length,
  firstFrameOffset: 62, maxGlyphs, maxFillBytes, generatedFrom: '50-byte static row metadata only; mathematical 8x256 fill-bit LUTs',
  preparedFrameScreensOrPerFrameCode: false };
fs.writeFileSync(path.join(output, 'generation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));
