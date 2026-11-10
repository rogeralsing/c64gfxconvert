'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const common = require('../common.cjs'), wire = require('../container.cjs');
const fill = require('../fill.cjs').codecs[1];
const { makeMotion } = require('../player/motion.cjs');
const MIN_LENGTH = 4, MAX_LENGTH = 16, MAX_ENTRIES = 64, MAX_CANDIDATES = 256;
const edge = glyph => glyph !== 0 && glyph !== 15;
const key = sequence => Buffer.from(sequence).toString('hex');

function occurrences(screen, frame = 0) {
  const result = new Map();
  for (const vertical of [false, true]) {
    const step = vertical ? 40 : 1;
    for (let start = 0; start < 1000; start++) {
      if (!edge(screen[start])) continue;
      if ((vertical ? start >= 40 : start % 40 > 0) && edge(screen[start - step])) continue;
      const run = [];
      for (let cell = start; cell < 1000 && (vertical || Math.floor(cell / 40) === Math.floor(start / 40)) && edge(screen[cell]); cell += step) run.push(cell);
      for (let first = 0; first < run.length; first++) {
        const glyphs = [];
        for (let length = 1; length <= MAX_LENGTH && first + length <= run.length; length++) {
          glyphs.push(screen[run[first + length - 1]]);
          if (length < MIN_LENGTH) continue;
          const signature = key(glyphs);
          if (!result.has(signature)) result.set(signature, []);
          result.get(signature).push({ frame, start: run[first], vertical, length });
        }
      }
    }
  }
  return result;
}

function motifMatches(entry, source) {
  const result = [], seen = new Set();
  for (const reverse of [false, true]) {
    const sequence = reverse ? Uint8Array.from(entry).reverse() : entry;
    for (let phase = 0; phase <= entry.length - MIN_LENGTH; phase++) {
      for (const occurrence of source.get(key(sequence.subarray(phase))) || []) {
        const signature = `${occurrence.frame}/${occurrence.start}/${Number(occurrence.vertical)}/${occurrence.length}`;
        if (seen.has(signature)) continue;
        seen.add(signature);
        result.push({ ...occurrence, reverse, phase });
      }
    }
  }
  return result.sort((a, b) => b.length - a.length || a.frame - b.frame || a.start - b.start || Number(a.vertical) - Number(b.vertical));
}

function selectMatches(matches, covered) {
  const taken = new Set(), selected = [];
  let saved = 0;
  for (const match of matches) {
    const step = match.vertical ? 40 : 1;
    let available = true;
    for (let i = 0; i < match.length; i++) {
      const cell = match.start + i * step, global = match.frame * 1000 + cell;
      if (covered[global] || taken.has(global)) { available = false; break; }
    }
    if (!available) continue;
    for (let i = 0; i < match.length; i++) taken.add(match.frame * 1000 + match.start + i * step);
    selected.push(match);
    saved += match.length - 3;
  }
  return { selected, saved, frames: new Set(selected.map(match => match.frame)).size };
}

function buildDictionary(frames) {
  const source = new Map();
  frames.forEach((screen, frame) => {
    for (const [signature, matches] of occurrences(screen, frame)) {
      if (!source.has(signature)) source.set(signature, []);
      source.get(signature).push(...matches);
    }
  });
  const canonical = new Map();
  for (const signature of source.keys()) {
    const sequence = Uint8Array.from(Buffer.from(signature, 'hex')), reversed = key(Uint8Array.from(sequence).reverse());
    const name = signature < reversed ? signature : reversed;
    if (canonical.has(name)) continue;
    const entry = Uint8Array.from(Buffer.from(name, 'hex')), matches = motifMatches(entry, source);
    const proof = selectMatches(matches, new Uint8Array(frames.length * 1000));
    if (proof.frames >= 3 && proof.saved > entry.length + 1) canonical.set(name, { entry, matches, initialScore: proof.saved - entry.length - 1 });
  }
  const candidates = [...canonical.values()].sort((a, b) => b.initialScore - a.initialScore || b.entry.length - a.entry.length).slice(0, MAX_CANDIDATES);
  const covered = new Uint8Array(frames.length * 1000), entries = [], training = [];
  while (entries.length < MAX_ENTRIES) {
    let best = null;
    for (const candidate of candidates) {
      if (candidate.used) continue;
      const proposal = selectMatches(candidate.matches, covered);
      const score = proposal.saved - candidate.entry.length - 1;
      if (proposal.frames >= 3 && score > 0 && (!best || score > best.score)) best = { candidate, proposal, score };
    }
    if (!best) break;
    best.candidate.used = true;
    entries.push(best.candidate.entry);
    training.push({ frames: best.proposal.frames, occurrences: best.proposal.selected.length,
      grossSavedGlyphBytesMinusCommands: best.proposal.saved, entryBytes: best.candidate.entry.length + 1 });
    for (const match of best.proposal.selected) for (let i = 0; i < match.length; i++) covered[match.frame * 1000 + match.start + i * (match.vertical ? 40 : 1)] = 1;
  }
  return { entries, training, candidatesExamined: candidates.length, recurrentCandidateCount: canonical.size };
}

function createEdgeCodec(entries, indices = common.layouts.circle.indices) {
  assert(entries.length <= MAX_ENTRIES);
  const layout = new Set(indices), bytes = Math.ceil(indices.length / 8);
  return {
    name: 'edges-shared-hv-motifs', requiresLayout: 'circle',
    encode(screen) {
      assert.equal(screen.length, 1000);
      const source = occurrences(screen), matches = [];
      entries.forEach((entry, id) => matches.push(...motifMatches(entry, source).map(match => ({ ...match, id }))));
      matches.sort((a, b) => b.length - a.length || a.id - b.id || a.start - b.start);
      const selected = selectMatches(matches, new Uint8Array(1000)).selected;
      assert(selected.length <= 255);
      const covered = new Uint8Array(1000), commands = [];
      for (const match of selected) {
        const word = match.start | (Number(match.vertical) << 10) | (match.phase << 11);
        commands.push(word & 255, word >>> 8, match.id | (Number(match.reverse) << 6));
        for (let i = 0; i < match.length; i++) covered[match.start + i * (match.vertical ? 40 : 1)] = 1;
      }
      const mask = new Uint8Array(bytes), literals = [];
      indices.forEach((cell, i) => {
        if (edge(screen[cell]) && !covered[cell]) { mask[i >>> 3] |= 0x80 >>> (i & 7); literals.push(screen[cell]); }
      });
      for (let cell = 0; cell < 1000; cell++) if (edge(screen[cell])) assert(layout.has(cell), 'Edge lies outside circle layout');
      return wire.bytes([[selected.length], commands, mask, literals]);
    },
    decode(payload, output) {
      assert.equal(output.length, 1000);
      assert(payload.length >= 1 + bytes);
      const count = payload[0], owned = new Uint8Array(1000);
      let read = 1;
      assert(1 + count * 3 + bytes <= payload.length);
      for (let command = 0; command < count; command++) {
        const word = payload[read++] | (payload[read++] << 8), tag = payload[read++];
        assert(!(word & 0x8000) && !(tag & 0x80));
        const start = word & 1023, vertical = !!(word & 1024), phase = (word >>> 11) & 15;
        const entry = entries[tag & 63], reverse = !!(tag & 64);
        assert(entry && phase < entry.length);
        const length = entry.length - phase;
        assert(start + (length - 1) * (vertical ? 40 : 1) < 1000);
        if (!vertical) assert(start % 40 + length <= 40);
        for (let i = 0; i < length; i++) {
          const cell = start + i * (vertical ? 40 : 1), source = reverse ? entry.length - 1 - phase - i : phase + i;
          assert(layout.has(cell) && !owned[cell] && edge(entry[source]));
          owned[cell] = 1; output[cell] = entry[source];
        }
      }
      const mask = payload.subarray(read, read + bytes); read += bytes;
      indices.forEach((cell, i) => {
        if ((mask[i >>> 3] >>> (7 - (i & 7))) & 1) {
          assert(!owned[cell] && read < payload.length && edge(payload[read]));
          output[cell] = payload[read++]; owned[cell] = 1;
        }
      });
      assert.equal(read, payload.length);
      return output;
    }
  };
}

function serialize(frames, entries) {
  const edgeCodec = createEdgeCodec(entries), metadata = common.layouts.circle.metadata;
  const header = wire.bytes([Buffer.from('LM64'), [1, 40, 25], wire.word(frames.length), [2, 1, 0], metadata, [entries.length]]);
  const dictionary = wire.bytes(entries.flatMap(entry => [[entry.length], entry]));
  const packets = frames.map(screen => {
    const fp = fill.encode(screen, common.layouts.circle.indices), ep = edgeCodec.encode(screen);
    return { fill: fp, edge: ep };
  });
  const blob = wire.bytes([header, dictionary, ...packets.flatMap(packet => [wire.word(packet.fill.length), wire.word(packet.edge.length), packet.fill, packet.edge])]);
  return { blob, packets, sharedDictionaryBytes: 1 + dictionary.length };
}

function deserialize(blob) {
  assert.equal(blob.subarray(0, 4).toString(), 'LM64');
  assert.deepEqual([...blob.subarray(4, 7)], [1, 40, 25]);
  assert.deepEqual([...blob.subarray(9, 12)], [2, 1, 0]);
  const count = blob.readUInt16LE(7), parsed = wire.readLayout(blob, blob[9], 12);
  let read = parsed.read;
  const dictionaryCount = blob[read++], entries = [];
  assert(dictionaryCount <= MAX_ENTRIES);
  for (let i = 0; i < dictionaryCount; i++) {
    const length = blob[read++]; assert(length >= MIN_LENGTH && length <= MAX_LENGTH && read + length <= blob.length);
    const entry = Uint8Array.from(blob.subarray(read, read + length)); read += length;
    assert(entry.every(edge)); entries.push(entry);
  }
  const codec = createEdgeCodec(entries, parsed.indices), frames = [];
  for (let frame = 0; frame < count; frame++) {
    const fn = blob.readUInt16LE(read), en = blob.readUInt16LE(read + 2); read += 4;
    assert(read + fn + en <= blob.length);
    const bits = fill.decode(blob.subarray(read, read + fn), parsed.indices.length); read += fn;
    const output = common.expandFill(bits, parsed.indices);
    codec.decode(blob.subarray(read, read + en), output); read += en;
    frames.push(output);
  }
  assert.equal(read, blob.length);
  return { frames, entries };
}

function study() {
  const { frames, motion } = makeMotion(), dictionary = buildDictionary(frames);
  const proposed = serialize(frames, dictionary.entries), control = serialize(frames, []);
  const decoded = deserialize(proposed.blob);
  decoded.frames.forEach((screen, frame) => assert.deepEqual(screen, frames[frame], `Exact smooth frame ${frame}`));
  deserialize(control.blob).frames.forEach((screen, frame) => assert.deepEqual(screen, frames[frame]));
  const codec = createEdgeCodec(dictionary.entries), usage = dictionary.entries.map(() => ({ commands: 0, frames: new Set() }));
  let motifCells = 0, literalCells = 0, phaseCommands = 0, reversedCommands = 0;
  proposed.packets.forEach((packet, frame) => {
    const before = Uint8Array.from({ length: 1000 }, (_, i) => (37 * i + 123) & 255), output = before.slice();
    codec.decode(packet.edge, output);
    for (let cell = 0; cell < 1000; cell++) assert.equal(output[cell], edge(frames[frame][cell]) ? frames[frame][cell] : before[cell]);
    const commandCount = packet.edge[0]; let read = 1;
    for (let command = 0; command < commandCount; command++) {
      const word = packet.edge[read++] | (packet.edge[read++] << 8), tag = packet.edge[read++], id = tag & 63, phase = (word >>> 11) & 15;
      usage[id].commands++; usage[id].frames.add(frame);
      motifCells += dictionary.entries[id].length - phase;
      phaseCommands += Number(phase > 0); reversedCommands += Number(!!(tag & 64));
    }
    literalCells += packet.edge.length - 1 - commandCount * 3 - 60;
  });
  // Independent command bytes exercise both direction and nonzero phase,
  // including reversed motif order and a literal exception.
  const testEntry = Uint8Array.of(16, 17, 18, 19, 20, 21), testCodec = createEdgeCodec([testEntry]);
  const testMask = new Uint8Array(60), exception = common.layouts.circle.indices.indexOf(418);
  testMask[exception >>> 3] |= 0x80 >>> (exception & 7);
  const commandA = 408 | (2 << 11), commandB = 413 | 1024 | (1 << 11);
  const manual = wire.bytes([[2, commandA & 255, commandA >>> 8, 0, commandB & 255, commandB >>> 8, 64], testMask, [42]]);
  const before = new Uint8Array(1000).fill(33), manualOutput = before.slice();
  testCodec.decode(manual, manualOutput);
  const manualExpected = before.slice();
  for (const [cell, glyph] of [[408, 18], [409, 19], [410, 20], [411, 21], [413, 20], [453, 19], [493, 18], [533, 17], [573, 16], [418, 42]]) manualExpected[cell] = glyph;
  assert.deepEqual(manualOutput, manualExpected);
  const empty = new Uint8Array(1000), solid = new Uint8Array(1000), mixed = new Uint8Array(1000);
  for (const cell of common.layouts.circle.indices) solid[cell] = 15;
  for (let cell = 0; cell < 1000; cell++) if (manualExpected[cell] !== before[cell]) mixed[cell] = manualExpected[cell];
  const syntheticFrames = [empty, solid, mixed];
  deserialize(serialize(syntheticFrames, [testEntry]).blob).frames.forEach((screen, i) => assert.deepEqual(screen, syntheticFrames[i]));
  const report = { pass: true, motion, frames: frames.length, exactScreenBytesChecked: frames.length * 1000,
    overlayCellsChecked: frames.length * 1000, syntheticFramesChecked: syntheticFrames.length,
    manualPhaseReverseAndLiteralChecked: true, serializedBytes: proposed.blob.length,
    emptyDictionaryControlBytes: control.blob.length, bestIndependentHC64Bytes: 19096, bestPreviousImageHD64Bytes: 15169,
    differenceFromHC64Bytes: proposed.blob.length - 19096, differenceFromHD64Bytes: proposed.blob.length - 15169,
    dictionaryEntries: dictionary.entries.length, sharedDictionaryBytes: proposed.sharedDictionaryBytes,
    globalHeaderBytes: 12, layoutMetadataBytes: 50, frameHeaderBytes: 4,
    edgeCommandHeaderBytesPerFrame: 1, bytesPerCommand: 3, residualMaskBytesPerFrame: 60,
    fillPayloadBytes: proposed.packets.reduce((n, p) => n + p.fill.length, 0),
    edgePayloadBytes: proposed.packets.reduce((n, p) => n + p.edge.length, 0), motifCells, literalCells, phaseCommands, reversedCommands,
    dictionary: dictionary.entries.map((entry, id) => ({ id, glyphs: [...entry], bytes: entry.length + 1,
      actualCommands: usage[id].commands, actualFrames: usage[id].frames.size, training: dictionary.training[id] })),
    candidatesExamined: dictionary.candidatesExamined, recurrentCandidateCount: dictionary.recurrentCandidateCount,
    boundedSearch: { minimumLength: MIN_LENGTH, maximumLength: MAX_LENGTH, maximumEntries: MAX_ENTRIES, maximumCandidates: MAX_CANDIDATES, minimumTrainingFrames: 3 },
    packetBytes: proposed.packets.map(p => 4 + p.fill.length + p.edge.length),
    sha256: crypto.createHash('sha256').update(proposed.blob).digest('hex'),
    scope: 'Actual serialized shared H/V glyph motifs plus exact literal residuals and on/off fill. Host decoding only; no native timing.' };
  const output = path.join(__dirname, 'build'); fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'dictionary-lines.lm64'), proposed.blob);
  fs.writeFileSync(path.join(output, 'dictionary-report.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ ...report, dictionary: report.dictionary.map(({ glyphs, ...entry }) => entry), packetBytes: undefined }, null, 2));
  return report;
}

module.exports = { buildDictionary, createEdgeCodec, serialize, deserialize, study };
if (require.main === module) study();
