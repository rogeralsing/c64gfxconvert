'use strict';
// A key image is the measured hybrid format; a predictive image patches char
// codes directly. All flags, lengths, startup images and loop resets are real.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const common=require('./common.cjs'),wire=require('./container.cjs');
const fill=require('./fill.cjs').codecs,edges=[...require('./edges.cjs').codecs,...require('./edge-maps.cjs').codecs];
const patches=require('./delta.cjs').codecs;
const corpus=common.getCorpus(),layout=common.layouts.circle,fid=1,eid=edges.findIndex(c=>c.name==='edges-map-raw-circle');
const {serialize,verify}=require('./delta-wire.cjs');

const report={pass:false,scope:'Precomputed independent key images plus skip/render predictive packets. Host serialized round trips, no C64 timings.',headerBytes:14,frameHeaderBytes:2,layoutMetadataBytes:50,fontBytes:2048,inputHashes:corpus.inputHashes,lag1:'One persistent canonical previous-image buffer; alternating display screens require extra synchronization.',lag2:'The actual target of alternating two screen buffers.',models:{}};
let compared=0;
for(const[name,all]of Object.entries(corpus.models)){
 report.models[name]={};
 for(const step of[1,4]){
  const frames=all.filter((_,i)=>i%step===0),keys=frames.map(screen=>wire.encodeKey(fill[fid].encode(screen,layout.indices),edges[eid].encode(screen))),rows=[];
  for(let d=0;d<patches.length;d++)for(const lag of[1,2]){
   const deltas=frames.map((screen,i)=>i<lag?null:patches[d].encode(screen,frames[i-lag]));
   for(const policy of['predictive','key16','key32','adaptive']){
    const{blob,keyCount,patchCount}=serialize(frames,keys,deltas,d,lag,policy);compared+=verify(blob,frames);
    rows.push({name:patches[d].name,lag,policy,fileBytes:blob.length,meanFrameBytes:blob.length/frames.length,keyFrames:keyCount,patchFrames:patchCount,frames:frames.length});
   }
  }
  rows.sort((a,b)=>a.fileBytes-b.fileBytes);report.models[name][`${frames.length}frames`]={frames:frames.length,best:rows[0],bestLag1:rows.find(r=>r.lag===1),bestLag2:rows.find(r=>r.lag===2),rows};
  for(const lag of[1,2]){const best=rows.find(r=>r.lag===lag),d=patches.findIndex(c=>c.name===best.name),deltas=frames.map((s,i)=>i<lag?null:patches[d].encode(s,frames[i-lag])),{blob}=serialize(frames,keys,deltas,d,lag,best.policy);fs.writeFileSync(path.join(__dirname,'build',`${name}-${frames.length}-lag${lag}.hd64`),blob);}
 }
}
report.pass=true;report.comparedBytes=compared;fs.writeFileSync(path.join(__dirname,'build','delta-study.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({pass:true,comparedBytes:compared,models:Object.fromEntries(Object.entries(report.models).map(([n,groups])=>[n,Object.fromEntries(Object.entries(groups).map(([count,g])=>[count,{bestLag1:g.bestLag1,bestLag2:g.bestLag2}]))]))},null,2));
