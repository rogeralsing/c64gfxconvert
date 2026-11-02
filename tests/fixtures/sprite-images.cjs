const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class ImageData {
  constructor(data, width, height) {
    if (typeof data === 'number') {
      this.width = data;
      this.height = width;
      this.data = new Uint8ClampedArray(data * width * 4);
    } else {
      this.data = data;
      this.width = width;
      this.height = height;
    }
  }
}

function srgbToLinear(channel) {
  const value = channel / 255;
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}
function linearToSrgb(value) {
  return 255 * (value <= 0.0031308 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - 0.055);
}
function rgbToOklab(red, green, blue) {
  const [r, g, b] = [red, green, blue].map(srgbToLinear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return {
    lightness: 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    a: 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    b: 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
  };
}
const palette = [
  [0, 0, 0], [255, 255, 255], [150, 40, 46], [91, 214, 206],
  [159, 45, 173], [65, 185, 54], [39, 36, 196], [239, 243, 71],
  [159, 72, 21], [94, 53, 0], [218, 95, 102], [71, 71, 71],
  [120, 120, 120], [145, 255, 132], [104, 100, 255], [174, 174, 174]
].map((rgb, index) => ({ index, rgb }));
const bands = [[0], [6, 9], [2, 11], [4, 8], [14, 12], [5, 10], [3, 15], [13, 7], [1]]
  .map(indices => {
    const colors = indices.map(index => ({ color: palette[index], lab: rgbToOklab(...palette[index].rgb) }));
    return { colors, lightness: colors.reduce((sum, entry) => sum + entry.lab.lightness, 0) / colors.length };
  });

function createContext(files) {
  const context = vm.createContext({
    ImageData, Uint8Array, Uint8ClampedArray, rgbToOklab, srgbToLinear, linearToSrgb
  });
  for (const file of files) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', '..', file), 'utf8'), context);
  }
  return context;
}

function image(rgb = palette[0].rgb, width = 320) {
  const pixels = new ImageData(width, 200);
  for (let offset = 0; offset < pixels.data.length; offset += 4) pixels.data.set([...rgb, 255], offset);
  return pixels;
}
function setPixel(pixels, x, y, rgba) {
  pixels.data.set(rgba.length === 3 ? [...rgba, 255] : rgba, (y * pixels.width + x) * 4);
}

module.exports = { ImageData, palette, bands, rgbToOklab, createContext, image, setPixel };
