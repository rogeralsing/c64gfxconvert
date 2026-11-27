const BallTiles = (() => {
  const TILE_CHARS = 3;
  const BALL_CHARS = 2;
  const CHAR_WIDTH = 4; // One multicolor pixel is two physical pixels wide.
  const CHAR_HEIGHT = 8;
  const TILE_WIDTH = TILE_CHARS * CHAR_WIDTH;
  const TILE_HEIGHT = TILE_CHARS * CHAR_HEIGHT;
  const BALL_WIDTH = BALL_CHARS * CHAR_WIDTH;
  const BALL_HEIGHT = BALL_CHARS * CHAR_HEIGHT;
  const Y_STEP = 2;

  // Multicolor char order: background, shared colors 1 and 2, per-char color.
  // Colodore PAL colors 0, 14, 3 and 6 from palettes.js.
  const palette = [
    ['#000000', 'Svart'],
    ['#6864ff', 'Ljusblå'],
    ['#5bd6ce', 'Cyan'],
    ['#2724c4', 'Blå'],
  ];
  const shadeCodes = [0, 3, 1, 2]; // Palette codes from darkest to brightest.
  const bayer = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
  ];

  function spherePixel(x, y) {
    const samplesPerAxis = 8;
    const sampleCount = samplesPerAxis ** 2;
    let covered = 0;
    let tone = 0;

    // Outside samples contribute black, softening the silhouette at partial coverage.
    for (let sy = 0; sy < samplesPerAxis; sy++) {
      const vertical = 2 * (y + (sy + 0.5) / samplesPerAxis) / BALL_HEIGHT - 1;
      for (let sx = 0; sx < samplesPerAxis; sx++) {
        const horizontal = 2 * (x + (sx + 0.5) / samplesPerAxis) / BALL_WIDTH - 1;
        const radiusSquared = horizontal ** 2 + vertical ** 2;
        if (radiusSquared > 1) continue;

        const depth = Math.sqrt(1 - radiusSquared);
        const light = Math.max(0, -0.43 * horizontal - 0.55 * vertical + 0.72 * depth);
        tone += 1 + 1.55 * light + 0.65 * light ** 9;
        covered++;
      }
    }

    const coverage = covered / sampleCount;
    if (coverage < 0.25) return shadeCodes[0];

    // Anchor the dither to the ball and taper it at the silhouette.
    const threshold = (bayer[(y + 3) % 4][x % 4] + 0.5) / 16 - 0.5;
    const shade = Math.round(tone / sampleCount - 0.75 * coverage ** 2 * threshold);
    return shadeCodes[Math.max(1, Math.min(3, shade))];
  }

  const sphere = Array.from({ length: BALL_HEIGHT }, (_, y) =>
    Uint8Array.from({ length: BALL_WIDTH }, (_, x) => spherePixel(x, y))
  );
  const charset = [new Uint8Array(CHAR_HEIGHT)];
  const charCodes = new Map([[charset[0].join(','), 0]]);

  function rasterizeTile(offsetX, offsetY) {
    // Glyphs are stored in row order, each with eight bytes of four 2-bit pixels.
    const tileCells = TILE_CHARS ** 2;
    const glyphs = new Uint8Array(tileCells * CHAR_HEIGHT);
    const visiblePixels = new Uint8Array(tileCells);
    sphere.forEach((row, y) => {
      const tileY = offsetY + y;
      row.forEach((color, x) => {
        if (color === 0) return;
        const tileX = offsetX + x;
        const charX = Math.floor(tileX / CHAR_WIDTH);
        const charY = Math.floor(tileY / CHAR_HEIGHT);
        const glyph = charY * TILE_CHARS + charX;
        visiblePixels[glyph]++;
        const byte = glyph * CHAR_HEIGHT + tileY % CHAR_HEIGHT;
        const shift = 2 * (CHAR_WIDTH - 1 - tileX % CHAR_WIDTH);
        glyphs[byte] |= color << shift;
      });
    });
    return Array.from({ length: tileCells }, (_, slot) => {
      if (visiblePixels[slot] <= 1) return charset[0];
      const start = slot * CHAR_HEIGHT;
      return glyphs.subarray(start, start + CHAR_HEIGHT);
    });
  }

  function encodeTile(glyphs) {
    return Uint8Array.from(glyphs, glyph => {
      const key = glyph.join(',');
      if (!charCodes.has(key)) {
        if (charset.length === 256) throw new Error('Ball tiles exceed the 256-character charset.');
        charCodes.set(key, charset.length);
        charset.push(glyph);
      }
      return charCodes.get(key);
    });
  }

  // Y phase first, then X phase. Each entry is a row-major 3×3 tile.
  const phaseGlyphs = [];
  for (let y = 0; y < CHAR_HEIGHT; y += Y_STEP) {
    for (let x = 0; x < CHAR_WIDTH; x++) phaseGlyphs.push(rasterizeTile(x, y));
  }
  // Reuse the middle-right glyph from X=1, Y=4 at Y=2 and Y=6.
  const middleRight = 2 * TILE_CHARS - 1;
  const sharedRight = phaseGlyphs[2 * CHAR_WIDTH + 1][middleRight];
  phaseGlyphs[CHAR_WIDTH + 1][middleRight] = sharedRight;
  phaseGlyphs[3 * CHAR_WIDTH + 1][middleRight] = sharedRight;
  const phaseTiles = phaseGlyphs.map(encodeTile);

  const sprite = new Uint8Array(64);
  for (let y = 0; y < BALL_HEIGHT; y++) {
    const rowStart = Math.floor(y / CHAR_HEIGHT) * TILE_CHARS;
    for (let column = 0; column < BALL_CHARS; column++) {
      const glyph = phaseTiles[0][rowStart + column];
      sprite[y * 3 + column] = charset[glyph][y % CHAR_HEIGHT];
    }
  }

  function tileAt(offsetX, offsetY) {
    const shiftX = Math.floor(offsetX / CHAR_WIDTH);
    const shiftY = Math.floor(offsetY / CHAR_HEIGHT);
    const phase = offsetY % CHAR_HEIGHT / Y_STEP * CHAR_WIDTH + offsetX % CHAR_WIDTH;
    const tile = phaseTiles[phase];
    if (shiftX === 0 && shiftY === 0) return tile;

    return tile.map((_, slot) => {
      const x = slot % TILE_CHARS - shiftX;
      const y = Math.floor(slot / TILE_CHARS) - shiftY;
      return x < 0 || y < 0 ? 0 : tile[y * TILE_CHARS + x];
    });
  }

  return {
    CHAR_WIDTH, CHAR_HEIGHT, TILE_CHARS, TILE_WIDTH, TILE_HEIGHT, BALL_WIDTH, BALL_HEIGHT,
    Y_STEP, palette, charset, phaseTiles, sprite, tileAt,
  };
})();

if (typeof module !== 'undefined') module.exports = BallTiles;
