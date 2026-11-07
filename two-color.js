/** Ordered coverage thresholds shared by tone and opacity in two-color hires. */
const TWO_COLOR_THRESHOLDS = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];

/** Source luma selects shadow/highlight coverage; output colors never affect that decision. */
function convertTwoColorHires(source, palette, colorIndices, ditherAmount = 1) {
  const colors = colorIndices.map(index => palette[index].rgb);
  const result = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  for (let pixel = 0; pixel < source.width * source.height; pixel += 1) {
    const offset = pixel * 4;
    if (source.data[offset + 3] === 0) continue;
    const x = pixel % source.width;
    const y = Math.floor(pixel / source.width);
    const ordered = (TWO_COLOR_THRESHOLDS[(y % 4) * 4 + x % 4] + 0.5) / 16;
    const threshold = 0.5 + (ordered - 0.5) * ditherAmount;
    const luma = (0.2126 * source.data[offset] + 0.7152 * source.data[offset + 1] +
      0.0722 * source.data[offset + 2]) / 255;
    result.data.set(colors[luma >= threshold ? 1 : 0], offset);
  }
  return result;
}

/** Hardware pixels are opaque: dither layer opacity instead of blending extra colors. */
function compositeTwoColorHires(images, width, height, shadowRgb) {
  const result = new ImageData(width, height);
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    const offset = pixel * 4;
    result.data.set([...shadowRgb, 255], offset);
    const x = pixel % width;
    const y = Math.floor(pixel / width);
    const threshold = (TWO_COLOR_THRESHOLDS[(y % 4) * 4 + x % 4] + 0.5) / 16;
    for (const image of images) {
      if (image.data[offset + 3] / 255 > threshold) {
        result.data.set(image.data.subarray(offset, offset + 3), offset);
      }
    }
  }
  return result;
}
