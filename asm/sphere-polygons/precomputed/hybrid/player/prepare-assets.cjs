'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const common=require('../common.cjs'),wire=require('../container.cjs');
const fills=require('../fill.cjs').codecs,edges=[...require('../edges.cjs').codecs,...require('../edge-maps.cjs').codecs];
const fast=process.argv.includes('--motion=fast');
const prepared=fast?{frames:common.getCorpus().models.checker.filter((_,i)=>i%4===0),motion:{kind:'original-three-axis-loop',step:[8,4,4],frames:64}}:require('./motion.cjs').makeMotion();
const frames=prepared.frames,layout=common.layouts.circle,edgeId=edges.findIndex(c=>c.name==='edges-map-raw-circle');
const target=path.join(__dirname,'build','assets'),reference=path.join(__dirname,'build','reference');fs.mkdirSync(target,{recursive:true});fs.mkdirSync(reference,{recursive:true});
const ep=[];ep[edgeId]=frames.map(screen=>edges[edgeId].encode(screen));
let compact;
for(const fillId of[1,0]){
 const fp=[];fp[fillId]=frames.map(screen=>fills[fillId].encode(screen,layout.indices));
 const file=wire.serializeHybrid(frames,layout,fillId,edgeId,fp,ep);const decoded=wire.deserialize(file);decoded.forEach((screen,i)=>assert.deepEqual(screen,frames[i]));
 const name=fillId===1?'checker-64.hc64':'checker-64-raw.hc64';fs.writeFileSync(path.join(target,name),file);if(fillId===1)compact=file;
}
fs.copyFileSync(path.join(common.BASE,'assets','font.bin'),path.join(target,'font.bin'));
fs.writeFileSync(path.join(reference,'checker-64-screen.bin'),Buffer.concat(frames.map(frame=>Buffer.from(frame))));
const packets=[];let offset=62;
for(let i=0;i<64;i++){const fillLength=compact.readUInt16LE(offset),edgeLength=compact.readUInt16LE(offset+2);packets.push({frame:i,offset,fillLength,edgeLength,glyphs:edgeLength-60,length:4+fillLength+edgeLength});offset+=packets[i].length;}assert.equal(offset,compact.length);
const description={format:'HC64 v1',model:'checker',motion:prepared.motion,frames:64,frameBytes:1000,frameCountOffset:7,layoutOffset:12,layoutBytes:50,firstFrameOffset:62,fillCodec:1,edgeCodec:edgeId,activeCells:475,expandedFillBytes:60,edgePresenceBytes:60,maxGlyphs:Math.max(...packets.map(p=>p.glyphs)),rowSpans:Array.from({length:25},(_,row)=>({row,start:compact[12+2*row],length:compact[13+2*row],screenOffset:row*40+compact[12+2*row]})),indices:layout.indices,packets,encodedBytes:compact.length,sha256:crypto.createHash('sha256').update(compact).digest('hex'),fontSha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(target,'font.bin'))).digest('hex')};
fs.writeFileSync(path.join(target,'data-layout.json'),JSON.stringify(description,null,2)+'\n');console.log(JSON.stringify({assets:target,frames:64,bytes:compact.length,maxGlyphs:description.maxGlyphs,firstFrameOffset:62},null,2));
