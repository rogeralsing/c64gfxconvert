'use strict';
// Freeze the checker movie as projected vertices and shared white-face topology.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {BASE}=require('../common.cjs');
const mesh=require(path.join(BASE,'meshes.cjs')).getMesh('checker');
const {projectSmoothFrame}=require('../lines/geometry-lines.cjs');
const {makeMotion}=require('../player/motion.cjs');
const {createModel}=require(path.join(BASE,'native-model.cjs'));
const raster=require(path.join(BASE,'raster.cjs'));
const selected=mesh.faces.map((face,index)=>({face,index})).filter(record=>record.face.color);
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');

function projectedFrames(){
 const cp=Math.cos(22*Math.PI/180),sp=Math.sin(22*Math.PI/180);
 return Array.from({length:64},(_,index)=>{
  const geometry=projectSmoothFrame(index),yaw=index*60/64*Math.PI/180,cy=Math.cos(yaw),sy=Math.sin(yaw);
  return{xy:Uint8Array.from(geometry.points.flat()),visible:selected.map(({face})=>(-cp*sy*face.normal[0]+sp*face.normal[1]+cp*cy*face.normal[2]) < -1e-10)};
 });
}

function serialize(frames){
 const pairs=new Map();
 for(let frame=1;frame<frames.length;frame++)for(let v=0;v<62;v++){
  const pair=[frames[frame].xy[v*2]-frames[frame-1].xy[v*2],frames[frame].xy[v*2+1]-frames[frame-1].xy[v*2+1]];pairs.set(pair.join(','),pair);
 }
 const book=[...pairs.values()].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);assert.equal(book.length,15);
 const codes=new Map(book.map((pair,i)=>[pair.join(','),i]));
 const header=Buffer.from([80,86,54,52,1,1,62,36,64,0,4,book.length]);
 const topology=Buffer.from(selected.flatMap(({face})=>[(face.color<<7)|face.indices.length,...face.indices]));assert.equal(topology.length,168);
 const parts=[header,topology,Buffer.from(book.flat().map(value=>value&255))];
 for(let frame=0;frame<frames.length;frame++){
  let xy;
  if(!frame)xy=Buffer.from(frames[frame].xy);
  else{
   xy=Buffer.alloc(31);
   for(let v=0;v<62;v++){
    const pair=[frames[frame].xy[v*2]-frames[frame-1].xy[v*2],frames[frame].xy[v*2+1]-frames[frame-1].xy[v*2+1]];
    xy[v>>>1]|=codes.get(pair.join(','))<<((v&1)*4);
   }
  }
  const visible=Buffer.alloc(5);frames[frame].visible.forEach((value,face)=>{if(value)visible[face>>>3]|=1<<(face&7);});parts.push(xy,visible);
 }
 const blob=Buffer.concat(parts);assert.equal(blob.length,2607);return blob;
}

function deserialize(blob){
 assert.equal(blob.subarray(0,4).toString(),'PV64');assert.deepEqual(Array.from(blob.subarray(4,12)),[1,1,62,36,64,0,4,15]);
 let read=12;const faces=[];
 for(let face=0;face<36;face++){
  const tag=blob[read++],count=tag&127;assert(count===3||count===4);assert(tag&128);
  const indices=Array.from(blob.subarray(read,read+count));assert(indices.every(index=>index<62));faces.push({color:1,indices});read+=count;
 }
 assert.equal(read,180);const book=[];
 for(let code=0;code<15;code++){book.push([blob.readInt8(read),blob.readInt8(read+1)]);read+=2;}
 assert.equal(read,210);let xy;
 const frames=[];
 for(let frame=0;frame<64;frame++){
  if(!frame){xy=Uint8Array.from(blob.subarray(read,read+124));read+=124;}
  else{
   for(let v=0;v<62;v++){
    const code=(blob[read+(v>>>1)]>>>((v&1)*4))&15;assert(code<book.length);
    for(let axis=0;axis<2;axis++){const value=xy[v*2+axis]+book[code][axis];assert(value>=0&&value<=255);xy[v*2+axis]=value;}
   }
   read+=31;
  }
  const visibility=Uint8Array.from(blob.subarray(read,read+5));read+=5;
  assert.equal(visibility[4]&240,0);
  frames.push({xy:Uint8Array.from(xy),visibility,faces:faces.map((face,index)=>({...face,visible:!!(visibility[index>>>3]&(1<<(index&7)))}))});
 }
 assert.equal(read,blob.length);return{faces,book,frames};
}

function generate(directory=path.join(__dirname,'build/assets')){
 fs.mkdirSync(directory,{recursive:true});
 const input=projectedFrames(),blob=serialize(input),decoded=deserialize(blob),model=createModel(),motion=makeMotion();
 const coverage=[];
 decoded.frames.forEach((frame,index)=>{
  assert.deepEqual(frame.xy,input[index].xy);
  const x=Uint8Array.from({length:62},(_,v)=>frame.xy[v*2]),y=Uint8Array.from({length:62},(_,v)=>frame.xy[v*2+1]);
  const result=raster.rasterize(x,y,frame.faces,{tables:model.tables});coverage.push(result.coverage);
  assert.deepEqual(model.resolve(result.coverage),motion.frames[index],`Projected geometry frame${index}`);
 });
 fs.writeFileSync(path.join(directory,'white-delta.pv64'),blob);
 fs.writeFileSync(path.join(directory,'reference.bin'),Buffer.concat(motion.frames.map(frame=>Buffer.from(frame))));
 fs.writeFileSync(path.join(directory,'coverage-reference.bin'),Buffer.concat(coverage.map(frame=>Buffer.from(frame))));
 fs.writeFileSync(path.join(directory,'xy-reference.bin'),Buffer.concat(input.map(frame=>Buffer.from(frame.xy))));
 const tables=['font','ratio-q','ratio-r','ratio-row-lo','ratio-row-hi','sample-y','sample-gap','first-sample','sample-row-lo','sample-row-hi','left-masks','right-masks','full-masks','glyph-lut','glyph-compact','limb-remap','clip-records'];
 tables.forEach(name=>fs.copyFileSync(path.join(BASE,'assets',name+'.bin'),path.join(directory,name+'.bin')));
 const report={pass:true,format:'PV64 v1',motion:motion.motion,vertices:62,whiteFaces:36,triangleFaces:12,quadFaces:24,
  bytes:blob.length,headerBytes:12,topologyBytes:168,codebookBytes:30,firstFrameOffset:210,firstFrameBytes:129,followingFrameBytes:36,
  packedVertexBytes:31,visibilityBytes:5,framesVerified:64,screenBytesVerified:64000,movieSha256:hash(blob),
  fontSha256:hash(model.assets.font),tableBytes:tables.reduce((sum,name)=>sum+fs.statSync(path.join(directory,name+'.bin')).size,0),
  assetHashes:Object.fromEntries(tables.map(name=>[name+'.bin',hash(fs.readFileSync(path.join(directory,name+'.bin')))])),
  inputHashes:Object.fromEntries(['meshes.cjs','raster.cjs','native-model.cjs','precomputed/hybrid/player/motion.cjs','precomputed/hybrid/lines/geometry-lines.cjs','precomputed/hybrid/vertices/generate.cjs'].map(name=>[name,hash(fs.readFileSync(path.join(BASE,name)))]))};
 fs.writeFileSync(path.join(directory,'manifest.json'),JSON.stringify(report,null,2)+'\n');return report;
}
module.exports={projectedFrames,serialize,deserialize,generate};
if(require.main===module)console.log(JSON.stringify(generate(),null,2));
