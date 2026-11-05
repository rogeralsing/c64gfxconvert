/** Image layers are stored bottom to top. Settings are owned by each layer. */
function createC64LayerStack(defaultSettings) {
  let nextId = 1;
  const layers = [];
  let selectedId;
  const copy = settings => structuredClone(settings);
  const active = () => layers.find(layer => layer.id === selectedId);
  function create({ name, autoName = !name, image = null, fileName = '', sourceDataUrl = '',
    visible = true, settings = defaultSettings } = {}) {
    return {
      id: nextId++, name: name || `Layer ${nextId - 1}`, autoName, image, fileName, sourceDataUrl,
      visible, settings: copy(settings), cache: null, loadRequest: 0
    };
  }
  function add(options) {
    const layer = create(options);
    const index = layers.findIndex(layer => layer.id === selectedId);
    layers.splice(index + 1, 0, layer);
    selectedId = layer.id;
    return layer;
  }
  add();
  return {
    layers, active,
    select(id) {
      if (!layers.some(layer => layer.id === id)) throw new Error('Unknown image layer.');
      selectedId = id;
      return active();
    },
    add,
    duplicate() {
      const layer = active();
      const result = add({ name: `${layer.name} copy`, image: layer.image,
        fileName: layer.fileName, sourceDataUrl: layer.sourceDataUrl, settings: layer.settings });
      result.visible = layer.visible;
      return result;
    },
    remove() {
      if (layers.length === 1) return active();
      const index = layers.indexOf(active());
      layers.splice(index, 1);
      selectedId = layers[Math.min(index, layers.length - 1)].id;
      return active();
    },
    move(direction) {
      const index = layers.indexOf(active());
      const next = Math.max(0, Math.min(layers.length - 1, index + direction));
      const [layer] = layers.splice(index, 1);
      layers.splice(next, 0, layer);
    },
    updateSettings(settings) {
      const layer = active();
      if (JSON.stringify(layer.settings) === JSON.stringify(settings)) return false;
      layer.settings = copy(settings);
      layer.cache = null;
      return true;
    },
    invalidate() {
      for (const layer of layers) layer.cache = null;
    },
    replace(entries, activeIndex) {
      if (!entries.length || !Number.isInteger(activeIndex) || activeIndex < 0 || activeIndex >= entries.length) {
        throw new Error('A project requires layers and a valid active layer.');
      }
      const restored = entries.map(create);
      layers.splice(0, layers.length, ...restored);
      selectedId = restored[activeIndex].id;
    }
  };
}

/** Straight-alpha source-over composition; inputs and hidden RGB are preserved for a single layer. */
function compositeC64LayerPixels(images, width, height) {
  if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0 ||
      images.some(image => image.width !== width || image.height !== height || image.data?.length !== width * height * 4)) {
    throw new Error('Layer images must have matching positive dimensions.');
  }
  if (images.length === 1) return new ImageData(new Uint8ClampedArray(images[0].data), width, height);
  const result = new ImageData(width, height);
  for (const image of images) {
    for (let offset = 0; offset < image.data.length; offset += 4) {
      const alpha = image.data[offset + 3] / 255;
      if (alpha === 0) continue;
      if (alpha === 1) {
        result.data.set(image.data.subarray(offset, offset + 4), offset);
        continue;
      }
      const below = result.data[offset + 3] / 255;
      const combined = alpha + below * (1 - alpha);
      for (let channel = 0; channel < 3; channel += 1) {
        result.data[offset + channel] = (image.data[offset + channel] * alpha +
          result.data[offset + channel] * below * (1 - alpha)) / combined;
      }
      result.data[offset + 3] = combined * 255;
    }
  }
  return result;
}

/** A foreground bitmap occludes sprites belonging to lower image layers too. */
function compositeC64LayerSprites(layers, colorIndex, rgb) {
  const spriteMask = new Uint8Array(64000);
  const spritePixels = new ImageData(320, 200);
  const thresholds = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
  for (const { source, mask } of layers) {
    if (source.width !== 320 || source.height !== 200 || source.data.length !== 256000 || mask.length !== 64000) {
      throw new Error('Sprite image layers require 320 × 200 source pixels and matching masks.');
    }
    if (layers.length === 1) {
      spriteMask.set(mask);
      continue;
    }
    for (let pixel = 0; pixel < 64000; pixel += 1) {
      const alpha = source.data[pixel * 4 + 3] / 255;
      const x = pixel % 320;
      const y = Math.floor(pixel / 320);
      if (alpha > (thresholds[y % 4][x % 4] + 0.5) / 16) spriteMask[pixel] = mask[pixel];
    }
  }
  let spritePixelCount = 0;
  for (let pixel = 0; pixel < 64000; pixel += 1) {
    if (!spriteMask[pixel]) continue;
    spritePixels.data.set([...rgb, 255], pixel * 4);
    spritePixelCount++;
  }
  return { spriteMask, spritePixels, spriteColorIndex: colorIndex, spritePixelCount };
}
