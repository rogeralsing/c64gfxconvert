'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const crypto = require('node:crypto');
const here = __dirname;
const input = path.join(here, 'build/huffman-study/current');
const output = path.join(here, 'build/huffman-native');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function main() {
  fs.mkdirSync(output, {recursive: true});
  const codes = JSON.parse(fs.readFileSync(path.join(input, 'codes.json')));
  const lengths = fs.readFileSync(path.join(input, 'prefix-length.bin'));
  const values = Buffer.from(fs.readFileSync(path.join(input, 'prefix-value.bin')));
  const secondaryValues = Buffer.alloc(256), secondaryLengths = Buffer.alloc(256);
  let fallbackPrefixes = 0;
  for (let prefix = 0; prefix < 256; prefix++) {
    if (lengths[prefix]) continue;
    const base = fallbackPrefixes++ * 4;
    assert(base + 3 < 256, 'Secondary lookup requires more than one page');
    values[prefix] = base;
    for (let suffix = 0; suffix < 4; suffix++) {
      const lookahead = prefix * 4 + suffix;
      const match = codes.find(code => code.length > 8 && code.length <= 10 && code.code === lookahead >>> (10 - code.length));
      assert(match, 'Incomplete10-bit codebook');
      secondaryValues[base + suffix] = match.symbol;
      secondaryLengths[base + suffix] = match.length - 8;
    }
  }
  const compressed = fs.readFileSync(path.join(input, 'compressed.bin'));
  const index = JSON.parse(fs.readFileSync(path.join(input, 'frames-index.json')));
  fs.writeFileSync(path.join(output, 'prefix-value.bin'), values);
  fs.writeFileSync(path.join(output, 'prefix-length.bin'), lengths);
  fs.writeFileSync(path.join(output, 'secondary-value.bin'), secondaryValues);
  fs.writeFileSync(path.join(output, 'secondary-length.bin'), secondaryLengths);
  fs.writeFileSync(path.join(output, 'first-frame.bin'), compressed.subarray(index[0].offset, index[0].offset + index[0].bytes));
  const font = fs.readFileSync(path.join(here, 'build/font4-dedupe/font.bin'));
  fs.writeFileSync(path.join(output, 'font.bin'), font);
  const assembler = process.env.KICKASS || '/Users/rogerjohansson/.local/bin/kickass';
  const build = spawnSync('rtk', ['proxy', assembler, 'huffman-decoder.asm', '-odir', output, '-o', path.join(output, 'decoder.prg'), '-symbolfile', '-vicesymbols'], {cwd: here, stdio: 'inherit'});
  if (build.status !== 0) throw new Error('KickAssembler failed');
  const symbols = fs.readFileSync(path.join(output, 'huffman-decoder.sym'), 'utf8');
  const labels = Object.fromEntries([...symbols.matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g)].map(match => [match[1], parseInt(match[2], 16)]));
  const manifest = {pass: true, decoder: '8-bit prefix lookup plus2-bit secondary lookup; eight alignment states',
    lookupTableBytes: 5120, codeAndStateBytes: labels.decoder_code_end - labels.start,
    fontBytes: font.length, fallbackPrefixes, maximumCodeBits: Math.max(...codes.map(code => code.length)),
    programSha256: sha(fs.readFileSync(path.join(output, 'decoder.prg'))), compressedSha256: sha(compressed),
    programBytes: fs.statSync(path.join(output, 'decoder.prg')).size,
    sourceAddress: 0x7000, outputAddress: 0x3000,
    scope: 'Huffman decoding into hidden RAM only. No delta application or disk-loader CPU is included.'};
  fs.writeFileSync(path.join(output, 'build.json'), JSON.stringify(manifest, null, 2) + '\n');
  console.log(JSON.stringify(manifest, null, 2));
  return manifest;
}

if (require.main === module) main();
module.exports = {main};
