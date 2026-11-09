'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const common=require('../common.cjs'),wire=require('../container.cjs'),predictive=require('../delta-wire.cjs');
const fill=require('../fill.cjs').codecs[1],edge=require('../edge-maps.cjs').codecs.find(codec=>codec.name==='edges-map-raw-circle');
const patch=require('../delta.cjs').codecs[1];

function prepareDelta(frames,directory){
 const keys=frames.map(screen=>wire.encodeKey(fill.encode(screen,common.layouts.circle.indices),edge.encode(screen)));
 const deltas=frames.map((screen,i)=>i?patch.encode(screen,frames[i-1]):null);
 const packed=predictive.serialize(frames,keys,deltas,1,1,'adaptive');
 const checkedBytes=predictive.verify(packed.blob,frames);
 fs.mkdirSync(directory,{recursive:true});
 const filename='checker-64-smooth-delta1-lag1.hd64';
 fs.writeFileSync(path.join(directory,filename),packed.blob);
 const metadata={format:'HD64 v1',file:filename,frames:frames.length,encodedBytes:packed.blob.length,
  keyFrames:packed.keyCount,patchFrames:packed.patchCount,codec:'delta-packets64',lag:1,
  firstFrameOffset:64,layoutBytes:50,checkedBytes,
  sha256:crypto.createHash('sha256').update(packed.blob).digest('hex')};
 fs.writeFileSync(path.join(directory,'delta-layout.json'),JSON.stringify(metadata,null,2)+'\n');
 return metadata;
}
module.exports={prepareDelta};
