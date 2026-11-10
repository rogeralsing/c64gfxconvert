'use strict';
// Apply the existing 64-cell delta packets to line-program bytes, rather than
// final glyph codes. The fixed workspace keeps the decoder contract explicit.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const common=require('../common.cjs'),wire=require('../container.cjs'),geometry=require('./geometry-lines.cjs');
const fill=require('../fill.cjs').codecs[1],patch=require('../delta.cjs').codecs[1];
const {createModel}=require(path.join(common.BASE,'native-model.cjs'));
const {makeMotion}=require('../player/motion.cjs');
const word=wire.word;
const counts=Uint8Array.from(require(path.join(common.BASE,'meshes.cjs')).getMesh('checker').faces.filter(face=>face.color),face=>face.indices.length);

function serialize(programs,q,storedFill,exact,tables){
 const header=Buffer.from([76,80,54,52,1,q,Number(storedFill),Number(exact),programs.length,40,25,1,counts.length,2]);
 const parts=[header,counts,common.layouts.circle.metadata,tables.glyphLut,tables.ge,tables.eq];
 let previous,keys=0,patches=0;
 for(const program of programs){
  assert(program.length<=1000,'Line program exceeds the fixed parameter workspace');
  const padded=new Uint8Array(1000);padded.set(program);
  const delta=previous?patch.encode(padded,previous):null,key=!delta||program.length<=delta.length;
  const payload=key?program:delta;parts.push(word(payload.length|(key?32768:0)),payload);
  previous=padded;if(key)keys++;else patches++;
 }
 return{blob:Buffer.concat(parts.map(p=>Buffer.from(p))),keys,patches};
}

function decode(blob,expectedPrograms,expectedScreens){
 assert.equal(blob.subarray(0,4).toString(),'LP64');assert.equal(blob[4],1);
 const q=blob[5],storedFill=!!blob[6],count=blob[8],faceCount=blob[12];
 assert.equal(blob[9],40);assert.equal(blob[10],25);assert.equal(blob[11],1);assert.equal(blob[13],2);
 assert([8,16].includes(q));assert.equal(count,expectedPrograms.length);
 let read=14;const faces=blob.subarray(read,read+faceCount);read+=faceCount;
 const layout=wire.readLayout(blob,2,read);read=layout.read;
 const glyphLut=blob.subarray(read,read+256);read+=256;
 const size=(2*q+1)*q*2*3,ge=blob.subarray(read,read+size);read+=size;
 const eq=blob.subarray(read,read+size);read+=size;const start=read,tables={q,ge,eq,glyphLut};
 let workspace=null,comparedBytes=0;
 for(let loop=0;loop<3;loop++){
  read=start;
  for(let frame=0;frame<count;frame++){
   const tag=blob.readUInt16LE(read),key=!!(tag&32768),length=tag&32767;read+=2;
   assert(read+length<=blob.length);const payload=blob.subarray(read,read+length);read+=length;
   if(key){workspace=new Uint8Array(1000);assert(payload.length<=1000);workspace.set(payload);}
   else{assert(workspace);workspace=patch.decode(payload,workspace);}
   const expected=new Uint8Array(1000);expected.set(expectedPrograms[frame]);assert.deepEqual(workspace,expected);
   const f=workspace[0]|workspace[1]<<8,l=workspace[2]|workspace[3]<<8,p=workspace[4]|workspace[5]<<8;
   assert(6+f+l+p<=1000);
   const coverage=geometry.decodeCoverage(workspace.subarray(6+f,6+f+l),tables,faces,layout.indices);
   const lineScreen=geometry.resolveCoverage(coverage,glyphLut);
   let screen=lineScreen;
   if(storedFill){screen=common.expandFill(fill.decode(workspace.subarray(6,6+f),layout.indices.length),layout.indices);for(const cell of layout.indices)if(coverage[cell]!==0&&coverage[cell]!==255)screen[cell]=lineScreen[cell];}
   screen=geometry.applyPatches(screen,workspace.subarray(6+f+l,6+f+l+p));
   assert.deepEqual(screen,expectedScreens[frame]);comparedBytes+=2000;
  }
  assert.equal(read,blob.length);
 }
 return{comparedBytes,loops:3};
}

function study(directory=path.join(__dirname,'build')){
 fs.mkdirSync(directory,{recursive:true});
 const model=createModel(),{frames}=makeMotion(),q=8,tables=geometry.createTables(q,model.assets.glyphLut);
 const linePackets=frames.map((_,i)=>geometry.encodeFrame(i,q).packet);
 const coverages=linePackets.map(packet=>geometry.decodeCoverage(packet,tables));
 const fills=frames.map(screen=>fill.encode(screen,common.layouts.circle.indices)),rows=[];
 for(const storedFill of[false,true])for(const exact of[false,true]){
  const programs=[],screens=[];
  for(let i=0;i<frames.length;i++){
   const lineScreen=geometry.resolveCoverage(coverages[i],tables.glyphLut);let predicted=lineScreen;
   if(storedFill){predicted=common.expandFill(fill.decode(fills[i],common.layouts.circle.indices.length),common.layouts.circle.indices);for(const cell of common.layouts.circle.indices)if(coverages[i][cell]!==0&&coverages[i][cell]!==255)predicted[cell]=lineScreen[cell];}
   const exceptions=exact?geometry.encodePatches(predicted,frames[i]).packet:Buffer.from([0,0]);
   const f=storedFill?fills[i]:Buffer.alloc(0),l=linePackets[i];
   programs.push(Buffer.concat([word(f.length),word(l.length),word(exceptions.length),Buffer.from(f),l,exceptions]));
   screens.push(exact?frames[i]:predicted);
  }
  const packed=serialize(programs,q,storedFill,exact,tables),proof=decode(packed.blob,programs,screens);
  const name=`q${q}-${storedFill?'fill':'polygon'}-${exact?'exact':'approx'}`;
  fs.writeFileSync(path.join(directory,name+'.lp64'),packed.blob);
  rows.push({name,storedFill,exact,bytes:packed.blob.length,keys:packed.keys,patches:packed.patches,workspaceBytes:1000,sharedLookupBytes:tables.ge.length+tables.eq.length+tables.glyphLut.length,...proof});
 }
 const report={pass:true,scope:'Host-only serialized parameter deltas, including shared mathematical line tables. Full polygon half-plane baseline; not the edge-only renderer. No native timing or code size claim.',fontBytesSeparate:2048,rows};
 fs.writeFileSync(path.join(directory,'parameter-report.json'),JSON.stringify(report,null,2)+'\n');return report;
}
module.exports={serialize,decode,study};
if(require.main===module)console.log(JSON.stringify(study(),null,2));
