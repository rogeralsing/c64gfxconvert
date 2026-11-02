/**
 * Feather horizontal interlace-line ends before the hardware fit.
 * Each transition stays inside a strip at most 15 logical pixels wide. The
 * interiors of long runs remain solid. An opaque solid run qualifies only
 * when every pixel directly above and below has the same different color,
 * also present immediately to its left or right. Every edit exchanges two
 * existing RGBA pixels, preserving their counts and mean RGB.
 * All detection reads the original image, so new dither cannot expand the
 * affected region. No second stripe or absolute even/odd row parity is needed.
 */
function breakUpScanlines(source) {
  const { width, height, data } = source ?? {};
  if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0 ||
      !data || data.length !== width * height * 4) {
    throw new Error('Scanline dithering requires positive dimensions and matching RGBA pixels.');
  }
  const output = new ImageData(new Uint8ClampedArray(data), width, height);
  const keys = new Int32Array(width * height);
  for (let p = 0; p < keys.length; p += 1) {
    const offset = p * 4;
    keys[p] = data[offset + 3] === 255
      ? data[offset] | data[offset + 1] << 8 | data[offset + 2] << 16 : -1;
  }
  // Positions 0, 2, 5 leave 1-, 2-, and 3-pixel gaps around a nine-pixel
  // repeat. Mirror the exchanges into both sides and stagger neighboring lines.
  const scatter = [1, 0, 1, 0, 0, 1, 0, 0, 0];
  const changed = new Uint8Array(keys.length);
  const color = (x, y) => keys[y * width + x];
  // Both neighboring rows must exist, so the image's outer rows cannot qualify.
  for (let y = 1; y + 1 < height; y += 1) {
    const runs = [];
    for (let start = 0; start < width;) {
      const value = color(start, y);
      let end = start + 1;
      while (end < width && color(end, y) === value) end += 1;
      runs.push({ start, end, value });
      start = end;
    }
    for (let i = 0; i < runs.length; i += 1) {
      const run = runs[i];
      const background = color(run.start, y - 1);
      if (run.value < 0 || background < 0 || background === run.value) continue;
      let enclosed = true;
      for (let x = run.start; x < run.end; x += 1) {
        if (color(x, y - 1) !== background || color(x, y + 1) !== background) {
          enclosed = false;
          break;
        }
      }
      if (!enclosed) continue;
      for (const side of [-1, 1]) {
        const flank = runs[i + side];
        if (!flank || flank.value !== background) continue;
        const boundary = side === -1 ? run.start : run.end;
        // Keep the same 15-pixel endpoint limit. Only the stripe's half-run
        // needs reserving; even a narrow matching flank can supply one pixel.
        const radius = Math.min(7, Math.floor((run.end - run.start) / 2), flank.end - flank.start);
        const stagger = radius > 1 ? (y >> 1) & 1 : 0;
        for (let distance = 0; distance < radius; distance += 1) {
          if (!scatter[(distance + 9 - stagger) % scatter.length]) continue;
          const a = y * width + boundary - 1 - distance;
          const b = y * width + boundary + distance;
          if (changed[a] || changed[b]) continue;
          output.data.set(data.subarray(b * 4, b * 4 + 4), a * 4);
          output.data.set(data.subarray(a * 4, a * 4 + 4), b * 4);
          changed[a] = changed[b] = 1;
        }
      }
    }
  }
  return output;
}
