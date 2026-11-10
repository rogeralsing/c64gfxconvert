'use strict';

// Every translated integer half-plane with primitive normal components up to
// the limit. Deduplication is on the actual eight row bytes, not its equation.
function gcd(a, b) {
  a = Math.abs(a); b = Math.abs(b);
  while (b) [a, b] = [b, a % b];
  return a;
}
function countBits(value) {
  let count = 0;
  for (; value; value &= value - 1) count++;
  return count;
}

function candidates(maxComponent = 15) {
  if (!Number.isInteger(maxComponent) || maxComponent < 1 || maxComponent > 31) throw new Error('Normal component limit must be an integer from 1 to 31.');
  const seen = new Set(), result = [];
  for (let a = -maxComponent; a <= maxComponent; a++) for (let b = -maxComponent; b <= maxComponent; b++) {
    if (gcd(a, b) !== 1) continue;
    const minimum = Math.min(0, 7 * a) + Math.min(0, 7 * b);
    const maximum = Math.max(0, 7 * a) + Math.max(0, 7 * b);
    for (let threshold = minimum + 1; threshold <= maximum; threshold++) {
      const rows = [];
      let filled = 0;
      for (let y = 0; y < 8; y++) {
        let row = 0;
        for (let x = 0; x < 8; x++) if (a * x + b * y >= threshold) row |= 128 >>> x;
        rows.push(row); filled += countBits(row);
      }
      if (Math.min(filled, 64 - filled) <= 2) continue;
      const key = rows.join(',');
      if (seen.has(key)) continue;
      seen.add(key);
      result.push({rows, filled, kind: 'diagonal', label: 'Matematiskt rakt snitt', family: 'general-line',
        normal: [a, b], threshold, fixed: false,
        metadata: {operation: 'half-plane', coordinateSystem: 'integer tile coordinates x,y=0..7', maxComponent}});
    }
  }
  return result;
}

module.exports = {candidates};

if (require.main === module) {
  const assert = require('node:assert/strict');
  const {orbit} = require('./junction-candidates.cjs');
  const glyphs = candidates(), keys = new Set(glyphs.map(value => value.rows.join(',')));
  for (const glyph of glyphs) for (const counterpart of orbit(glyph.rows)) assert(keys.has(counterpart.rows.join(',')), 'Incomplete half-plane symmetry');
  const shallowStep = [248,248,248,248,252,252,252,252];
  assert(keys.has(shallowStep.join(',')), 'Missing shallow one-column step');
  console.log(JSON.stringify({pass: true, glyphs: glyphs.length, maxNormalComponent: 15,
    allTranslatedPrimitiveHalfPlanes: true, completeRotationsMirrorsInverses: true,
    maximumExcludedFragmentPixels: 2, requestedShallowStepPresent: true}, null, 2));
}
