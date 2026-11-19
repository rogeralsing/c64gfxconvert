(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const text = (id, value) => { byId(id).textContent = value; };
  const choice = (name) => document.querySelector(`input[name="${name}"]:checked`).value;
  const shapeNames = { cube: "Cube", football: "Football", globe: "Globe" };
  const paletteLimit = 55;
  const compactPatchSlots = 22;
  const poseCount = 256;
  const columnCount = 40;
  const rowCount = 25;
  const cellSize = 4;
  const formatter = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });
  const number = (value) => formatter.format(value);
  const percentage = (count, total) => total ? `${number(100 * count / total)}%` : "—";
  const hex = (value, width) => `$${value.toString(16).toUpperCase().padStart(width, "0")}`;

  const ink = [232, 232, 238, 255];
  const commonInk = [158, 158, 176, 255];
  const addedInk = [124, 227, 139, 255];
  const removedInk = [255, 107, 107, 255];
  const pose = byId("pose");
  const play = byId("play");
  const previewMode = byId("preview-mode");
  const difference = byId("show-difference");
  const frameSets = new Map();
  const evaluations = new Map();
  const data = globalThis.JOIN_STUDY_DATA;
  let trainedPalette;
  let compactPlan;
  let evaluation;
  let playback = null;

  function screenBuffer(id) {
    const canvas = byId(id);
    const context = canvas.getContext("2d");
    return { context, image: context.createImageData(canvas.width, canvas.height) };
  }

  const exactPreview = screenBuffer("exact-preview");
  const fixedPreview = screenBuffer("fixed-preview");

  function draw({ context, image }, shown, reference = null) {
    const pixels = image.data;
    pixels.fill(0);
    for (let row = 0; row < rowCount; row++) {
      for (let col = 0; col < columnCount; col++) {
        const cell = row * columnCount + col;
        const mask = shown[cell];
        const original = reference ? reference[cell] : mask;
        if (!(mask | original)) continue;
        for (let bit = 0; bit < cellSize * cellSize; bit++) {
          const flag = 1 << bit;
          if (!((mask | original) & flag)) continue;
          const x = col * cellSize + bit % cellSize;
          const y = row * cellSize + (bit >> 2);
          const offset = (y * image.width + x) * 4;
          const color = reference
            ? (!(mask & flag) ? removedInk : !(original & flag) ? addedInk : commonInk)
            : ink;
          pixels.set(color, offset);
        }
      }
    }
    context.putImageData(image, 0, 0);
  }

  function renderPose() {
    const index = Number(pose.value);
    const { masks } = frameSets.get(choice("shape"))[index];
    const mapping = previewMode.value === "hybrid" ? evaluation.hybridMapping : evaluation.mapping;
    const shown = Uint16Array.from(masks, (mask) => mapping[mask]);
    let changed = 0;
    for (let cell = 0; cell < masks.length; cell++) {
      if (masks[cell] !== shown[cell]) changed++;
    }
    draw(exactPreview, masks);
    draw(fixedPreview, shown, difference.checked ? masks : null);
    text("pose-number", `${String(index).padStart(3, "0")} / ${poseCount - 1}`);
    text("pose-difference", changed === 1 ? "1 changed cell" : `${changed} changed cells`);
    byId("diff-legend").hidden = !difference.checked;
    const capacity = byId("preview-capacity");
    capacity.hidden = previewMode.value !== "hybrid" || !capacity.classList.contains("warning");
  }

  function drawGlyph(canvas, mask) {
    const context = canvas.getContext("2d");
    context.fillStyle = "#0b0b0f";
    context.fillRect(0, 0, cellSize, cellSize);
    context.fillStyle = "#e8e8ee";
    for (let bit = 0; bit < cellSize * cellSize; bit++) {
      if (mask & (1 << bit)) context.fillRect(bit % cellSize, bit >> 2, 1, 1);
    }
  }

  function renderGlyphRows() {
    const field = choice("frequency");
    const ranked = evaluation.glyphs
      .filter((glyph) => glyph[field] > 0)
      .sort((a, b) => b[field] - a[field] || a.mask - b.mask)
      .slice(0, 12);
    byId("glyph-list").replaceChildren(...ranked.map((glyph) => {
      const item = document.createElement("li");
      const icon = document.createElement("canvas");
      const detail = document.createElement("div");
      const count = document.createElement("strong");
      const mask = document.createElement("small");
      const pattern = hex(glyph.mask, 4);
      item.title = glyph.bankCode === null ? `Mask ${pattern}` : `Mask ${pattern} · line code ${hex(glyph.bankCode, 2)}`;
      icon.width = icon.height = cellSize;
      icon.setAttribute("aria-hidden", "true");
      drawGlyph(icon, glyph.mask);
      count.textContent = number(glyph[field]);
      mask.textContent = pattern;
      detail.append(count, mask);
      item.append(icon, detail);
      return item;
    }));
  }

  function renderStats(lineSlots, joinSlots) {
    const s = evaluation.stats;
    text("study-status", `${shapeNames[choice("shape")]} · ${s.frameCount} held-out poses · 4×4 glyphs`);
    const free = 255 - lineSlots - joinSlots;
    text("bank-size", `${lineSlots} line + ${joinSlots} join + ${free} dynamic + 1 blank`);
    text("legacy-patches", number(s.legacyPatchesPerFrame));
    text("batch-patches", number(s.batchPatchesPerFrame));
    text("remaining-patches", number(s.remainingPatchesPerFrame));
    text("hybrid-patches", number(s.hybridPatchesPerFrame));
    text("fixed-patches", "0");
    const peak = s.maxHybridPatchesPerFrame;
    const overBudget = peak > free;
    const capacity = `Hybrid needs up to ${peak} dynamic slots · ${free} available.`;
    text("hybrid-capacity", capacity);
    text("preview-capacity", `Software preview · ${capacity}`);
    text("hybrid-note", `Hybrid adds ${number(s.hybridAddedPixels / s.frameCount)} pixels per frame on average. It retains every source pixel and adds up to two connected pixels per cell.`);
    byId("hybrid-capacity").classList.toggle("warning", overBudget);
    byId("preview-capacity").classList.toggle("warning", overBudget);
    text("exact-cells", percentage(s.exactCells, s.finalCells));
    text("exact-joins", percentage(s.exactJoinCells, s.joinCells));
    text("pixel-errors", `${number(s.removedPixels / s.frameCount)} / ${number(s.addedPixels / s.frameCount)}`);
    text("boundary-loss", number(s.lostBoundaryPixels / s.frameCount));
    text("short-masks", `${percentage(s.shortStamps, s.stampCount)} → ${percentage(s.shortFinal, s.finalCells)}`);
    text("stamp-bank-usage", `${number(s.stampBankCodesUsed)} / ${data.bank.length}`);
    text("final-bank-usage", `${number(s.finalBankCodesUsed)} / ${data.bank.length}`);
    text("endpoint-exact", percentage(s.exactJunctionCells, s.junctionCells));
  }

  function selectEvaluation() {
    const shape = choice("shape");
    const budget = choice("budget");
    const key = `${shape}:${budget}`;
    const { bank, palette } = budget === "compact" ? compactPlan : {
      bank: data.bank,
      palette: trainedPalette.slice(0, Number(budget)),
    };
    if (!evaluations.has(key)) {
      const measured = frameSets.get(shape).filter((_, index) => index % 2 === 1);
      evaluations.set(key, JoinStudyPalette.evaluate(data.bank, palette, measured, bank));
    }
    evaluation = evaluations.get(key);
    renderStats(bank.length, palette.length);
    renderGlyphRows();
    renderPose();
  }

  function stopPlayback() {
    if (playback === null) return;
    window.clearInterval(playback);
    playback = null;
    play.textContent = "Play";
  }

  function initialize() {
    const training = [];
    for (const shape of Object.keys(shapeNames)) {
      const frames = [];
      for (let index = 0; index < poseCount; index++) {
        const frame = JoinStudyModel.frame(data, shape, index);
        frames.push(frame);
        if (index % 2 === 0) training.push(frame);
      }
      frameSets.set(shape, frames);
    }
    trainedPalette = JoinStudyPalette.train(data.bank, training, paletteLimit);
    const used = new Set();
    for (const frame of training) {
      for (const mask of frame.masks) used.add(mask);
    }
    const bank = data.bank.filter((mask) => used.has(mask));
    const palette = JoinStudyPalette.trainAdditive(bank, training, 255 - bank.length - compactPatchSlots);
    compactPlan = { bank, palette };
    selectEvaluation();
    document.querySelectorAll("fieldset[disabled], button[disabled], select[disabled], input[disabled]")
      .forEach((control) => { control.disabled = false; });
  }

  document.querySelectorAll('input[name="shape"]')
    .forEach((control) => control.addEventListener("change", selectEvaluation));
  document.querySelectorAll('input[name="budget"]')
    .forEach((control) => control.addEventListener("change", () => {
      previewMode.value = choice("budget") === "compact" ? "hybrid" : "fixed";
      selectEvaluation();
    }));
  document.querySelectorAll('input[name="frequency"]')
    .forEach((control) => control.addEventListener("change", renderGlyphRows));
  pose.addEventListener("input", () => { stopPlayback(); renderPose(); });
  previewMode.addEventListener("change", renderPose);
  difference.addEventListener("change", renderPose);
  play.addEventListener("click", () => {
    if (playback !== null) {
      stopPlayback();
      return;
    }
    play.textContent = "Pause";
    playback = window.setInterval(() => {
      pose.value = (Number(pose.value) + 1) % poseCount;
      renderPose();
    }, 90);
  });

  window.setTimeout(() => {
    try {
      initialize();
    } catch (error) {
      text("study-status", `Study unavailable. ${error.message}`);
      console.error(error);
    }
  });
})();
