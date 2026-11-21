/** Search sprite palettes and normal-width placement off the editor's main thread. */
importScripts('./color-math.js?v=1', './ifli.js?v=talent-shadow-patterns',
  './talent-mapping.js?v=talent-shadow-patterns', './virtual-color-mapping.js?v=1',
  './layers.js?v=tile-markers', './border-sprites.js?v=normal-placement',
  './border-color-optimizer.js?v=normal-placement');

self.onmessage = event => {
  const { generation, source, palette, settings, backgroundColorIndex, interlaced, options } = event.data;
  try {
    const colorPlan = optimizeC64BorderColors(source, palette, settings, backgroundColorIndex,
      interlaced, { ...options, onProgress(progress) {
        self.postMessage({ generation, type: 'progress', progress });
      } });
    self.postMessage({ generation, type: 'complete', colorPlan });
  } catch (error) {
    self.postMessage({ generation, type: 'error', message: error.message });
  }
};
