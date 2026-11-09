'use strict';
const assert=require('node:assert/strict');
const common=require('./common.cjs'),fill=require('./fill.cjs').codecs;
const edges=[...require('./edges.cjs').codecs,...require('./edge-maps.cjs').codecs];
const alternating=require('./alternating.cjs').variants,baseline=require('./baseline-rle.cjs');
function bytes(parts){return Buffer.concat(parts.map(p=>Buffer.from(p)));}
function word(n){assert(n>=0&&n<=65535);return Uint8Array.from([n&255,n>>>8]);}
function header(count,layout,fillId,edgeId){return bytes([Buffer.from('HC64'),[1,40,25],word(count),[layout.id,fillId,edgeId],layout.metadata]);}
function serializeHybrid(frames,layout,fillId,edgeId,fillPackets,edgePackets,selection){
 const parts=[header(frames.length,layout,selection?253:fillId,selection?253:edgeId)];
 for(let i=0;i<frames.length;i++){const pair=selection?selection[i]:[fillId,edgeId];const fp=fillPackets[pair[0]][i],ep=edgePackets[pair[1]][i];if(selection)parts.push([pair[0]|(pair[1]<<4)]);parts.push(word(fp.length),word(ep.length),fp,ep);}return bytes(parts);
}
function serializeUnified(frames,codecId,packets){const parts=[header(frames.length,common.layouts.full,255,codecId)];for(const p of packets)parts.push(word(p.length),p);return bytes(parts);}
function readLayout(src,kind,read){let indices=[];
 if(kind===0)indices=Array.from({length:1000},(_,i)=>i);
 else if(kind===1){const[x,y,w,h]=src.subarray(read,read+4);read+=4;assert(x+w<=40&&y+h<=25);for(let row=y;row<y+h;row++)for(let col=x;col<x+w;col++)indices.push(row*40+col);}
 else if(kind===2){for(let row=0;row<25;row++){const x=src[read++],length=src[read++];assert(x+length<=40);for(let col=x;col<x+length;col++)indices.push(row*40+col);}}
 else throw Error('Unknown layout');return{indices,read};
}
function deserialize(src){
 assert.equal(src.subarray(0,4).toString(),'HC64');assert.equal(src[4],1);assert.equal(src[5],40);assert.equal(src[6],25);
 const count=src.readUInt16LE(7),kind=src[9],fillId=src[10],edgeId=src[11];let{indices,read}=readLayout(src,kind,12);const result=[];
 for(let i=0;i<count;i++){
  if(fillId===255){const n=src.readUInt16LE(read);read+=2;const p=src.subarray(read,read+n);read+=n;result.push(edgeId===254?baseline.decode(p):alternating[edgeId].decode(p));continue;}
  let f=fillId,e=edgeId;if(f===253){const mode=src[read++];f=mode&15;e=mode>>>4;}
  const fn=src.readUInt16LE(read),en=src.readUInt16LE(read+2);read+=4;
  const bits=fill[f].decode(src.subarray(read,read+fn),indices.length);read+=fn;
  const out=common.expandFill(bits,indices);edges[e].decode(src.subarray(read,read+en),out,indices);read+=en;result.push(out);
 }
 assert.equal(read,src.length);return result;
}
function encodeKey(fillPayload,edgePayload){return bytes([word(fillPayload.length),fillPayload,edgePayload]);}
function decodeKey(payload,indices,fillId,edgeId){const n=payload.readUInt16LE(0);const bits=fill[fillId].decode(payload.subarray(2,2+n),indices.length);const out=common.expandFill(bits,indices);edges[edgeId].decode(payload.subarray(2+n),out,indices);return out;}
module.exports={bytes,word,header,readLayout,serializeHybrid,serializeUnified,deserialize,encodeKey,decodeKey};
