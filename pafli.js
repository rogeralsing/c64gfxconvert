/**
 * PAFLI (Phase-Alternating FLI) fits two full-resolution AFLI images.
 * The second source moves left by four hires pixels before the same AFLI fit.
 * Playback moves that bitmap right by four, cancelling the artwork movement
 * while shifting its 8 × 1 color-cell boundaries. No sampling or averaging
 * happens before fitting. Virtual colors, if enabled, are resolved upstream
 * with exactly the same row parity as AFLI Virtual.
 */
function optimizePafliImages(source, palette, brightnessBands) {
  if (source?.width !== 320 || source.height !== 200 || source.data?.length !== 256000) {
    throw new Error('PAFLI requires a 320 × 200 source image.');
  }
  const first = new ImageData(new Uint8ClampedArray(source.data), 320, 200);
  const second = new ImageData(320, 200);
  const masks = [new Uint8Array(64000), new Uint8Array(64000)];
  for (let y = 0; y < 200; y += 1) {
    const start = y * 320 * 4;
    second.data.set(source.data.subarray(start + 16, start + 1280), start);
    // Keep the same black matte as AFLI. These padded columns are clipped
    // when phase B is positioned on screen, rather than wrapping around.
    for (let x = 316; x < 320; x += 1) {
      second.data.set([...palette[0].rgb, 255], start + x * 4);
    }
    // Reuse AFLI's coverage weights to exclude pixels outside the common
    // display area. Invisible padding must not consume a fitted row color.
    masks[0].fill(1, y * 320, y * 320 + 28);
    masks[1].fill(1, y * 320, y * 320 + 24);
    masks[1].fill(1, y * 320 + 316, y * 320 + 320);
  }
  const frames = [first, second].map((pixels, phase) =>
    optimizeAfliImage(pixels, palette, brightnessBands, masks[phase]));
  // Reserve the last character row as black data, including both color slots.
  // Clearing bitmap bits alone would expose its paper color during the tail.
  for (const frame of frames) {
    frame.rowColors.fill(0, 24 * 40 * 8 * 2);
    for (let offset = 192 * 320 * 4; offset < frame.pixels.data.length; offset += 4) {
      frame.pixels.data.set(palette[0].rgb, offset);
      frame.pixels.data[offset + 3] = 255;
    }
  }
  const displayFrames = frames.map((frame, phase) => alignPafliFrame(frame.pixels, phase, palette[0].rgb));
  const blended = new ImageData(320, 200);
  for (let offset = 0; offset < blended.data.length; offset += 4) {
    for (let channel = 0; channel < 3; channel += 1) {
      blended.data[offset + channel] = Math.round((displayFrames[0].data[offset + channel] +
        displayFrames[1].data[offset + channel]) / 2);
    }
    blended.data[offset + 3] = 255;
  }
  return { frames, displayFrames, blended };
}

/** Display phase B at +4, hiding the common 28-pixel AFLI hardware strip. */
function alignPafliFrame(source, phase, matteRgb) {
  if (source?.width !== 320 || source.height !== 200 || source.data?.length !== 256000 ||
      (phase !== 0 && phase !== 1)) {
    throw new Error('PAFLI alignment requires a 320 × 200 frame and phase 0 or 1.');
  }
  const display = new ImageData(320, 200);
  for (let y = 0; y < 200; y += 1) {
    for (let x = 0; x < 320; x += 1) {
      const destination = (y * 320 + x) * 4;
      if (x < 28) {
        display.data.set(matteRgb, destination);
        display.data[destination + 3] = 255;
      } else {
        const offset = (y * 320 + x - phase * 4) * 4;
        display.data.set(source.data.subarray(offset, offset + 4), destination);
      }
    }
  }
  return display;
}
