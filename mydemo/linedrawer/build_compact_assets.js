"use strict";

const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

require("../../linefont-viewer/join-study-data.js");
const { frame } = require("../../linefont-viewer/join-study-model.js");
const { evaluate, trainAdditive } = require("../../linefont-viewer/join-study-palette.js");
const data = globalThis.JOIN_STUDY_DATA;

const poseCount = 256;
const dynamicSlots = 22;

function chooseFixedMasks() {
  const training = Object.keys(data.shapes).flatMap(shape =>
    Array.from({ length: poseCount / 2 }, (_, n) => frame(data, shape, 2 * n)));
  const shown = new Set();
  for (const pose of training) {
    for (const mask of pose.masks) shown.add(mask);
  }
  const lineMasks = data.bank.filter(mask => shown.has(mask));
  const joinMasks = trainAdditive(lineMasks, training, 255 - lineMasks.length - dynamicSlots);
  return { lineMasks, joinMasks };
}

// The native bitmap expands each logical pixel to a 2×2 block.
function encodeCharset(fixedMasks) {
  const charset = Buffer.alloc(256 * 8);
  for (const [code, mask] of fixedMasks.entries()) {
    for (let y = 0; y < 4; y++) {
      let row = 0;
      for (let x = 0; x < 4; x++) {
        if (mask & (1 << (4 * y + x))) row |= 0xc0 >> (2 * x);
      }
      charset[code * 8 + y * 2] = row;
      charset[code * 8 + y * 2 + 1] = row;
    }
  }
  return charset;
}

// Each high byte selects an ascending list of the supported low bytes.
// The directory offsets address parallel key and screen-code arrays.
function encodeLookup(mapping, codeByMask) {
  const offsetsLo = Buffer.alloc(256);
  const offsetsHi = Buffer.alloc(256);
  const lengths = Buffer.alloc(256);
  const keys = [];
  const codes = [];
  for (let high = 0; high < 256; high++) {
    const start = keys.length;
    offsetsLo[high] = start & 255;
    offsetsHi[high] = start >> 8;
    for (let low = 0; low < 256; low++) {
      const code = codeByMask.get(mapping[256 * high + low]);
      if (!code) continue;
      keys.push(low);
      codes.push(code);
    }
    const length = keys.length - start;
    assert(length <= 255, "Compact lookup bucket exceeds one byte");
    lengths[high] = length;
  }
  return { offsetsLo, offsetsHi, lengths, keys, codes };
}

// Split the high-byte buckets on bit 7 of the low byte. This lets two
// groups with shorter probe ranges share a 4 KiB lookup without aliasing.
function encodeDisplacedLookup(lookup, mapping, codeByMask) {
  const slots = 4096;
  const slotMask = slots - 1;
  const directorySize = 512;
  const probeWidth = 128;
  const codes = Buffer.alloc(slots - 6); // Leave the interrupt vectors free.
  const tags = Buffer.alloc(slots);
  const occupied = new Uint8Array(slots);
  occupied.fill(1, codes.length);
  const groups = Array.from({ length: directorySize }, (_, index) => ({
    index,
    entries: [],
    offset: undefined,
  }));

  for (let high = 0; high < 256; high++) {
    const start = lookup.offsetsLo[high] | (lookup.offsetsHi[high] << 8);
    const end = start + lookup.lengths[high];
    for (let index = start; index < end; index++) {
      const low = lookup.keys[index];
      groups[high + ((low >> 7) * 256)].entries.push([low & 127, lookup.codes[index]]);
    }
  }

  const slotAt = (offset, key) => (offset + key) & slotMask;
  const reaches = (offset, slot) => ((slot - offset) & slotMask) < probeWidth;
  const ordered = [...groups].sort((a, b) => b.entries.length - a.entries.length || a.index - b.index);
  for (const group of ordered) {
    const mate = groups[group.index ^ 256];
    for (let offset = 0; offset < slots; offset++) {
      if (group.entries.some(([key]) => occupied[slotAt(offset, key)])) continue;
      // Both halves of this high byte have the same tag, so miss probes
      // from either half must not reach entries belonging to the other.
      if (mate.offset !== undefined &&
          (mate.entries.some(([key]) => reaches(offset, slotAt(mate.offset, key))) ||
           group.entries.some(([key]) => reaches(mate.offset, slotAt(offset, key))))) continue;
      group.offset = offset;
      for (const [key, code] of group.entries) {
        const slot = slotAt(offset, key);
        occupied[slot] = 1;
        tags[slot] = group.index & 255;
        codes[slot] = code;
      }
      break;
    }
    assert(group.offset !== undefined, `Cannot place compact lookup group ${group.index}`);
  }

  // An unused cell (including those with no code byte) gets a tag that
  // cannot reach it with any possible low byte.
  for (let slot = 0; slot < slots; slot++) {
    if (codes[slot]) continue;
    let high = 0;
    while (high < 256 &&
           (reaches(groups[high].offset, slot) || reaches(groups[high + 256].offset, slot))) {
      high++;
    }
    assert(high < 256, `No invalid tag for empty compact lookup slot ${slot}`);
    tags[slot] = high;
  }

  const offsetsLo = Buffer.from(groups.map(group => group.offset & 255));
  const offsetsHi = Buffer.from(groups.map(group => 0xe0 | (group.offset >> 8)));
  for (let mask = 0; mask < 65536; mask++) {
    const high = mask >> 8;
    const group = high + (((mask & 128) >> 7) * 256);
    const offset = offsetsLo[group] | ((offsetsHi[group] & 15) << 8);
    const slot = slotAt(offset, mask & 127);
    const actual = tags[slot] === high ? codes[slot] : 0;
    const expected = codeByMask.get(mapping[mask]) ?? 0;
    assert.equal(actual, expected, `Displaced compact lookup for mask ${mask}`);
  }
  return { offsetsLo, offsetsHi, tags, codes };
}

function verifyGlobeDepthModes(mapping, codeByMask) {
  // These are the globe's depth key phases in main.asm. X and Y continue
  // moving while either key overrides Z.
  const modes = Object.entries({ auto: null, near: 208, far: 64 });
  return Object.fromEntries(modes.map(([name, phase]) => {
    const scene = phase === null ? data : {
      ...data,
      motionPhases: [...data.motionPhases.slice(0, 2), phase],
      motionSteps: [...data.motionSteps.slice(0, 2), 0],
    };
    const counts = [];
    for (let n = 0; n < poseCount; n++) {
      const missing = new Set();
      for (const mask of frame(scene, "globe", n).masks) {
        if (mask && !codeByMask.has(mapping[mask])) missing.add(mask);
      }
      counts.push(missing.size);
    }
    const sum = counts.reduce((a, b) => a + b, 0);
    return [name, {
      frames: counts.length,
      mean: sum / counts.length,
      peak: Math.max(...counts),
      overflow: counts.filter(count => count > dynamicSlots).length,
    }];
  }));
}

function main(outputDir) {
  assert(outputDir, "Usage: node build_compact_assets.js <output-dir>");
  const { lineMasks, joinMasks } = chooseFixedMasks();
  const fixedMasks = [0, ...lineMasks, ...joinMasks];
  const codeByMask = new Map(fixedMasks.map((mask, code) => [mask, code]));
  assert.equal(fixedMasks.length + dynamicSlots, 256);
  assert.equal(codeByMask.size, fixedMasks.length);

  const { hybridMapping } = evaluate(data.bank, joinMasks, [], lineMasks);
  const lookup = encodeLookup(hybridMapping, codeByMask);
  const displaced = encodeDisplacedLookup(lookup, hybridMapping, codeByMask);
  const mappingEntries = lookup.keys.length;
  const bucketLookupBytes = 3 * 256 + 2 * mappingEntries;
  const lookupBytes = Object.values(displaced).reduce((sum, bytes) => sum + bytes.length, 0);

  const globeDepthModes = verifyGlobeDepthModes(hybridMapping, codeByMask);
  assert(Object.values(globeDepthModes).every(mode => !mode.overflow),
    "Globe depth sweep exceeds the dynamic slot budget");

  const plan = {
    fixedMasks,
    lineGlyphs: lineMasks.length,
    fixedJoinGlyphs: joinMasks.length,
    firstDynamicCode: fixedMasks.length,
    dynamicSlots,
    mappingEntries,
    largestBucket: Math.max(...lookup.lengths),
    bucketLookupBytes,
    lookupBytes,
    globeDepthModes,
  };
  fs.mkdirSync(outputDir, { recursive: true });
  const files = {
    "charset": encodeCharset(fixedMasks),
    "buckets-lo": lookup.offsetsLo,
    "buckets-hi": lookup.offsetsHi,
    "buckets-length": lookup.lengths,
    "keys": Buffer.from(lookup.keys),
    "codes": Buffer.from(lookup.codes),
    "hash-disp-lo": displaced.offsetsLo,
    "hash-disp-hi": displaced.offsetsHi,
    "hash-tags": displaced.tags,
    "hash-codes": displaced.codes,
  };
  for (const [name, bytes] of Object.entries(files)) {
    fs.writeFileSync(path.join(outputDir, `compact-${name}.bin`), bytes);
  }
  fs.writeFileSync(path.join(outputDir, "compact-plan.json"), JSON.stringify(plan, null, 2) + "\n");
  const { fixedMasks: _, ...stats } = plan;
  console.log(JSON.stringify(stats));
}

if (require.main === module) main(process.argv[2]);
