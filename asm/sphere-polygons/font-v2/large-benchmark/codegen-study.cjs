'use strict';

// Character-update grouping and actual 6502 drawing routines. Only the offline
// representation changes; all decoders must reproduce the same screen codes.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const {encodeSparse, decodeSparse, maxPrefix, summary, sha, ARENA_START, ARENA_END} = require('./delta-study.cjs');

const HERE = __dirname;
const OUT = path.join(HERE, 'build/codegen');
const SCREEN = 1000;
const FRAMES = 384;
const PY65 = '/tmp/disco-sid-analysis-py65';

function changed(previous, target) {
  const cells = [];
  for (let cell = 0; cell < SCREEN; cell++) if (previous[cell] !== target[cell]) cells.push({cell, glyph: target[cell]});
  return cells;
}

function pageGroups(previous, target) {
  return Array.from({length: 4}, (_, page) => {
    const groups = new Map();
    for (let offset = 0; offset < Math.min(256, SCREEN - page * 256); offset++) {
      const cell = page * 256 + offset;
      if (previous[cell] === target[cell]) continue;
      const glyph = target[cell];
      if (!groups.has(glyph)) groups.set(glyph, []);
      groups.get(glyph).push(offset);
    }
    return Array.from(groups, ([glyph, offsets]) => ({glyph, offsets})).sort((a, b) => a.glyph - b.glyph);
  });
}

function encodeGroups(previous, target, hybrid = false) {
  const bytes = [];
  for (const page of pageGroups(previous, target)) {
    const groups = hybrid ? page.filter(group => group.offsets.length >= 3) : page;
    const singles = hybrid ? page.filter(group => group.offsets.length < 3).flatMap(group => group.offsets.map(offset => [offset, group.glyph])) : [];
    assert(groups.length <= 255 && singles.length <= 255);
    bytes.push(groups.length);
    if (hybrid) bytes.push(singles.length);
    for (const group of groups) {
      assert(group.offsets.length <= 255);
      bytes.push(group.glyph, group.offsets.length, ...group.offsets);
    }
    for (const [offset, glyph] of singles.sort((a, b) => a[0] - b[0])) bytes.push(offset, glyph);
  }
  return Buffer.from(bytes);
}

function decodeGroups(payload, previous, hybrid = false) {
  const result = Buffer.from(previous);
  let cursor = 0;
  for (let page = 0; page < 4; page++) {
    const groups = payload[cursor++], singles = hybrid ? payload[cursor++] : 0;
    for (let group = 0; group < groups; group++) {
      const glyph = payload[cursor++], count = payload[cursor++];
      for (let index = 0; index < count; index++) result[page * 256 + payload[cursor++]] = glyph;
    }
    for (let index = 0; index < singles; index++) {
      const offset = payload[cursor++], glyph = payload[cursor++];
      result[page * 256 + offset] = glyph;
    }
  }
  assert.equal(cursor, payload.length);
  return result;
}

function generateCode(previous, target, grouped = false) {
  const cells = changed(previous, target);
  if (grouped) cells.sort((a, b) => a.glyph - b.glyph || a.cell - b.cell);
  const code = [];
  let accumulator;
  for (const {cell, glyph} of cells) {
    if (glyph !== accumulator) { code.push(0xa9, glyph); accumulator = glyph; }
    const address = 0x0400 + cell;
    code.push(0x8d, address & 255, address >>> 8);
  }
  code.push(0x60);
  return Buffer.from(code);
}

function decodeCode(code, previous) {
  // Bytecode contract checked here; real assembled execution is additionally
  // checked through py65 below, including the actual RTS stack operation.
  const result = Buffer.from(previous);
  let cursor = 0, accumulator;
  while (cursor < code.length) {
    const opcode = code[cursor++];
    if (opcode === 0xa9) accumulator = code[cursor++];
    else if (opcode === 0x8d) {
      const address = code[cursor++] | code[cursor++] << 8;
      assert(address >= 0x0400 && address < 0x0400 + SCREEN);
      assert.notEqual(accumulator, undefined);
      result[address - 0x0400] = accumulator;
    } else if (opcode === 0x60) { assert.equal(cursor, code.length); return result; }
    else throw new Error('Unexpected generated opcode: ' + opcode);
  }
  throw new Error('Generated routine has no RTS');
}

const PYTHON_VERIFY = `#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
from py65.devices.mpu6502 import MPU

here=Path(__file__).resolve().parent
report={'pass':False,'engine':'py65.devices.mpu6502.MPU','cases':[],'scope':'Actual 6502 instruction execution; no VIC stalls or raster waits, so not an FPS result.'}
for dataset in ('analytic','geometry','protected4'):
    directory=here/dataset
    frames=(directory/'reference.frames').read_bytes()
    for variant in ('ordered','grouped'):
        code=(directory/(variant+'.bin')).read_bytes()
        index=json.loads((directory/(variant+'-index.json')).read_text())
        cpu=MPU()
        cycles=[]
        for pose,record in enumerate(index):
            previous=frames[pose*1000:(pose+1)*1000]
            target_pose=(pose+1)%384
            target=frames[target_pose*1000:(target_pose+1)*1000]
            routine=code[record['offset']:record['offset']+record['bytes']]
            cpu.memory[0x0400:0x07e8]=previous
            cpu.memory[0x3000:0x3000+len(routine)]=routine
            cpu.memory[0x01fe]=0xff
            cpu.memory[0x01ff]=0x0f
            cpu.pc=0x3000
            cpu.sp=0xfd
            cpu.a=0x5a
            cpu.x=0x73
            cpu.y=0xb7
            before=cpu.processorCycles
            steps=0
            while cpu.pc!=0x1000:
                cpu.step()
                steps+=1
                if steps>5000: raise AssertionError((dataset,variant,pose,'runaway routine'))
            actual=bytes(cpu.memory[0x0400:0x07e8])
            if actual!=target: raise AssertionError((dataset,variant,pose,'screen mismatch'))
            if cpu.x!=0x73 or cpu.y!=0xb7 or cpu.sp!=0xff: raise AssertionError('Unexpected register/stack effects')
            cycles.append(cpu.processorCycles-before)
        report['cases'].append({'dataset':dataset,'variant':variant,'transitionsVerified':len(index),'codeSha256':hashlib.sha256(code).hexdigest(),'instructionCycles':{'min':min(cycles),'mean':sum(cycles)/len(cycles),'max':max(cycles)}})
report['pass']=True
(here/'py65-proof.json').write_text(json.dumps(report,indent=2)+'\\n')
print(json.dumps(report))
`;

function main() {
  fs.mkdirSync(OUT, {recursive: true});
  const inputs = {
    analytic: path.join(HERE, '../c64-preview/build/movie.frames'),
    geometry: path.join(HERE, 'build/geometry/frames.screen'),
    protected4: path.join(HERE, 'build/lossy/analytic/threshold-4-protect-solids/reference.frames')
  };
  const cases = [];
  const font = fs.readFileSync(path.join(HERE, '../c64-preview/build/font.bin'));
  for (const [dataset, input] of Object.entries(inputs)) {
    const directory = path.join(OUT, dataset);
    fs.mkdirSync(directory, {recursive: true});
    const raw = fs.readFileSync(input);
    assert.equal(raw.length, FRAMES * SCREEN);
    const frames = Array.from({length: FRAMES}, (_, pose) => raw.subarray(pose * SCREEN, (pose + 1) * SCREEN));
    const encoded = {sparse: [], 'page-groups': [], hybrid: [], ordered: [], grouped: []};
    const updates = [], glyphGroups = [], orderedLoads = [];
    for (let pose = 0; pose < FRAMES; pose++) {
      const previous = frames[pose], target = frames[(pose + 1) % FRAMES];
      const sparse = encodeSparse(target, previous);
      assert(decodeSparse(sparse, previous).equals(target));
      encoded.sparse.push(sparse);
      for (const hybrid of [false, true]) {
        const payload = encodeGroups(previous, target, hybrid);
        assert(decodeGroups(payload, previous, hybrid).equals(target));
        encoded[hybrid ? 'hybrid' : 'page-groups'].push(payload);
      }
      for (const grouped of [false, true]) {
        const code = generateCode(previous, target, grouped);
        assert(decodeCode(code, previous).equals(target));
        encoded[grouped ? 'grouped' : 'ordered'].push(code);
      }
      const cells = changed(previous, target);
      updates.push(cells.length);
      glyphGroups.push(new Set(cells.map(cell => cell.glyph)).size);
      orderedLoads.push(cells.reduce((count, cell, i) => count + (i === 0 || cell.glyph !== cells[i - 1].glyph), 0));
    }
    fs.writeFileSync(path.join(directory, 'reference.frames'), raw);
    fs.writeFileSync(path.join(directory, 'font.bin'), font);
    const formats = {};
    for (const [name, payloads] of Object.entries(encoded)) {
      let offset = 0;
      const index = payloads.map((payload, pose) => {
        const record = {pose, targetPose: (pose + 1) % FRAMES, offset, bytes: payload.length}; offset += payload.length; return record;
      });
      const all = Buffer.concat(payloads);
      fs.writeFileSync(path.join(directory, name + '.bin'), all);
      fs.writeFileSync(path.join(directory, name + '-index.json'), JSON.stringify(index));
      formats[name] = {cyclicPayloadBytes: offset, payloadBytes: summary(payloads.map(payload => payload.length)),
        maximumPrefix: maxPrefix(payloads), cyclicPointerBytesOutsideArena: FRAMES * 2,
        sourceSha256: sha(all), nativeTimingMeasured: false};
    }
    const row = {dataset, frames: FRAMES, targetSourceSha256: sha(raw), fontSha256: sha(font),
      arena: {start: ARENA_START, endExclusive: ARENA_END, bytes: ARENA_END - ARENA_START},
      firstImageBytesOutsideArena: SCREEN, framePointerBytesOutsideArena: FRAMES * 2,
      changedCells: summary(updates), glyphGroups: summary(glyphGroups), orderedAccumulatorLoads: summary(orderedLoads),
      formats};
    fs.writeFileSync(path.join(directory, 'study.json'), JSON.stringify(row, null, 2) + '\n');
    cases.push(row);
    console.log(JSON.stringify({dataset, formats: Object.fromEntries(Object.entries(formats).map(([name, value]) =>
      [name, {bytes: value.cyclicPayloadBytes, frames: value.maximumPrefix.frames}]))}));
  }
  const report = {pass: true, scope: 'All formats encode identical character updates. Byte counts include actual headers/opcodes and RTS; pointer tables and raw first screen are outside the fixed arena. No native FPS claim from code size or py65 instruction cycles.',
    formats: {
      sparse: 'Four pages: count8, then count (offset8,glyph8) pairs.',
      'page-groups': 'Four pages: groupCount8, then groups (glyph8,count8,offset8[count]). Four frame header bytes.',
      hybrid: 'Four pages: groupCount8,pairCount8, then groups with >=3 offsets (glyph8,count8,offsets...), then single pairs (offset8,glyph8). Eight frame header bytes.',
      ordered: 'Actual 6502 routine: A9 glyph when accumulator value changes, then 8D absolute screen address per changed cell, ascending cell order; final60 RTS.',
      grouped: 'Actual 6502 routine: group updates by glyph, A9 glyph once per group, 8D absolute address per changed cell; final60 RTS. Store order differs from raster order.'
    }, cases};
  fs.writeFileSync(path.join(OUT, 'summary.json'), JSON.stringify(report, null, 2) + '\n');
  fs.writeFileSync(path.join(OUT, 'verify-codegen.py'), PYTHON_VERIFY);
  const verified = spawnSync('rtk', ['proxy', 'env', `PYTHONPATH=${PY65}`, 'python3', path.join(OUT, 'verify-codegen.py')], {cwd: HERE, encoding: 'utf8'});
  if (verified.status !== 0) throw new Error(verified.stderr || verified.stdout || 'py65 verification failed');
  report.py65Proof = JSON.parse(fs.readFileSync(path.join(OUT, 'py65-proof.json')));
  assert(report.py65Proof.pass && report.py65Proof.cases.every(row => row.transitionsVerified === FRAMES));
  fs.writeFileSync(path.join(OUT, 'summary.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({py65Pass: true, actualRoutinesExecuted: FRAMES * 2 * cases.length}));
  return report;
}

module.exports = {changed, pageGroups, encodeGroups, decodeGroups, generateCode, decodeCode, main};
if (require.main === module) main();
