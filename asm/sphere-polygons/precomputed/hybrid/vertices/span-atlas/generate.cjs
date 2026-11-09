'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const ROOT=path.resolve(__dirname,'../../../..');
const {projectedFrames}=require('../generate.cjs');
const {getMesh}=require(path.join(ROOT,'meshes.cjs'));
const {createModel}=require(path.join(ROOT,'native-model.cjs'));
const mesh=getMesh('checker'),faces=mesh.faces.filter(face=>face.color),counts=Uint8Array.from(faces,face=>face.indices.length);
const sampleY=Array.from({length:75},(_,sample)=>Math.floor(sample/3)*8+[1,4,6][sample%3]);
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');

function extract(frame,face){
 const points=face.indices.map(vertex=>[frame.xy[vertex*2],frame.xy[vertex*2+1]]);
 const low=Math.min(...points.map(point=>point[1])),high=Math.max(...points.map(point=>point[1]));
 const first=sampleY.findIndex(y=>y>=low),end=sampleY.findIndex(y=>y>=high);
 const stop=end<0?75:end,start=first<0?75:first,left=[],right=[];
 for(let sample=start;sample<stop;sample++){
  const crosses=[];
  points.forEach((a,i)=>{let b=points[(i+1)%points.length];if(a[1]===b[1])return;if(a[1]>b[1])[a,b]=[b,a];
   if(sampleY[sample]>=a[1]&&sampleY[sample]<b[1])crosses.push(Math.ceil((a[0]*(b[1]-a[1])+(b[0]-a[0])*(sampleY[sample]-a[1]))/(b[1]-a[1])));
  });
  left.push(crosses.length?Math.min(...crosses):255);right.push(crosses.length?Math.max(...crosses):0);
 }
 return {first:start,left,right};
}

function patternFor(span){
 const base=Math.min(...span.left,...span.right),left=span.left.map(x=>x-base),right=span.right.map(x=>x-base),bytes=[left.length];
 if(left.length){bytes.push(left[0],right[0]);for(let i=1;i<left.length;i++){
  const dl=left[i]-left[i-1],dr=right[i]-right[i-1];
  if(dl>=-7&&dl<=7&&dr>=-7&&dr<=7)bytes.push((dl+7)|((dr+7)<<4));
  else bytes.push(255,left[i],right[i]);
 }}
 return {base,bytes:Buffer.from(bytes)};
}

function serialize(frames){
 const pool=[],seen=new Map(),records=[];let poolBytes=0,visibleCount=0,rawSpanBytes=0;
 for(const frame of frames){const visibility=Buffer.alloc(5),parts=[visibility];
  faces.forEach((face,index)=>{if(!frame.visible[index])return;visibility[index>>>3]|=1<<(index&7);visibleCount++;
   const span=extract(frame,face),pattern=patternFor(span);rawSpanBytes+=span.left.length*2;
   const key=pattern.bytes.toString('hex');let offset=seen.get(key);
   if(offset===undefined){offset=poolBytes;seen.set(key,offset);pool.push(pattern.bytes);poolBytes+=pattern.bytes.length;}
   assert(offset<65536&&pattern.base>=0&&pattern.base<=255);parts.push(Buffer.from([span.first,pattern.base,offset&255,offset>>>8]));
  });records.push(Buffer.concat(parts));
 }
 const header=Buffer.from([83,65,54,52,1,36,64,0,poolBytes&255,poolBytes>>>8,1,0]);
 return {bytes:Buffer.concat([header,counts,...pool,...records]),poolBytes,uniquePatterns:seen.size,visibleCount,rawSpanBytes,frameBytes:records.map(record=>record.length)};
}

function deserialize(bytes){
 assert.equal(bytes.subarray(0,4).toString(),'SA64');assert.equal(bytes[4],1);assert.equal(bytes[5],36);assert.equal(bytes.readUInt16LE(6),64);
 assert.equal(bytes[10],1);assert.equal(bytes[11],0);const decodedCounts=bytes.subarray(12,48),poolBytes=bytes.readUInt16LE(8),pool=bytes.subarray(48,48+poolBytes),frames=[];
 let read=48+poolBytes;
 for(let frame=0;frame<64;frame++){
  const visible=bytes.subarray(read,read+5);read+=5;const spans=[];
  for(let face=0;face<36;face++)if((visible[face>>>3]>>>(face&7))&1){
   const first=bytes[read],base=bytes[read+1],offset=bytes.readUInt16LE(read+2);read+=4;
   let p=offset,n=pool[p++],left=[],right=[];
   if(n){let l=pool[p++],r=pool[p++];left.push(base+l);right.push(base+r);
    for(let i=1;i<n;i++){const code=pool[p++];if(code===255){l=pool[p++];r=pool[p++];}else{l+=(code&15)-7;r+=(code>>>4)-7;}left.push(base+l);right.push(base+r);}
   }
   assert(first+n<=75&&left.every(x=>x>=0&&x<256)&&right.every(x=>x>=0&&x<256));spans.push({face,count:decodedCounts[face],first,left,right});
  }frames.push(spans);
 }
 assert.equal(read,bytes.length);return {frames,counts:decodedCounts,poolBytes};
}

function coverageFor(spans,tables){
 const coverage=new Uint8Array(1000);
 for(const span of spans)for(let i=0;i<span.left.length;i++){
  const l=span.left[i],r=span.right[i];if(l>=r)continue;const sample=span.first+i,part=(sample%3)*8,row=Math.floor(sample/3)*40,lc=l>>>3,rc=r>>>3;
  const lm=tables.leftMasks[part+(l&7)],rm=tables.rightMasks[part+(r&7)];
  if(lc===rc)coverage[row+lc]|=lm&rm;else{coverage[row+lc]|=lm;for(let x=lc+1;x<rc;x++)coverage[row+x]|=tables.fullMasks[sample%3];coverage[row+rc]|=rm;}
 }return coverage;
}

function generate(output=path.join(__dirname,'build/assets')){
 fs.mkdirSync(output,{recursive:true});const frames=projectedFrames(),encoded=serialize(frames),decoded=deserialize(encoded.bytes),model=createModel();
 const ref=fs.readFileSync(path.join(__dirname,'../build/assets/reference.bin')),cov=fs.readFileSync(path.join(__dirname,'../build/assets/coverage-reference.bin'));
 decoded.frames.forEach((spans,index)=>{const coverage=coverageFor(spans,model.tables);assert.deepEqual(Buffer.from(coverage),cov.subarray(index*1000,(index+1)*1000));assert.deepEqual(Buffer.from(model.resolve(coverage)),ref.subarray(index*1000,(index+1)*1000));});
 fs.writeFileSync(path.join(output,'spans.sa64'),encoded.bytes);
 const names=['font','sample-row-lo','sample-row-hi','left-masks','right-masks','glyph-lut','glyph-compact','limb-remap','clip-records'];
 names.forEach(name=>fs.copyFileSync(path.join(ROOT,'assets',name+'.bin'),path.join(output,name+'.bin')));
 const report={pass:true,format:'SA64 v1',frames:64,whiteFaces:36,headerBytes:12,faceCountsBytes:36,poolBytes:encoded.poolBytes,
  uniquePatterns:encoded.uniquePatterns,visibleFaceRecords:encoded.visibleCount,rawSpanBytes:encoded.rawSpanBytes,
  movieBytes:encoded.bytes.length,frameRecordsBytes:encoded.frameBytes.reduce((a,b)=>a+b,0),meanFrameBytes:encoded.frameBytes.reduce((a,b)=>a+b,0)/64,
  sharedTableBytes:names.reduce((sum,name)=>sum+fs.statSync(path.join(output,name+'.bin')).size,0),movieSha256:sha(encoded.bytes),coverageBytesCompared:64000,screenBytesCompared:64000,
  sourceHashes:{'generate.cjs':sha(fs.readFileSync(__filename)),'fast-fill/kernel.asm':sha(fs.readFileSync(path.join(__dirname,'../fast-fill/kernel.asm')))}};
 fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify(report,null,2)+'\n');return report;
}
module.exports={extract,patternFor,serialize,deserialize,coverageFor,generate};
if(require.main===module)console.log(JSON.stringify(generate(),null,2));
