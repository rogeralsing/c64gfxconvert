'use strict';

// Check the delivered HTML boundary: embedded char/font bytes -> canvas pixels,
// plus shared JSON playback, transport controls and reduced-motion startup. Canvas
// only captures pixels supplied by the page; it contains no rendering logic.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const here = __dirname;
const input = path.resolve(process.argv[2] || path.join(here, 'build/scenes/spiral'));
const htmlFile = path.resolve(process.argv[3] || path.join(input, 'spiral-scene.html'));
const html = fs.readFileSync(htmlFile, 'utf8');
const scene = JSON.parse(fs.readFileSync(path.join(input, 'scene.json')));
const font = fs.readFileSync(path.join(input, 'font.bin'));
const screens = fs.readFileSync(path.join(input, 'reference.frames'));
const playbackPath = path.resolve(process.argv[4] || path.join(here, 'scenes/spiral.playback.json'));
const commands = JSON.parse(fs.readFileSync(playbackPath));
const expectedFrames = commands.flatMap(command => command.op === 'play'
  ? Array.from({length:command.frameCount * command.repeat},(_,index)=>command.startFrame+index%command.frameCount) : []);
const duration = expectedFrames.length / scene.fps;

function runtime(reducedMotion) {
  const elements = new Map(), documentEvents = {};
  let nextFrame;
  function element(id) {
    if (!elements.has(id)) {
      const context = {createImageData: (width,height) => ({data:new Uint8ClampedArray(width*height*4)}),
        putImageData(image) {this.pixels = Buffer.from(image.data);},
        beginPath() {}, moveTo() {}, lineTo() {}, stroke() {this.gridStrokes = (this.gridStrokes || 0) + 1;}};
      elements.set(id, {value:'',checked:false,textContent:'',attributes:{},listeners:{},
        addEventListener(name,handler) {this.listeners[name] = handler;},
        setAttribute(name,value) {this.attributes[name] = value;},getContext:() => context});
    }
    return elements.get(id);
  }
  const document = {hidden:false,getElementById:element,
    addEventListener(name,handler) {documentEvents[name] = handler;}};
  const sandbox = {document,console,Uint8Array,Uint8ClampedArray,
    atob:value=>Buffer.from(value,'base64').toString('binary'),
    matchMedia:()=>({matches:reducedMotion}),addEventListener() {},
    requestAnimationFrame:callback=>{nextFrame=callback;}};
  sandbox.window = sandbox;
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length,1,'HTML must contain its own script');
  vm.runInNewContext(scripts[0][1],sandbox,{filename:htmlFile});
  assert.equal(typeof nextFrame,'function');
  return {element,document,documentEvents,advance:time=>nextFrame(time),
    click:id=>element(id).listeners.click(),
    seek:time=>{element('time').value=String(time);element('time').listeners.input();},
    pixels:()=>element('screen').getContext('2d').pixels};
}

// Expand each glyph once from C64 MSB-first rows; then compose rows by copying
// whole glyph spans, independently of the HTML's per-cell pixel setter.
const glyphs = Array.from({length:font.length/8},(_,code)=> {
  const result = Buffer.alloc(8*8*4);
  Array.from(font.subarray(code*8,code*8+8),row=>row.toString(2).padStart(8,'0')).join('').split('').forEach((bit,index)=> {
    result.fill(bit==='1'?255:0,index*4,index*4+3);result[index*4+3]=255;
  });
  return result;
});
function expectedPixels(frame) {
  const rgba = Buffer.alloc(320*200*4), codes = screens.subarray(frame*1000,(frame+1)*1000);
  for(let y=0;y<200;y++) for(let column=0;column<40;column++) {
    const glyph=glyphs[codes[Math.floor(y/8)*40+column]],row=y%8;
    glyph.copy(rgba,(y*320+column*8)*4,row*32,(row+1)*32);
  }
  return rgba;
}

const page = runtime(false);
const label = frame => 'Bild '+frame+' / '+(scene.frames.length-1);
assert.equal(page.element('play').textContent,'Pausa');
for(let display=0;display<expectedFrames.length;display++) {
  const frame=expectedFrames[display];
  page.seek(display/scene.fps);
  assert.equal(page.element('frame').textContent,label(frame));
  assert(page.pixels().equals(expectedPixels(frame)),'HTML image differs from exported chars at frame '+frame);
}
page.seek(0);
if (expectedFrames[0] === 0) assert(page.pixels().every((value,index)=>index%4===3?value===255:value===0),'First frame must be black');
page.click('play');page.advance(100);
for(let display=0;display<expectedFrames.length;display++) {
  page.advance(100+display/scene.fps*1000);
  assert.equal(page.element('frame').textContent,label(expectedFrames[display]),'Playback disagrees with JSON at display '+display);
}
page.advance(100+duration*1000);
assert.equal(page.element('status').textContent,'Klart · sista bilden');
assert.equal(page.element('frame').textContent,label(expectedFrames.at(-1)));
assert.equal(Number(page.element('time').value),duration);
const final = page.pixels();page.advance(100+duration*1000+5000);
assert(page.pixels().equals(final),'HOLD replayed the sequence');
assert.equal(page.element('status').textContent,'Klart · sista bilden');
page.click('restart');
assert.equal(page.element('frame').textContent,label(expectedFrames[0]));
assert.equal(page.element('play').textContent,'Pausa');
page.advance(20200);page.advance(21200);page.click('play');
assert.equal(page.element('frame').textContent,label(expectedFrames[25]));
page.advance(22200);
assert.equal(page.element('frame').textContent,label(expectedFrames[25]),'Pause advanced playback');
page.seek(2);assert.equal(page.element('play').textContent,'Spela');
page.click('play');page.advance(23000);
page.document.hidden=true;page.documentEvents.visibilitychange();page.advance(30000);
page.document.hidden=false;page.documentEvents.visibilitychange();page.advance(40000);
assert.equal(page.element('frame').textContent,label(expectedFrames[50]),'Hidden-tab resumption skipped part of clip');
page.element('grid').checked=true;page.element('grid').listeners.change();
assert.equal(page.element('screen').getContext('2d').gridStrokes,1);
page.element('grid').checked=false;page.element('grid').listeners.change();
assert(page.pixels().equals(expectedPixels(expectedFrames[50])));
const reduced = runtime(true);
assert.equal(reduced.element('play').textContent,'Spela');
reduced.advance(0);reduced.advance(1000);
assert.equal(reduced.element('frame').textContent,label(expectedFrames[0]),'Reduced motion played automatically');
console.log(JSON.stringify({pass:true,html:htmlFile,framesCompared:new Set(expectedFrames).size,
  displayedFramesCompared:expectedFrames.length,playbackScript:playbackPath,nominalSeconds:duration,
  pixelsPerFrame:320*200,verified:['all delivered character/font pixels','blank first frame',
    'each JSON PLAY repetition then final HOLD',
    'pause/restart/scrub','hidden-tab resume','grid toggle','reduced-motion startup'],
  browserAccess:false,nativeC64FpsMeasured:false},null,2));
