'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const BASE=path.resolve(__dirname,'../../../..');
const atlas=require('../span-atlas/generate.cjs'),{createModel}=require(path.join(BASE,'native-model.cjs'));
const {encodePackets,decodePackets}=require('../../delta.cjs');
const pop=n=>{let count=0;for(;n;n&=n-1)count++;return count;};

function census(){
 const blob=fs.readFileSync(path.join(__dirname,'../span-atlas/build/assets/spans.sa64')),decoded=atlas.deserialize(blob),model=createModel();
 const faceMasks=decoded.frames.map(spans=>Array.from({length:36},(_,face)=>atlas.coverageFor(spans.filter(span=>span.face===face),model.tables)));
 const counts=faceMasks.map(masks=>{const result=new Uint8Array(8000);for(const mask of masks)for(let cell=0;cell<1000;cell++)for(let bit=0;bit<8;bit++)if(mask[cell]&(1<<bit))result[cell*8+bit]++;return result;});
 const maxima=counts.map(count=>Math.max(...count)),maxStatic=Math.max(...maxima),histogram={};for(const count of counts)for(const value of count)histogram[value]=(histogram[value]||0)+1;
 let maxIntermediate=0,where=null;const frames=[];
 for(let frame=0;frame<64;frame++){
  const previous=(frame+63)%64,working=Uint8Array.from(counts[previous]);
  for(let face=0;face<36;face++)for(let cell=0;cell<1000;cell++){
   const old=faceMasks[previous][face][cell],next=faceMasks[frame][face][cell],remove=old&~next,add=next&~old;
   for(let bit=0;bit<8;bit++)if(remove&(1<<bit)){assert(working[cell*8+bit]);working[cell*8+bit]--;}
   for(let bit=0;bit<8;bit++)if(add&(1<<bit)){const value=++working[cell*8+bit];if(value>maxIntermediate){maxIntermediate=value;where={previous,frame,face,cell,bit};}}
  }
  assert.deepEqual(working,counts[frame]);
  let dirtyCoverage=0,dirtyCounts=0,changedGlyphs=0,probeAdds=0,probeRemoves=0,cellMaskCommands=0,maskCommandBytes=2;
  const oldScreen=model.resolve(atlas.coverageFor(decoded.frames[previous],model.tables)),screen=model.resolve(atlas.coverageFor(decoded.frames[frame],model.tables));
  for(let cell=0;cell<1000;cell++){
   let oldCoverage=0,newCoverage=0,add=0,remove=0,changed=0;
   for(let bit=0;bit<8;bit++){
    const old=counts[previous][cell*8+bit],next=counts[frame][cell*8+bit];if(old)oldCoverage|=1<<bit;if(next)newCoverage|=1<<bit;
    if(old!==next)changed=1;
    probeAdds+=Math.max(0,next-old);probeRemoves+=Math.max(0,old-next);
    if(next>old)add|=1<<bit;if(next<old)remove|=1<<bit;
   }
   dirtyCoverage+=Number(oldCoverage!==newCoverage);dirtyCounts+=changed;changedGlyphs+=Number(oldScreen[cell]!==screen[cell]);
   if(add||remove){cellMaskCommands++;maskCommandBytes+=2+Number(Boolean(add))+Number(Boolean(remove));}
  }
  // Exact symmetric-difference intervals at each global sample height. These
  // preserve counts throughout each geometric interval, not just at probes.
  let intervalCommands=0;
  for(let sample=0;sample<75;sample++){
   const events=new Map();
   for(const [source,sign]of[[decoded.frames[frame],1],[decoded.frames[previous],-1]])for(const span of source){const index=sample-span.first;if(index<0||index>=span.left.length)continue;const l=span.left[index],r=span.right[index];if(l>=r)continue;events.set(l,(events.get(l)||0)+sign);events.set(r,(events.get(r)||0)-sign);}
   const points=[...events.keys()].sort((a,b)=>a-b);let delta=0;
   for(let i=0;i+1<points.length;i++){delta+=events.get(points[i]);if(delta&&points[i]<points[i+1])intervalCommands+=Math.abs(delta);}
  }
  frames.push({frame,previous,dirtyCoverage,dirtyCounts,changedGlyphs,probeAdds,probeRemoves,cellMaskCommands,maskCommandBytes,intervalCommands,intervalBytes:2+intervalCommands*3});
 }
 return {model,decoded,faceMasks,counts,report:{maxStatic,maxSequentialFaceIntermediate:maxIntermediate,maxIntermediateWhere:where,countHistogram:histogram,frames}};
}

function main(){
 const result=census(),r=result.report,mean=key=>r.frames.reduce((sum,frame)=>sum+frame[key],0)/64,total=key=>r.frames.reduce((sum,frame)=>sum+frame[key],0);
 r.summary={dirtyCoverageMean:mean('dirtyCoverage'),dirtyCountsMean:mean('dirtyCounts'),changedGlyphsMean:mean('changedGlyphs'),intervalCommandsMean:mean('intervalCommands'),intervalBytes:total('intervalBytes'),cellMaskCommandsMean:mean('cellMaskCommands'),cellMaskBytes:total('maskCommandBytes')};
 assert.equal(r.maxStatic,1,'XOR commands require disjoint probe coverage at every endpoint pose.');
 const coverages=result.decoded.frames.map(spans=>atlas.coverageFor(spans,result.model.tables));
 const initial=[result.decoded.frames[0].length];for(const span of result.decoded.frames[0]){initial.push(span.first,span.left.length);for(let i=0;i<span.left.length;i++)initial.push(span.left[i],span.right[i]);}
 const init=Buffer.from(initial),zero=new Uint8Array(1000),records=[],packetRows=[];
 for(let sequence=0;sequence<64;sequence++){
  const frame=(sequence+1)%64,previous=(frame+63)%64,mask=Uint8Array.from(coverages[frame],(value,cell)=>value^coverages[previous][cell]),payload=encodePackets(mask,zero);
  assert.deepEqual(decodePackets(payload,zero),mask);records.push(Buffer.from([payload.length&255,payload.length>>>8]),Buffer.from(payload));packetRows.push({frame,bytes:payload.length+2});
 }
 const header=Buffer.from([71,68,54,52,1,64,8,1,init.length&255,init.length>>>8,64,0]),movie=Buffer.concat([header,init,...records]);
 let read=12;const initEnd=read+movie.readUInt16LE(8),spanCount=movie[read++],initialSpans=[];
 for(let face=0;face<spanCount;face++){const first=movie[read++],length=movie[read++],left=[],right=[];for(let i=0;i<length;i++){left.push(movie[read++]);right.push(movie[read++]);}initialSpans.push({first,left,right});}
 assert.equal(read,initEnd);let current=atlas.coverageFor(initialSpans,result.model.tables);assert.deepEqual(current,coverages[0]);const recordsStart=read;let checked=0;
 for(let loop=0;loop<3;loop++){read=recordsStart;for(let sequence=0;sequence<64;sequence++){
  const length=movie.readUInt16LE(read);read+=2;const mask=decodePackets(movie.subarray(read,read+length),zero);read+=length;
  current=Uint8Array.from(current,(value,cell)=>value^mask[cell]);const frame=(sequence+1)%64;assert.deepEqual(current,coverages[frame]);assert.deepEqual(result.model.resolve(current),result.model.resolve(coverages[frame]));checked++;
 }assert.equal(read,movie.length);}
 r.geometryXorMovie={bytes:movie.length,headerBytes:12,initialGeometryBytes:init.length,initialSpanSamples:(init.length-1-2*spanCount)/2,frameRecordsBytes:movie.length-12-init.length,records:64,meanRecordBytes:packetRows.reduce((sum,row)=>sum+row.bytes,0)/64,hostFramesChecked:checked,packets:packetRows,scope:'Precomputed exact geometric eight-probe XOR changes; no glyph codes. Safe because every endpoint pose has at most one white contribution per probe.'};
 const output=path.join(__dirname,'build');fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,'census.json'),JSON.stringify(r,null,2)+'\n');
 fs.writeFileSync(path.join(output,'geometry.gd64'),movie);
 console.log(JSON.stringify({...r,frames:undefined,geometryXorMovie:{...r.geometryXorMovie,packets:undefined}},null,2));return result;
}
module.exports={census};
if(require.main===module)main();
