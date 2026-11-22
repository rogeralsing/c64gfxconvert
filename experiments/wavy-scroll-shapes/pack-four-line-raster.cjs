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

// The PAL kernel's 397-cycle delay crosses a natural VIC badline.
// Enter the job after 27 dispatch cycles, fetch its NOP at CPU cycle 197,
// and return in six cycles. The NOP absorbs all 43 clocks of VIC stall.
const dispatchCycles = 27;
const returnCycles = 6;
const dmaBridgeCycles = 2;
const beforeDmaCycles = 197;
const afterDmaCycles = 198;
const earlyBudget = beforeDmaCycles - dispatchCycles;
const lateBudget = afterDmaCycles - returnCycles;
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

function planScreen(groups, writers, destination) {
  const first = writers[`ScreenTop${destination}`];
  const second = writers[`ScreenBottom${destination}`];
  const original = [...first, ...second];
  const switches = groups.filter((group, index) => index === 0 || group === groups[index - 1] + 1);
  if (!original.length || !switches.length) return null;

  // Keep the original store order. Select the fewest consecutive fields,
  // then let the packer minimize repeated loads within those fields.
  const budgets = switches.flatMap(() => [earlyBudget, lateBudget]);
  for (let fieldCount = 1; fieldCount <= maxMappingFields; fieldCount++) {
    const result = packRasterWrites(original, Array.from({ length: fieldCount }, () => budgets).flat());
    if (result.remainder.length) continue;
    const fields = [];
    const jobs = [];
    for (let field = 0; field < fieldCount; field++) {
      fields.push(switches.map((group, index) => {
        const start = (field * switches.length + index) * 2;
        const [before, after] = result.chunks.slice(start, start + 2);
        const job = before.cycles + after.cycles ? emitRasterJob(before, after) : null;
        if (job) jobs.push(job);
        return { switchRaster: 55 + group * 8, before, after, job };
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
    const sections = {};
    for (const [name, section] of [[`ScreenTop${destination}`, jobs.slice(0, bestIndex)],
      [`ScreenBottom${destination}`, jobs.slice(bestIndex)]]) {
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

function compileRasterPlan(a, b, enabled) {
  const displayA = enabled ? planScreen(a.groups, b.writers, "B") : null;
  const displayB = enabled ? planScreen(b.groups, a.writers, "A") : null;
  const packed = Boolean(displayA && displayB);
  const tableWidth = packed ? Math.max(displayA.fields[0].length, displayB.fields[0].length) : 0;
  const tables = [];
  if (packed) {
    tables.push(Array(tableWidth).fill("rasterIdleChunk"));
    for (const slots of [...displayA.fields, ...displayB.fields]) {
      const entries = Array.from({ length: tableWidth }, (_, slot) => slots[slot]?.job?.address ?? "rasterIdleChunk");
      tables.push(entries);
    }
  }

  const describeWindow = (chunk, startRaster, startCycle) => ({
    startRaster,
    startCycle,
    mappingCycles: chunk.cycles,
    paddingCycles: chunk.pad,
    stores: chunk.instructions.filter((line) => line.startsWith("sta ")).length,
  });
  const describePhase = (plan) => plan.fields.map((slots) => slots.map(({ switchRaster, before, after }) => {
    const windows = [describeWindow(before, switchRaster - 7, 3 + dispatchCycles),
      describeWindow(after, switchRaster - 4, 56)];
    return { switchRaster, mappingCycles: before.cycles + after.cycles,
      stores: windows[0].stores + windows[1].stores, windows };
  }));
  const describeColorRam = (phase, name) => {
    const first = phase.groups.length ? 46 + phase.groups[0] * 8 : 51;
    const deadline = Math.min(51, first);
    return {
      startRaster: 256,
      deadlineRaster: deadline,
      mappingCycles: phase.writers[`Color${name}`].reduce((sum, line) => sum + instructionCycles(line), 0),
      budgetCycles: (312 - 256 + deadline) * 63 - 180,
    };
  };
  return {
    writers: packed ? { ...displayA.sections, ...displayB.sections } : {},
    startupCalls: packed ? displayB.startupCalls : [],
    constants: {
      rasterPacked: packed,
      rasterMapFieldsA: packed ? displayA.fields.length : 0,
      rasterMapFieldsB: packed ? displayB.fields.length : 0,
      rasterTableStride: tableWidth * 2,
      rasterChunkEntryCycles: dispatchCycles,
      rasterChunkExitCycles: returnCycles,
      rasterWorkDelayCycles: beforeDmaCycles + dmaBridgeCycles + afterDmaCycles,
    },
    tables: tables.map((entries) => `.word ${entries.join(", ")}`),
    report: packed ? {
      screenRam: { whileDisplayingA: describePhase(displayA), whileDisplayingB: describePhase(displayB) },
      payloadCyclesPerGap: earlyBudget + lateBudget,
      dispatchAndReturnCycles: dispatchCycles + returnCycles,
      colorRam: { phaseA: describeColorRam(a, "A"), phaseB: describeColorRam(b, "B") },
    } : null,
  };
}

module.exports = { compileRasterPlan, instructionCycles, packRasterWrites };
