'use strict';
const fs=require('node:fs');
const path=require('node:path');
const G=require('./geometry.cjs');
const R=require('./raster.cjs');
const F=require('./math-font.cjs');
const NAMES=['checker','football'];

function createModel(directory=path.join(__dirname,'assets')) {
  const read=name=>fs.readFileSync(path.join(directory,name));
  const manifest=JSON.parse(read('manifest.json'));
  const assets={font:read('font.bin'),glyphLut:read('glyph-lut.bin'),compact:read('glyph-compact.bin'),remap:read('limb-remap.bin'),clipRecords:read('clip-records.bin')};
  const font=F.generateFont(256),tables=R.buildTables(font,{bits:8});
  if(!Buffer.from(tables.glyphLut).equals(assets.glyphLut))throw Error('Host raster lookup does not match native assets');
  function resolve(coverage) {
    const screen=Uint8Array.from(coverage,mask=>assets.glyphLut[mask]);
    for(let record=0;record<assets.clipRecords.length;record+=4) {
      const cell=assets.clipRecords.readUInt16LE(record),base=assets.clipRecords.readUInt16LE(record+2);
      const source=assets.compact[screen[cell]];
      if(source===255)throw Error('Unreachable glyph reached the silhouette remap');
      screen[cell]=assets.remap[base+source];
    }
    return screen;
  }
  function frame(model=0,yaw=0,pitch=24,roll=0) {
    const name=typeof model==='string'?model:NAMES[model];
    if(!NAMES.includes(name))throw Error('Unknown polygon model');
    const geometry=G.project(name,yaw,pitch,roll);
    const raster=R.rasterize(geometry.projectedX,geometry.projectedY,geometry.faces,{tables});
    return {name,geometry,coverage:raster.coverage,screen:resolve(raster.coverage),ops:raster.ops};
  }
  function reconstruct(screen) {
    const pixels=new Uint8Array(64000);
    for(let cell=0;cell<1000;cell++)for(let y=0;y<8;y++)for(let x=0;x<8;x++) {
      pixels[(Math.floor(cell/40)*8+y)*320+(cell%40)*8+x]=(assets.font[screen[cell]*8+y]>>>(7-x))&1;
    }
    return pixels;
  }
  return{manifest,assets,font,tables,frame,resolve,reconstruct};
}

module.exports={createModel,NAMES};
if(require.main===module) {
  const args=process.argv.slice(2),model=Number(args[0]),yaw=Number(args[1]),pitch=Number(args[2]);
  let statePath=null,roll=0,valid=args.length>=4&&(args.length-4)%2===0;
  for(let index=4;index<args.length;index+=2){if(args[index]==='--state')statePath=args[index+1];else if(args[index]==='--roll')roll=Number(args[index+1]);else valid=false;}
  if(!valid||!Number.isInteger(model)||model<0||model>1||!Number.isInteger(yaw)||yaw<0||yaw>255||!Number.isInteger(pitch)||pitch<0||pitch>255||!Number.isInteger(roll)||roll<0||roll>255) {
    console.error('Usage: node native-model.cjs MODEL YAW PITCH OUTPUT [--state STATE_JSON] [--roll ROLL]');process.exitCode=1;
  } else {
    const m=createModel(),f=m.frame(model,yaw,pitch,roll);fs.writeFileSync(path.resolve(args[3]),f.screen);
    if(statePath)fs.writeFileSync(path.resolve(statePath),JSON.stringify({model,yaw,pitch,roll,projectedX:[...f.geometry.projectedX],projectedY:[...f.geometry.projectedY],faceDepths:[...f.geometry.faceDepths],visible:[...f.geometry.visible],vertexCount:f.geometry.mesh.vertexCount,faceCount:f.geometry.mesh.faceCount,coverage:[...f.coverage],matrix:f.geometry.matrix,ops:f.ops},null,2)+'\n');
  }
}
