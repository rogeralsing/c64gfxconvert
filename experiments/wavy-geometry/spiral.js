"use strict";

(function () {
  function createGeometry({ width, height }) {
    const horizontalScale = width / 320;
    const verticalScale = height / 200;
    const axisLength = Math.hypot(222, 76);
    const axisX = 222 / axisLength;
    const axisY = 76 / axisLength;
    const centerX = 175;
    const centerY = 98;
    const pitch = 85;
    const endPitch = 42;
    const ribbonWidth = 57;
    const depthShift = 8;
    const tubeRadius = 40;
    const startAngle = -0.7;
    const endAngle = 2.58;
    const middleStart = -0.25;
    const middleEnd = 2;
    const angleCenter = (middleStart + middleEnd) / 2;
    const halfBand = ribbonWidth / 2;

    function intersect(along, angle, rear) {
      for (let turn = Math.ceil(startAngle - angle); turn <= Math.floor(endAngle - angle); turn++) {
        const winding = turn + angle;
        // The extra turns curve around the tips without using the full pitch.
        const middle = Math.max(middleStart, Math.min(middleEnd, winding));
        const center = pitch * (middle - angleCenter) + endPitch * (winding - middle);
        const across = along - center;
        if (Math.abs(across) > halfBand) continue;

        const u = (winding - startAngle) / (endAngle - startAngle);
        const v = (across + halfBand) / ribbonWidth;
        return { uv: [u, v], rear };
      }
      return null;
    }

    function sampleFace(x, y) {
      const localX = x / horizontalScale - centerX;
      const localY = y / verticalScale - centerY;
      const along = localX * axisX + localY * axisY;
      const tubeY = (-localX * axisY + localY * axisX) / tubeRadius;
      if (Math.abs(tubeY) > 1) return null;

      const frontAngle = Math.asin(tubeY) / (2 * Math.PI);
      const rearAngle = 0.5 - frontAngle;
      const depth = depthShift * Math.sqrt(1 - tubeY * tubeY);

      // Both intersections use the same winding. Their opposite angular
      // directions mirror the tape on the back. The front hides it at overlaps.
      return intersect(along - depth, frontAngle, false) ?? intersect(along + depth, rearAngle, true);
    }

    // Each multicolor pixel spans two display pixels horizontally.
    const pixelWidth = 2 * horizontalScale;
    const pixelHeight = verticalScale;

    return (x, y) => {
      const face = sampleFace(x, y);
      if (!face) return null;
      if (face.rear) {
        const checker = Math.floor(x / pixelWidth) + Math.floor(y / pixelHeight);
        return checker % 2 === 0 ? face.uv : null;
      }

      // Cut the front edge where it touches the rear. Test the rear geometry
      // before checker masking so the black cut stays connected.
      if (sampleFace(x - pixelWidth, y)?.rear || sampleFace(x + pixelWidth, y)?.rear ||
          sampleFace(x, y - pixelHeight)?.rear || sampleFace(x, y + pixelHeight)?.rear) return null;
      return face.uv;
    };
  }

  const spiral = { createGeometry };
  if (typeof module === "object" && module.exports) {
    module.exports = spiral;
  } else {
    globalThis.WavyGeometry ??= {};
    globalThis.WavyGeometry.spiral = spiral;
  }
})();
