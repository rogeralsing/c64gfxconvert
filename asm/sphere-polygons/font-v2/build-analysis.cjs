'use strict';
const fs = require('node:fs'), path = require('node:path'), zlib = require('node:zlib');
const assert = require('node:assert/strict');
const args = process.argv.slice(2), positional = [];
let outputDirectory = path.join(__dirname, 'build');
for (let index = 0; index < args.length; index++) {
  if (args[index] === '--output-dir') {
    if (!args[index + 1] || args[index + 1].startsWith('--')) throw new Error('Missing --output-dir directory.');
    outputDirectory = path.resolve(args[++index]);
  } else if (args[index].startsWith('--')) throw new Error('Unknown option: ' + args[index]);
  else positional.push(args[index]);
}
if (positional.length > 5) throw new Error('Expected at most baseline, selected, search, iterations and final-test JSON paths.');
const results = path.join(__dirname, 'results');
function readJson(filename) {
  let bytes = fs.readFileSync(filename);
  if (filename.endsWith('.gz')) bytes = zlib.gunzipSync(bytes);
  return JSON.parse(bytes.toString('utf8'));
}
function optionalJson(argument, fallback) {
  const filename = argument ? path.resolve(argument) : path.join(results, fallback);
  return argument || fs.existsSync(filename) ? readJson(filename) : undefined;
}
const baselinePath = positional[0] ? path.resolve(positional[0]) : path.join(results, 'baseline.json.gz');
const improvedPath = positional[1] ? path.resolve(positional[1]) : path.join(results, 'selected.json.gz');
const baseline = readJson(baselinePath);
const improved = readJson(improvedPath);
fs.mkdirSync(outputDirectory, {recursive: true});
for (const report of [baseline, improved]) {
  assert(report.pass);
  assert.equal(report.usage.length, report.font.count);
  assert.equal(report.usage.reduce((sum, glyph) => sum + glyph.count, 0), report.summary.tilesChecked);
  assert.equal(report.usage.reduce((sum, glyph) => sum + glyph.sphereCount, 0), report.summary.activeSphereTilesChecked);
  assert(!report.usage.some(glyph => Object.hasOwn(glyph, 'fixed') || Object.hasOwn(glyph, 'locked')));
}
function topPatterns(patterns) {
  const selected = new Map();
  const byCount = [...patterns].sort((a, b) => b.count - a.count || b.totalError - a.totalError);
  const byError = [...patterns].sort((a, b) => b.totalError - a.totalError || b.count - a.count);
  for (const pattern of [...byCount.slice(0, 60), ...byError.slice(0, 60)]) selected.set(pattern.key, pattern);
  return [...selected.values()];
}
function compact(report) {
  const {frameSummaries, errorHistogram, sourceSha256, ...result} = report;
  return {...result, exactPatterns: topPatterns(report.exactPatterns), patternGroups: topPatterns(report.patternGroups)};
}
const search = optionalJson(positional[2], 'selected-search.json');
const selection = search?.report || search?.selection || search;
const iterations = optionalJson(positional[3], 'iterations.json');
const finalTest = optionalJson(positional[4], 'final-ui.json');
const data = {baseline: compact(baseline), improved: compact(improved), selection, iterations, finalTest};
const template = fs.readFileSync(path.join(__dirname, 'error-report-template.html'), 'utf8');
assert.equal(template.split('/*ERROR_DATA*/null').length, 2);
const links = '<a href="font-v2-usage.csv" download style="color:var(--accent)">Alla användningsantal som CSV</a> · '
  + '<a href="font-v2-error-baseline.json" download style="color:var(--accent)">Fullständig före-mätning</a> · '
  + '<a href="font-v2-error-current.json" download style="color:var(--accent)">Fullständig efter-mätning</a><br>';
const html = template.replace('/*ERROR_DATA*/null', JSON.stringify(data).replace(/</g, '\\u003c')).replace('<footer>', '<footer>' + links);
const output = path.join(outputDirectory, 'font-v2-analysis.html');
fs.writeFileSync(output, html);
fs.writeFileSync(path.join(outputDirectory, 'font-v2-error-baseline.json'), JSON.stringify(baseline, null, 2) + '\n');
fs.writeFileSync(path.join(outputDirectory, 'font-v2-error-current.json'), JSON.stringify(improved, null, 2) + '\n');
const quote = value => '"' + String(value).replace(/"/g, '""') + '"';
const rows = [['tecken', 'typ', 'beskrivning', 'antal_pa_sfaren', 'antal_hela_skarmen', 'bilder_pa_sfaren', 'bilder_totalt', 'andel_med_lika_vikt_per_fall', 'bitmap_hex']];
for (const glyph of [...improved.usage].sort((a, b) => a.sphereCount - b.sphereCount || a.index - b.index)) {
  rows.push([glyph.index, glyph.kind, glyph.label, glyph.sphereCount, glyph.count, glyph.sphereFramesUsed, glyph.framesUsed, glyph.weightedSphereUsage ?? '',
    glyph.rows.map(row => row.toString(16).padStart(2, '0')).join('')]);
}
fs.writeFileSync(path.join(outputDirectory, 'font-v2-usage.csv'), '\ufeff' + rows.map(row => row.map(quote).join(';')).join('\n') + '\n');
console.log(JSON.stringify({output, frames: improved.frames, glyphs: improved.font.count,
  unusedGlyphs: improved.summary.unusedGlyphs, sphereChoices: improved.summary.activeSphereTilesChecked,
  reportBytes: Buffer.byteLength(html), unprotectedGlyphs: improved.usage.length}, null, 2));
