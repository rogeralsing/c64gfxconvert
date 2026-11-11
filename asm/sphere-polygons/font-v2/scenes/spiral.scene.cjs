'use strict';

// Edit this function to script the scene. Positions and diameters are physical
// screen pixels; yaw, pitch and roll are radians. Rendering samples t = i/fps.
const clamp = value => Math.max(0, Math.min(1, value));
const smooth = value => value * value * (3 - 2 * value);
const interpolate = (start, startSpeed, end, endSpeed, progress) => {
  const p2 = progress * progress, p3 = p2 * progress;
  return (2 * p3 - 3 * p2 + 1) * start + (p3 - 2 * p2 + progress) * startSpeed
    + (-2 * p3 + 3 * p2) * end + (p3 - p2) * endSpeed;
};
const tumble = time => ({
  yaw: 0.5 + 0.9 * time + 0.18 * Math.sin(1.4 * time),
  pitch: 0.35 + 1.2 * time,
  roll: 0.15 + 0.75 * time + 0.22 * Math.sin(1.1 * time)
});
const fps = 25, checks = 14, introSeconds = 5, loopFrames = 32;
// Two checker columns repeat the same colors: no full 360-degree turn needed.
const periodRadians = 4 * Math.PI / checks;
const spinSpeed = periodRadians / (loopFrames / fps);
const settleStart = tumble(4);
const startSpeeds = {
  yaw: 0.9 + 0.252 * Math.cos(1.4 * 4),
  pitch: 1.2,
  roll: 0.75 + 0.242 * Math.cos(1.1 * 4)
};
const settled = {
  yaw: settleStart.yaw + (startSpeeds.yaw + spinSpeed) / 2,
  pitch: 2 * Math.PI + 0.65,
  roll: 5 * Math.PI / 4
};

module.exports = {
  name: 'spiral',
  width: 320,
  height: 200,
  fps,
  durationSeconds: introSeconds + loopFrames / fps,
  introSeconds,
  loop: {startFrame: introSeconds * fps, frameCount: loopFrames, periodRadians},
  checks,
  growSeconds: 3,
  frame(time) {
    const progress = clamp((time - 0.12) / (this.growSeconds - 0.12));
    const approach = smooth(progress);
    const helix = 26 * Math.sin(Math.PI * progress) ** 2;
    const winding = 4 * Math.PI * progress;
    let rotation = tumble(time);
    if (time >= 4 && time < introSeconds) {
      const settling = time - 4;
      rotation = Object.fromEntries(['yaw', 'pitch', 'roll'].map(axis => [axis,
        interpolate(settleStart[axis], startSpeeds[axis], settled[axis],
          axis === 'yaw' ? spinSpeed : 0, settling)]));
    } else if (time >= introSeconds) {
      // Snap numerical noise at sample boundaries so every loop renders alike.
      const frame = (time - introSeconds) * fps;
      const nearest = Math.round(frame);
      const sample = Math.abs(frame - nearest) < 1e-8 ? nearest : frame;
      const phase = ((sample % loopFrames) + loopFrames) % loopFrames / loopFrames;
      rotation = {...settled, yaw: settled.yaw + periodRadians * phase};
    }
    return {
      visible: time > 0,
      phase: time < this.growSeconds ? 'grow' : time < 4 ? 'tumble'
        : time < introSeconds ? 'settle' : 'spin',
      centerX: 33 + (210 - 33) * approach + helix * Math.cos(winding),
      centerY: 97 + (100 - 97) * approach + helix * Math.sin(winding),
      // Size grows linearly so the initial dot promptly gains visible pixels;
      // only the journey uses easing.
      diameter: time <= 0 ? 0 : 4 + (96 - 4) * clamp(time / this.growSeconds),
      // Keep tumbling around all three axes throughout the entrance.
      // Unequal speeds keep the axis moving before it settles into a fixed tilt.
      ...rotation
    };
  }
};
