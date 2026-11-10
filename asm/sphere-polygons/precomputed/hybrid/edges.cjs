'use strict';

const WIDTH = 40, HEIGHT = 25, CELLS = WIDTH * HEIGHT;

function edgeMask(screen) {
  if (!screen || screen.length !== CELLS) throw new Error('Edge encoding requires one 1,000-character screen.');
  return Uint8Array.from(screen, glyph => Number(glyph !== 0 && glyph !== 15));
}

function outputBuffer(out) {
  if (out === undefined) return new Uint8Array(CELLS);
  if (out.length !== CELLS) throw new Error('Edge destination must contain 1,000 characters.');
  return out;
}

function straightRuns(mask, vertical) {
  const result = [], outer = vertical ? WIDTH : HEIGHT, inner = vertical ? HEIGHT : WIDTH;
  const offset = (a, b) => vertical ? b * WIDTH + a : a * WIDTH + b;
  for (let a = 0; a < outer; a++) {
    let b = 0;
    while (b < inner) {
      if (!mask[offset(a, b)]) { b++; continue; }
      const start = b;
      while (b < inner && mask[offset(a, b)]) b++;
      for (let first = start; first < b; first += 32) result.push({ start: offset(a, first), length: Math.min(32, b - first), vertical });
    }
  }
  return result;
}

function mixedRuns(mask, preferVertical) {
  const remaining = Uint8Array.from(mask), result = [];
  let count = remaining.reduce((sum, value) => sum + value, 0);
  while (count) {
    let best = null;
    for (const vertical of [false, true]) {
      for (const candidate of straightRuns(remaining, vertical)) {
        if (!best || candidate.length > best.length || (candidate.length === best.length && candidate.vertical === preferVertical && best.vertical !== preferVertical)) best = candidate;
      }
    }
    result.push(best);
    const step = best.vertical ? WIDTH : 1;
    for (let i = 0; i < best.length; i++) remaining[best.start + i * step] = 0;
    count -= best.length;
  }
  return result;
}

function encodeStraight(screen) {
  const mask = edgeMask(screen);
  const candidates = [straightRuns(mask, false), straightRuns(mask, true), mixedRuns(mask, false), mixedRuns(mask, true)];
  let runs = candidates[0];
  // Every plan writes each edge once: minimizing record count minimizes bytes.
  for (const candidate of candidates) if (candidate.length < runs.length) runs = candidate;
  const edgeCount = mask.reduce((sum, value) => sum + value, 0);
  const payload = new Uint8Array(2 + runs.length * 2 + edgeCount);
  payload[0] = runs.length & 255; payload[1] = runs.length >>> 8;
  let index = 2;
  for (const run of runs) {
    const header = run.start | ((run.length - 1) << 10) | (run.vertical ? 0x8000 : 0);
    payload[index++] = header & 255; payload[index++] = header >>> 8;
    const step = run.vertical ? WIDTH : 1;
    for (let i = 0; i < run.length; i++) payload[index++] = screen[run.start + i * step];
  }
  return payload;
}

function decodeStraight(payload, out) {
  out = outputBuffer(out);
  if (payload.length < 2) throw new Error('Truncated edge record count.');
  const count = payload[0] | (payload[1] << 8);
  let index = 2;
  for (let record = 0; record < count; record++) {
    if (index + 2 > payload.length) throw new Error('Truncated straight edge header.');
    const header = payload[index++] | (payload[index++] << 8);
    const start = header & 1023, length = ((header >>> 10) & 31) + 1, step = header & 0x8000 ? WIDTH : 1;
    if (index + length > payload.length || start + (length - 1) * step >= CELLS || (step === 1 && start % WIDTH + length > WIDTH)) throw new Error('Invalid straight edge run.');
    for (let i = 0; i < length; i++) out[start + i * step] = payload[index++];
  }
  if (index !== payload.length) throw new Error('Trailing straight edge bytes.');
  return out;
}

function minimumPaths(mask, preferDown, reverse) {
  const positions = [], ids = new Int16Array(CELLS).fill(-1);
  for (let position = 0; position < CELLS; position++) if (mask[position]) { ids[position] = positions.length; positions.push(position); }
  const size = positions.length, outgoing = new Int16Array(size).fill(-1), incoming = new Int16Array(size).fill(-1);
  const seen = new Uint16Array(size);
  let stamp = 0;
  function augment(node) {
    const position = positions[node];
    const right = position % WIDTH < WIDTH - 1 ? ids[position + 1] : -1;
    const down = position + WIDTH < CELLS ? ids[position + WIDTH] : -1;
    for (const next of preferDown ? [down, right] : [right, down]) {
      if (next < 0 || seen[next] === stamp) continue;
      seen[next] = stamp;
      if (incoming[next] < 0 || augment(incoming[next])) {
        outgoing[node] = next; incoming[next] = node;
        return true;
      }
    }
    return false;
  }
  for (let i = 0; i < size; i++) { stamp++; augment(reverse ? size - 1 - i : i); }
  const paths = [], visited = new Uint8Array(size);
  let covered = 0;
  for (let start = 0; start < size; start++) if (incoming[start] < 0) {
    const path = [];
    for (let node = start; node >= 0; node = outgoing[node]) {
      if (visited[node]) throw new Error('Path cover revisits a vertex.');
      visited[node] = 1; covered++; path.push(positions[node]);
    }
    if (path.length > WIDTH + HEIGHT - 1) throw new Error('A monotone grid path cannot exceed 64 vertices.');
    paths.push(path);
  }
  if (covered !== size) throw new Error('Path cover omitted an edge cell.');
  return paths;
}

function pathBytes(paths) {
  return 2 + paths.reduce((sum, path) => sum + 2 + path.length + Math.ceil((path.length - 1) / 8), 0);
}

function encodePaths(screen) {
  const mask = edgeMask(screen), candidates = [];
  for (const reverse of [false, true]) for (const preferDown of [false, true]) candidates.push(minimumPaths(mask, preferDown, reverse));
  let paths = candidates[0];
  for (const candidate of candidates) {
    if (candidate.length !== paths.length) throw new Error('Maximum matchings disagree on minimum path count.');
    if (pathBytes(candidate) < pathBytes(paths)) paths = candidate;
  }
  const payload = new Uint8Array(pathBytes(paths));
  payload[0] = paths.length & 255; payload[1] = paths.length >>> 8;
  let index = 2;
  for (const path of paths) {
    const header = path[0] | ((path.length - 1) << 10);
    payload[index++] = header & 255; payload[index++] = header >>> 8;
    for (const position of path) payload[index++] = screen[position];
    const directionBytes = Math.ceil((path.length - 1) / 8);
    for (let step = 0; step + 1 < path.length; step++) if (path[step + 1] - path[step] === WIDTH) payload[index + (step >>> 3)] |= 1 << (step & 7);
    index += directionBytes;
  }
  return payload;
}

function decodePaths(payload, out) {
  out = outputBuffer(out);
  if (payload.length < 2) throw new Error('Truncated edge path count.');
  const count = payload[0] | (payload[1] << 8);
  let index = 2;
  for (let record = 0; record < count; record++) {
    if (index + 2 > payload.length) throw new Error('Truncated edge path header.');
    const header = payload[index++] | (payload[index++] << 8), length = (header >>> 10) + 1;
    const glyphStart = index, directionStart = index + length, directionBytes = Math.ceil((length - 1) / 8);
    if (directionStart + directionBytes > payload.length) throw new Error('Truncated edge path data.');
    let position = header & 1023;
    for (let step = 0; step < length; step++) {
      if (position >= CELLS) throw new Error('Edge path leaves the screen.');
      out[position] = payload[glyphStart + step];
      if (step + 1 < length) {
        const down = (payload[directionStart + (step >>> 3)] >>> (step & 7)) & 1;
        if (!down && position % WIDTH === WIDTH - 1) throw new Error('Edge path crosses a row boundary.');
        position += down ? WIDTH : 1;
      }
    }
    index = directionStart + directionBytes;
  }
  if (index !== payload.length) throw new Error('Trailing edge path bytes.');
  return out;
}

const codecs = [
  { name: 'edges-hv-best', encode: encodeStraight, decode: decodeStraight },
  { name: 'edges-monotone-minpaths', encode: encodePaths, decode: decodePaths }
];

module.exports = { codecs };
