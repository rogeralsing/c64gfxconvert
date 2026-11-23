(function () {
  "use strict";

  function createGeometry({ width, height }) {
    const mouthX = width * 0.54;
    const mouthY = height * 0.475;
    const radiusX = width * 0.44;
    const radiusY = height * 0.37;
    const vanishX = width * 0.48;
    const vanishY = height * 0.43;
    const axisX = (mouthX - vanishX) / radiusX;
    const axisY = (mouthY - vanishY) / radiusY;
    const axisFactor = 1 - axisX * axisX - axisY * axisY;
    const farScale = 0.42;
    const farLogScale = Math.log(farScale);

    return function sample(x, y) {
      const dx = (x - vanishX) / radiusX;
      const dy = (y - vanishY) / radiusY;
      const dot = dx * axisX + dy * axisY;
      // A cylinder cross-section at inverse depth s projects with center
      // s * axis and radius s. Solve |(dx, dy) - s * axis|² = s².
      const scale = (Math.sqrt(dot * dot + axisFactor * (dx * dx + dy * dy)) - dot) / axisFactor;
      if (scale < farScale || scale > 1) return null;

      const angle = Math.atan2(dy - scale * axisY, dx - scale * axisX);
      const v = (angle / (2 * Math.PI) + 1.75) % 1;
      // Logarithmic depth keeps the inner bands wide enough to read through
      // perspective. Advancing the texture moves them towards the mouth.
      const u = Math.log(scale) / farLogScale;
      return [u, v];
    };
  }

  const geometry = { createGeometry };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = geometry;
  } else {
    globalThis.WavyGeometry ??= {};
    globalThis.WavyGeometry.tunnel = geometry;
  }
})();
