"use strict";

function parseInstruction(line) {
  const match = /^\s*(lda|ora|sta)\s+(\S.*?)\s*$/i.exec(line);
  if (!match) throw new Error(`Unsupported raster mapping instruction: ${line}`);
  const opcode = match[1].toLowerCase();
  const operand = match[2];
  if (operand.startsWith("#")) {
    if (opcode === "sta") throw new Error(`Store requires an absolute address: ${line}`);
    return { opcode, cycles: 2 };
  }

  // Generated symbolic addresses name Screen RAM, Color RAM or the lookup
  // tables. All of them reside outside zero page and use absolute addressing.
  const literal = /^(?:\$([0-9a-f]+)|(\d+))$/i.exec(operand);
  const address = literal ? (literal[1] ? Number.parseInt(literal[1], 16) : Number(literal[2])) : null;
  if ((address !== null && (address < 0x100 || address > 0xffff)) || /[,()]/.test(operand)) {
    throw new Error(`Expected a fixed-cycle absolute address: ${line}`);
  }
  return { opcode, cycles: 4 };
}

function instructionCycles(line) {
  return parseInstruction(line).cycles;
}

function readStores(instructions) {
  const stores = [];
  const prefixCycles = [0];
  let group;
  for (const line of instructions) {
    const { opcode, cycles } = parseInstruction(line);
    if (opcode === "lda" && (!group || group.hasStore)) {
      group = { load: [line], cycles, hasStore: false };
    } else if (opcode === "ora" && group && group.load.length === 1 && !group.hasStore) {
      group.load.push(line);
      group.cycles += cycles;
    } else if (opcode === "sta" && group) {
      const reload = group.hasStore ? group.cycles : 0;
      const added = cycles + (group.hasStore ? 0 : group.cycles);
      stores.push({ line, load: group.load, reload });
      prefixCycles.push(prefixCycles.at(-1) + added);
      group.hasStore = true;
    } else {
      throw new Error(`Expected LDA, optional ORA and at least one STA before: ${line}`);
    }
  }
  if (group && !group.hasStore) throw new Error("The last raster mapping value has no stores.");
  return { stores, prefixCycles };
}

function instructionsFor(stores, start, end) {
  const instructions = [];
  for (let index = start; index < end; index++) {
    const { line, load, reload } = stores[index];
    if (index === start || reload === 0) instructions.push(...load);
    instructions.push(line);
  }
  return instructions;
}

function packRasterWrites(instructions, budgets) {
  const { stores, prefixCycles } = readStores(instructions);
  const storeCount = stores.length;
  let costs = new Float64Array(storeCount + 1).fill(Infinity);
  costs[0] = 0;
  const boundaries = [];

  for (const budget of budgets) {
    if (!Number.isSafeInteger(budget) || budget < 0 || budget === 1) {
      throw new Error(`Invalid raster window budget: ${budget}`);
    }
    const nextCosts = new Float64Array(storeCount + 1).fill(Infinity);
    const starts = new Int32Array(storeCount + 1).fill(-1);
    for (let start = storeCount; start >= 0; start--) {
      if (costs[start] === Infinity) continue;
      if (costs[start] < nextCosts[start]) {
        nextCosts[start] = costs[start];
        starts[start] = start;
      }
      if (start === storeCount) continue;

      // A chunk that starts between stores of the same value must reload it.
      const reload = stores[start].reload;
      const cost = costs[start] + reload;
      for (let end = start + 1; end <= storeCount; end++) {
        const spent = prefixCycles[end] - prefixCycles[start] + reload;
        const pad = budget - spent;
        if (pad < 0) break;
        if (pad === 1 || cost >= nextCosts[end]) continue;
        nextCosts[end] = cost;
        starts[end] = start;
      }
    }
    costs = nextCosts;
    boundaries.push(starts);
  }

  // First place as many stores as possible. For each reachable prefix the
  // dynamic program keeps the plan with the fewest extra load cycles.
  let end = storeCount;
  while (costs[end] === Infinity) end--;
  const remainder = instructionsFor(stores, end, storeCount);
  const chunks = new Array(budgets.length);
  for (let index = budgets.length - 1; index >= 0; index--) {
    const start = boundaries[index][end];
    const cycles = start === end ? 0 : prefixCycles[end] - prefixCycles[start] + stores[start].reload;
    chunks[index] = {
      instructions: instructionsFor(stores, start, end),
      cycles,
      pad: budgets[index] - cycles,
    };
    end = start;
  }
  return { chunks, remainder };
}

// Each job crosses a natural VIC badline. The NOP absorbs all 43
// clocks of VIC stall. With a 4/4 split it starts at CPU cycle 197.
const dispatchCycles = 27;
const returnCycles = 6;
const dmaBridgeCycles = 2;
const beforeDmaCycles = 197;
const afterDmaCycles = 198;
const palCyclesPerLine = 63;
const baseDelay = beforeDmaCycles + dmaBridgeCycles + afterDmaCycles;
// The other fields leave room for preparing the next decoded LUT.
const maxMappingFields = 2;

function instructionBytes(line) {
  return instructionCycles(line) === 2 ? 2 : 3;
}

function emitPadding(cycles) {
  const padding = [];
  if (cycles & 1) {
    padding.push("bit $02");
    cycles -= 3;
  }
  if (cycles > 0) padding.push(`.fill ${cycles / 2}, $ea`);
  return padding;
}

function emitRasterJob(before, after) {
  const code = [
    ...before.instructions, ...emitPadding(before.pad),
    "nop",
    ...after.instructions, ...emitPadding(after.pad),
    "rts",
  ];
  const payload = [...before.instructions, ...after.instructions];
  const paddingBytes = (ticks) => (ticks & 1) ? 2 + (ticks - 3) / 2 : ticks / 2;
  const bytes = payload.reduce((sum, line) => sum + instructionBytes(line), 0) +
    paddingBytes(before.pad) + paddingBytes(after.pad) + 2;
  return { code, bytes };
}

function timingWindows(groups, splits) {
  const windows = [];
  for (const [index, group] of groups.entries()) {
    const previousSplit = index === 0 ? 4 : splits[index - 1];
    if (index > 0 && (group !== groups[index - 1] + 1 || previousSplit === 7)) continue;
    const split = splits[index];
    const naturalRaster = 51 + group * 8;
    const earlyBudget = beforeDmaCycles + (4 - previousSplit) * palCyclesPerLine - dispatchCycles;
    const lateBudget = afterDmaCycles + (split - 4) * palCyclesPerLine - returnCycles;
    windows.push({
      switchRaster: naturalRaster + split,
      firstRaster: naturalRaster + previousSplit - 7,
      naturalRaster,
      delay: earlyBudget + lateBudget + dispatchCycles + dmaBridgeCycles + returnCycles,
      earlyBudget,
      lateBudget,
    });
  }
  return windows;
}

function planScreen({ groups, splits }, writers, destination, tailCapacity = 0) {
  const first = writers[`ScreenTop${destination}`];
  const second = writers[`ScreenBottom${destination}`];
  const original = [...first, ...second];
  const windows = timingWindows(groups, splits);
  if (!original.length || !windows.length) return null;

  // Keep the original store order. Select the fewest consecutive fields,
  // then let the packer minimize repeated loads within those fields.
  const budgets = windows.flatMap(({ earlyBudget, lateBudget }) => [earlyBudget, lateBudget]);
  for (let fieldCount = 1; fieldCount <= maxMappingFields; fieldCount++) {
    const result = packRasterWrites(original, Array.from({ length: fieldCount }, () => budgets).flat());
    if (result.remainder.length) continue;
    const fields = [];
    const jobs = [];
    for (let field = 0; field < fieldCount; field++) {
      fields.push(windows.map((window, index) => {
        const start = (field * windows.length + index) * 2;
        const [before, after] = result.chunks.slice(start, start + 2);
        const job = before.cycles + after.cycles ? emitRasterJob(before, after) : null;
        if (job) jobs.push(job);
        return { ...window, before, after, job };
      }));
    }

    // Split code between the two existing free areas for this VIC bank.
    const firstBytes = first.reduce((sum, line) => sum + instructionBytes(line), 0);
    const secondBytes = second.reduce((sum, line) => sum + instructionBytes(line), 0);
    const totalBytes = jobs.reduce((sum, job) => sum + job.bytes, 0);
    let bestIndex = 0;
    let bestGrowth = totalBytes - secondBytes;
    let prefixBytes = 0;
    for (const [index, job] of jobs.entries()) {
      prefixBytes += job.bytes;
      const growth = Math.max(prefixBytes - firstBytes, totalBytes - prefixBytes - secondBytes);
      if (growth < bestGrowth) {
        bestIndex = index + 1;
        bestGrowth = growth;
      }
    }
    let tailStart = jobs.length;
    let tailBytes = 0;
    while (tailStart > bestIndex && tailBytes + jobs[tailStart - 1].bytes <= tailCapacity) {
      tailBytes += jobs[--tailStart].bytes;
    }
    const sections = {};
    const placements = [[`ScreenTop${destination}`, jobs.slice(0, bestIndex)],
      [`ScreenBottom${destination}`, jobs.slice(bestIndex, tailStart)]];
    if (tailCapacity) placements.push([`ScreenTail${destination}`, jobs.slice(tailStart)]);
    for (const [name, section] of placements) {
      let offset = 0;
      sections[name] = section.flatMap((job) => {
        job.address = `write${name} + ${offset}`;
        offset += job.bytes;
        return job.code;
      });
    }
    return { fields, sections, startupCalls: jobs.map(({ address }) => `jsr ${address}`) };
  }
  return null;
}

function makePlanTables(displayA, displayB) {
  const tableWidth = Math.max(displayA.fields[0].length, displayB.fields[0].length);
  const idleDelays = new Set();
  for (const { delay } of [...displayA.fields[0], ...displayB.fields[0]]) idleDelays.add(delay);
  const delays = [...idleDelays];
  const idleEntry = (slot) => {
    const index = slot ? delays.indexOf(slot.delay) : 0;
    return `rasterIdleChunkBase + ${index} * rasterIdleChunkStride`;
  };
  const idleA = Array.from({ length: tableWidth }, (_, slot) => idleEntry(displayA.fields[0][slot]));
  const idleB = Array.from({ length: tableWidth }, (_, slot) => idleEntry(displayB.fields[0][slot]));
  const distinct = idleA.some((entry, index) => entry !== idleB[index]);
  const tables = distinct ? [idleA, idleB] : [idleA];
  for (const slots of [...displayA.fields, ...displayB.fields]) {
    tables.push(Array.from({ length: tableWidth }, (_, slot) => slots[slot]?.job?.address ?? idleEntry(slots[slot])));
  }
  const stride = tableWidth * 2;
  return stride * tables.length <= 256 ? { tables, delays, stride, idlePlanB: Number(distinct) } : null;
}

function compileRasterPlan(a, b, enabled, { screenTailB, vblankRaster = 256 } = {}) {
  const displayA = enabled ? planScreen(a, b.writers, "B", screenTailB) : null;
  const displayB = enabled ? planScreen(b, a.writers, "A") : null;
  const plan = displayA && displayB ? makePlanTables(displayA, displayB) : null;
  const packed = Boolean(plan);
  const tables = plan?.tables ?? [];

  const describeWindow = (chunk, startRaster, startCycle) => ({
    startRaster,
    startCycle,
    mappingCycles: chunk.cycles,
    paddingCycles: chunk.pad,
    stores: chunk.instructions.filter((line) => line.startsWith("sta ")).length,
  });
  const describePhase = (phase) => phase.fields.map((slots) => slots.map(({
    switchRaster, firstRaster, naturalRaster, earlyBudget, lateBudget, before, after,
  }) => {
    const windows = [describeWindow(before, firstRaster, 3 + dispatchCycles),
      describeWindow(after, naturalRaster, 56)];
    return { switchRaster, mappingCycles: before.cycles + after.cycles,
      budgetCycles: earlyBudget + lateBudget,
      stores: windows[0].stores + windows[1].stores, windows };
  }));
  const describeColorRam = (phase, name) => {
    const first = phase.groups.length ? 46 + phase.groups[0] * 8 : 51;
    const deadline = Math.min(51, first);
    return {
      startRaster: vblankRaster,
      deadlineRaster: deadline,
      mappingCycles: phase.writers[`Color${name}`].reduce((sum, line) => sum + instructionCycles(line), 0),
      budgetCycles: (312 - vblankRaster + deadline) * palCyclesPerLine - 180,
    };
  };
  return {
    writers: packed ? { ...displayA.sections, ...displayB.sections } : {},
    startupCalls: packed ? displayB.startupCalls : [],
    constants: {
      rasterPacked: packed,
      rasterMapFieldsA: packed ? displayA.fields.length : 0,
      rasterMapFieldsB: packed ? displayB.fields.length : 0,
      rasterTableStride: plan?.stride ?? 0,
      rasterIdlePlanA: 0,
      rasterIdlePlanB: plan?.idlePlanB ?? 0,
      rasterIdleFields: plan ? plan.idlePlanB + 1 : 0,
      rasterChunkEntryCycles: dispatchCycles,
      rasterChunkExitCycles: returnCycles,
      rasterWorkDelayCycles: baseDelay,
    },
    idleDelays: plan?.delays ?? [],
    tables: tables.map((entries) => `.word ${entries.join(", ")}`),
    report: packed ? {
      screenRam: { whileDisplayingA: describePhase(displayA), whileDisplayingB: describePhase(displayB) },
      ...(plan.delays.length === 1 ? {
        payloadCyclesPerGap: plan.delays[0] - dispatchCycles - dmaBridgeCycles - returnCycles,
      } : {}),
      dispatchAndReturnCycles: dispatchCycles + returnCycles,
      colorRam: { phaseA: describeColorRam(a, "A"), phaseB: describeColorRam(b, "B") },
    } : null,
  };
}

module.exports = { compileRasterPlan, instructionCycles, packRasterWrites };
