'use strict';
const fs = require('node:fs');
const path = require('node:path');
const math = require('./math-font.cjs');
const OUT = path.join(__dirname, 'assets');
const GEOMETRY = { width:320, height:200, radius:94, camera:3.2, tilt:22, checks:12, bands:6 };
const clamp = (n,a,b) => Math.max(a,Math.min(b,n));
const sector = (x,y,n) => Math.round((Math.atan2(y,x)+2*Math.PI)*n/(2*Math.PI))%n;

function mask(nx,ny,d) {
  let lo=0,hi=0;
  for(let y=0;y<8;y++)for(let x=0;x<8;x++)if(nx*(x-3.5)+ny*(y-3.5)>=d) {
    const bit=y*8+x;if(bit<32)lo|=1<<bit;else hi|=1<<(bit-32);
  }
  return {lo:lo>>>0,hi:hi>>>0};
}

function generate() {
  fs.mkdirSync(OUT,{recursive:true});
  const font=math.generateFont(256), nearest=(m)=>math.nearestGlyph(m.lo,m.hi,font).index;
  const fontBytes=Buffer.concat(font.glyphs.map(g=>Buffer.from(g.rows)));
  const single=Buffer.alloc(800), xor=Buffer.alloc(5256), halves=[];
  for(let a=0;a<32;a++)for(let d=0;d<25;d++)single[a*25+d]=nearest(mask(Math.cos(a*Math.PI/16),Math.sin(a*Math.PI/16),(d-12)*.5));
  for(let a=0;a<8;a++)for(let d=0;d<9;d++)halves.push(mask(Math.cos(a*Math.PI/8),Math.sin(a*Math.PI/8),(d-4)*1.25));
  for(let b=0;b<72;b++)for(let a=0;a<=b;a++) {
    const lo=(halves[a].lo^halves[b].lo)>>>0,hi=(halves[a].hi^halves[b].hi)>>>0,index=b*(b+1)+2*a;
    xor[index]=nearest({lo,hi});xor[index+1]=nearest({lo:(~lo)>>>0,hi:(~hi)>>>0});
  }
  const fontKeys=new Map(font.glyphs.map((g,i)=>[g.lo+':'+g.hi,i])),inverse=Buffer.alloc(256);
  for(let i=0;i<256;i++) {
    const g=font.glyphs[i],j=fontKeys.get(((~g.lo)>>>0)+':'+((~g.hi)>>>0));
    if(j===undefined)throw Error('Font lacks exact complement for glyph '+i);
    inverse[i]=j;
  }
  const probePositions=[1,4,6],signatures=font.glyphs.map(g=>{
    let bits=0;for(let y=0;y<3;y++)for(let x=0;x<3;x++)bits|=((g.rows[probePositions[y]]>>>(7-probePositions[x]))&1)<<(y*3+x);return bits;
  });
  const probeLut=Buffer.alloc(512);
  for(let bits=0;bits<512;bits++) {
    let best=Infinity,index=0;const coverage=math.popcount32(bits)/9;
    for(let i=0;i<256;i++) {
      const score=math.popcount32(bits^signatures[i])*100+Math.abs(font.glyphs[i].coverage-coverage);
      if(score<best){best=score;index=i;}
    }
    probeLut[bits]=index;
  }
  const camera=GEOMETRY.camera,radius=GEOMETRY.radius,focal=radius*Math.sqrt(camera*camera-1);
  const tilt=GEOMETRY.tilt*Math.PI/180,sx=Math.sin(tilt),cx=Math.cos(tilt);
  function point(x,y) {
    const u=(x-160)/focal,v=(100-y)/focal,a=1+u*u+v*v,disc=camera*camera-a*(camera*camera-1);
    if(disc<0)return null;
    const t=(camera-Math.sqrt(disc))/a;
    return {px:t*u,py:t*v,pz:camera-t};
  }
  function uv(p) {
    const x=p.px,y=cx*p.py+sx*p.pz,z=-sx*p.py+cx*p.pz;
    return {u:(Math.atan2(x,z)+Math.PI)*GEOMETRY.checks/(2*Math.PI),v:(Math.asin(clamp(y,-1,1))+Math.PI/2)*GEOMETRY.bands/Math.PI,x,y,z};
  }
  function gradients(p,q) {
    const t=camera-p.pz,den=1-camera*p.pz,tx=-t*t*p.px/(focal*den),ty=t*t*p.py/(focal*den),vx=p.px/t,vy=p.py/t;
    const dx=[t/focal+tx*vx,tx*vy,-tx],dy=[ty*vx,-t/focal+ty*vy,-ty];
    function derivative(d) {
      const X=d[0],Y=cx*d[1]+sx*d[2],Z=-sx*d[1]+cx*d[2];
      return {u:GEOMETRY.checks/(2*Math.PI)*(q.z*X-q.x*Z)/(q.x*q.x+q.z*q.z),v:GEOMETRY.bands/Math.PI*Y/Math.sqrt(Math.max(1e-12,1-q.y*q.y))};
    }
    const a=derivative(dx),b=derivative(dy);return {ux:a.u,uy:b.u,vx:a.v,vy:b.v};
  }
  const tiles=[];
  for(let ty=0;ty<25;ty++)for(let tx=0;tx<40;tx++) {
    const x=tx*8,y=ty*8,left=x+.5-160,right=x+7.5-160,top=y+.5-100,bottom=y+7.5-100;
    const nx=left>0?left:right<0?right:0,ny=top>0?top:bottom<0?bottom:0;
    if(nx*nx+ny*ny>radius*radius)continue;
    const limb=Math.max(Math.abs(left),Math.abs(right))**2+Math.max(Math.abs(top),Math.abs(bottom))**2>radius*radius;
    const p=point(x+4,y+4),q=p&&uv(p),g=p&&gradients(p,q);
    let validity=0;const probes=Buffer.alloc(9);
    for(let py=0;py<3;py++)for(let px=0;px<3;px++) {
      const i=py*3+px,sample=point(x+probePositions[px]+.5,y+probePositions[py]+.5);
      if(!sample)continue;
      validity|=1<<i;const v=uv(sample);probes[i]=(Math.floor(v.u*64)&127)^((Math.floor(v.v)&1)?64:0);
    }
    const span=g?Math.ceil(3.5*(Math.abs(g.ux)+Math.abs(g.uy))*64):255;
    const vSpan=g?3.5*(Math.abs(g.vx)+Math.abs(g.vy)):1;
    const fallback=limb||!p||!Number.isFinite(span)||span>=28||vSpan>=.45||q.x*q.x+q.z*q.z<.025;
    const uLength=g?Math.hypot(g.ux,g.uy):.02,vLength=g?Math.hypot(g.vx,g.vy):.02;
    const uAngle=g?sector(g.ux,g.uy,32):0,uHalfAngle=g?sector(g.ux,g.uy,16):0;
    const latParity=q?(Math.floor(q.v)&1):0;
    let latBoundary=false,latGlyph=latParity?15:0,latState=0,latCenter=1;
    if(q&&g&&vLength>0) {
      const f=q.v-Math.floor(q.v),d=(f<.5?-f:1-f)/vLength;
      latBoundary=Math.min(f,1-f)<=vSpan+.005;
      if(latBoundary) {
        const a=sector(g.vx,g.vy,32),offset=clamp(Math.round(d/.5)+12,0,24),center=Number(f<.5);
        latGlyph=single[a*25+offset];if(latParity^center)latGlyph=inverse[latGlyph];
        let half=sector(g.vx,g.vy,16),halfD=d;const halfReversed=half>=8;if(halfReversed){half-=8;halfD=-halfD;}
        const pairOffset=clamp(Math.round(halfD/1.25)+4,0,8);
        latState=half*9+pairOffset;latCenter=Number(f<.5)^Number(halfReversed);
      }
    }
    tiles.push({index:ty*40+tx,limb,fallback,span:clamp(span,0,255),phase:q?(Math.floor(q.u*64)&127):0,uLength,uAngle,uHalfAngle,latBoundary,latGlyph,latState,latCenter,latParity,probes,validity});
  }
  // Restrict limb results to glyphs whose every white pixel lies inside the
  // exact fixed sphere. Classes depend only on static geometry and font bits.
  // Reachable source glyphs come from all 512 probe signatures, not poses.
  const sourceGlyphs=Array.from(new Set(probeLut)).sort((a,b)=>a-b);
  const glyphCompact=Buffer.alloc(256,255);
  sourceGlyphs.forEach((glyph,index)=>{glyphCompact[glyph]=index;});
  const clipClasses=[],clipClassIndices=new Map();
  for(const tile of tiles)if(tile.limb) {
    const x=(tile.index%40)*8,y=Math.floor(tile.index/40)*8;let lo=0,hi=0;
    for(let py=0;py<8;py++)for(let px=0;px<8;px++)if((x+px+.5-160)**2+(y+py+.5-100)**2<=radius*radius) {
      const bit=py*8+px;if(bit<32)lo|=1<<bit;else hi|=1<<(bit-32);
    }
    lo>>>=0;hi>>>=0;
    const allowed=[];
    for(let glyph=0;glyph<font.count;glyph++)if(((font.glyphs[glyph].lo&~lo)|(font.glyphs[glyph].hi&~hi))===0)allowed.push(glyph);
    const key=allowed.join(',');
    if(!clipClassIndices.has(key)){clipClassIndices.set(key,clipClasses.length);clipClasses.push(allowed);}
    tile.clipClass=clipClassIndices.get(key);
  }
  const limbRemap=Buffer.alloc(clipClasses.length*sourceGlyphs.length);
  for(let group=0;group<clipClasses.length;group++)for(let source=0;source<sourceGlyphs.length;source++) {
    const original=font.glyphs[sourceGlyphs[source]];let best=65,selected=0;
    for(const glyph of clipClasses[group]) {
      const candidate=font.glyphs[glyph],error=math.popcount32(original.lo^candidate.lo)+math.popcount32(original.hi^candidate.hi);
      if(error<best){best=error;selected=glyph;}
    }
    limbRemap[group*sourceGlyphs.length+source]=selected;
  }
  // Geometric-mean clusters preserve relative gradient precision without any
  // animation poses or reference images participating in asset selection.
  const magnitudes=tiles.filter(t=>!t.fallback).map(t=>Math.log(t.uLength));
  const low=Math.min(...magnitudes),high=Math.max(...magnitudes);
  let logs=Array.from({length:32},(_,i)=>low+(high-low)*i/31);
  for(let pass=0;pass<12;pass++) {
    const sums=new Float64Array(32),counts=new Uint16Array(32);
    for(const value of magnitudes){let best=0;for(let i=1;i<32;i++)if(Math.abs(value-logs[i])<Math.abs(value-logs[best]))best=i;sums[best]+=value;counts[best]++;}
    logs=logs.map((v,i)=>counts[i]?sums[i]/counts[i]:v).sort((a,b)=>a-b);
  }
  const scales=logs.map(Math.exp),scaleSingle=Buffer.alloc(2048),scalePair=Buffer.alloc(2048);
  for(let row=0;row<32;row++)for(let f=0;f<64;f++) {
    const d=(f<32?-f:64-f)/(64*scales[row]);
    scaleSingle[row*64+f]=clamp(Math.round(d/.5)+12,0,24);
    scalePair[row*64+f]=clamp(Math.round(d/1.25)+4,0,8);
  }
  const records=Buffer.alloc(tiles.length*13),probes=Buffer.alloc(tiles.length*9),valid=Buffer.alloc(tiles.length*2);
  for(let i=0;i<tiles.length;i++) {
    const t=tiles[i];let row=0;for(let j=1;j<32;j++)if(Math.abs(Math.log(t.uLength)-logs[j])<Math.abs(Math.log(t.uLength)-logs[row]))row=j;
    const tableBase=t.limb?t.clipClass*sourceGlyphs.length:t.uAngle*25;
    records.set([t.index&255,t.index>>>8,Number(t.fallback)|(Number(t.latBoundary)<<1)|(Number(t.uHalfAngle>=8)<<2)|(Number(t.limb)<<3),t.phase,row,tableBase&255,tableBase>>>8,(t.uHalfAngle&7)*9,t.latGlyph,t.latState,t.latCenter,t.latParity,t.span],i*13);
    probes.set(t.probes,i*9);valid.writeUInt16LE(t.validity,i*2);
  }
  function offsets(count,fn){const lo=Buffer.alloc(count),hi=Buffer.alloc(count);for(let i=0;i<count;i++){const value=fn(i);lo[i]=value&255;hi[i]=value>>>8;}return{lo,hi};}
  const scaleOffsets=offsets(32,i=>i*64),pairOffsets=offsets(72,i=>i*(i+1));
  const files={'font.bin':fontBytes,'records.bin':records,'probes.bin':probes,'valid.bin':valid,'single.bin':single,'xor.bin':xor,'inverse.bin':inverse,'probe-lut.bin':probeLut,'glyph-compact.bin':glyphCompact,'limb-remap.bin':limbRemap,'scale-single.bin':scaleSingle,'scale-pair.bin':scalePair,'scale-lo.bin':scaleOffsets.lo,'scale-hi.bin':scaleOffsets.hi,'pair-lo.bin':pairOffsets.lo,'pair-hi.bin':pairOffsets.hi};
  for(const [name,data]of Object.entries(files))fs.writeFileSync(path.join(OUT,name),data);
  fs.writeFileSync(path.join(OUT,'constants.asm'),`.const SPHERE_TILE_COUNT = ${tiles.length};\n.const RECORD_SIZE = 13;\n.const SPHERE_PHASE_STEP = 4;\n.const LIMB_SOURCE_GLYPH_COUNT = ${sourceGlyphs.length};\n.const LIMB_CLIP_CLASS_COUNT = ${clipClasses.length};\n`);
  const manifest={version:1,geometry:GEOMETRY,recordSize:13,tileCount:tiles.length,fallbackTiles:tiles.filter(t=>t.fallback).length,limbTiles:tiles.filter(t=>t.limb).length,latitudeBoundaryTiles:tiles.filter(t=>t.latBoundary).length,fontGlyphs:256,fontSignature:font.signature,exactComplementMap:true,probePixelIndices:probePositions,clipClasses:clipClasses.length,sourceGlyphs:sourceGlyphs.length,limbRemapSelection:'Exact circle-safe candidate sets; source glyph IDs ascending from all probe signatures; minimum full-font 64-bit Hamming distance, lowest glyph ID on ties; no poses or reference images',scaleRepresentatives:scales,scaleUnits:'checker units per display pixel',scaleSelection:'32 log-gradient clusters from analytic-eligible static geometry; no poses or image fitting',bytes:Object.fromEntries(Object.entries(files).map(([name,data])=>[name,data.length])),totalAssetBytes:Object.values(files).reduce((sum,data)=>sum+data.length,0)};
  fs.writeFileSync(path.join(OUT,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  return manifest;
}

module.exports={generate,GEOMETRY};
if(require.main===module) {
  const manifest=generate(),model=require('./native-model.cjs').createModel();
  manifest.quality=model.benchmark(Array.from({length:16},(_,i)=>i*8));
  fs.writeFileSync(path.join(OUT,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  console.log(JSON.stringify({tileCount:manifest.tileCount,fallbackTiles:manifest.fallbackTiles,totalAssetBytes:manifest.totalAssetBytes,quality:manifest.quality.map(({mode,poses,meanError,maxError})=>({mode,poses,meanError,maxError}))},null,2));
}
