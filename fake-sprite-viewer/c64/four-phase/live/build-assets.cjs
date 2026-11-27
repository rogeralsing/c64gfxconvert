const { mkdirSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const { charset, phaseTiles, sprite } = require('../../../ball-tiles.js');
const {
  DEFAULT_LIVE_BALL_COUNT, DEFAULT_LIVE_SAMPLING, RETAINED_LIVE_BALL_COUNT, SOURCE_BALLS,
  selectLiveSources, selectSpriteSources, sine,
} = require('../motion.cjs');

function parseOptions([outputDirectory, ...args]) {
  if (!outputDirectory || outputDirectory.startsWith('--')) return null;

  let count = DEFAULT_LIVE_BALL_COUNT;
  let sampling = DEFAULT_LIVE_SAMPLING;
  for (let index = 0; index < args.length; index += 2) {
    const option = args[index];
    const value = args[index + 1];
    if (option === '--count') count = Number(value);
    else if (option === '--sampling') sampling = value;
    else return null;
  }
  if (!['retain21', 'uniform'].includes(sampling)) return null;
  const minimumCount = sampling === 'retain21' ? RETAINED_LIVE_BALL_COUNT : 2;
  if (!Number.isInteger(count) || count < minimumCount || count > SOURCE_BALLS) return null;
  return { outputDirectory, count, sampling };
}

const options = parseOptions(process.argv.slice(2));
if (!options) {
  console.error('Usage: node build-assets.cjs <output-dir> [--count N] [--sampling retain21|uniform]');
  process.exit(1);
}

const { outputDirectory, count, sampling } = options;
const sources = selectLiveSources(count, sampling);
const files = {
  'charset.bin': Buffer.concat(charset),
  'tiles.bin': Buffer.concat(phaseTiles),
  'sources.bin': Buffer.from(sources),
  'sprite-sources.bin': Buffer.from(selectSpriteSources(sources)),
  'sprite.bin': sprite,
  'sine.bin': sine,
};

mkdirSync(outputDirectory, { recursive: true });
for (const [file, data] of Object.entries(files)) writeFileSync(join(outputDirectory, file), data);
