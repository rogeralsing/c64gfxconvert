'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const common=require('./common.cjs'),keyCodec=require('./baseline-rle.cjs');
const SCREEN=1000;
function screen(value){if(!(value instanceof Uint8Array)||value.length!==SCREEN)throw Error('Expected 1000 character bytes');return value;}
function putVar(out,value){do{const byte=value&127;value>>>=7;out.push(byte|(value?128:0));}while(value);}
function varSize(value){return value<128?1:2;}

// Literal groups begin/end at changed cells; DP can bridge any unchanged gap.
// The final group may also consume the unchanged tail instead of another pair.
function encodePairs(input,reference){
 const target=screen(input),base=screen(reference),changed=[];
 for(let i=0;i<SCREEN;i++)if(target[i]!==base[i])changed.push(i);
 if(!changed.length){const out=[];putVar(out,SCREEN);putVar(out,0);return Uint8Array.from(out);}
 const count=changed.length,cost=new Uint32Array(count+1),end=new Uint16Array(count),tail=new Uint8Array(count);
 const remaining=SCREEN-changed[count-1]-1;cost[count]=remaining?varSize(remaining)+1:0;
 for(let first=count-1;first>=0;first--){
  const skip=changed[first]-(first?changed[first-1]+1:0);let best=Infinity,bestEnd=first,bestTail=0;
  for(let last=first;last<count;last++){
   const length=changed[last]-changed[first]+1,value=varSize(skip)+varSize(length)+length+cost[last+1];
   if(value<best){best=value;bestEnd=last;}
  }
  const length=SCREEN-changed[first],value=varSize(skip)+varSize(length)+length;
  if(value<best){best=value;bestEnd=count-1;bestTail=1;}
  cost[first]=best;end[first]=bestEnd;tail[first]=bestTail;
 }
 const out=[];let first=0,position=0;
 while(first<count){const last=end[first],start=changed[first],stop=tail[first]?SCREEN:changed[last]+1;putVar(out,start-position);putVar(out,stop-start);for(let i=start;i<stop;i++)out.push(target[i]);position=stop;first=last+1;}
 if(position<SCREEN){putVar(out,SCREEN-position);putVar(out,0);}
 assert.equal(out.length,cost[0]);return Uint8Array.from(out);
}

function decodePairs(payload,reference,stats){
 const output=Uint8Array.from(screen(reference));let read=0,write=0;
 function variable(){let value=0,shift=0;for(;;){if(read>=payload.length||shift>21)throw Error('Truncated/oversized delta integer');const byte=payload[read++];value|=(byte&127)<<shift;if(!(byte&128))return value;shift+=7;}}
 while(write<SCREEN){const skip=variable(),literal=variable();if(!skip&&!literal)throw Error('Nonprogressing delta pair');if(write+skip+literal>SCREEN||read+literal>payload.length)throw Error('Delta pair exceeds frame/payload');write+=skip;output.set(payload.subarray(read,read+literal),write);read+=literal;write+=literal;if(stats){stats.skipped=(stats.skipped||0)+skip;stats.written=(stats.written||0)+literal;stats.packets=(stats.packets||0)+1;}}
 if(read!==payload.length)throw Error('Trailing delta pair bytes');return output;
}

function encodePackets(input,reference){
 const target=screen(input),base=screen(reference),same=new Uint16Array(SCREEN+1),repeat=new Uint16Array(SCREEN+1),cost=new Uint32Array(SCREEN+1),types=new Uint8Array(SCREEN),lengths=new Uint8Array(SCREEN);
 for(let i=SCREEN-1;i>=0;i--){same[i]=target[i]===base[i]?same[i+1]+1:0;repeat[i]=i+1<SCREEN&&target[i]===target[i+1]?repeat[i+1]+1:1;let best=Infinity,type=1,chosen=1;
  for(let length=1;length<=Math.min(64,SCREEN-i);length++){
   let value=1+length+cost[i+length];if(value<=best){best=value;type=1;chosen=length;}
   if(length<=repeat[i]){value=2+cost[i+length];if(value<=best){best=value;type=2;chosen=length;}}
   if(length<=same[i]){value=1+cost[i+length];if(value<=best){best=value;type=0;chosen=length;}}
  }
  cost[i]=best;types[i]=type;lengths[i]=chosen;
 }
 const out=[];for(let i=0;i<SCREEN;){const type=types[i],length=lengths[i];out.push((type<<6)|(length-1));if(type===1)for(let j=0;j<length;j++)out.push(target[i+j]);else if(type===2)out.push(target[i]);i+=length;}
 assert.equal(out.length,cost[0]);return Uint8Array.from(out);
}

function decodePackets(payload,reference,stats){
 const output=Uint8Array.from(screen(reference));let read=0,write=0;
 while(write<SCREEN){if(read>=payload.length)throw Error('Truncated delta opcode');const header=payload[read++],type=header>>>6,length=(header&63)+1;if(type===3||write+length>SCREEN)throw Error('Invalid delta opcode/range');
  if(type===0){if(stats)stats.skipped=(stats.skipped||0)+length;}
  else if(type===1){if(read+length>payload.length)throw Error('Truncated delta literals');output.set(payload.subarray(read,read+length),write);read+=length;if(stats)stats.written=(stats.written||0)+length;}
  else{if(read>=payload.length)throw Error('Truncated delta repeat');output.fill(payload[read++],write,write+length);if(stats)stats.written=(stats.written||0)+length;}
  if(stats)stats.packets=(stats.packets||0)+1;write+=length;
 }
 if(read!==payload.length)throw Error('Trailing delta opcode bytes');return output;
}

const codecs=[{name:'delta-varint-pairs',encode:encodePairs,decode:decodePairs},{name:'delta-packets64',encode:encodePackets,decode:decodePackets}];
function word(value){assert(value>=0&&value<=65535);return Buffer.from([value&255,value>>>8]);}
function record(mode,payload){return Buffer.concat([Buffer.from([mode]),word(payload.length),Buffer.from(payload)]);}

// This actual container includes a 12-byte global header and a mode byte plus
// 16-bit payload length for every frame. Font and optional seek index are separate.
function serialize(frames,{codecId,lag,policy='adaptive',closing=false,keys,patches}){
 const count=frames.length,header=Buffer.from([68,67,54,52,1,codecId,0,lag,count&255,count>>>8,policy==='adaptive'?0:Number(policy),closing?1:0]);
 const parts=[header],records=[];let keyframes=0,keyBytes=0,deltaBytes=0;
 for(let i=0;i<count;i++){
  const forced=i<lag||(policy!=='adaptive'&&i%Number(policy)<lag),isKey=forced||(policy==='adaptive'&&keys[i].length<=patches[i].length),payload=isKey?keys[i]:patches[i];
  parts.push(record(isKey?1:0,payload));records.push({mode:isKey?1:0,payload});if(isKey){keyframes++;keyBytes+=payload.length;}else deltaBytes+=payload.length;
 }
 let closingBytes=0;if(closing)for(let i=0;i<lag;i++){const packed=record(0,patches[i]);parts.push(packed);closingBytes+=packed.length;}
 const bytes=Buffer.concat(parts);
 return{bytes,keyframes,keyBytes,deltaBytes,closingBytes,framingBytes:12+3*(count+(closing?lag:0)),records};
}

function play(container,{loops=3,onFrame}={}){
 const src=Buffer.from(container);if(src.subarray(0,4).toString()!=='DC64'||src[4]!==1||src[6]!==0)throw Error('Unknown delta container');
 const codec=codecs[src[5]],lag=src[7],count=src.readUInt16LE(8),closing=src[11];if(!codec||![1,2].includes(lag)||count<lag||closing>1)throw Error('Invalid delta container metadata');let read=12;
 function packet(){if(read+3>src.length)throw Error('Truncated frame header');const mode=src[read++],length=src.readUInt16LE(read);read+=2;if(mode>1||read+length>src.length)throw Error('Invalid frame record');const payload=src.subarray(read,read+length);read+=length;return{mode,payload};}
 const records=Array.from({length:count},packet),closingRecords=closing?Array.from({length:lag},packet):[];
 if(read!==src.length)throw Error('Trailing container bytes');for(let i=0;i<lag;i++)if(records[i].mode!==1)throw Error('Missing initial keyframe');
 let canonical=new Uint8Array(SCREEN),global=0,decodedFrames=0;const buffers=[new Uint8Array(SCREEN),new Uint8Array(SCREEN)],stats={skipped:0,written:0,packets:0,keyframes:0};
 for(let loop=0;loop<loops;loop++)for(let index=0;index<count;index++,global++){
  const frame=closing&&loop>0&&index<lag?closingRecords[index]:records[index],target=global&1,reference=lag===1?canonical:buffers[target];
  let output;if(frame.mode===1){output=keyCodec.decode(frame.payload,SCREEN);stats.keyframes++;stats.written+=SCREEN;}else output=codec.decode(frame.payload,reference,stats);
  if(lag===1)canonical=output;else buffers[target]=output;
  if(onFrame)onFrame(output,index,loop);decodedFrames++;
 }
 return{decodedFrames,comparedBytes:decodedFrames*SCREEN,stats,referenceModel:lag===1?'canonical previous frame':'physical alternating back buffer (t-2)'};
}

function syntheticChecks(){
 const empty=new Uint8Array(SCREEN),solid=new Uint8Array(SCREEN).fill(15),edges=Uint8Array.from({length:SCREEN},(_,i)=>i%2?37:0),arbitrary=Uint8Array.from({length:SCREEN},(_,i)=>i&255);
 const results=[];for(const codec of codecs){const sizes=[];for(const[base,target]of[[empty,empty],[empty,solid],[solid,empty],[edges,empty],[edges,solid],[arbitrary,edges],[edges,arbitrary]]){const payload=codec.encode(target,base),before=Buffer.from(base),output=codec.decode(payload,base);assert.deepEqual(output,target);assert(Buffer.from(base).equals(before));sizes.push(payload.length);}results.push({codec:codec.name,serializedBytes:sizes});}
 return results;
}

async function study(){
 const corpus=common.getCorpus(),report={pass:false,scope:'Actual serialized key/delta containers, fixed font; host roundtrips only, no C64 cycle or FPS claim.',keyCodec:'baseline-rle.cjs common-character RLE',headerBytes:12,frameHeaderBytes:3,fontBytes:corpus.fontBytes,optionalSeekIndex:'Not included; records have sequential lengths.',loops:3,inputHashes:corpus.inputHashes,synthetic:syntheticChecks(),results:[],best:[]};
 const outdir=path.join(__dirname,'build');fs.mkdirSync(outdir,{recursive:true});
 const keyCache=new Map();let checkedFrames=0;
 for(const[model,all]of Object.entries(corpus.models))for(const step of[1,4]){
  const frames=all.filter((_,i)=>i%step===0),period=frames.length;
  const keys=frames.map(frame=>{if(!keyCache.has(frame))keyCache.set(frame,keyCodec.encode(frame));return keyCache.get(frame);});
  const independentBytes=12+2*period+keys.reduce((sum,p)=>sum+p.length,0);
  for(const lag of[1,2]){
   let best=null;
   for(let codecId=0;codecId<codecs.length;codecId++){
    const codec=codecs[codecId],patches=frames.map((frame,i)=>codec.encode(frame,frames[(i-lag+period)%period])),sizes=patches.map(p=>p.length);
    console.log(JSON.stringify({progress:model,period,lag,codec:codec.name,meanCircularPatchBytes:sizes.reduce((a,b)=>a+b,0)/period}),);
    for(const policy of['16','32','adaptive'])for(const closing of[false,true]){
     const packed=serialize(frames,{codecId,lag,policy,closing,keys,patches});
     const proof=play(packed.bytes,{loops:3,onFrame(output,index){assert.deepEqual(output,frames[index],model+'/'+period+'/'+lag+'/'+codec.name+'/'+policy+'/'+index);}});checkedFrames+=proof.decodedFrames;
     const row={model,period,step,lag,codec:codec.name,policy,wrap:closing?'closing patches':'reload first keys',serializedBytes:packed.bytes.length,withFontBytes:packed.bytes.length+corpus.fontBytes,keyframes:packed.keyframes,keyPayloadBytes:packed.keyBytes,deltaPayloadBytes:packed.deltaBytes,framingBytes:packed.framingBytes,closingPatchRecordBytes:packed.closingBytes,independentRleBytes:independentBytes,changeFromIndependentPercent:100*(packed.bytes.length/independentBytes-1),meanCircularPatchBytes:sizes.reduce((a,b)=>a+b,0)/period,minPatchBytes:Math.min(...sizes),maxPatchBytes:Math.max(...sizes),decodedFrames:proof.decodedFrames,loopDecoder:proof.referenceModel,patchAndKeyWritesPerFrame:proof.stats.written/proof.decodedFrames,skippedCellsPerFrame:proof.stats.skipped/proof.decodedFrames};
     report.results.push(row);if(!best||row.serializedBytes<best.row.serializedBytes)best={row,bytes:packed.bytes};
    }
   }
   const filename=`delta-best-${model}-${period}-lag${lag}.dc64`;fs.writeFileSync(path.join(outdir,filename),best.bytes);report.best.push({...best.row,file:filename});
  }
 }
 report.pass=true;report.checkedFrames=checkedFrames;report.checkedBytes=checkedFrames*SCREEN;fs.writeFileSync(path.join(outdir,'delta-report.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({pass:true,report:path.join(outdir,'delta-report.json'),checkedFrames,best:report.best},null,2));return report;
}

module.exports={codecs,encodePairs,decodePairs,encodePackets,decodePackets,serialize,play,syntheticChecks,study};
if(require.main===module)study().catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});
