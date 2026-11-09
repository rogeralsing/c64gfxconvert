'use strict';
// Independent-frame reference: two common glyphs have one-byte run packets.
function encode(screen){
 const n=screen.length,cost=new Uint32Array(n+1),choice=new Array(n);
 for(let i=n-1;i>=0;i--){let best=Infinity,bestLength=1,bestType=2;
  for(let length=1;length<=64&&i+length<=n;length++){const c=1+length+cost[i+length];if(c<best){best=c;bestLength=length;bestType=2;}}
  let run=1;while(run<64&&i+run<n&&screen[i+run]===screen[i])run++;
  for(let length=1;length<=run;length++){const common=screen[i]===0||screen[i]===15,type=common?(screen[i]===0?0:1):3,c=(common?1:2)+cost[i+length];if(c<best){best=c;bestLength=length;bestType=type;}}
  cost[i]=best;choice[i]=[bestLength,bestType];
 }
 const out=[];for(let i=0;i<n;){const[length,type]=choice[i];out.push((type<<6)|(length-1));if(type===2)out.push(...screen.subarray(i,i+length));else if(type===3)out.push(screen[i]);i+=length;}return Uint8Array.from(out);
}
function decode(payload,count=1000){
 const out=new Uint8Array(count);let read=0,write=0;
 while(write<count){if(read>=payload.length)throw Error('Truncated RLE header');const tag=payload[read++],type=tag>>>6,length=(tag&63)+1;if(write+length>count)throw Error('RLE exceeds screen');
  if(type===2){if(read+length>payload.length)throw Error('Truncated RLE literals');out.set(payload.subarray(read,read+length),write);read+=length;}
  else if(type===3){if(read>=payload.length)throw Error('Truncated RLE repeat');out.fill(payload[read++],write,write+length);}
  else out.fill(type===0?0:15,write,write+length);write+=length;
 }
 if(read!==payload.length)throw Error('Trailing RLE bytes');return out;
}
module.exports={encode,decode};
