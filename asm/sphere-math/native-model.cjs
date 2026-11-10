'use strict';
const fs=require('node:fs');
const path=require('node:path');

function createModel(directory=path.join(__dirname,'assets')) {
  const manifest=JSON.parse(fs.readFileSync(path.join(directory,'manifest.json'),'utf8'));
  const read=name=>fs.readFileSync(path.join(directory,name));
  const assets={records:read('records.bin'),probes:read('probes.bin'),valid:read('valid.bin'),single:read('single.bin'),xor:read('xor.bin'),inverse:read('inverse.bin'),probeLut:read('probe-lut.bin'),font:read('font.bin'),scaleSingle:read('scale-single.bin'),scalePair:read('scale-pair.bin')};
  const clipped=Array.from({length:manifest.tileCount},(_,tile)=>assets.records[tile*13+2]).some(flags=>flags&8);
  assets.glyphCompact=clipped?read('glyph-compact.bin'):null;
  assets.limbRemap=clipped?read('limb-remap.bin'):null;
  function render(spin=0,mode=0) {
    spin&=127;const screen=new Uint8Array(1000);
    for(let tile=0;tile<manifest.tileCount;tile++) {
      const r=tile*13,flags=assets.records[r+2],phase=(assets.records[r+3]+spin)&127,uParity=phase>>>6,f=phase&63;
      let glyph;
      if(mode===1||(flags&1)) {
        const valid=assets.valid.readUInt16LE(tile*2);let bits=0;
        for(let probe=0;probe<9;probe++)if((valid&(1<<probe))&&((assets.probes[tile*9+probe]+spin)&64))bits|=1<<probe;
        glyph=assets.probeLut[bits];
        if(flags&8) {
          const base=assets.records.readUInt16LE(r+5);
          glyph=assets.limbRemap[base+assets.glyphCompact[glyph]];
        }
      }else if(Math.min(f,64-f)>assets.records[r+12]) {
        glyph=assets.records[r+8];if(uParity)glyph=assets.inverse[glyph];
      }else {
        const row=assets.records[r+4]*64;
        if(!(flags&2)) {
          const offset=assets.scaleSingle[row+f],base=assets.records[r+5]+256*assets.records[r+6];
          glyph=assets.single[base+offset];
          if(uParity^assets.records[r+11]^Number(f<32))glyph=assets.inverse[glyph];
        }else {
          let offset=assets.scalePair[row+f];if(flags&4)offset=8-offset;
          const a=assets.records[r+7]+offset,b=assets.records[r+9],hi=Math.max(a,b),lo=Math.min(a,b);
          const centerSide=Number(f<32)^Number((flags&4)!==0);
          const polarity=uParity^assets.records[r+11]^centerSide^assets.records[r+10];
          glyph=assets.xor[hi*(hi+1)+2*lo+polarity];
        }
      }
      screen[assets.records[r]+256*assets.records[r+1]]=glyph;
    }
    return screen;
  }
  function reconstruct(screen) {
    const pixels=new Uint8Array(64000);
    for(let cell=0;cell<1000;cell++)for(let y=0;y<8;y++)for(let x=0;x<8;x++)pixels[(Math.floor(cell/40)*8+y)*320+(cell%40)*8+x]=(assets.font[screen[cell]*8+y]>>>(7-x))&1;
    return pixels;
  }
  // Quality measurement uses independent ray/sphere intersections and UV
  // functions. The native model never reads these pixels or stores frames.
  function reference(spin=0) {
    const g=manifest.geometry,camera=g.camera,focal=g.radius*Math.sqrt(camera*camera-1),tilt=g.tilt*Math.PI/180,sx=Math.sin(tilt),cx=Math.cos(tilt);
    const pixels=new Uint8Array(64000),inside=new Uint8Array(64000);let area=0;
    for(let y=0;y<200;y++)for(let x=0;x<320;x++) {
      const dx=(x+.5-160)/focal,dy=(100-y-.5)/focal,a=1+dx*dx+dy*dy,disc=camera*camera-a*(camera*camera-1);
      if(disc<0)continue;
      const t=(camera-Math.sqrt(disc))/a,px=t*dx,py=t*dy,pz=camera-t;
      const ox=px,oy=cx*py+sx*pz,oz=-sx*py+cx*pz;
      const u=(Math.atan2(ox,oz)+Math.PI)*g.checks/(2*Math.PI)+(spin&127)/64;
      const v=(Math.asin(Math.max(-1,Math.min(1,oy)))+Math.PI/2)*g.bands/Math.PI,i=y*320+x;
      pixels[i]=(Math.floor(u)^Math.floor(v))&1;inside[i]=1;area++;
    }
    return{pixels,inside,area};
  }
  function compare(spin=0,mode=0) {
    const screen=render(spin,mode),pixels=reconstruct(screen),ref=reference(spin);let errors=0,spill=0;
    for(let i=0;i<64000;i++)if(pixels[i]!==ref.pixels[i]){errors++;if(!ref.inside[i])spill++;}
    return {spin:spin&127,mode,errors,spill,area:ref.area,error:errors/ref.area};
  }
  function benchmark(phases=Array.from({length:16},(_,i)=>i*8)) {
    return[0,1].map(mode=>{
      const rows=phases.map(spin=>compare(spin,mode));
      return{mode,poses:rows.length,meanError:rows.reduce((sum,r)=>sum+r.error,0)/rows.length,maxError:Math.max(...rows.map(r=>r.error)),meanSpill:rows.reduce((sum,r)=>sum+r.spill,0)/rows.length,maxSpill:Math.max(...rows.map(r=>r.spill)),rows};
    });
  }
  return{manifest,assets,render,reconstruct,reference,compare,benchmark};
}

let defaultModel;
const getDefault=()=>defaultModel||(defaultModel=createModel());
module.exports={createModel,render:(spin,mode)=>getDefault().render(spin,mode),reference:spin=>getDefault().reference(spin),compare:(spin,mode)=>getDefault().compare(spin,mode),benchmark:phases=>getDefault().benchmark(phases)};

if(require.main===module) {
  const args=process.argv.slice(2),spin=Number(args[0]),mode=Number(args[1]);
  if(args.length!==3||!Number.isInteger(spin)||spin<0||spin>127||!Number.isInteger(mode)||mode<0||mode>1) {
    console.error('Usage: node native-model.cjs SPIN MODE OUTPUT\nSPIN must be 0..127. MODE must be 0 (analytic) or 1 (nine probes).');
    process.exitCode=1;
  }else {
    try {
      fs.writeFileSync(path.resolve(args[2]),getDefault().render(spin,mode));
    }catch(error) {
      console.error('native-model: '+error.message);process.exitCode=1;
    }
  }
}
