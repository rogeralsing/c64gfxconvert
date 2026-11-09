'use strict';
// Shared frozen inputs and validation for the offline packing experiments.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const BASE=path.resolve(__dirname,'../..');
const {createModel}=require(path.join(BASE,'native-model.cjs'));
const circle=[];
for(let cell=0;cell<1000;cell++){
 let touches=false;
 for(let y=0;y<8&&!touches;y++)for(let x=0;x<8;x++)if(((cell%40)*8+x-160)**2+(Math.floor(cell/40)*8+y-100)**2<=94**2){touches=true;break;}
 if(touches)circle.push(cell);
}
const rowSpans=[];
for(let row=0;row<25;row++){
 const cells=circle.filter(cell=>Math.floor(cell/40)===row);
 rowSpans.push(cells.length?cells[0]%40:0,cells.length);
}
const layouts={
 full:{id:0,name:'full',indices:Array.from({length:1000},(_,i)=>i),metadata:new Uint8Array(0)},
 rectangle:{id:1,name:'rectangle',indices:Array.from({length:600},(_,i)=>Math.floor(i/24)*40+8+i%24),metadata:Uint8Array.from([8,0,24,25])},
 circle:{id:2,name:'circle',indices:circle,metadata:Uint8Array.from(rowSpans)}
};
let corpus;
function getCorpus(){
 if(corpus)return corpus;
 const model=createModel(),models={};
 for(const[name,id]of [['checker',0]])models[name]=Array.from({length:256},(_,i)=>model.frame(id,(2*i)&255,(24+i)&255,i).screen);
 const inputHashes=Object.fromEntries(['native-model.cjs','geometry.cjs','raster.cjs','meshes.cjs','math-font.cjs','assets/font.bin','assets/glyph-lut.bin','assets/clip-records.bin','assets/glyph-compact.bin','assets/limb-remap.bin'].map(file=>[file,crypto.createHash('sha256').update(fs.readFileSync(path.join(BASE,file))).digest('hex')]));
 corpus={models,inputHashes,fontBytes:2048,frames:256,trajectory:{start:[0,24,0],step:[2,1,1],period:256},layouts};
 return corpus;
}
function constraints(screen,indices){return Int8Array.from(indices,index=>screen[index]===0?0:screen[index]===15?1:-1);}
function edgeCells(screen){const edges=[];for(let i=0;i<1000;i++)if(screen[i]!==0&&screen[i]!==15)edges.push(i);return edges;}
function expandFill(bits,indices){assert.equal(bits.length,indices.length);const screen=new Uint8Array(1000);indices.forEach((cell,i)=>{assert(bits[i]===0||bits[i]===1);screen[cell]=bits[i]?15:0;});return screen;}
function checkFill(bits,screen,indices){const fixed=constraints(screen,indices);assert.equal(bits.length,fixed.length);for(let i=0;i<bits.length;i++){assert(bits[i]===0||bits[i]===1);if(fixed[i]>=0)assert.equal(bits[i],fixed[i],`Fixed fill bit ${i}`);}return true;}
function stats(values){assert(values.length);return{samples:values.length,min:Math.min(...values),mean:values.reduce((a,b)=>a+b,0)/values.length,max:Math.max(...values),total:values.reduce((a,b)=>a+b,0)};}
module.exports={BASE,getCorpus,layouts,constraints,edgeCells,expandFill,checkFill,stats};
