'use strict';
// An independent wire fixture guards transport of serialized layout metadata.
// The original edge-map decoder used the corpus circle instead of these cells.
const assert=require('node:assert/strict');
const wire=require('./container.cjs');
const metadata=new Uint8Array(50);metadata[10]=8;metadata[11]=8;
const header=Buffer.from([72,67,54,52,1,40,25,1,0,2,0,5]);
const frame=Buffer.from([1,0,2,0,0xaa,0x10,42]);
const file=Buffer.concat([header,metadata,frame]);
const expected=new Uint8Array(1000),indices=Array.from({length:8},(_,i)=>5*40+8+i);
indices.forEach((cell,i)=>{expected[cell]=i%2===0?15:0;});expected[indices[3]]=42;
assert.deepEqual(wire.deserialize(file),[expected]);
const key=Buffer.from([1,0,0xaa,0x10,42]);
assert.deepEqual(wire.decodeKey(key,indices,0,5),expected);
console.log(JSON.stringify({pass:true,serializedLayoutUsedByScreenDecoder:true,serializedLayoutUsedByDeltaKeyDecoder:true}));
