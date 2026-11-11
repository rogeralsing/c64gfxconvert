'use strict';

// Host-only study: exact independently compressed rows, then row deltas with
// periodic independent keys. Existing movie/player/font files are read-only.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

const HERE = __dirname;
const REFERENCE_SHA = '5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c';
const FONT_SHA = '1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1';
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

// Packet tag's high2 bits identify the type; low6 bits encode count-1.
// Independent rows: 00zero,01literal,10repeat (11 invalid).
// Delta rows:       00copy previous row,01literal,10repeat,11zero.
function encodeRow(row, previous, independent) {
  const dp = new Array(41);
  dp[40] = {bytes: 0, packets: 0};
  for (let x = 39; x >= 0; x--) {
    let best = null;
    const consider = (count, tag, payload) => {
      const candidate = {bytes: 1 + payload.length + dp[x + count].bytes,
        packets: 1 + dp[x + count].packets, count, tag, payload};
      if (!best || candidate.bytes < best.bytes ||
          candidate.bytes === best.bytes && candidate.packets < best.packets) best = candidate;
    };
    let zero = true, same = true, repeat = true;
    for (let count = 1; count <= 40 - x; count++) {
      zero &&= row[x + count - 1] === 0;
      same &&= row[x + count - 1] === previous[x + count - 1];
      repeat &&= row[x + count - 1] === row[x];
      if (independent && zero) consider(count, 0, Buffer.alloc(0));
      if (!independent && same) consider(count, 0, Buffer.alloc(0));
      if (!independent && zero) consider(count, 3, Buffer.alloc(0));
      if (repeat) consider(count, 2, Buffer.from([row[x]]));
      consider(count, 1, row.subarray(x, x + count));
    }
    dp[x] = best;
  }
  const chunks = [], counts = [0, 0, 0, 0];
  for (let x = 0; x < 40;) {
    const packet = dp[x];
    chunks.push(Buffer.from([(packet.tag << 6) | (packet.count - 1)]), packet.payload);
    counts[packet.tag]++;
    x += packet.count;
  }
  const data = Buffer.concat(chunks);
  assert.equal(data.length, dp[0].bytes);
  return {data, counts};
}

function skipRow(stream, offset, independent) {
  let x = 0;
  while (x < 40) {
    assert(offset < stream.length);
    const token = stream[offset++], tag = token >> 6, count = (token & 63) + 1;
    assert(x + count <= 40);
    assert(!independent || tag !== 3);
    offset += tag === 1 ? count : tag === 2 ? 1 : 0;
    assert(offset <= stream.length);
    x += count;
  }
  return offset;
}

function decodeRow(stream, offset, previous, independent) {
  const row = independent ? Buffer.alloc(40) : Buffer.from(previous);
  let x = 0;
  while (x < 40) {
    assert(offset < stream.length);
    const token = stream[offset++], tag = token >> 6, count = (token & 63) + 1;
    assert(x + count <= 40);
    assert(!independent || tag !== 3);
    if (tag === 1) {
      assert(offset + count <= stream.length);
      stream.copy(row, x, offset, offset + count);
      offset += count;
    } else if (tag === 2) {
      assert(offset < stream.length);
      row.fill(stream[offset++], x, x + count);
    } else if (tag === 3 || independent) row.fill(0, x, x + count);
    x += count;
  }
  return {row, end: offset};
}

function proveForwardWave(folder, packets, schedule, reference) {
  const chunks = [], bases = [];
  let bytes = 0;
  for (let row = 0; row < 25; row++) {
    bases.push(bytes);
    for (let frame = 1; frame < 97; frame++) {
      const packet = packets[(frame - 1) * 25 + row];
      chunks.push(packet);
      bytes += packet.length;
    }
  }
  const baseTable = Buffer.alloc(50);
  bases.forEach((offset, row) => baseTable.writeUInt16LE(offset, row * 2));
  fs.writeFileSync(path.join(folder, 'row-major.bin'), Buffer.concat(chunks));
  fs.writeFileSync(path.join(folder, 'row-stream-bases16.bin'), baseTable);
  const stream = fs.readFileSync(path.join(folder, 'row-major.bin'));
  const actualBases = fs.readFileSync(path.join(folder, 'row-stream-bases16.bin'));
  const actualSchedule = fs.readFileSync(path.join(folder, 'schedule.bin'));
  assert(actualSchedule.equals(schedule));
  const period = actualSchedule[0], firstKey = actualSchedule[1];
  const key = frame => period === 0 || (frame - firstKey) % period === 0;
  const cursor = Array.from({length: 25}, (_, row) => actualBases.readUInt16LE(row * 2));
  const rowPhase = new Uint8Array(25);
  const absoluteTime = new Array(25).fill(0); // Proof oracle only, not proposed runtime state.
  const screen = Buffer.alloc(1000), advanceHistogram = [0, 0, 0];
  let rowRecordsDecoded = 0, rowLoopResets = 0;
  const digest = crypto.createHash('sha256');
  for (let serial = 0; serial < 290; serial++) {
    const wavePhase = serial % 96;
    for (let row = 0; row < 25; row++) {
      const age = Math.round(4.5 + 4.5 * Math.sin(2 * Math.PI * (row / 24 + wavePhase / 96)));
      const targetTime = Math.max(0, serial - age);
      const advances = targetTime - absoluteTime[row];
      assert(advances >= 0 && advances <= 2, 'Wave must be forward-only with at most2 row records per image.');
      advanceHistogram[advances]++;
      for (let step = 0; step < advances; step++) {
        let next = rowPhase[row] + 1;
        if (next === 97) {
          next = 1;
          cursor[row] = actualBases.readUInt16LE(row * 2);
          rowLoopResets++;
        }
        const decoded = decodeRow(stream, cursor[row], screen.subarray(row * 40, (row + 1) * 40), key(next));
        decoded.row.copy(screen, row * 40);
        cursor[row] = decoded.end;
        rowPhase[row] = next;
        absoluteTime[row]++;
        rowRecordsDecoded++;
      }
      const pose = targetTime === 0 ? 0 : 1 + (targetTime - 1) % 96;
      assert.equal(rowPhase[row], pose);
      assert(screen.subarray(row * 40, (row + 1) * 40).equals(
        reference.subarray(pose * 1000 + row * 40, pose * 1000 + (row + 1) * 40)));
    }
    digest.update(screen);
  }
  return {passed: true, packetPayloadBytes: stream.length,
    rowStreamBaseBytes: actualBases.length, scheduleBytes: actualSchedule.length,
    forwardWaveStoredBytes: stream.length + actualBases.length + actualSchedule.length,
    framePointerBytes: 0, directRowIndexBytes: 0,
    compositesVerified: 290, rowSelectionsVerified: 7250,
    rowRecordsDecoded, rowLoopResets, advanceHistogram,
    maximumRowRecordsPerOutputRow: 2, imageHistoriesStoredInRam: 0,
    runtimeRowCursorBytes: 50, runtimeRowPhaseBytes: 25,
    runtimeRowStateBytes: 75, liveOutputCharacterCells: 1000,
    c64ScreenAllocationBytes: 1024, fontBytes: 2048,
    knownSubtotalWithAllocatedScreen: stream.length + actualBases.length + actualSchedule.length + 75 + 1024 + 2048,
    memoryScope: 'Measured stream/base/schedule plus conceptual75-byte cursor/phase state and one1024-byte output screen. Native player, global state, ZP and sine/LUT code are unbuilt; separate Color RAM not included. No native RAM/FPS claim.',
    seekScope: 'This path supports the measured forward monotonic wave. Arbitrary backward jumps still require key seeking or a separate random-access index.',
    hashes: {rowMajor: sha(stream), rowStreamBases16: sha(actualBases), compositeStream: digest.digest('hex')}
  };
}

function proveTemporalHolds(folder, packets, schedule, reference) {
  assert.equal(schedule[0], 96);
  const chunks = [], bases = [];
  let bytes = 0, heldFrames = 0, holdRuns = 0, holdMarkerBytes = 0;
  for (let row = 0; row < 25; row++) {
    bases.push(bytes);
    for (let frame = 1; frame <= 96;) {
      const current = reference.subarray(frame * 1000 + row * 40, frame * 1000 + (row + 1) * 40);
      const previous = reference.subarray((frame - 1) * 1000 + row * 40, (frame - 1) * 1000 + (row + 1) * 40);
      if (frame > 1 && current.equals(previous)) {
        let count = 1;
        while (frame + count <= 96) {
          const next = reference.subarray((frame + count) * 1000 + row * 40, (frame + count) * 1000 + (row + 1) * 40);
          if (!next.equals(current)) break;
          count++;
        }
        for (let offset = 0; offset < count; offset++) assert(
          packets[(frame + offset - 1) * 25 + row].equals(Buffer.from([0x27])));
        const token = count === 1 ? Buffer.from([0x27]) : count <= 24 ?
          Buffer.from([0x28 + count - 2]) : Buffer.from([0x3f, count]);
        chunks.push(token); bytes += token.length;
        heldFrames += count; holdRuns++; holdMarkerBytes += token.length;
        frame += count;
      } else {
        const packet = packets[(frame - 1) * 25 + row];
        chunks.push(packet); bytes += packet.length;
        frame++;
      }
    }
  }
  const baseTable = Buffer.alloc(50);
  bases.forEach((offset, row) => baseTable.writeUInt16LE(offset, row * 2));
  fs.writeFileSync(path.join(folder, 'row-major-holds.bin'), Buffer.concat(chunks));
  fs.writeFileSync(path.join(folder, 'row-stream-bases16-holds.bin'), baseTable);
  const stream = fs.readFileSync(path.join(folder, 'row-major-holds.bin'));
  const actualBases = fs.readFileSync(path.join(folder, 'row-stream-bases16-holds.bin'));
  const makeMachine = () => {
    const screen = Buffer.alloc(1000);
    const cursor = Array.from({length: 25}, (_, row) => actualBases.readUInt16LE(row * 2));
    const phase = new Uint8Array(25), pending = new Uint8Array(25);
    let virtualRows = 0, rowRecordReads = 0, loops = 0, keysAfterOld96 = 0;
    const advance = row => {
      let next = phase[row] + 1;
      if (next === 97) {
        assert.equal(pending[row], 0, 'Hold must not cross the independent loop key.');
        next = 1; cursor[row] = actualBases.readUInt16LE(row * 2); loops++;
        keysAfterOld96++;
      }
      if (pending[row]) pending[row]--;
      else {
        const token = stream[cursor[row]];
        if (token >= 0x28 && token <= 0x3f) {
          assert(next > 1, 'First independent key must never be encoded as a hold.');
          cursor[row]++;
          const count = token === 0x3f ? stream[cursor[row]++] : token - 0x28 + 2;
          assert(count >= 2 && (token !== 0x3f || count >= 25));
          assert(next + count - 1 <= 96);
          pending[row] = count - 1;
        } else {
          const decoded = decodeRow(stream, cursor[row], screen.subarray(row * 40, (row + 1) * 40), next === 1);
          decoded.row.copy(screen, row * 40);
          cursor[row] = decoded.end;
        }
        rowRecordReads++;
      }
      phase[row] = next; virtualRows++;
      // Check EVERY virtual step, including an intermediate key1 in a2-step
      // update. This catches old96 pixels left behind in key1's empty margins.
      assert(screen.subarray(row * 40, (row + 1) * 40).equals(
        reference.subarray(next * 1000 + row * 40, next * 1000 + (row + 1) * 40)));
    };
    return {screen, phase, advance, stats: () => ({virtualRows, rowRecordReads, loops, keysAfterOld96})};
  };
  const sequential = makeMachine();
  for (let serial = 1; serial <= 289; serial++) for (let row = 0; row < 25; row++) sequential.advance(row);
  const wave = makeMachine(), time = new Array(25).fill(0), advanceHistogram = [0, 0, 0];
  const digest = crypto.createHash('sha256');
  let wrapKey1Then2Events = 0;
  for (let serial = 0; serial < 290; serial++) {
    const phase = serial % 96;
    for (let row = 0; row < 25; row++) {
      const age = Math.round(4.5 + 4.5 * Math.sin(2 * Math.PI * (row / 24 + phase / 96)));
      const target = Math.max(0, serial - age), advances = target - time[row];
      assert(advances >= 0 && advances <= 2);
      advanceHistogram[advances]++;
      if (advances === 2 && wave.phase[row] === 96) wrapKey1Then2Events++;
      for (let step = 0; step < advances; step++) wave.advance(row);
      time[row] = target;
      const pose = target === 0 ? 0 : 1 + (target - 1) % 96;
      assert.equal(wave.phase[row], pose);
      assert(wave.screen.subarray(row * 40, (row + 1) * 40).equals(
        reference.subarray(pose * 1000 + row * 40, pose * 1000 + (row + 1) * 40)));
    }
    digest.update(wave.screen);
  }
  const packetBytesBefore = packets.reduce((sum, packet) => sum + packet.length, 0);
  return {passed: true, scope: 'OnlyK96 row-major temporal holds; no native implementation.',
    markerAbi: 'Between row records:27=copy40/hold1;28..3e=hold2..24;3f,next8=hold25..255. Keys are never folded. Holds never cross the row stream or independent key.',
    packetBytesBefore, packetPayloadBytes: stream.length,
    savedPacketBytes: packetBytesBefore - stream.length,
    heldFrames, holdRuns, holdMarkerBytes, rowStreamBaseBytes: 50, scheduleBytes: 4,
    forwardWaveStoredBytes: stream.length + 54,
    runtimeRowCursorBytes: 50, runtimeRowPhaseBytes: 25, runtimePendingHoldBytes: 25,
    runtimeRowStateBytes: 100, liveOutputCharacterCells: 1000,
    c64ScreenAllocationBytes: 1024, fontBytes: 2048,
    knownSubtotalWithAllocatedScreen: stream.length + 54 + 100 + 1024 + 2048,
    sequentialVirtualRowsVerified: sequential.stats().virtualRows,
    sequentialRowLoopResetsVerified: sequential.stats().loops,
    everyIntermediateStepCompared: true, key1MarginsAfterOld96Verified: true,
    compositesVerified: 290, waveAdvanceHistogram: advanceHistogram,
    wrapKey1Then2Events, wave: wave.stats(),
    memoryScope: 'Serialized data/base/schedule are measured. Row state100B and one1024B screen are conceptual allocations; native code, global state, ZP and sine/LUTs are unbuilt. No native FPS/total-RAM claim.',
    hashes: {rowMajorHolds: sha(stream), rowStreamBases16: sha(actualBases), compositeStream: digest.digest('hex')}
  };
}

function main(argv = process.argv.slice(2)) {
  const option = (name, fallback) => {
    const i = argv.indexOf(`--${name}`);
    return i < 0 ? fallback : argv[i + 1];
  };
  const input = path.resolve(option('input', path.join(HERE, 'three-scene/results/flagship-star-ten-buffer')));
  const output = path.resolve(option('output', path.join(HERE, 'build/row-packets-study')));
  const reference = fs.readFileSync(path.join(input, 'reference.frames'));
  const font = fs.readFileSync(path.join(input, 'font.bin'));
  assert.equal(sha(reference), REFERENCE_SHA);
  assert.equal(sha(font), FONT_SHA);
  assert.equal(reference.length, 97000);
  assert.equal(font.length, 2048);
  assert(reference.subarray(0, 1000).every(code => code === 0));
  fs.mkdirSync(output, {recursive: true});
  const variants = [];
  for (const period of [0, 4, 8, 16, 32, 96]) {
    const name = period === 0 ? 'independent' : `delta-key-${period}`;
    const folder = path.join(output, name);
    fs.mkdirSync(folder, {recursive: true});
    const isKey = frame => frame > 0 && (period === 0 || (frame - 1) % period === 0);
    const frameOffsets = new Array(97).fill(0xffff);
    const rowOffsets = new Array(97 * 25).fill(0xffff);
    const chunks = [], frameRecords = [{frame: 0, implicitBlank: true, bytes: 0, key: false}];
    const independentPackets = [0, 0, 0, 0], deltaPackets = [0, 0, 0, 0];
    let bytes = 0;
    for (let frame = 1; frame < 97; frame++) {
      const start = bytes, independent = isKey(frame);
      frameOffsets[frame] = bytes;
      for (let row = 0; row < 25; row++) {
        rowOffsets[frame * 25 + row] = bytes;
        const current = reference.subarray(frame * 1000 + row * 40, frame * 1000 + (row + 1) * 40);
        const previous = reference.subarray((frame - 1) * 1000 + row * 40, (frame - 1) * 1000 + (row + 1) * 40);
        const encoded = encodeRow(current, previous, independent);
        chunks.push(encoded.data);
        encoded.counts.forEach((count, tag) => {(independent ? independentPackets : deltaPackets)[tag] += count;});
        bytes += encoded.data.length;
      }
      frameRecords.push({frame, key: independent, implicitBlank: false, bytes: bytes - start});
    }
    const stream = Buffer.concat(chunks);
    assert.equal(stream.length, bytes);
    assert(bytes < 0xffff);
    const frameIndex = Buffer.alloc(194), directIndex = Buffer.alloc(4850);
    frameOffsets.forEach((offset, i) => frameIndex.writeUInt16LE(offset, i * 2));
    rowOffsets.forEach((offset, i) => directIndex.writeUInt16LE(offset, i * 2));
    // These four actual serialized bytes define the entire key/mode/loop
    // schedule. K0 means all independent; first key1 makes loop reset exact.
    const schedule = Buffer.from([period, 1, 1, 96]);
    for (const [file, data] of Object.entries({'rows.bin': stream,
      'frame-offsets16.bin': frameIndex, 'row-offsets16.bin': directIndex,
      'schedule.bin': schedule, 'font.bin': font})) fs.writeFileSync(path.join(folder, file), data);
    // Decode bytes from disk, not the encoder's temporary packet objects.
    const actual = fs.readFileSync(path.join(folder, 'rows.bin'));
    const frameTable = fs.readFileSync(path.join(folder, 'frame-offsets16.bin'));
    const directTable = fs.readFileSync(path.join(folder, 'row-offsets16.bin'));
    const actualSchedule = fs.readFileSync(path.join(folder, 'schedule.bin'));
    const actualPeriod = actualSchedule[0], firstKey = actualSchedule[1];
    assert.equal(actualSchedule[2], 1); assert.equal(actualSchedule[3], 96);
    const actualKey = frame => frame >= firstKey && (actualPeriod === 0 || (frame - firstKey) % actualPeriod === 0);
    const rowPointer = (frame, row, direct) => {
      if (frame === 0) return 0xffff;
      if (direct) return directTable.readUInt16LE((frame * 25 + row) * 2);
      let offset = frameTable.readUInt16LE(frame * 2);
      for (let y = 0; y < row; y++) offset = skipRow(actual, offset, actualKey(frame));
      return offset;
    };
    let randomDecodedRows = 0, chainRows = 0, maximumChainRows = 0;
    const fetchRow = (frame, row, direct) => {
      if (frame === 0) return Buffer.alloc(40);
      const key = actualPeriod === 0 ? frame : firstKey + Math.floor((frame - firstKey) / actualPeriod) * actualPeriod;
      let current = Buffer.alloc(40), chain = 0;
      for (let pose = key; pose <= frame; pose++) {
        const offset = rowPointer(pose, row, direct);
        const decoded = decodeRow(actual, offset, current, actualKey(pose));
        assert.equal(decoded.end, skipRow(actual, offset, actualKey(pose)));
        current = decoded.row;
        chain++;
      }
      chainRows += chain; maximumChainRows = Math.max(maximumChainRows, chain);
      return current;
    };
    for (let frame = 0; frame < 97; frame++) {
      let cursor = frame === 0 ? 0xffff : frameTable.readUInt16LE(frame * 2);
      for (let row = 0; row < 25; row++) {
        const expected = reference.subarray(frame * 1000 + row * 40, frame * 1000 + (row + 1) * 40);
        assert.equal(rowPointer(frame, row, true), cursor);
        assert(fetchRow(frame, row, true).equals(expected));
        assert(fetchRow(frame, row, false).equals(expected));
        if (frame) cursor = skipRow(actual, cursor, actualKey(frame));
        randomDecodedRows++;
      }
      if (frame) assert.equal(cursor, frame < 96 ? frameTable.readUInt16LE((frame + 1) * 2) : actual.length);
    }
    // Reset straight to independent frame1 after frame96, three times. The
    // final1 certifies the third closing transition without storing a patch.
    const playback = [0, ...Array.from({length: 288}, (_, i) => 1 + i % 96), 1];
    let current = Buffer.alloc(1000);
    for (const frame of playback) {
      if (frame === 0) current.fill(0);
      else for (let row = 0; row < 25; row++) {
        const decoded = decodeRow(actual, rowPointer(frame, row, true),
          current.subarray(row * 40, (row + 1) * 40), actualKey(frame));
        decoded.row.copy(current, row * 40);
      }
      assert(current.equals(reference.subarray(frame * 1000, (frame + 1) * 1000)));
    }
    assert(fs.readFileSync(path.join(folder, 'font.bin')).equals(font));
    const forwardWave = proveForwardWave(folder, chunks, actualSchedule, reference);
    assert.equal(forwardWave.packetPayloadBytes, actual.length);
    const sizes = frameRecords.map(record => record.bytes);
    const variant = {
      name, keyPeriod: period || null, storedSourceFrames: 97, implicitBlankFrame: 0,
      encodedFrames: 96, encodedRows: 2400,
      keyFrames: frameRecords.filter(record => record.key).map(record => record.frame),
      independentKeyRows: frameRecords.filter(record => record.key).length * 25,
      deltaRows: frameRecords.filter(record => !record.key && !record.implicitBlank).length * 25,
      packetPayloadBytes: actual.length, modeBytesPerRow: 0, scheduleBytes: actualSchedule.length,
      loopClosingBytes: 0, loopReset: 'Frame1 is an independent key; decode it directly after96. No delta closing patch or additional reset state.',
      framePointerBytes: frameTable.length, directRowPointerBytes: directTable.length,
      sequentialWithFramePointersBytes: actual.length + actualSchedule.length + frameTable.length,
      directRowAccessBytes: actual.length + actualSchedule.length + directTable.length,
      fontBytes: font.length,
      meanPacketBytesPerSourceFrame: actual.length / 97,
      meanPacketBytesPerEncodedFrame: actual.length / 96,
      minimumFramePacketBytes: Math.min(...sizes), maximumFramePacketBytes: Math.max(...sizes),
      independentPackets, deltaPackets, frameRecords,
      access: {rowBytes: 40, maximumRowDecodesFromNearestKey: maximumChainRows,
        meanRowDecodesFromNearestKey: chainRows / (2400 * 2),
        note: 'Direct indexes locate encoded rows; delta rows still need decoding from their nearest independent key. Frame pointers require scanning up to25 self-delimiting packets rows for each requested frame.'},
      runtimeConcept: {rowDecodeScratchBytes: 40, optionalTenHistoryRowPointerCacheBytes: 500,
        note: 'One40-byte decoded-row scratch can reconstruct a selected row. A500-byte encoded-row pointer cache speeds location, but does not remove delta dependencies. Native code, total RAM and FPS are unbuilt.'},
      proof: {passed: true, randomAccessRowsVerified: randomDecodedRows,
        directAndFrameScanBothExact: true, playbackFramesVerified: playback.length,
        loopClosingTransitionsVerified: 3, fontUnchanged: true},
      hashes: {rows: sha(actual), schedule: sha(actualSchedule), framePointers: sha(frameTable), rowPointers: sha(directTable), font: sha(font)}
    };
    variant.forwardWave = forwardWave;
    if (period === 96) variant.temporalHolds = proveTemporalHolds(folder, chunks, actualSchedule, reference);
    fs.writeFileSync(path.join(folder, 'study.json'), JSON.stringify(variant, null, 2) + '\n');
    variants.push(variant);
  }
  const result = {passed: true, input, output,
    format: {screenColumns: 40, screenRows: 25, countBits: 6, countBias: 1,
      independentTags: ['zero', 'literal', 'repeat', 'invalid'],
      deltaTags: ['copyPreviousFrameSameRowCells', 'literal', 'repeat', 'zero'],
      rowTermination: 'Decoded width reaches exactly40 cells; no outer x/length header.',
      frameZero: 'Implicit blank; frame/row index containsffff sentinel. No row packet data stored.',
      schedule: 'Four serialized bytes: keyPeriod8(0=allIndependent),firstKeyFrame8=1,loopStart8=1,loopFrameCount8=96.',
      modeSelection: 'Derived from serialized schedule and source frame index; no omitted per-row mode byte.'},
    sourceHashes: {reference: sha(reference), font: sha(font), script: sha(fs.readFileSync(__filename))},
    memoryScope: 'Only measured serialized packet data, schedule and alternative indexes plus unchanged font. Native decoder, image buffers, row cache, row selection sine/LUTs and ZP are not built. No FPS or native total-RAM claim.',
    variants};
  fs.writeFileSync(path.join(output, 'study.json'), JSON.stringify(result, null, 2) + '\n');
  const lines = ['# Independent row packets and periodic row deltas', '',
    'Host-only exact format study. Each40-cell row is self-delimiting by decoded width.',
    'One-byte tag/count: top2 type bits, low6 count-1. Literals append raw bytes; repeat appends one glyph.',
    'Independent rows use zero/literal/repeat. Delta rows use copy-previous/literal/repeat/zero.', '',
    '| Variant | Packet bytes | Schedule | Total with194B frame pointers | Total with4850B direct index | Forward wave with50B stream bases | Max random row chain |',
    '|---|---:|---:|---:|---:|---:|---:|'];
  for (const v of variants) lines.push(`| ${v.name} | ${v.packetPayloadBytes} | ${v.scheduleBytes} | ${v.sequentialWithFramePointersBytes} | ${v.directRowAccessBytes} | ${v.forwardWave.forwardWaveStoredBytes} | ${v.access.maximumRowDecodesFromNearestKey} |`);
  const holds = variants.at(-1).temporalHolds;
  lines.push('', `K96 temporal holds: ${holds.packetPayloadBytes} packet bytes +50 row-stream bases +4 schedule =${holds.forwardWaveStoredBytes} stored bytes.`,
    `This saves${holds.savedPacketBytes} packet bytes while adding25 pending-hold bytes (100B total row state).`,
    `Known data/font/one-screen/row-state subtotal:${holds.knownSubtotalWithAllocatedScreen}B before unbuilt native/global/sine/ZP costs.`,
    'The hold stream passes290 wave composites plus every virtual row step in three sequential loops and resets.',
    'Key1 always decodes independently over old96, clearing empty margins; two-step updates check key1 before patch2.');
  lines.push('', 'Index columns are alternatives. Add2048 bytes for the unchanged font.',
    'Frame0 is implicit blank. All modes/keys/loop behavior are defined by the actual4-byte schedule file.',
    'Frame1 is always independent, so96→1 needs no closing delta. All97 source frames remain addressable.',
    'Every frame and every row roundtrips through both index styles, including nearest-key reconstruction,',
    'plus three loop-closing transitions in sequential playback. No native player or emulator was used.', '',
    'Runtime concepts only:40-byte decoded-row scratch; optionally500 bytes for ten sets of25 encoded-row pointers.',
    'The pointer cache does not remove delta dependency chains. Decoder/sine code, buffers, native RAM and FPS are unmeasured.', '',
    'A separately serialized forward path stores25 row-major streams (frames1..96 each) and only50 bytes of stream bases.',
    'The tested sine advances each output row by0..2 source frames per image, so deltas update that row directly.',
    'All290 composite images match independently selected source rows. This path needs no stored frame/direct-row index,',
    'no full image histories and no500-byte history-pointer cache. Proposed per-row state is50 cursor bytes +25 phase bytes.',
    'The output has1000 character cells (1024-byte C64 screen allocation). Global state/decoder/sine/ZP remain unbuilt.',
    'A backward/random-time effect still needs key seeking; this forward-only access contract is deliberately separate.', '',
    'Reproduce: `rtk proxy node asm/sphere-polygons/font-v2/study-row-packets.cjs`', '');
  fs.writeFileSync(path.join(output, 'README.md'), lines.join('\n'));
  console.log(JSON.stringify({passed: true, output, variants: variants.map(v => ({name: v.name,
    packets: v.packetPayloadBytes, schedule: v.scheduleBytes,
    frameIndexTotal: v.sequentialWithFramePointersBytes, directRowIndexTotal: v.directRowAccessBytes,
    forwardWaveBytes: v.forwardWave.forwardWaveStoredBytes,
    ...(v.temporalHolds ? {temporalHoldForwardWaveBytes: v.temporalHolds.forwardWaveStoredBytes,
      temporalHoldPacketSavings: v.temporalHolds.savedPacketBytes} : {}),
    maxRowChain: v.access.maximumRowDecodesFromNearestKey}))}, null, 2));
  return result;
}

module.exports = {main};
if (require.main === module) main();
