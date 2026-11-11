'use strict';

// Greedy append-only palette selection for the supplied, immutable bitmap
// movie. Every candidate is an observed target; each gain includes ALL contexts.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const crypto = require('node:crypto');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const bits = new Uint8Array(65536);
for (let n = 1; n < bits.length; n++) bits[n] = bits[n >> 1] + (n & 1);
function expand(pattern) {
  const rows = Buffer.alloc(8);
  for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if (pattern & (1 << (y * 4 + 3 - x))) {
    rows[y * 2] |= 3 << (6 - x * 2); rows[y * 2 + 1] |= 3 << (6 - x * 2);
  }
  return rows;
}
function compact(rows) {
  let result = 0;
  for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) if ((rows[y * 2] >> (7 - x * 2)) & 1) result |= 1 << (y * 4 + 3 - x);
  assert(expand(result).equals(rows), 'Every glyph must use strict2x2 physical pixels.'); return result;
}
function tile(movie, frame, cell) {
  const x = cell % 40 * 4, y = Math.floor(cell / 40) * 4, shift = x % 8 ? 0 : 4;
  const at = frame * 2000 + y * 20 + (x >> 3); let result = 0;
  for (let row = 0; row < 4; row++) result |= ((movie[at + row * 20] >> shift) & 15) << (row * 4);
  return result;
}
function main(argv = process.argv.slice(2)) {
  const options = {};
  for (let i = 0; i < argv.length; i++) {
    const [key, inline] = argv[i].split('=');
    assert(['--input','--font','--output','--limit'].includes(key), `Unknown option${key}`);
    options[key] = inline ?? argv[++i]; assert(options[key]);
  }
  assert(options['--input'] && options['--font'] && options['--output']);
  const input = path.resolve(options['--input']), output = path.resolve(options['--output']);
  const source = JSON.parse(fs.readFileSync(path.join(input, 'metadata.json'))), frames = source.frameCount;
  assert.equal(source.width,160); assert.equal(source.height,100); assert.equal(source.fps,25);
  assert(Number.isInteger(frames) && frames>=2 && frames<=255, 'Movie frameCount must be an integer2..255.');
  if(source.frames!==undefined)assert(Array.isArray(source.frames) && source.frames.length===frames, 'Phase metadata must describe every movie frame.');
  const raw = fs.readFileSync(path.resolve(input,source.framesFile));
  const mask = fs.readFileSync(path.resolve(input,source.objectMaskFile));
  assert.equal(raw.length, frames*2000); assert.equal(mask.length,raw.length);
  assert.equal(sha(raw),source.hashes.frames); assert.equal(sha(mask),source.hashes.objectMask);
  const baseFont = fs.readFileSync(path.resolve(options['--font']));
  assert.equal(baseFont.length,1448); assert.equal(sha(baseFont),'21428b389e5831802cd6a0ad3880d7d8dde32e7e30a16de2a7c599b8b3ee05fa');
  const patterns = Array.from({length:181},(_,code)=>compact(baseFont.subarray(code*8,code*8+8)));
  const limit = Number(options['--limit'] ?? 256); assert(Number.isInteger(limit) && limit>=181 && limit<=256);
  // Use the declared comparison window, clipped for the legacy default. Gray
  // statistics apply only to explicitly labeled gray frames, never a time guess.
  if(source.approvedPrefixFrames!==undefined)assert(Number.isInteger(source.approvedPrefixFrames) && source.approvedPrefixFrames>=0 && source.approvedPrefixFrames<=frames, 'approvedPrefixFrames must be an integer0..frameCount.');
  const prefixFrames = Math.min(source.approvedPrefixFrames??125,frames), isGrayFrame = frame => source.frames?.[frame]?.phase==='gray';
  const seen = new Map(), contexts = [], cells = new Uint32Array(frames*1000);
  const choose = (target,allowed,count) => {
    let code=0,error=17;
    for(let i=0;i<count;i++) if(!(patterns[i]&~allowed)) {
      const value=bits[target^patterns[i]];
      if(value<error){code=i;error=value;}
      if(!value)break;
    }
    return {code,error};
  };
  for(let frame=0;frame<frames;frame++)for(let cell=0;cell<1000;cell++){
    const target=tile(raw,frame,cell),allowed=tile(mask,frame,cell); assert.equal(target&~allowed,0);
    const key=target+':'+allowed; let id=seen.get(key);
    if(id===undefined){id=contexts.length;seen.set(key,id);contexts.push({target16:target,mask16:allowed,weight:0,weightPrefix:0,weightGray:0,
      base181:choose(target,allowed,181),base168:choose(target,allowed,168),firstFrame:frame,firstCell:cell});}
    const context=contexts[id];context.weight++;context.weightPrefix+=Number(frame<prefixFrames);context.weightGray+=Number(isGrayFrame(frame));
    cells[frame*1000+cell]=id;
  }
  const currentCodes=Uint16Array.from(contexts,context=>context.base181.code);
  const currentErrors=Uint8Array.from(contexts,context=>context.base181.error);
  const active=contexts.map((context,id)=>({context,id})).filter(row=>row.context.base181.error>0);
  const candidates=[...new Set(active.map(row=>row.context.target16))].sort((a,b)=>a-b);
  const stride=active.length, distances=new Uint8Array(candidates.length*stride), gains=new Float64Array(candidates.length);
  distances.fill(255);
  for(let c=0;c<candidates.length;c++)for(let r=0;r<stride;r++){
    const context=active[r].context,pattern=candidates[c];if(pattern&~context.mask16)continue;
    const distance=bits[pattern^context.target16];distances[c*stride+r]=distance;
    gains[c]+=Math.max(0,context.base181.error-distance)*context.weight;
  }
  fs.mkdirSync(output,{recursive:true});
  const checkpoints={}, steps=[];
  function evaluate(codes,errors,fontCount,startFrame){
    const screens=Buffer.alloc(frames*1000),groups={};let prefixChanged=0;
    for(let frame=0;frame<frames;frame++)for(let cell=0;cell<1000;cell++){
      const id=cells[frame*1000+cell],context=contexts[id],pinned=frame<startFrame;
      const code=pinned?context.base168.code:codes[id],error=pinned?context.base168.error:errors[id];
      assert(code<fontCount);assert.equal(patterns[code]&~context.mask16,0);
      screens[frame*1000+cell]=code;
      if(frame<prefixFrames)prefixChanged+=Number(code!==context.base168.code);
      const category=context.mask16===0?'Background':context.mask16===65535?'Interior':'Boundary';
      const keys=['all',frame<prefixFrames?'prefix':'tail',category.toLowerCase()];
      if(frame<prefixFrames)keys.push('prefix'+category);
      if(isGrayFrame(frame))keys.push('gray','gray'+category);
      for(const key of keys){const stats=groups[key]||=( {tiles:0,errors:0,objectPixels:0,exactTiles:0,sourceWhitePixels:0,outputWhitePixels:0});
        stats.tiles++;stats.errors+=error*4;stats.objectPixels+=bits[context.mask16]*4;stats.exactTiles+=Number(error===0);
        stats.sourceWhitePixels+=bits[context.target16]*4;stats.outputWhitePixels+=bits[patterns[code]]*4;}
    }
    for(const stats of Object.values(groups)){stats.objectErrorFraction=stats.errors/Math.max(1,stats.objectPixels);}
    let payload=0;const writes=[];
    for(let frame=1;frame<frames;frame++){
      let changed=0;
      for(let page=0;page<4;page++){
        let count=0;for(let offset=0;offset<Math.min(256,1000-page*256);offset++){
          const cell=page*256+offset;count+=Number(screens[frame*1000+cell]!==screens[(frame-1)*1000+cell]);}
        assert(count<=255);payload+=1+2*count;changed+=count;
      }writes.push(changed);
    }
    return {screens,report:{glyphs:fontCount,fontBytes:fontCount*8,candidateStartFrame:startFrame,groups,prefixChangedCharacters:prefixChanged,
      screensSha256:sha(screens),prefixScreensSha256:sha(screens.subarray(0,prefixFrames*1000)),silhouetteSpill:0,
      sparsePayloadBytes:payload,sourceArenaRemainingBytes:40960-payload,fitsSourceArena:payload<=40960,pointerBytes:frames*2,playbackScriptBytes:6,
      estimatedLoadedBytesWith473BytePlayerAnd13ByteBasic:payload+fontCount*8+frames*2+6+473+13,
      changedCharactersPerUpdate:{min:Math.min(...writes),mean:writes.reduce((a,b)=>a+b,0)/writes.length,max:Math.max(...writes)},nativeFpsMeasured:false}};
  }
  function checkpoint(){
    const count=patterns.length,all=evaluate(currentCodes,currentErrors,count,0),pinned=evaluate(currentCodes,currentErrors,count,prefixFrames);
    checkpoints[count]={unlocked:all.report,[`prefixLocked${prefixFrames}`]:pinned.report};
    fs.writeFileSync(path.join(output,`font-${count}.bin`),Buffer.concat(patterns.map(expand)));
    fs.writeFileSync(path.join(output,`expected-${count}.reference.frames`),all.screens);
    fs.writeFileSync(path.join(output,`prefix-locked-${count}.reference.frames`),pinned.screens);
    return all;
  }
  checkpoint();
  while(patterns.length<limit){
    let best=-1,gain=0;for(let c=0;c<candidates.length;c++)if(gains[c]>gain){best=c;gain=gains[c];}
    if(best<0)break;
    const before=contexts.reduce((sum,context,id)=>sum+context.weight*currentErrors[id],0);
    const code=patterns.length,pattern=candidates[best],changed=[];
    patterns.push(pattern);gains[best]=-1;
    for(let r=0;r<stride;r++){
      const id=active[r].id,distance=distances[best*stride+r],old=currentErrors[id];
      if(distance<old){changed.push({r,old,next:distance,weight:active[r].context.weight});currentErrors[id]=distance;currentCodes[id]=code;}
    }
    const after=contexts.reduce((sum,context,id)=>sum+context.weight*currentErrors[id],0);
    assert.equal(before-after,gain,'Selected score must equal the measured total weighted error reduction.');
    for(let c=0;c<candidates.length;c++)if(gains[c]>=0){
      let delta=0;const at=c*stride;
      for(const row of changed){const distance=distances[at+row.r];delta+=(Math.max(0,row.next-distance)-Math.max(0,row.old-distance))*row.weight;}
      gains[c]+=delta;assert(gains[c]>=0);
    }
    steps.push({code,pattern16:pattern,patternHex:pattern.toString(16).padStart(4,'0'),weightedGain:gain,
      weightedGainPhysicalPixels:gain*4,remainingWeightedErrorsPhysicalPixels:after*4,changedContexts:changed.length});
    if([224,240,256,limit].includes(patterns.length))checkpoint();
  }
  const final=checkpoint(),font=Buffer.concat(patterns.map(expand));
  assert(font.subarray(0,baseFont.length).equals(baseFont));
  const patternErrors=new Map();
  contexts.forEach((context,id)=>{
    const row=patternErrors.get(context.target16)||{pattern16:context.target16,rows:Array.from(expand(context.target16)),weight:0,
      weightedErrorsBefore:0,weightedErrorsAfter:0,firstFrame:context.firstFrame,firstCell:context.firstCell};
    row.weight+=context.weight;row.weightedErrorsBefore+=context.weight*context.base181.error*4;
    row.weightedErrorsAfter+=context.weight*currentErrors[id]*4;patternErrors.set(context.target16,row);
  });
  const atlas={selected:steps.map(step=>({...step,rows:Array.from(expand(step.pattern16))})),
    remaining:[...patternErrors.values()].filter(row=>row.weightedErrorsAfter>0).sort((a,b)=>b.weightedErrorsAfter-a.weightedErrorsAfter||a.pattern16-b.pattern16)};
  const metadata={pass:true,glyphs:patterns.length,fontBytes:font.length,baseGlyphs:181,appendedGlyphs:steps.length,
    baseFontSha256:sha(baseFont),fontSha256:sha(font),base181BytesUnchanged:true,firstEligibleSourceFrame:0,
    sourcePackedSha256:sha(raw),sourceMaskSha256:sha(mask),sourceSceneSha256:source.sourceSha256,
    objective:'Largest total frequency-weighted admissible Hamming reduction over all observed target/mask contexts; ties choose the numerically smallest16-bit actual target.',
    expectedScreensSha256:sha(final.screens),stoppedBecause:patterns.length===limit?'glyph limit':'no positive gain'};
  const study={pass:true,metadata,contextCount:contexts.length,activeContextCount:active.length,candidatePatternCount:candidates.length,
    weightedGainUnits:'One logical4x4 bit is four physical screen pixels.',steps,checkpoints,
    scope:'Actual movie patterns appended only; no Three, source bitmap, base181 glyph or font-code replacement. Primary candidates are available in all frames.'};
  fs.writeFileSync(path.join(output,'font.bin'),font);
  fs.writeFileSync(path.join(output,'expected.reference.frames'),final.screens);
  fs.writeFileSync(path.join(output,'metadata.json'),JSON.stringify(metadata,null,2)+'\n');
  fs.writeFileSync(path.join(output,'study.json'),JSON.stringify(study,null,2)+'\n');
  fs.writeFileSync(path.join(output,'contexts.json'),JSON.stringify(contexts,null,2)+'\n');
  fs.writeFileSync(path.join(output,'error-patterns.json'),JSON.stringify(atlas,null,2)+'\n');
  console.log(JSON.stringify({metadata,contextCount:contexts.length,candidatePatternCount:candidates.length,
    checkpoints:Object.fromEntries(Object.entries(checkpoints).map(([count,modes])=>[count,Object.fromEntries(Object.entries(modes).map(([mode,report])=>[mode,
      {...report,groups:{all:report.groups.all,prefix:report.groups.prefix,gray:report.groups.gray,grayInterior:report.groups.grayInterior,grayBoundary:report.groups.grayBoundary}}]))]))},null,2));
  return study;
}
module.exports={main};
if(require.main===module)main();
