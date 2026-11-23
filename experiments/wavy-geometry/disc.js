"use strict";

(() => {
  const turn = 2 * Math.PI;
  const radians = (degrees) => degrees * Math.PI / 180;

  function createGeometry({ width, height }) {
    const depth = 240;
    const focalLength = 270;
    const innerRadius = 34;
    const outerRadius = 101;
    const tilt = radians(55);
    const roll = radians(14);
    const cosTilt = Math.cos(tilt);
    const sinTilt = Math.sin(tilt);
    const cosRoll = Math.cos(roll);
    const sinRoll = Math.sin(roll);
    const scaleX = 320 / width;
    const scaleY = 200 / height;

    return (x, y) => {
      const rayX = (x * scaleX - 173) / focalLength;
      const rayY = (y * scaleY - 73) / focalLength;

      // Rotate the camera ray into the disc's horizontal and tilted axes.
      const horizontal = cosRoll * rayX + sinRoll * rayY;
      const vertical = cosRoll * rayY - sinRoll * rayX;
      const normal = cosTilt + sinTilt * vertical;
      if (normal <= 0) return null;

      // The plane passes through (0, 0, depth). Intersect the ray with
      // it to recover the position on the record in world units.
      const distance = depth * cosTilt / normal;
      const across = distance * vertical / cosTilt;
      const along = distance * horizontal;
      const radius = Math.hypot(along, across);
      if (radius < innerRadius || radius > outerRadius) return null;

      // Place the wrap at the far side, away from the record's near edge.
      const angle = Math.atan2(across, along) / turn + 0.25;
      return [angle - Math.floor(angle), (radius - innerRadius) / (outerRadius - innerRadius)];
    };
  }

  const disc = { createGeometry, wrapU: true };
  if (typeof module !== "undefined" && module.exports) module.exports = disc;
  else (globalThis.WavyGeometry ??= {}).disc = disc;
})();
