'use strict';
const assert=require('node:assert/strict');
const common=require('./common.cjs'),wire=require('./container.cjs');
const patches=require('./delta.cjs').codecs;
const edges=[...require('./edges.cjs').codecs,...require('./edge-maps.cjs').codecs];
const layout=common.layouts.circle,fid=1,eid=edges.findIndex(c=>c.name==='edges-map-raw-circle');
function serialize(frames,keys,deltas,deltaId,lag,policy){
 const parts=[Buffer.from('HD64'),[1,40,25],wire.word(frames.length),[layout.id,fid,eid,deltaId,lag],layout.metadata];
 let keyCount=0,patchCount=0;
 for(let i=0;i<frames.length;i++){
  const forced=i<lag||(policy==='key16'&&i%16<lag)||(policy==='key32'&&i%32<lag);
  const key=forced||(policy==='adaptive'&&keys[i].length<=deltas[i].length);
  const payload=key?keys[i]:deltas[i];assert(payload.length<32768);
  parts.push(wire.word(payload.length|(key?0x8000:0)),payload);if(key)keyCount++;else patchCount++;
 }
 return{blob:wire.bytes(parts),keyCount,patchCount};
}
function verify(blob,expected,loops=3){
 assert.equal(blob.subarray(0,4).toString(),'HD64');assert.equal(blob[4],1);assert.equal(blob[5],40);assert.equal(blob[6],25);
 const count=blob.readUInt16LE(7),kind=blob[9],f=blob[10],e=blob[11],d=blob[12],lag=blob[13];
 assert(lag===1||lag===2);assert.equal(count,expected.length);const parsed=wire.readLayout(blob,kind,14),buffers=new Array(lag).fill(null);let tick=0,compared=0;
 for(let loop=0;loop<loops;loop++){let read=parsed.read;
  for(let i=0;i<count;i++){
   const tag=blob.readUInt16LE(read);read+=2;const key=!!(tag&32768),length=tag&32767;assert(read+length<=blob.length);
   const payload=blob.subarray(read,read+length);read+=length;const slot=tick%lag;
   if(!key)assert(buffers[slot],'Delta refers to an uninitialized destination');
   const out=key?wire.decodeKey(payload,parsed.indices,f,e):patches[d].decode(payload,buffers[slot]);
   assert.deepEqual(out,expected[i],`Loop${loop} frame${i} lag${lag}`);buffers[slot]=out;tick++;compared+=1000;
  }
  assert.equal(read,blob.length);
 }
 return compared;
}
module.exports={serialize,verify};
