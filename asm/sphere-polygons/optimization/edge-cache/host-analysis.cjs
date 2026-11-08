'use strict';
const fs=require('node:fs');
const path=require('node:path');
const G=require('../../geometry.cjs');
const SAMPLE_Y=Array.from({length:75},(_,i)=>Math.floor(i/3)*8+[1,4,6][i%3]);
const first=Array.from({length:256},(_,y)=>{const i=SAMPLE_Y.findIndex(value=>value>=y);return i<0?75:i;});
const hashes={
  xor:(dx,dy,phase)=>dx^dy^phase,
  y2:(dx,dy,phase)=>dx^(dy<<1)^phase,
  x2:(dx,dy,phase)=>(dx<<1)^dy^phase,
  y4p2:(dx,dy,phase)=>dx^(dy<<2)^(phase<<1),
  y5:(dx,dy,phase)=>dx^(dy*5)^phase
};

function edgesForFrame(model,frame,mode) {
  const yaw=mode===2||mode===3?0:frame*2&255;
  const pitch=mode===1||mode===3?24:(24+frame)&255;
  const roll=mode===1||mode===2?0:frame&255;
  const geometry=G.project(model,yaw,pitch,roll),edges=[];
  for(const face of geometry.faces)if(face.color&&face.visible)for(let edge=0;edge<face.indices.length;edge++) {
    const a=face.indices[edge],b=face.indices[(edge+1)%face.indices.length];
    let x0=geometry.x[a],y0=geometry.y[a],x1=geometry.x[b],y1=geometry.y[b];
    if(y0===y1)continue;
    if(y0>y1){[x0,x1]=[x1,x0];[y0,y1]=[y1,y0];}
    const start=first[y0],end=first[y1];if(start===end)continue;
    const dx=Math.abs(x1-x0),dy=y1-y0,phase=(y0&7)|(x1<x0?8:0);
    edges.push({dx,dy,phase,samples:end-start,key:dx+':'+dy+':'+phase});
  }
  return edges;
}

const report={framesPerCase:512,curveCapacity:24,cases:{}};
for(const model of ['checker','football'])for(let mode=0;mode<4;mode++) {
  const frames=Array.from({length:512},(_,frame)=>edgesForFrame(model,frame,mode));
  const all=frames.flat(),entry={edges:all.length,edgeSamples:all.reduce((sum,e)=>sum+e.samples,0),maximumSamples:Math.max(...all.map(e=>e.samples)),candidates:{}};
  for(const slots of [32,64,128])for(const [name,hash]of Object.entries(hashes)) {
    const cache=new Array(slots).fill(null);let hits=0,misses=0,bypasses=0,sampleHits=0;
    for(const edge of all) {
      if(edge.samples>24){bypasses++;continue;}
      const slot=hash(edge.dx,edge.dy,edge.phase)&(slots-1);
      if(cache[slot]===edge.key){hits++;sampleHits+=edge.samples;}
      else {misses++;cache[slot]=edge.key;}
    }
    entry.candidates[slots+'/'+name]={slots,hash:name,hits,misses,bypasses,hitRate:hits/Math.max(1,hits+misses),sampleHitRate:sampleHits/entry.edgeSamples};
  }
  report.cases[model+'/'+mode]=entry;
}
const totals={};for(const entry of Object.values(report.cases))for(const [name,counts]of Object.entries(entry.candidates)) {
  const row=totals[name]||(totals[name]={hits:0,misses:0,edges:0,sampleHits:0,samples:0});
  row.hits+=counts.hits;row.misses+=counts.misses;row.edges+=entry.edges;row.sampleHits+=counts.sampleHitRate*entry.edgeSamples;row.samples+=entry.edgeSamples;
}
report.totals=Object.fromEntries(Object.entries(totals).map(([name,row])=>[name,{...row,hitRate:row.hits/row.edges,sampleHitRate:row.sampleHits/row.samples}]));
fs.writeFileSync(path.join(__dirname,'host-hits.json'),JSON.stringify(report,null,2)+'\n');
console.table(Object.fromEntries(Object.entries(report.totals).map(([name,row])=>[name,{edgeHitPercent:(100*row.hitRate).toFixed(2),sampleHitPercent:(100*row.sampleHitRate).toFixed(2)}])));
