'use strict';
const fs=require('node:fs'),path=require('node:path');
const common=require('../common.cjs'),wire=require('../container.cjs'),predictive=require('../delta-wire.cjs');
const fill=require('../fill.cjs').codecs,edges=[...require('../edges.cjs').codecs,...require('../edge-maps.cjs').codecs],patches=require('../delta.cjs').codecs;
const{frames,motion}=require('./motion.cjs').makeMotion(),layout=common.layouts.circle,eid=edges.findIndex(c=>c.name==='edges-map-raw-circle');
fs.mkdirSync(path.join(__dirname,'build/assets'),{recursive:true});
const keys=frames.map(screen=>wire.encodeKey(fill[1].encode(screen,layout.indices),edges[eid].encode(screen))),rows=[];
let checked=0;
for(let d=0;d<patches.length;d++)for(const lag of[1,2]){
 const deltas=frames.map((screen,i)=>i<lag?null:patches[d].encode(screen,frames[i-lag]));
 const changed=frames.slice(lag).map((screen,j)=>screen.reduce((n,value,i)=>n+(value!==frames[j][i]),0));
 for(const policy of['predictive','key32','adaptive']){
  const{blob,keyCount,patchCount}=predictive.serialize(frames,keys,deltas,d,lag,policy);checked+=predictive.verify(blob,frames);
  rows.push({codec:patches[d].name,lag,policy,bytes:blob.length,meanFrameBytes:blob.length/64,keyFrames:keyCount,patchFrames:patchCount,meanChangedCells:changed.reduce((a,b)=>a+b,0)/changed.length});
  if(policy==='adaptive')fs.writeFileSync(path.join(__dirname,'build/assets',`checker-64-smooth-delta${d}-lag${lag}.hd64`),blob);
 }
}
const fillPayloads=[],edgePayloads=[];
fillPayloads[1]=frames.map(screen=>fill[1].encode(screen,layout.indices));
edgePayloads[eid]=frames.map(screen=>edges[eid].encode(screen));
const independent=wire.serializeHybrid(frames,layout,1,eid,fillPayloads,edgePayloads).length;
rows.sort((a,b)=>a.bytes-b.bytes);
const report={pass:true,motion,independentBytes:independent,comparedBytes:checked,bestLag1:rows.find(r=>r.lag===1),bestLag2:rows.find(r=>r.lag===2),rows};
fs.writeFileSync(path.join(__dirname,'build','motion-delta.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
