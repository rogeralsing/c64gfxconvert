'use strict';
const fs=require('node:fs');
const path=require('node:path');
const M=require('./meshes.cjs');
const G=require('./geometry.cjs');
const R=require('./raster.cjs');
const F=require('./math-font.cjs');
const OUT=path.join(__dirname,'assets');
const pop=F.popcount32;

function generate() {
  fs.mkdirSync(OUT,{recursive:true});
  const font=F.generateFont(256),tables=R.buildTables(font,{bits:8});
  if(tables.glyphLut[0]!==0||tables.glyphLut[255]!==15)throw Error('Empty/full coverage must select empty/full glyph');
  const values=G.coordinateValues(['checker','football']),pageOf=new Map(values.map((value,index)=>[value,index]));
  const bytes={
    'font.bin':Buffer.concat(font.glyphs.map(g=>Buffer.from(g.rows))),
    'products.bin':Buffer.from(G.productPages(values)),
    'sin.bin':Buffer.from(Uint8Array.from({length:256},(_,i)=>G.sine(i)&255)),
    'ratio-q.bin':Buffer.from(tables.ratioQ),'ratio-r.bin':Buffer.from(tables.ratioR),
    'ratio-row-lo.bin':Buffer.from(Uint8Array.from({length:64},(_,i)=>(i*64)&255)),
    'ratio-row-hi.bin':Buffer.from(Uint8Array.from({length:64},(_,i)=>(i*64)>>>8)),
    'sample-y.bin':Buffer.from(tables.sampleY),'sample-gap.bin':Buffer.from(tables.sampleGap),
    'first-sample.bin':Buffer.from(tables.firstSample),
    'sample-row-lo.bin':Buffer.from(tables.rowOffsetLo),'sample-row-hi.bin':Buffer.from(tables.rowOffsetHi),
    'left-masks.bin':Buffer.from(tables.leftMasks),'right-masks.bin':Buffer.from(tables.rightMasks),
    'full-masks.bin':Buffer.from(tables.fullMasks),'glyph-lut.bin':Buffer.from(tables.glyphLut)
  };

  // All geometry can move, but its quantized vertices stay inside this outer
  // bound. Only circle-edge and nearby exterior tiles need the safety pass.
  const outerRadius=101,sourceGlyphs=[...new Set(tables.glyphLut)].sort((a,b)=>a-b);
  const compact=Buffer.alloc(256,255);sourceGlyphs.forEach((code,index)=>{compact[code]=index;});
  const classes=[],classMap=new Map(),clipTiles=[];
  for(let cell=0;cell<1000;cell++) {
    const left=(cell%40)*8,top=Math.floor(cell/40)*8;
    let lo=0,hi=0,reachable=false;
    for(let y=0;y<8;y++)for(let x=0;x<8;x++) {
      const distance=(left+x-160)**2+(top+y-100)**2;
      if(distance<=outerRadius*outerRadius)reachable=true;
      if(distance>94*94)continue;
      const bit=y*8+x;if(bit<32)lo|=1<<bit;else hi|=1<<(bit-32);
    }
    lo>>>=0;hi>>>=0;
    if(!reachable||(lo===0xffffffff&&hi===0xffffffff))continue;
    const allowed=[];
    font.glyphs.forEach((glyph,index)=>{if(((glyph.lo&~lo)|(glyph.hi&~hi))===0)allowed.push(index);});
    const key=allowed.join(',');
    if(!classMap.has(key)){classMap.set(key,classes.length);classes.push(allowed);}
    clipTiles.push({cell,group:classMap.get(key)});
  }
  const remap=Buffer.alloc(classes.length*sourceGlyphs.length);
  classes.forEach((allowed,group)=>sourceGlyphs.forEach((source,index)=>{
    const original=font.glyphs[source];let best=0,error=65;
    for(const code of allowed) {
      const glyph=font.glyphs[code],e=pop(original.lo^glyph.lo)+pop(original.hi^glyph.hi);
      if(e<error){error=e;best=code;}
    }
    remap[group*sourceGlyphs.length+index]=best;
  }));
  const clipRecords=Buffer.alloc(clipTiles.length*4);
  clipTiles.forEach(({cell,group},index)=>{
    clipRecords.writeUInt16LE(cell,index*4);clipRecords.writeUInt16LE(group*sourceGlyphs.length,index*4+2);
  });
  bytes['glyph-compact.bin']=compact;bytes['limb-remap.bin']=remap;bytes['clip-records.bin']=clipRecords;
  for(const[name,data]of Object.entries(bytes))fs.writeFileSync(path.join(OUT,name),data);

  fs.writeFileSync(path.join(OUT,'constants.asm'),'.const CLIP_TILE_COUNT = '+clipTiles.length+';\n.const GLYPH_SOURCE_COUNT = '+sourceGlyphs.length+';\n.const FACE_RECORD_SIZE = 12;\n');
  const asm=[
    '.align $100','product_pages: .import binary "assets/products.bin"',
    '.align $100','sin_table: .import binary "assets/sin.bin"'
  ];
  for(const name of ['checker','football']) {
    const mesh=M.getMesh(name);asm.push(name+'_vertices:');
    for(const vertex of mesh.verticesQ6)asm.push('    .byte '+vertex.map(value=>`>(product_pages+${pageOf.get(value)}*$100)`).join(','));
    asm.push(name+'_faces:');
    mesh.faces.forEach(face=>{
      const entries=[face.indices.length,face.color,...face.normalQ6.map(value=>`>(product_pages+${pageOf.get(value)}*$100)`),...face.indices];
      while(entries.length<12)entries.push(0);asm.push('    .byte '+entries.join(','));
    });
  }
  const imports=[
    ['ratio_q','ratio-q.bin',true],['ratio_r','ratio-r.bin',true],
    ['ratio_row_lo','ratio-row-lo.bin'],['ratio_row_hi','ratio-row-hi.bin'],
    ['sample_y','sample-y.bin'],['sample_gap','sample-gap.bin'],['first_sample','first-sample.bin'],
    ['sample_row_lo','sample-row-lo.bin'],['sample_row_hi','sample-row-hi.bin'],
    ['left_masks','left-masks.bin'],['right_masks','right-masks.bin'],['full_masks','full-masks.bin'],
    ['glyph_lut','glyph-lut.bin',true],['glyph_compact','glyph-compact.bin',true],
    ['clip_records','clip-records.bin'],['limb_remap','limb-remap.bin',true]
  ];
  for(const[label,file,align]of imports){if(align)asm.push('.align $100');asm.push(label+': .import binary "assets/'+file+'"');}
  fs.writeFileSync(path.join(OUT,'data.asm'),asm.join('\n')+'\n');
  const manifest={version:1,coordinateUnit:'Q3 characters (1/8 character)',screenChars:[40,25],centerChars:[20,12.5],radiusChars:11.75,
    dotCenterOffset:0,projection:'live orthographic yaw, pitch and roll',fontSignature:font.signature,fontGlyphs:font.count,
    coverageBits:8,probePoints:[[1,1],[4,1],[6,1],[1,4],[6,4],[1,6],[4,6],[6,6]],
    models:Object.fromEntries(['checker','football'].map(name=>{const mesh=M.getMesh(name);return[name,{vertices:mesh.vertices.length,faces:mesh.faces.length,whiteFaces:mesh.faces.filter(f=>f.color).length,kinds:mesh.faces.reduce((counts,f)=>{counts[f.kind]=(counts[f.kind]||0)+1;return counts;},{})}];})),
    productCoordinateValues:values,productPages:values.length,edgeRatioLimit:63,
    clip:{outerRadiusQ3:outerRadius,tileCount:clipTiles.length,classes:classes.length,sourceGlyphs:sourceGlyphs.length,tableBytes:remap.length+compact.length},
    bytes:Object.fromEntries(Object.entries(bytes).map(([name,data])=>[name,data.length])),totalBinaryBytes:Object.values(bytes).reduce((sum,data)=>sum+data.length,0)};
  fs.writeFileSync(path.join(OUT,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  return manifest;
}
module.exports={generate};
if(require.main===module){const m=generate();console.log(JSON.stringify({models:m.models,productPages:m.productPages,clip:m.clip,totalBinaryBytes:m.totalBinaryBytes}));}
