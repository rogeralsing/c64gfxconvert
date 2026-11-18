"use strict";
/* Line Font Lab — interactive replica of the precomputed line-drawing scheme.
 *
 * Modes (measured; see README.md):
 *  A "259 dirs · free start"  — 132 exact tiles, 200 flip-closed glyphs.
 *  B "259 dirs · 2×2 start"   —  96 exact tiles, 194 flip-closed; starts snap
 *                               to the even fat lattice (jump up to 1.7 fat px).
 *  C "519 dirs · free start"  — identical 132/200 bank (the 4×4 pattern
 *                               alphabet saturates at 259 directions) with
 *                               better worst-case slope fit.
 *  D "dynamic hires"          — simulates runtime charset patching: exact-slope
 *                               1px lines, per-cell glyphs, unlimited bank.
 */
window.addEventListener("error", (e) => {
  const s = document.getElementById("stats");
  if (s) s.textContent = `ERROR: ${e.message} @${e.filename || "?"}:${e.lineno || "?"}`;
});

const FW = 40, FH = 25;
const PW = 160, PH = 100;
const CW = 320, CH = 200;

/* ---------- Bresenham — exact port; tie-breaking decides font membership ---------- */
function bresenham(x0, y0, x1, y1) {
  const pts = [];
  const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
  let err = dx + dy, x = x0, y = y0;
  for (;;) {
    pts.push([x, y]);
    if (x === x1 && y === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) { err += dy; x += sx; }
    if (e2 <= dx) { err += dx; y += sy; }
  }
  return pts;
}

/* ---------- direction sets ---------- */
const D259 = [];
for (let d = 1; d <= 160; d++) D259.push([d, 100]);
for (let h = 1; h <= 99; h++) D259.push([160, h]);
const D519 = [];
for (let d = 1; d <= 320; d++) D519.push([d, 200]);
for (let h = 1; h <= 199; h++) D519.push([320, h]);
const ENT16 = [];
for (let sy = 0; sy < 4; sy++) for (let sx = 0; sx < 4; sx++) ENT16.push([sx, sy]);
const ENT4 = [[0, 0], [0, 2], [2, 0], [2, 2]];

function anglesOf(eps) {
  const a = eps.map(([ex, ey]) => [Math.atan2(ey, ex), ex, ey]);
  a.push([0, 1, 0], [Math.PI / 2, 0, 1]);
  return a;
}

/* ---------- font bank ---------- */
function hflip(t)  { let r = 0; for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if (t >> (y * 4 + x) & 1) r |= 1 << (y * 4 + 3 - x); return r; }
function vflip(t)  { let r = 0; for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if (t >> (y * 4 + x) & 1) r |= 1 << ((3 - y) * 4 + x); return r; }
function hvflip(t) { return hflip(vflip(t)); }

function buildFont(eps, entries) {
  const tileToCode = new Map(), codeTiles = [];
  const acc = new Map(), cnt = new Map();     // per-tile smooth coverage votes
  const flipOf = new Map();                   // flip-added tile -> [source tile, kind]
  const add = (t) => {
    let c = tileToCode.get(t);
    if (c === undefined) { c = codeTiles.length; tileToCode.set(t, c); codeTiles.push(t); }
  };
  /* Accumulate one vote: a 2px hires band along the true generating line,
     clipped to the cell and to the stamped span (truncations end mid-cell). */
  function note(t, ex, ey, sx, sy, cellX, cellY, p0, p1) {
    let a = acc.get(t);
    if (!a) { a = new Float32Array(64); acc.set(t, a); }
    cnt.set(t, (cnt.get(t) || 0) + 1);
    const X0 = cellX * 4, Y0 = cellY * 4;
    const Sx = sx + 0.5, Sy = sy + 0.5;
    const len = Math.hypot(ex, ey), ux = ex / len, uy = ey / len;
    let lo = ((p0[0] - Sx) * ux + (p0[1] - Sy) * uy) - 0.6;
    let hi = ((p1[0] - Sx) * ux + (p1[1] - Sy) * uy) + 0.6;
    for (const [o, u, b0] of [[Sx, ux, X0], [Sy, uy, Y0]]) {   // clip to cell rect
      if (u > 1e-9) { lo = Math.max(lo, (b0 - o) / u); hi = Math.min(hi, (b0 + 4 - o) / u); }
      else if (u < -1e-9) { lo = Math.max(lo, (b0 + 4 - o) / u); hi = Math.min(hi, (b0 - o) / u); }
    }
    if (hi <= lo) return;
    const ax = Sx + lo * ux, ay = Sy + lo * uy;
    const abx = (hi - lo) * ux, aby = (hi - lo) * uy, ab2 = abx * abx + aby * aby || 1e-12;
    for (let py = 0; py < 8; py++) {
      const qy = Y0 + (py + 0.5) / 2;
      for (let px = 0; px < 8; px++) {
        const qx = X0 + (px + 0.5) / 2;
        let tt = ((qx - ax) * abx + (qy - ay) * aby) / ab2;
        tt = tt < 0 ? 0 : tt > 1 ? 1 : tt;
        const dx = qx - (ax + tt * abx), dy = qy - (ay + tt * aby);
        if (dx * dx + dy * dy <= 0.25) a[py * 8 + px] += 1;    // half-width 0.5 fat = 2 hires px
      }
    }
  }
  for (const [ex, ey] of eps) {
    for (const [sx, sy] of entries) {
      const grid = new Map(), last = new Map(), first = new Map(), lastPt = new Map();
      for (const [x, y] of bresenham(sx, sy, sx + ex, sy + ey)) {
        if (x < 0 || x >= PW || y < 0 || y >= PH) continue;
        const key = (y >> 2) * FW + (x >> 2);
        if (!first.has(key)) first.set(key, [x, y]);
        lastPt.set(key, [x, y]);
        const p = (grid.get(key) || 0) | (1 << ((y & 3) * 4 + (x & 3)));
        grid.set(key, p);
        if (last.get(key) !== p) {
          add(p);
          note(p, ex, ey, sx, sy, x >> 2, y >> 2, first.get(key), [x, y]);
          last.set(key, p);
        }
      }
      for (const [key, p] of grid) {
        add(p);
        note(p, ex, ey, sx, sy, key % FW, (key / FW) | 0, first.get(key), lastPt.get(key));
      }
    }
  }
  const exact = codeTiles.length;
  for (let i = 0; i < exact; i++) {
    for (const [f, kind] of [[hflip(codeTiles[i]), "h"], [vflip(codeTiles[i]), "v"], [hvflip(codeTiles[i]), "hv"]]) {
      if (!tileToCode.has(f)) { flipOf.set(f, [codeTiles[i], kind]); add(f); }
    }
  }
  const glyphs = codeTiles.length;
  const charset = new Uint8Array(glyphs * 8);   // mechanical 2x2 expansion
  const smooth = new Uint8Array(glyphs * 8);    // consensus hires bands
  const flipCov = (src, kind) => {
    const a = acc.get(src), n = cnt.get(src);
    if (!a || !n) return null;
    const out = new Float32Array(64);
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
      const sx2 = kind === "h" || kind === "hv" ? 7 - x : x;   // h-mirror flips columns
      const sy2 = kind === "v" || kind === "hv" ? 7 - y : y;   // v-mirror flips rows
      out[y * 8 + x] = a[sy2 * 8 + sx2] / n;
    }
    return out;
  };
  codeTiles.forEach((t, i) => {
    for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
      if (t >> (y * 4 + x) & 1) {
        charset[i * 8 + 2 * y]     |= 0xc0 >> (2 * x);
        charset[i * 8 + 2 * y + 1] |= 0xc0 >> (2 * x);
      }
    }
    let cov = null;
    const a = acc.get(t), n = cnt.get(t);
    if (a && n) { cov = new Float32Array(64); for (let k = 0; k < 64; k++) cov[k] = a[k] / n; }
    else if (flipOf.has(t)) cov = flipCov(...flipOf.get(t));
    for (let k = 0; k < 64; k++) {
      if (cov ? cov[k] >= 0.4 : (charset[i * 8 + (k >> 3)] >> (7 - (k & 7))) & 1)
        smooth[i * 8 + (k >> 3)] |= 0x80 >> (k & 7);
    }
  });
  return { tileToCode, charset, smooth, glyphs, exact };
}

/* ---------- modes ---------- */
const MODES = [
  { id: "a", label: "259 dirs · free start", eps: D259, entries: ENT16, snapStart: false },
  { id: "b", label: "259 dirs · 2×2 start", eps: D259, entries: ENT4, snapStart: true },
  { id: "c", label: "519 dirs · free start", eps: D519, entries: ENT16, snapStart: false },
  { id: "d", label: "dynamic hires (patched)", dynamic: true },
];
let mode = MODES[0];
let font = buildFont(mode.eps, mode.entries);   // ~132/200 glyphs
let angles = anglesOf(mode.eps);

/* ---------- joint composition: shadow OR + patched glyph slots ----------
 * Two lines sharing a cell ideally show the OR of their patterns; that space
 * is unbounded (6,806 distinct ORs in a 40 s soak), so it cannot be a static
 * bank. Instead: keep a 16-bit shadow per cell, resolve ORs that already are
 * line glyphs for free, and patch everything else into glyph slots 200..255
 * (rewritten per frame on the C64 — ≤ ~40 joints × 8 bytes). */
const PATCH_BUDGET = 56;
const shadow = new Uint16Array(FW * FH);
let patchSlots = [];                 // slot pattern -> glyph code 200+i
const patchMap = new Map();
let fullCharset = null;
const usedPatches = new Set();
let jointsOn = true, cullOn = true, smoothOn = false;   // default: 4×4 fat glyphs

function rebuildCharset() {
  fullCharset = new Uint8Array((200 + patchSlots.length) * 8);
  fullCharset.set((smoothOn ? font.smooth : font.charset).subarray(0, 200 * 8));
  patchSlots.forEach((t, i) => {
    for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
      if (t >> (y * 4 + x) & 1) {
        fullCharset[(200 + i) * 8 + 2 * y]     |= 0xc0 >> (2 * x);
        fullCharset[(200 + i) * 8 + 2 * y + 1] |= 0xc0 >> (2 * x);
      }
    }
  });
}
function resetPatches() {
  patchSlots = [];
  patchMap.clear();
  usedPatches.clear();
  rebuildCharset();
}
/* Resolve one cell against shadow; alloc=false is a side-effect-free preview. */
function composeCell(key, pat, lineCode, alloc) {
  const merged = shadow[key] | pat;
  shadow[key] = merged;
  const code = font.tileToCode.get(merged);
  if (code !== undefined) return { code, kind: "line" };
  let pc = patchMap.get(merged);
  if (pc === undefined) {
    if (!alloc || patchSlots.length >= PATCH_BUDGET) return { code: lineCode, kind: "fallback" };
    pc = 200 + patchSlots.length;
    patchSlots.push(merged);
    patchMap.set(merged, pc);
    rebuildCharset();
  }
  return { code: pc, kind: "joint" };
}
const screenCodes = new Uint8Array(FW * FH);    // static modes: 0 blank, code+1
const cellBytes = new Uint8Array(FW * FH * 8);  // dynamic mode: per-cell glyph rows
const dynamicPatterns = new Set();              // distinct patched glyphs seen
const usedCodes = new Set();
const undoStack = [];
let pending = null, hover = null;

const $ = (id) => document.getElementById(id);
const screenCtx = $("screen").getContext("2d");
const overlayCtx = $("overlay").getContext("2d");
const bankCtx = $("bank").getContext("2d");
const bankCanvas = $("bank");
const statsEl = $("stats");
const show = { charGrid: true, fatGrid: false, rawLine: true };

/* ---------- the drawer ---------- */
function snapDirection(x0, y0, x1, y1) {
  if (x1 === x0 && y1 === y0) return null;
  const mx = x1 < x0 ? -1 : 1, my = y1 < y0 ? -1 : 1;
  const a = Math.atan2((y1 - y0) * my, (x1 - x0) * mx);
  let best = 0, bd = Infinity;
  for (let i = 0; i < angles.length; i++) {
    const d = Math.abs(angles[i][0] - a);
    if (d < bd) { bd = d; best = i; }
  }
  return { mx, my, ex: angles[best][1], ey: angles[best][2], index: best };
}

/* Static fat-grid stamps for one line. */
function lineStamps(x0, y0, x1, y1) {
  if (mode.snapStart) { x0 &= ~1; y0 &= ~1; }
  const snap = snapDirection(x0, y0, x1, y1);
  let pts;
  if (!snap) {
    pts = [[x0, y0]];
  } else {
    const { mx, my, ex, ey } = snap;
    const K = Math.ceil(220 / Math.max(ex, ey, 1));
    const ray = bresenham(x0, y0, x0 + mx * ex * K, y0 + my * ey * K);
    const xMajor = ex >= ey;
    pts = [];
    for (const p of ray) {
      pts.push(p);
      if (xMajor ? mx * p[0] >= mx * x1 : my * p[1] >= my * y1) break;
    }
  }
  const cells = new Map();
  for (const [x, y] of pts) {
    if (x < 0 || x >= PW || y < 0 || y >= PH) continue;
    const key = (y >> 2) * FW + (x >> 2);
    cells.set(key, (cells.get(key) || 0) | (1 << ((y & 3) * 4 + (x & 3))));
  }
  let misses = 0;
  const stamps = [];
  for (const [key, pat] of cells) {
    const code = font.tileToCode.get(pat);
    if (code === undefined) misses++; else stamps.push({ key, pat, code });
  }
  return { snap, stamps, misses, forms: cells.size, x0, y0 };
}

/* Dynamic hires: exact slope, 1px line at hires resolution, per-cell bytes. */
function lineStampsDynamic(x0, y0, x1, y1) {
  const cells = new Map();   // key -> Uint8Array(8)
  for (const [hx, hy] of bresenham(x0 * 2, y0 * 2, x1 * 2, y1 * 2)) {
    if (hx < 0 || hx >= CW || hy < 0 || hy >= CH) continue;
    const key = ((hy >> 3) * FW) + (hx >> 3);
    let rows = cells.get(key);
    if (!rows) { rows = new Uint8Array(8); cells.set(key, rows); }
    rows[hy & 7] |= 0x80 >> (hx & 7);
  }
  return { stamps: [...cells.entries()].map(([key, rows]) => ({ key, rows })), misses: 0 };
}

function stampsFor(x0, y0, x1, y1) {
  return mode.dynamic ? lineStampsDynamic(x0, y0, x1, y1)
                      : lineStamps(x0, y0, x1, y1);
}

/* ---------- rendering ---------- */
const img = screenCtx.createImageData(CW, CH);
const FG = [232, 232, 238], BG = [16, 16, 22];

function renderScreen(extra) {
  const data = img.data;
  for (let cy = 0; cy < FH; cy++) {
    for (let cx = 0; cx < FW; cx++) {
      const cellIdx = cy * FW + cx;
      const base = (cy * 8) * CW + cx * 8;
      for (let row = 0; row < 8; row++) {
        let bits = 0;
        if (mode.dynamic) {
          bits = cellBytes[cellIdx * 8 + row];
          if (extra) { const e = extra.get(cellIdx); if (e) bits |= e[row]; }
        } else {
          let code = screenCodes[cellIdx];
          if (code === 0 && extra) code = (extra.get(cellIdx) || 0) + 1;
          if (code) bits = fullCharset[(code - 1) * 8 + row];   // styled line glyph or joint slot
        }
        let px = base + row * CW;
        for (let bit = 0; bit < 8; bit++, px++) {
          const on = (bits >> (7 - bit)) & 1;
          const c = on ? FG : BG;
          const o = px * 4;
          data[o] = c[0]; data[o + 1] = c[1]; data[o + 2] = c[2]; data[o + 3] = 255;
        }
      }
    }
  }
  screenCtx.putImageData(img, 0, 0);
}

function renderOverlay() {
  const c = overlayCtx;
  c.clearRect(0, 0, CW, CH);
  if (show.charGrid) {
    c.strokeStyle = "rgba(255,255,255,0.14)";
    c.beginPath();
    for (let x = 8; x < CW; x += 8) { c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, CH); }
    for (let y = 8; y < CH; y += 8) { c.moveTo(0, y + 0.5); c.lineTo(CW, y + 0.5); }
    c.stroke();
  }
  if (show.fatGrid) {
    c.strokeStyle = "rgba(255,255,255,0.07)";
    c.beginPath();
    for (let x = 2; x < CW; x += 2) { c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, CH); }
    for (let y = 2; y < CH; y += 2) { c.moveTo(0, y + 0.5); c.lineTo(CW, y + 0.5); }
    c.stroke();
  }
  if (hover && !pending && !cube3d.running) {
    c.strokeStyle = "rgba(124,227,139,0.8)";
    c.strokeRect((hover[0] >> 2) * 8 + 0.5, (hover[1] >> 2) * 8 + 0.5, 7, 7);
  }
  if (pending) {
    if (show.rawLine) {
      c.strokeStyle = "rgba(255,180,84,0.65)";
      c.beginPath();
      c.moveTo(pending.x0 * 2 + 1, pending.y0 * 2 + 1);
      c.lineTo(pending.x1 * 2 + 1, pending.y1 * 2 + 1);
      c.stroke();
    }
    c.strokeStyle = "rgba(255,180,84,0.9)";
    for (const [x, y] of [[pending.x0, pending.y0], [pending.x1, pending.y1]]) {
      c.strokeRect(x * 2 - 2, y * 2 - 2, 6, 6);
    }
    if (mode.snapStart) {   // where the start actually went
      c.strokeStyle = "rgba(124,227,139,0.9)";
      c.strokeRect((pending.x0 & ~1) * 2 - 2, (pending.y0 & ~1) * 2 - 2, 6, 6);
    }
  }
}

function renderBank() {
  const c = bankCtx, cell = 12, cols = 25;
  if (mode.dynamic) {
    bankCanvas.height = 96;
    c.fillStyle = "#14141c";
    c.fillRect(0, 0, bankCanvas.width, bankCanvas.height);
    let i = 0;
    for (const pat of dynamicPatterns) {
      if (i >= 200) break;
      const gx = (i % cols) * cell, gy = ((i / cols) | 0) * cell;
      c.fillStyle = "#ffb454";
      for (let row = 0; row < 8; row++) {
        const bits = parseInt(pat.substr(row * 8, 8), 2);
        for (let bit = 0; bit < 8; bit++) if ((bits >> (7 - bit)) & 1) c.fillRect(gx + 2 + bit, gy + 2 + row, 1, 1);
      }
      i++;
    }
    $("bankTitle").textContent = `dynamic patched glyphs — ${dynamicPatterns.size} distinct (no bank limit)`;
    return;
  }
  const total = 200 + patchSlots.length;
  const rows = Math.ceil(total / cols);
  bankCanvas.height = rows * cell;
  c.fillStyle = "#14141c";
  c.fillRect(0, 0, bankCanvas.width, bankCanvas.height);
  for (let i = 0; i < total; i++) {
    const gx = (i % cols) * cell, gy = ((i / cols) | 0) * cell;
    const isPatch = i >= 200;
    const used = isPatch ? usedPatches.has(i) : usedCodes.has(i);
    if (used) { c.fillStyle = isPatch ? "#1a2a22" : "#2a2a1a"; c.fillRect(gx, gy, cell, cell); }
    c.fillStyle = used ? (isPatch ? "#7ce38b" : "#ffb454") : (isPatch ? "#4a6a55" : "#5a5a6a");
    for (let row = 0; row < 8; row++) {
      const bits = fullCharset[i * 8 + row];
      for (let bit = 0; bit < 8; bit++) if ((bits >> (7 - bit)) & 1) c.fillRect(gx + 2 + bit, gy + 2 + row, 1, 1);
    }
  }
  $("bankTitle").textContent =
    `glyph bank — ${font.glyphs} line (${font.exact} exact + flips) + ${patchSlots.length}/${PATCH_BUDGET} joint slots (green)`;
}

function redraw() {
  let extra = null;
  if (pending) {
    extra = new Map();
    for (const s of stampsFor(pending.x0, pending.y0, pending.x1, pending.y1).stamps) {
      if (mode.dynamic) extra.set(s.key, s.rows);
      else if (jointsOn) extra.set(s.key, composeCell(s.key, s.pat, s.code, false).code);
      else extra.set(s.key, s.code);
    }
  }
  renderScreen(extra);
  renderOverlay();
}

/* ---------- stats ---------- */
function describeLine(r, x0, y0, x1, y1) {
  if (mode.dynamic) return `dynamic hires · ${r.stamps.length} cells`;
  if (!r.snap) return "dot";
  const { mx, my, ex, ey, index } = r.snap;
  const deg = (Math.atan2(ey * my, ex * mx) * 180 / Math.PI).toFixed(1);
  const nDirs = angles.length - 2;
  const kind = index >= nDirs ? (ex === 1 ? "H" : "V") : `#${index}`;
  const jumped = mode.snapStart && ((x0 & 1) || (y0 & 1)) ? ` · start snapped (${x0 & 1},${y0 & 1})` : "";
  const over = r.misses ? ` · MISSES ${r.misses}` : "";
  return `dir ${kind} (${ex * mx},${ey * my}) ${deg}° · entry (${r.x0 & 3},${r.y0 & 3}) · ` +
         `${r.stamps.length} chars · ${r.forms} forms${jumped}${over}`;
}

/* ---------- actions ---------- */
function commit(x0, y0, x1, y1) {
  const r = stampsFor(x0, y0, x1, y1);
  if (r.misses) statsEl.textContent = "INTERNAL ERROR — uncovered stamps: " + r.misses;
  undoStack.push(mode.dynamic ? { cells: cellBytes.slice() }
                              : { screen: screenCodes.slice(), shadow: shadow.slice() });
  if (undoStack.length > 200) undoStack.shift();
  let joints = 0;
  if (mode.dynamic) {
    for (const s of r.stamps) {
      const base = s.key * 8;
      for (let row = 0; row < 8; row++) cellBytes[base + row] |= s.rows[row];
      dynamicPatterns.add(Array.from(s.rows).map((b) => b.toString(2).padStart(8, "0")).join(""));
    }
  } else if (jointsOn) {
    for (const s of r.stamps) {
      const c = composeCell(s.key, s.pat, s.code, true);
      screenCodes[s.key] = c.code + 1;
      if (c.kind === "joint") { joints++; usedPatches.add(c.code); }
      else if (c.kind !== "fallback") usedCodes.add(c.code);
    }
  } else {
    for (const s of r.stamps) { screenCodes[s.key] = s.code + 1; usedCodes.add(s.code); }
  }
  statsEl.textContent = describeLine(r, x0, y0, x1, y1) +
                        (joints ? ` · ${joints} joint${joints > 1 ? "s" : ""} patched` : "");
  renderBank();
}

function undo() {
  if (!undoStack.length) return;
  const snap = undoStack.pop();
  if (snap.cells) cellBytes.set(snap.cells);
  else { screenCodes.set(snap.screen); shadow.set(snap.shadow); }
  refreshUsage();
}

function refreshUsage() {
  usedCodes.clear();
  usedPatches.clear();
  dynamicPatterns.clear();
  if (mode.dynamic) {
    for (let i = 0; i < FW * FH; i++) {
      let any = false;
      for (let row = 0; row < 8; row++) if (cellBytes[i * 8 + row]) { any = true; break; }
      if (any) dynamicPatterns.add(Array.from(cellBytes.slice(i * 8, i * 8 + 8))
        .map((b) => b.toString(2).padStart(8, "0")).join(""));
    }
  } else {
    for (const v of screenCodes) {
      if (!v) continue;
      if (v - 1 >= 200) usedPatches.add(v - 1);
      else usedCodes.add(v - 1);
    }
  }
  renderBank();
  redraw();
}

function clearScreen() {
  undoStack.length = 0;
  screenCodes.fill(0);
  cellBytes.fill(0);
  shadow.fill(0);
  resetPatches();
  refreshUsage();
}

function switchMode(m) {
  mode = m;
  if (!m.dynamic) { font = buildFont(m.eps, m.entries); angles = anglesOf(m.eps); }
  undoStack.length = 0;
  screenCodes.fill(0);
  cellBytes.fill(0);
  shadow.fill(0);
  resetPatches();
  refreshUsage();
  statsEl.textContent = selfTest();
  document.querySelectorAll("[data-mode]").forEach(
    (b) => b.classList.toggle("on", b.dataset.mode === m.id));
}

/* ---------- 3D wireframe proof: every edge goes through the line drawer ---------- */
const SHAPES = {
  cube: {
    vertices: [[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],
    edges: [[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]],
    faces: [[0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[1,2,6,5],[0,3,7,4]],
  },
  tetra: {
    vertices: [[1,1,1],[1,-1,-1],[-1,1,-1],[-1,-1,1]],
    edges: [[0,1],[0,2],[0,3],[1,2],[1,3],[2,3]],
    faces: [[0,1,2],[0,1,3],[0,2,3],[1,2,3]],
  },
  octa: {
    vertices: [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]],
    edges: [[0,2],[0,3],[0,4],[0,5],[1,2],[1,3],[1,4],[1,5],[2,4],[4,3],[3,5],[5,2]],
    faces: [[0,2,4],[0,4,3],[0,3,5],[0,5,2],[1,2,4],[1,4,3],[1,3,5],[1,5,2]],
  },
};
for (const s of Object.values(SHAPES)) {          // edge -> faces containing it
  s.edgeFaces = s.edges.map(([a, b]) =>
    s.faces.map((f, i) => f.includes(a) && f.includes(b) ? i : -1).filter((i) => i >= 0));
}
const cube3d = { running: false, shape: "cube", yaw: 0.7, pitch: 0.4, roll: 0.3,
                 scale: 1, dragging: false, lastX: 0, lastY: 0, fps: 0, frames: 0 };

function frame3d() {
  const s = SHAPES[cube3d.shape];
  const cy = Math.cos(cube3d.yaw), sy = Math.sin(cube3d.yaw);
  const cp = Math.cos(cube3d.pitch), sp = Math.sin(cube3d.pitch);
  const cr = Math.cos(cube3d.roll), sr = Math.sin(cube3d.roll);
  const F = 80 * cube3d.scale, CAM = 4.5;
  const tv = s.vertices.map(([x, y, z]) => {
    const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;    // yaw (Y)
    const y1 = y * cp - z1 * sp, z2 = y * sp + z1 * cp;   // pitch (X)
    return [x1 * cr - y1 * sr, x1 * sr + y1 * cr, z2];    // roll (Z)
  });
  const pts = tv.map(([x2, y2, z2]) => {
    const d = CAM + z2;
    return [Math.round(80 + x2 * F / d), Math.round(50 - y2 * F / d)];
  });
  // backface culling (convex): keep edges of faces whose outward normal
  // points toward the camera at (0, 0, -CAM)
  let keep = s.edges.map((_, i) => i);
  if (cullOn && s.faces) {
    const vis = new Set();
    s.faces.forEach((f, fi) => {
      const [ax, ay, az] = tv[f[0]], [bx, by, bz] = tv[f[1]], [cx, cy2, cz] = tv[f[2]];
      let nx = (by - ay) * (cz - az) - (bz - az) * (cy2 - ay);
      let ny = (bz - az) * (cx - ax) - (bx - ax) * (cz - az);
      let nz = (bx - ax) * (cy2 - ay) - (by - ay) * (cx - ax);
      let mx = 0, my = 0, mz = 0;                      // orient outward via centroid
      for (const i of f) { mx += tv[i][0]; my += tv[i][1]; mz += tv[i][2]; }
      if (nx * mx + ny * my + nz * mz < 0) { nx = -nx; ny = -ny; nz = -nz; }
      // visible iff outward normal · (vertex - camera) < 0, camera at (0, 0, -CAM)
      if (nx * ax + ny * ay + nz * (az + CAM) < 0) vis.add(fi);
    });
    keep = s.edges.map((_, i) => i).filter((i) => s.edgeFaces[i].some((f) => vis.has(f)));
  }
  screenCodes.fill(0);
  cellBytes.fill(0);
  shadow.fill(0);
  usedCodes.clear();
  usedPatches.clear();
  dynamicPatterns.clear();
  if (!mode.dynamic && jointsOn) resetPatches();      // slots are per-frame scratch
  let chars = 0, misses = 0, joints = 0, fallbacks = 0;
  for (const i of keep) {
    const [a, b] = s.edges[i];
    const r = stampsFor(pts[a][0], pts[a][1], pts[b][0], pts[b][1]);
    chars += r.stamps.length;
    misses += r.misses || 0;
    if (mode.dynamic) {
      for (const st of r.stamps) {
        const base = st.key * 8;
        for (let row = 0; row < 8; row++) cellBytes[base + row] |= st.rows[row];
      }
    } else if (jointsOn) {
      for (const st of r.stamps) {
        const c = composeCell(st.key, st.pat, st.code, true);
        screenCodes[st.key] = c.code + 1;
        if (c.kind === "joint") { joints++; usedPatches.add(c.code); }
        else if (c.kind === "fallback") fallbacks++;
        else usedCodes.add(c.code);
      }
    } else {
      for (const st of r.stamps) { screenCodes[st.key] = st.code + 1; usedCodes.add(st.code); }
    }
  }
  return { chars, misses, edges: keep.length, joints, fallbacks };
}

let lastT = 0;
function animate(t) {
  if (!cube3d.running) return;
  const dt = Math.min(0.05, Math.max(0.001, (t - lastT) / 1000));
  lastT = t;
  if (!cube3d.dragging) {          // tumble on all three axes
    cube3d.yaw += dt * 0.7;
    cube3d.pitch += dt * 0.4;
    cube3d.roll += dt * 0.25;
  }
  const r = frame3d();
  cube3d.frames++;
  cube3d.fps = cube3d.fps ? cube3d.fps * 0.9 + (1 / dt) * 0.1 : 1 / dt;
  statsEl.textContent = `3D ${cube3d.shape} · ${cube3d.fps.toFixed(0)} fps · scale ${cube3d.scale.toFixed(2)} · ` +
                        `${r.edges} edges · ${r.chars} chars/frame · misses ${r.misses}` +
                        (mode.dynamic ? "" : ` · joints ${r.joints}${r.fallbacks ? " · fallback " + r.fallbacks : ""}`) +
                        ` · ${mode.label}`;
  if (cube3d.frames % 20 === 0) renderBank();
  redraw();
  requestAnimationFrame(animate);
}
function start3d() {
  cube3d.running = true;
  undoStack.length = 0;
  $("cube3d").classList.add("on");
  lastT = performance.now();
  requestAnimationFrame(animate);
}
function stop3d() {
  cube3d.running = false;
  $("cube3d").classList.remove("on");
  renderBank();
  redraw();
}

/* ---------- input ---------- */
const stage = $("stage");
let dragging = false;
const screenCanvas = $("screen");

function fatPixel(e) {
  const r = screenCanvas.getBoundingClientRect();
  const x = Math.floor((e.clientX - r.left) / r.width * PW);
  const y = Math.floor((e.clientY - r.top) / r.height * PH);
  return [Math.max(0, Math.min(PW - 1, x)), Math.max(0, Math.min(PH - 1, y))];
}

stage.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  stage.setPointerCapture(e.pointerId);
  if (cube3d.running) {          // grab the wireframe instead of drawing
    cube3d.dragging = true;
    cube3d.lastX = e.clientX;
    cube3d.lastY = e.clientY;
    return;
  }
  dragging = true;
  const [x, y] = fatPixel(e);
  pending = { x0: x, y0: y, x1: x, y1: y };
  redraw();
});
stage.addEventListener("pointermove", (e) => {
  if (cube3d.dragging) {
    cube3d.yaw += (e.clientX - cube3d.lastX) * 0.008;
    cube3d.pitch += (e.clientY - cube3d.lastY) * 0.008;
    cube3d.lastX = e.clientX;
    cube3d.lastY = e.clientY;
    return;
  }
  const [x, y] = fatPixel(e);
  hover = [x, y];
  if (dragging) {
    pending.x1 = x; pending.y1 = y;
    statsEl.textContent = describeLine(stampsFor(pending.x0, pending.y0, x, y),
                                       pending.x0, pending.y0, x, y);
  }
  redraw();
});
function endDrag() {
  if (cube3d.dragging) { cube3d.dragging = false; return; }
  if (!dragging) return;
  dragging = false;
  const { x0, y0, x1, y1 } = pending;
  pending = null;
  commit(x0, y0, x1, y1);
  redraw();
}
stage.addEventListener("pointerup", endDrag);
stage.addEventListener("pointercancel", endDrag);
stage.addEventListener("pointerleave", () => { if (!dragging) { hover = null; redraw(); } });

/* ---------- controls ---------- */
function toggle(name, btn) {
  show[name] = !show[name];
  btn.classList.toggle("on", show[name]);
  redraw();
}
$("charGrid").onclick = (e) => toggle("charGrid", e.target);
$("fatGrid").onclick = (e) => toggle("fatGrid", e.target);
$("rawLine").onclick = (e) => toggle("rawLine", e.target);
$("joints").onclick = (e) => {
  jointsOn = !jointsOn;
  e.target.classList.toggle("on", jointsOn);
  clearScreen();
  statsEl.textContent = `joints ${jointsOn ? "on — OR-composed into patched slots" : "off — overwrite (holes return)"}`;
};
$("backfaces").onclick = (e) => {
  cullOn = !cullOn;
  e.target.classList.toggle("on", cullOn);
};
$("smooth").onclick = (e) => {
  smoothOn = !smoothOn;
  e.target.classList.toggle("on", smoothOn);
  rebuildCharset();
  renderBank();
  redraw();
  statsEl.textContent = smoothOn
    ? "glyphs: smooth — consensus hires bands from the generating lines"
    : "glyphs: fat — mechanical 2×2 expansion";
};
$("undo").onclick = undo;
$("clear").onclick = clearScreen;
$("demo").onclick = () => {
  undoStack.length = 0;
  screenCodes.fill(0);
  shadow.fill(0);
  resetPatches();
  usedCodes.clear();
  usedPatches.clear();
  const segs = [
    [2, 2, 157, 49], [2, 2, 78, 97], [2, 2, 34, 97], [80, 50, 155, 8],
    [19, 14, 10, 43], [120, 90, 30, 20], [60, 80, 140, 70], [30, 5, 155, 5],
  ];
  let misses = 0, chars = 0, joints = 0;
  for (const s of segs) {
    const r = stampsFor(...s);
    misses += r.misses; chars += r.stamps.length;
    if (mode.dynamic) {
      for (const st of r.stamps) {
        const base = st.key * 8;
        for (let row = 0; row < 8; row++) cellBytes[base + row] |= st.rows[row];
        dynamicPatterns.add(Array.from(st.rows).map((b) => b.toString(2).padStart(8, "0")).join(""));
      }
    } else if (jointsOn) {
      for (const st of r.stamps) {
        const c = composeCell(st.key, st.pat, st.code, true);
        screenCodes[st.key] = c.code + 1;
        if (c.kind === "joint") { joints++; usedPatches.add(c.code); }
        else if (c.kind !== "fallback") usedCodes.add(c.code);
      }
    } else {
      for (const st of r.stamps) { screenCodes[st.key] = st.code + 1; usedCodes.add(st.code); }
    }
  }
  statsEl.textContent = `demo: 8 lines, ${chars} chars, ${misses} uncovered` +
                        (mode.dynamic ? "" : `, ${joints} joints patched`);
  renderBank();
  redraw();
};
document.querySelectorAll("[data-mode]").forEach((b) => b.onclick = () => {
  switchMode(MODES.find((m) => m.id === b.dataset.mode));
});
$("cube3d").onclick = () => (cube3d.running ? stop3d() : start3d());
const scaleInput = $("scale"), scaleVal = $("scaleVal");
function setScale(v) {
  cube3d.scale = Math.min(2.2, Math.max(0.3, v));
  scaleInput.value = cube3d.scale.toFixed(2);
  scaleVal.textContent = cube3d.scale.toFixed(2);
}
scaleInput.oninput = () => setScale(parseFloat(scaleInput.value));
stage.addEventListener("wheel", (e) => {
  e.preventDefault();
  setScale(cube3d.scale * Math.exp(-e.deltaY * 0.0012));
}, { passive: false });
document.querySelectorAll("[data-shape]").forEach((b) => b.onclick = () => {
  cube3d.shape = b.dataset.shape;
  document.querySelectorAll("[data-shape]").forEach(
    (x) => x.classList.toggle("on", x === b));
  if (!cube3d.running) start3d();
});

function setZoom(z) {
  stage.style.width = CW * z + "px";
  stage.style.height = CH * z + "px";
  document.querySelectorAll("[data-zoom]").forEach(
    (b) => b.classList.toggle("on", b.dataset.zoom === String(z)));
}
document.querySelectorAll("[data-zoom]").forEach(
  (b) => b.onclick = () => setZoom(+b.dataset.zoom));

document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "u") undo();
  else if (e.key === "c") $("clear").click();
  else if (e.key === "g") $("charGrid").click();
  else if (e.key === "f") $("fatGrid").click();
  else if (e.key === "r") $("rawLine").click();
  else if (e.key === "j") $("joints").click();
  else if (e.key === "b") $("backfaces").click();
  else if (e.key === "s") $("smooth").click();
  else if (e.key === "2" || e.key === "3" || e.key === "4") setZoom(+e.key);
});

/* ---------- startup self-test ---------- */
const TEST_SEGS = [
  [2, 2, 157, 49], [2, 2, 78, 97], [2, 2, 34, 97], [80, 50, 155, 8],
  [19, 14, 10, 43], [120, 90, 30, 20], [60, 80, 140, 70], [30, 5, 155, 5],
  [5, 90, 150, 92], [150, 10, 152, 95],
];
function selfTest() {
  if (mode.dynamic) return "mode: dynamic hires — exact slopes, per-cell patched glyphs";
  let stamps = 0, misses = 0;
  for (const s of TEST_SEGS) {
    const r = lineStamps(...s);
    stamps += r.stamps.length;
    misses += r.misses;
  }
  const nDirs = angles.length - 2;
  const bankOk = font.exact === (mode.entries === ENT4 ? 96 : 132) &&
                 font.glyphs === (mode.entries === ENT4 ? 194 : 200);
  return `mode: ${mode.label} — ${font.exact} exact tiles, ${font.glyphs} glyphs` +
         (bankOk ? "" : " — UNEXPECTED BANK") +
         ` · self-test: ${stamps} stamps, ${misses} uncovered` +
         (misses === 0 && bankOk ? " ✓" : " ✗");
}

setZoom(3);
resetPatches();
document.querySelector('[data-mode="a"]').classList.add("on");
statsEl.textContent = selfTest();
renderBank();
redraw();

if (new URLSearchParams(location.search).has("demo")) $("demo").click();

window.__linefont = { lineStamps, screenCodes, cellBytes, shadow, MODES, switchMode, commit, redraw,
                      cube3d, patchInfo: () => ({ slots: patchSlots.length, budget: PATCH_BUDGET }),
                      get font() { return font; },
                      fontInfo: () => ({ exact: font.exact, glyphs: font.glyphs }) };
