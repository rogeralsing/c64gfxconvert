'use strict';
// One bounded exact atlas: normalized sampled edge paths, not glyph strings.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const parent=path.resolve(__dirname,'..'),source=path.join(parent,'build/assets');
const {deserialize}=require('../generate.cjs'),{BASE}=require('../../common.cjs');
const {createModel}=require(path.join(BASE,'native-model.cjs'));
const word=n=>Buffer.from([n&255,n>>>8]),signed=n=>n<128?n:n-256;
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');

function edgePath(frame,a,b,tables){
 let x0=frame.xy[a*2],y0=frame.xy[a*2+1],x1=frame.xy[b*2],y1=frame.xy[b*2+1];
 if(y0>y1){[x0,x1]=[x1,x0];[y0,y1]=[y1,y0];}
 const first=tables.firstSample[y0],end=tables.firstSample[y1],xs=[];
 for(let sample=first;sample<end;sample++){
  // Exact rational ceil, equivalent to the native quotient/remainder DDA.
  xs.push(Math.ceil((x0*(y1-y0)+(x1-x0)*(tables.sampleY[sample]-y0))/(y1-y0)));
 }
 return{first:xs.length?first:0,xs};
}

function decodeCoverage(blob,frameIndex,frame,tables){
 assert.equal(blob.subarray(0,4).toString(),'EA64');
 assert.deepEqual(Array.from(blob.subarray(4,8)),[1,64,4,0]);
 const poolBytes=blob.readUInt16LE(8),recordBytes=blob.readUInt16LE(10),indexBytes=blob.readUInt16LE(12);
 assert.equal(indexBytes,128);const poolBase=16+indexBytes,recordsBase=poolBase+poolBytes;
 assert.equal(blob.length,recordsBase+recordBytes);
 let read=recordsBase+blob.readUInt16LE(16+frameIndex*2);
 const stop=recordsBase+(frameIndex<63?blob.readUInt16LE(18+frameIndex*2):recordBytes),coverage=new Uint8Array(1000);
 for(const face of frame.faces){if(!face.visible)continue;
  const ys=face.indices.map(i=>frame.xy[i*2+1]),first=tables.firstSample[Math.min(...ys)],end=tables.firstSample[Math.max(...ys)];
  const left=new Uint8Array(75).fill(255),right=new Uint8Array(75);
  for(let edge=0;edge<face.indices.length;edge++){
   const sample=blob[read],base=blob[read+1],offset=blob.readUInt16LE(read+2);read+=4;
   assert(offset<poolBytes);const entry=poolBase+offset,count=blob[entry];assert(sample+count<=75);
   assert(entry+Math.max(1,count)<=recordsBase);
   for(let i=0;i<count;i++){
    const x=base+(i?signed(blob[entry+i]):0),row=sample+i;assert(x>=0&&x<=255);
    left[row]=Math.min(left[row],x);right[row]=Math.max(right[row],x);
   }
  }
  for(let sample=first;sample<end;sample++){
   const l=left[sample],r=right[sample];if(r<=l)continue;
   const part=sample%3,row=Math.floor(sample/3)*40,lc=l>>>3,rc=r>>>3;
   const lm=tables.leftMasks[part*8+(l&7)],rm=tables.rightMasks[part*8+(r&7)];
   if(lc===rc)coverage[row+lc]|=lm&rm;
   else{coverage[row+lc]|=lm;for(let col=lc+1;col<rc;col++)coverage[row+col]|=tables.fullMasks[part];coverage[row+rc]|=rm;}
  }
 }
 assert.equal(read,stop);return coverage;
}

function generate(){
 const out=path.join(__dirname,'build');fs.mkdirSync(out,{recursive:true});
 const pv64=fs.readFileSync(path.join(source,'white-delta.pv64')),frames=deserialize(pv64).frames,model=createModel();
 const patterns=new Map(),pool=[],records=[],offsets=[];let edgeUses=0,sampleUses=0,emptyEdges=0;
 for(const frame of frames){offsets.push(word(records.length));
  for(const face of frame.faces){if(!face.visible)continue;
   for(let edge=0;edge<face.indices.length;edge++){
    const p=edgePath(frame,face.indices[edge],face.indices[(edge+1)%face.indices.length],model.tables);
    const base=p.xs.length?p.xs[0]:0,relative=p.xs.map(x=>x-base),key=relative.join(',');
    assert(relative.every(x=>x>=-128&&x<=127));
    if(!patterns.has(key)){patterns.set(key,pool.length);pool.push(relative.length,...relative.slice(1).map(x=>x&255));}
    const id=patterns.get(key);records.push(p.first,base,id&255,id>>>8);
    edgeUses++;sampleUses+=p.xs.length;if(!p.xs.length)emptyEdges++;
   }
  }
 }
 assert(pool.length<65536&&records.length<65536);
 const header=Buffer.from([69,65,54,52,1,64,4,0,...word(pool.length),...word(records.length),128,0,0,0]);
 const blob=Buffer.concat([header,...offsets,Buffer.from(pool),Buffer.from(records)]);
 const expectedCoverage=fs.readFileSync(path.join(source,'coverage-reference.bin')),expectedScreen=fs.readFileSync(path.join(source,'reference.bin'));
 frames.forEach((frame,index)=>{
  const coverage=decodeCoverage(blob,index,frame,model.tables);assert.deepEqual(Buffer.from(coverage),expectedCoverage.subarray(index*1000,(index+1)*1000));
  assert.deepEqual(Buffer.from(model.resolve(coverage)),expectedScreen.subarray(index*1000,(index+1)*1000));
 });
 fs.writeFileSync(path.join(out,'edge-atlas.ea64'),blob);
 fs.writeFileSync(path.join(out,'native-source.bin'),Buffer.concat([pv64,blob]));
 const report={pass:true,scope:'Exact sampled-edge atlas, fixed64checkerposes; no global dictionary optimum or nativeFPS claim.',frames:64,
  headerBytes:16,indexBytes:128,patternPoolBytes:pool.length,recordBytes:records.length,edgeRecordBytes:4,
  patterns:patterns.size,edgeUses,sampleUses,emptyEdges,atlasBytes:blob.length,pv64Bytes:pv64.length,combinedMovieBytes:pv64.length+blob.length,
  poolOffset:144,recordsOffset:144+pool.length,coverageBytesCompared:64000,screenBytesCompared:64000,
  atlasSha256:sha(blob),combinedSourceSha256:sha(Buffer.concat([pv64,blob])),pv64Sha256:sha(pv64)};
 fs.writeFileSync(path.join(out,'atlas.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));return report;
}
module.exports={generate,edgePath,decodeCoverage};if(require.main===module)generate();
