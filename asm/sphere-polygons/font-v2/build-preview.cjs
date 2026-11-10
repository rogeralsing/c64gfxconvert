'use strict';
const fs = require('node:fs'), path = require('node:path');
const {buildBrowserSource4} = require('./browser-font4.cjs');
const {generateFont} = require('./font.cjs');
const args = process.argv.slice(2);
let outputDirectory = path.join(__dirname, 'build');
for (let index = 0; index < args.length; index++) {
  if (args[index] === '--html-only') continue;
  if (args[index] !== '--output-dir' || !args[index + 1] || args[index + 1].startsWith('--')) {
    throw new Error('Usage: node build-preview.cjs [--html-only] [--output-dir DIRECTORY]');
  }
  outputDirectory = path.resolve(args[++index]);
}
fs.mkdirSync(outputDirectory, {recursive: true});
const read = name => fs.readFileSync(path.join(__dirname, 'preview', name), 'utf8');
const conics = fs.readFileSync(path.join(__dirname, 'method-conics-fine.js'), 'utf8');
const directCore = fs.readFileSync(path.join(__dirname, 'matching/direct-core.js'), 'utf8');
const sphereRenderer = fs.readFileSync(path.join(__dirname, 'matching/sphere-renderer.js'), 'utf8');
const palette = generateFont();
const kinds = palette.glyphs.reduce((counts, glyph) => {counts[glyph.kind] = (counts[glyph.kind] || 0) + 1; return counts;}, {});
const browserFont = buildBrowserSource4();
const fragment = fs.readFileSync(path.join(__dirname, 'preview-template.html'), 'utf8').replace('/* RENDER_SOURCES */',
  [browserFont, sphereRenderer, directCore, conics].join('\n'));
if (!args.includes('--html-only')) fs.writeFileSync(path.join(outputDirectory, 'checker-font-v2.html'), fragment);

// Also update the full original HTML variant, retaining its existing controls.
// Its old benchmark used a different font, so it is omitted from this preview.
let standalone = read('sphere-shell.html')
  .replace('/* FONT_MATH */', browserFont)
  .replace('/* SPHERE_MATH */', sphereRenderer)
  .replace('/* DIRECT_METHODS */', [directCore, ...['method-probes.js','method-gradient.js'].map(read), conics].join('\n'))
  .replace('/* BENCHMARK_DATA */', '')
  .replace(/<details class="bench">[\s\S]*?<\/details>/, '')
  .replace('SFÄR — ett experiment med 256 tecken', 'SFÄR — genomsnittsfont med 256 tecken')
  .replace('16 · fyra kvadranter', '30 · mindre urval')
  .replace('<option value="16">', '<option value="30">')
  .replace('256 · hela teckenuppsättningen', '256 · genomsnittsfont')
  .replace('coarse:{ ...DEFAULTS, fontSize:16 }', 'coarse:{ ...DEFAULTS, fontSize:30 }')
  .replace('>Kvadranter</button>', '>30 tecken</button>')
  .replace('>Fin font</button>', '>Genomsnittsfont</button>')
  .replace("quadrant:'fyra kvadranter'", "quadrant:'rak fyllning'")
  .replace("edge:'rakt snitt'", "edge:'diagonal'")
  .replace('<footer><span>', '<footer><span><a href="font-v2-analysis.html" style="color:var(--accent);font-size:12px">Användning per tecken och återkommande fel</a> · ')
  .replace("$('fontValue').textContent = state.fontSize + ' tecken';", "$('fontValue').textContent = font.count + ' tecken';")
  .replace('Två snitt bildar hörn och korsningar.', `${kinds.basic || 0} raka fyllningar, ${kinds.diagonal || 0} diagonaler och ${(kinds.corner || 0) + (kinds.crossing || 0)} hörn/korsningar har valts genom mätning över olika vinklar, storlekar och schackrutningar. Inga tecken är låsta. Fragment på 1–2 pixlar är borttagna.`)
  .replace("method:'conics'", "method:'matching'")
  .replace("+ state.fontSize + ' tecken à 8 × 8 pixlar.", "+ font.count + ' tecken à 8 × 8 pixlar.");
fs.writeFileSync(path.join(outputDirectory, 'font-v2.html'), standalone);
fs.writeFileSync(path.join(outputDirectory, 'font-v2-4x4.html'), standalone);
console.log(JSON.stringify({fragment:path.join(outputDirectory,'checker-font-v2.html'), html:path.join(outputDirectory,'font-v2.html'),
  coarseHtml:path.join(outputDirectory,'font-v2-4x4.html'), fragmentBytes:Buffer.byteLength(fragment), activeGlyphs:168, reservedExcluded:true}));
