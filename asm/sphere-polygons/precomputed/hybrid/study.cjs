'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const common=require('./common.cjs'),fill=require('./fill.cjs').codecs;
const edges=[...require('./edges.cjs').codecs,...require('./edge-maps.cjs').codecs];
const alternating=require('./alternating.cjs').variants,baseline=require('./baseline-rle.cjs');
const corpus=common.getCorpus(),layoutList=Object.values(common.layouts);
const {serializeHybrid,serializeUnified,deserialize}=require('./container.cjs');

const report={pass:false,scope:'Serialized independent-frame formats; host round trips, no C64 decoder timings.',fontBytes:2048,headerBytes:12,hybridFrameHeaderBytes:4,unifiedFrameHeaderBytes:2,adaptiveModeBytesPerFrame:1,optionalIndex:'Not included; sequential frame lengths are stored. Random access needs an additional index.',inputHashes:corpus.inputHashes,models:{}};
const outdir=path.join(__dirname,'build');fs.mkdirSync(outdir,{recursive:true});
let restoredFrames=0;
for(const[name,all]of Object.entries(corpus.models)){
 const edgePackets=edges.map(codec=>all.map(screen=>codec.encode(screen))),baselinePackets=all.map(screen=>baseline.encode(screen)),alternatingPackets=alternating.map(codec=>all.map(screen=>codec.encode(screen)));
 const layoutData={};for(const layout of layoutList){layoutData[layout.name]=fill.map(codec=>all.map(screen=>{const p=codec.encode(screen,layout.indices);common.checkFill(codec.decode(p,layout.indices.length),screen,layout.indices);return p;}));}
 report.models[name]={};
 for(const step of[1,4]){
  const chosen=all.map((_,i)=>i).filter(i=>i%step===0),frames=chosen.map(i=>all[i]),candidates=[];
  const verify=(blob)=>{const decoded=deserialize(blob);assert.equal(decoded.length,frames.length);for(let i=0;i<frames.length;i++)assert.deepEqual(decoded[i],frames[i]);restoredFrames+=frames.length;};
  const reference=serializeUnified(frames,254,chosen.map(i=>baselinePackets[i]));verify(reference);
  candidates.push({name:'common-char-rle',bytes:reference.length,meanFrameBytes:reference.length/frames.length});
  for(let a=0;a<alternating.length;a++){const blob=serializeUnified(frames,a,chosen.map(i=>alternatingPackets[a][i]));verify(blob);candidates.push({name:alternating[a].name,bytes:blob.length,meanFrameBytes:blob.length/frames.length});}
  for(const layout of layoutList){
   const fp=layoutData[layout.name].map(packets=>chosen.map(i=>packets[i])),ep=edgePackets.map(packets=>chosen.map(i=>packets[i]));
   const allowed=edges.map((c,i)=>[c,i]).filter(([c])=>!c.requiresLayout||c.requiresLayout===layout.name).map(([,i])=>i);
   for(let f=0;f<fill.length;f++)for(const e of allowed){const blob=serializeHybrid(frames,layout,f,e,fp,ep);verify(blob);candidates.push({name:`${layout.name}/${fill[f].name}/${edges[e].name}`,bytes:blob.length,meanFrameBytes:blob.length/frames.length,fillBytes:fp[f].reduce((n,p)=>n+p.length,0),edgeBytes:ep[e].reduce((n,p)=>n+p.length,0),layoutMetadataBytes:layout.metadata.length,frameHeaderBytes:4*frames.length,layout:layout.name,fillId:f,edgeId:e});}
   const selection=frames.map((_,i)=>{let best=Infinity,pair;for(let f=0;f<fill.length;f++)for(const e of allowed){const n=fp[f][i].length+ep[e][i].length;if(n<best){best=n;pair=[f,e];}}return pair;});
   const blob=serializeHybrid(frames,layout,0,0,fp,ep,selection);verify(blob);candidates.push({name:`${layout.name}/adaptive-hybrid`,bytes:blob.length,meanFrameBytes:blob.length/frames.length,modeBytes:frames.length,layoutMetadataBytes:layout.metadata.length});
  }
  candidates.sort((a,b)=>a.bytes-b.bytes);
  const best=candidates[0];report.models[name][`${frames.length}frames`]={frames:frames.length,angleStep:[2*step,step,step],baselineBytes:reference.length,best,candidates};
  const practical=candidates.find(candidate=>candidate.fillId!==undefined);
  for(const[selected,suffix]of[[best,''],[practical,'-fixed']]){
   const layout=common.layouts[selected.layout||selected.name.split('/')[0]],fp=layoutData[layout.name].map(p=>chosen.map(i=>p[i])),ep=edgePackets.map(p=>chosen.map(i=>p[i]));
   let selection;
   if(selected.fillId===undefined){const allowed=edges.map((c,i)=>[c,i]).filter(([c])=>!c.requiresLayout||c.requiresLayout===layout.name).map(([,i])=>i);selection=frames.map((_,i)=>{let minimum=Infinity,pair;for(let f=0;f<fill.length;f++)for(const e of allowed){const size=fp[f][i].length+ep[e][i].length;if(size<minimum){minimum=size;pair=[f,e];}}return pair;});}
   const blob=serializeHybrid(frames,layout,selected.fillId||0,selected.edgeId||0,fp,ep,selection);verify(blob);assert.equal(blob.length,selected.bytes);
   fs.writeFileSync(path.join(outdir,`${name}-${frames.length}${suffix}.hc64`),blob);
  }
 }
}
report.pass=true;report.roundTripFrames=restoredFrames;fs.writeFileSync(path.join(outdir,'study.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({pass:true,roundTripFrames:restoredFrames,models:Object.fromEntries(Object.entries(report.models).map(([name,groups])=>[name,Object.fromEntries(Object.entries(groups).map(([count,d])=>[count,{baselineBytes:d.baselineBytes,best:d.best,topFive:d.candidates.slice(0,5)}]))]))},null,2));
