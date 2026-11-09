'use strict';

// Execute the built preview controllers offline. File-URL browser access is
// unavailable; real rendering is checked against the frozen character export.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {performance} = require('node:perf_hooks');

const here = __dirname;
const directory = path.resolve(process.argv[2] || path.join(here, 'build'));
const expected = fs.readFileSync(path.join(here, 'build/font4-dedupe/reference.frames')).subarray(0, 1000);
const fineExpected = fs.readFileSync(path.join(here, 'c64-preview/build/movie.frames')).subarray(0, 1000);
const fontBytes = fs.readFileSync(path.join(here, 'build/font4-dedupe/font.bin'));

function hasOnlyDoublePixels(rgba) {
  for (let y = 0; y < 200; y += 2) for (let x = 0; x < 320; x += 2) {
    const at = (y * 320 + x) * 4;
    for (const offset of [4, 320 * 4, 321 * 4]) for (let channel = 0; channel < 4; channel++) {
      if (rgba[at + channel] !== rgba[at + offset + channel]) return false;
    }
  }
  return true;
}

function runtime(html, fragment) {
  const elements = new Map();
  const saved = [];
  let tick;
  function element(key) {
    if (elements.has(key)) return elements.get(key);
    const drawing = {createImageData: (width, height) => ({data: new Uint8ClampedArray(width * height * 4)}),
      putImageData(value) {this.lastImage = value.data.slice();},
      fillRect() {}, stroke() {}, beginPath() {}, moveTo() {}, lineTo() {}};
    const node = {value: '', checked: false, textContent: '', innerHTML: '', dataset: {}, isConnected: true,
      listeners: {}, attributes: {}, classList: {toggle() {}},
      addEventListener(name, handler) {(this.listeners[name] ||= []).push(handler);},
      setAttribute(name, value) {this.attributes[name] = value;},
      getContext: () => drawing, setPointerCapture() {}, click() {}, append() {},
      getBoundingClientRect: () => ({left: 0, top: 0, width: 208, height: 208}),
      querySelector: selector => element(selector)};
    elements.set(key, node);
    return node;
  }
  const views = ['font', 'reference', 'difference'].map(view => {
    const node = element('view-' + view); node.dataset.view = view; return node;
  });
  const presets = ['fine', 'coarse', 'hard'].map(preset => {
    const node = element('preset-' + preset); node.dataset.preset = preset; return node;
  });
  const document = {hidden: false, getElementById: element, querySelector: element,
    querySelectorAll: selector => selector === '[data-view]' ? views : selector === '[data-preset]' ? presets : [],
    createElement: element};
  const context = vm.createContext({document, performance, console,
    matchMedia: () => ({matches: false}), requestAnimationFrame: callback => {tick = callback;},
    addEventListener() {}, getComputedStyle: () => ({color: '#d9f18a', getPropertyValue: () => ''}),
    navigator: {clipboard: {writeText: async () => {}}},
    Blob, URL, setTimeout: () => 0,
    openai: {widgetState: {modelContent: {fontVersion: 'v2', fontCount: 230, method: 'matching', grid: false},
      privateContent: {angle: 0.38}}, setWidgetState(value) {saved.push(value); return Promise.resolve();}}});
  context.window = context;
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1, 'The preview must be self-contained');
  vm.runInContext(scripts[0][1], context, {filename: fragment ? 'checker-font-v2.html' : 'font-v2-4x4.html'});
  assert.equal(typeof tick, 'function', 'Animation did not schedule its next frame');
  return {context, elements, saved, fragment};
}

const results = [];
for (const name of ['font-v2.html', 'font-v2-4x4.html', 'checker-font-v2.html']) {
  const fragment = name === 'checker-font-v2.html';
  const html = fs.readFileSync(path.join(directory, name), 'utf8');
  const page = runtime(html, fragment);
  const lab = page.context.sphereLab;
  assert(lab, 'Preview controller did not initialize');
  assert.equal(lab.font.count, 168);
  assert(lab.font.coarsened);
  assert(Buffer.concat(Array.from(lab.font.glyphs, glyph => Buffer.from(glyph.rows))).equals(fontBytes));
  assert(Buffer.from(lab.screen).equals(expected), name + ' shows a different font or screen than the exported experiment');
  assert.equal(lab.state.radius, 145);
  assert.equal(lab.state.checks, 20);
  assert.equal(lab.state.tilt, 65);
  if (fragment) {
    assert.equal(page.saved.at(-1).modelContent.fontCount, 168);
    assert.equal(page.saved.at(-1).modelContent.fontResolution, '4x4');
    assert(page.elements.get('[data-value="font-summary"]').textContent.includes('168'));
    page.elements.get('[data-control="method"]').value = 'conics';
    page.elements.get('[data-control="method"]').listeners.change[0]({target: {value: 'conics'}});
    assert.equal(lab.font.count, 168);
    assert(Math.max(...lab.screen) < 168);
  } else {
    assert.equal(page.elements.get('fontSize').value, 168);
    assert.equal(page.elements.get('fontValue').textContent, '168 tecken');
    assert(page.elements.get('viewLegend').textContent.includes('2 × 2'));
    assert(page.elements.get('fontBytes').textContent.includes('344'));
    page.elements.get('view-reference').listeners.click[0]();
    const canvas = page.elements.get('screen').getContext('2d');
    assert(hasOnlyDoublePixels(canvas.lastImage), 'The coarse-font reference view still contains single-pixel details.');
    assert(canvas.lastImage.some((value, index) => index % 4 === 0 && value === 255));
    assert(canvas.lastImage.some((value, index) => index % 4 === 0 && value === 0));
    assert(page.elements.get('viewLegend').textContent.includes('160 × 100'));
    page.elements.get('view-difference').listeners.click[0]();
    assert(hasOnlyDoublePixels(canvas.lastImage), 'The difference view must use the same 2x2 reference grid.');
    page.elements.get('fontSize').value = '256';
    page.elements.get('fontSize').listeners.input[0]();
    assert.equal(lab.font.count, 256);
    assert(Buffer.from(lab.screen).equals(fineExpected));
    page.elements.get('view-reference').listeners.click[0]();
    assert(!hasOnlyDoublePixels(canvas.lastImage), 'Original-font reference must retain its fine pixels.');
    page.elements.get('fontSize').value = '168';
    page.elements.get('fontSize').listeners.input[0]();
    assert(Buffer.from(lab.screen).equals(expected));
    assert(hasOnlyDoublePixels(canvas.lastImage));
    page.elements.get('method').value = 'conics';
    page.elements.get('method').listeners.input[0]();
    assert(Math.max(...lab.screen) < 168);
    assert(hasOnlyDoublePixels(canvas.lastImage), 'Direct-method reference must also use double pixels.');
  }
  results.push({file: name, pass: true, glyphs: 168, fontBytes: 1344,
    startupScreenEqualsDeduplicatedExport: true, originalModeAndDirectModeChecked: true});
}
console.log(JSON.stringify({pass: true, browserAccess: false, offlineControllerAndRealRenderer: true, results}, null, 2));
