var FourPhaseMotion = (({ CHAR_HEIGHT, CHAR_WIDTH, TILE_CHARS, Y_STEP, charset, phaseTiles }) => {
  const PHASE_COUNT = 256;
  const SOURCE_BALLS = 64;
  const SCREEN_COLUMNS = 40;
  const SCREEN_ROWS = 25;
  const DEFAULT_LIVE_BALL_COUNT = 33;
  const DEFAULT_LIVE_SAMPLING = 'uniform';
  const RETAINED_LIVE_BALL_COUNT = 21;
  const TOP_SPRITE_COUNT = 8;
  const phaseMask = PHASE_COUNT - 1;
  const preferredAdditions = [2, 14, 52, 23, 56, 5, 61, 34, 39, 15, 48];
  const sine = Uint8Array.from({ length: PHASE_COUNT }, (_, index) =>
    Math.round(63.5 + 63.5 * Math.sin(index * Math.PI / 128))
  );
  const glyphCoverage = new Uint32Array(charset.length);
  const coveringGlyphs = new Uint8Array(charset.length);
  for (const [code, glyph] of charset.entries()) {
    let mask = 0;
    let visiblePixels = 0;
    for (const [row, byte] of glyph.entries()) {
      for (let x = 0; x < CHAR_WIDTH; x++) {
        if (byte & (3 << (2 * (CHAR_WIDTH - 1 - x)))) {
          mask |= 1 << (row * CHAR_WIDTH + x);
          visiblePixels++;
        }
      }
    }
    glyphCoverage[code] = mask;
    coveringGlyphs[code] = visiblePixels >= CHAR_WIDTH * CHAR_HEIGHT - 1;
  }

  function selectSources(count, sampling) {
    const sources = Array.from({ length: count }, (_, ball) => {
      if (sampling === 'uniform') return Math.round((SOURCE_BALLS - 1) * ball / (count - 1));
      const offset = sampling === 'midpoint' ? 0.5 : (ball % 2 === 0 ? 0.25 : 0.75);
      return Math.floor(SOURCE_BALLS * (ball + offset) / count);
    });
    if (new Set(sources).size !== count) throw new Error(`${sampling} sampling repeats source indices for ${count} balls.`);
    return sources;
  }

  function selectLiveSources(count = DEFAULT_LIVE_BALL_COUNT, sampling = DEFAULT_LIVE_SAMPLING) {
    const minimum = sampling === 'retain21' ? RETAINED_LIVE_BALL_COUNT : 2;
    if (!['retain21', 'uniform'].includes(sampling) ||
      !Number.isInteger(count) || count < minimum || count > SOURCE_BALLS) {
      throw new RangeError(`Invalid live sampling or count: ${sampling}, ${count}.`);
    }
    if (sampling === 'uniform') return selectSources(count, 'uniform');

    const originals = selectSources(RETAINED_LIVE_BALL_COUNT, 'uniform');
    const selected = new Set([...originals, ...preferredAdditions]);
    const additions = preferredAdditions.slice();
    for (let source = 0; source < SOURCE_BALLS; source++) {
      if (!selected.has(source)) additions.push(source);
    }
    return originals.concat(additions.slice(0, count - RETAINED_LIVE_BALL_COUNT)).sort((a, b) => a - b);
  }

  function selectSpriteSources(charSources) {
    const last = charSources.at(-1);
    const step = last - charSources.at(-2);
    return Array.from({ length: TOP_SPRITE_COUNT }, (_, i) => (last + (i + 1) * step) & phaseMask);
  }

  function placeBall(frame, source) {
    const x1 = (frame + 3 * source) & phaseMask;
    const x2 = (47 - 2 * frame + 5 * source) & phaseMask;
    const y1 = (83 + 3 * frame + 2 * source) & phaseMask;
    const y2 = (167 - 4 * frame + 7 * source) & phaseMask;
    // Match the 6502 motionQuantX and motionQuantY tables.
    const x = 4 + Math.floor((144 * (sine[x1] + sine[x2]) + 127) / 254);
    const y = 2 * (8 + Math.floor((76 * (sine[y1] + sine[y2]) + 127) / 254));
    const phase = (y % CHAR_HEIGHT / Y_STEP) * CHAR_WIDTH + x % CHAR_WIDTH;
    const origin = Math.floor(y / CHAR_HEIGHT) * SCREEN_COLUMNS + Math.floor(x / CHAR_WIDTH);
    return { x, y, phase, origin };
  }

  function plotFrame(frame, sources = selectLiveSources(), patching = false) {
    const screen = new Uint8Array(SCREEN_COLUMNS * SCREEN_ROWS);
    const hits = new Uint8Array(screen.length);
    const coverage = new Uint32Array(screen.length);
    const missingPixels = new Uint32Array(screen.length);
    const patchedCells = new Uint8Array(screen.length);
    const font = patching ? charset.slice() : charset;
    const ballPositions = Array.from(sources, source => ({ source, ...placeBall(frame, source) }));
    for (const { phase, origin } of ballPositions) {
      for (const [slot, glyph] of phaseTiles[phase].entries()) {
        if (glyph === 0) continue;
        const cell = origin + Math.floor(slot / TILE_CHARS) * SCREEN_COLUMNS + slot % TILE_CHARS;
        const back = screen[cell];
        screen[cell] = glyph;
        hits[cell]++;
        const visible = glyphCoverage[glyph];
        missingPixels[cell] = coverage[cell] & ~visible;
        coverage[cell] |= visible;

        if (!patching) continue;
        patchedCells[cell] = 0;
        if (back === 0 || back === glyph || coveringGlyphs[glyph]) continue;
        const code = back < charset.length ? font.length : back;
        if (code === 256) continue;

        const bitmap = font[code] ?? new Uint8Array(CHAR_HEIGHT);
        for (const [row, front] of charset[glyph].entries()) {
          const occupied = (front | (front >> 1)) & 0x55;
          const under = font[back][row] & ~(occupied | (occupied << 1));
          bitmap[row] = front | under;
          if (under) patchedCells[cell] = 1;
        }
        font[code] = bitmap;
        screen[cell] = code;
      }
    }
    return { screen, hits, missingPixels, ballPositions, font, patchedCells };
  }

  return {
    PHASE_COUNT, SOURCE_BALLS, SCREEN_COLUMNS, SCREEN_ROWS, DEFAULT_LIVE_BALL_COUNT, DEFAULT_LIVE_SAMPLING,
    RETAINED_LIVE_BALL_COUNT, sine, coveringGlyphs, placeBall, selectSources, selectLiveSources, selectSpriteSources, plotFrame,
  };
})(typeof module === 'undefined' ? BallTiles : require('./ball-tiles.js'));

if (typeof module !== 'undefined') module.exports = FourPhaseMotion;
