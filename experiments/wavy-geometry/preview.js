"use strict";

const data = JSON.parse(document.getElementById("data").textContent);
const { width, height, columns, palette, pattern } = data;
const rowBytes = 1000;
const period = rowBytes + 1 - columns;
const stride = columns + 1;
const fixedBlack = 0xff00;
const bytes = (value) => Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
const words = (value) => {
  const raw = bytes(value);
  const view = new DataView(raw.buffer);
  return Uint16Array.from({ length: raw.length / 2 }, (_, index) => view.getUint16(index * 2, true));
};
const tape = bytes(data.colors);

function decode([bitmapData, ownerData, targetData]) {
  const bitmap = bytes(bitmapData);
  const owners = words(ownerData);
  const fitted = new Uint16Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const cell = (y >> 3) * (width / 4) + (x >> 2);
      const code = (bitmap[cell * 8 + (y & 7)] >> ((3 - (x & 3)) * 2)) & 3;
      const slot = code === 3 ? 4 : ((y & 7) >= 4 ? 2 : 0) + code - 1;
      fitted[y * width + x] = code ? owners[cell * 5 + slot] : fixedBlack;
    }
  }
  return { fitted, target: words(targetData) };
}

const shapes = data.shapes.map((shape) => ({ ...shape, phases: shape.phases.map(decode) }));
const canvas = document.getElementById("screen");
const slider = document.getElementById("position");
const output = document.querySelector("output");
const view = document.getElementById("view");
const texture = document.getElementById("texture");
const play = document.getElementById("play");
const program = document.getElementById("program");
const nav = document.querySelector("nav");
const context = canvas.getContext("2d");
canvas.width = width;
canvas.height = height;
const image = context.createImageData(width, height);
const colors = image.data;
const positionCount = period * 2;

let current = shapes[0];
let position = 0;
let playing = true;
let previousDraw = 0;
slider.max = positionCount - 1;

function draw() {
  const offset = position >> 1;
  const references = current.phases[position & 1][view.value];
  for (let pixel = 0; pixel < references.length; pixel += 1) {
    const reference = references[pixel];
    let color = reference & 15;
    if (reference < fixedBlack) {
      const row = Math.floor(reference / stride);
      const column = offset + reference % stride;
      color = texture.value === "tape"
        ? tape[row * rowBytes + column % period]
        : pattern[row % pattern.length][column % pattern[0].length];
    }
    const [red, green, blue] = palette[color];
    const at = pixel * 4;
    colors[at] = red;
    colors[at + 1] = green;
    colors[at + 2] = blue;
    colors[at + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  slider.value = position;
  output.value = (position / 2).toLocaleString("sv-SE", { maximumFractionDigits: 1 });
}

function selectShape(shape) {
  current = shape;
  previousDraw = performance.now();
  for (const button of nav.children) button.setAttribute("aria-pressed", button.value === shape.id);
  canvas.setAttribute("aria-label", shape.title);
  program.href = `./${shape.id}/wave-four-line-scroll.prg`;
  program.download = `${shape.id}.prg`;
  draw();
}

function setPlaying(value) {
  playing = value;
  previousDraw = performance.now();
  play.textContent = playing ? "Pausa" : "Spela";
}

for (const shape of shapes) {
  const button = document.createElement("button");
  button.type = "button";
  button.value = shape.id;
  button.textContent = shape.title;
  button.addEventListener("click", () => selectShape(shape));
  nav.append(button);
}
play.addEventListener("click", () => setPlaying(!playing));
slider.addEventListener("input", () => {
  setPlaying(false);
  position = Number(slider.value);
  draw();
});
view.addEventListener("change", draw);
texture.addEventListener("change", draw);
selectShape(current);
setPlaying(true);

function tick(time) {
  const millisecondsPerStep = current.fields * 1000 / 50.1246;
  const steps = Math.floor((time - previousDraw) / millisecondsPerStep);
  if (playing && steps > 0) {
    position = (position + steps) % positionCount;
    previousDraw += steps * millisecondsPerStep;
    draw();
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
