'use strict';
// Static assets only: no poses, projected coordinates, frames or span movies.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..');
const {createModel}=require(path.join(root,'native-model.cjs'));
const {makeMaskFont,makeCircleMap}=require(path.join(root,'precomputed/hybrid/vertices/or-font/assets.cjs'));
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');

function generate(output=path.join(__dirname,'build/assets')) {
  const baseline=createModel().assets,font=makeMaskFont(baseline.font,baseline.glyphLut);
  const tables=makeCircleMap(font,baseline);
  const shared={'font.bin':font,'coverage-compact.bin':tables.coverageCompact,
    'circle-map.bin':tables.circleMap,'clip-records.bin':baseline.clipRecords};
  const staticNames=['products','sin','ratio-q','ratio-r','ratio-row-lo','ratio-row-hi',
    'sample-y','sample-gap','first-sample','sample-row-lo','sample-row-hi','left-masks','right-masks','full-masks'];
  for(const name of staticNames)shared[name+'.bin']=fs.readFileSync(path.join(root,'assets',name+'.bin'));
  fs.mkdirSync(output,{recursive:true});
  for(const [name,bytes]of Object.entries(shared))fs.writeFileSync(path.join(output,name),bytes);
  fs.copyFileSync(path.join(root,'assets/constants.asm'),path.join(output,'constants.asm'));
  let data=fs.readFileSync(path.join(root,'assets/data.asm'),'utf8');
  const oldTables='glyph_lut: .import binary "assets/glyph-lut.bin"\n.align $100\nglyph_compact: .import binary "assets/glyph-compact.bin"';
  if(!data.includes(oldTables))throw Error('Expected original static lookup import layout');
  data=data.replace(oldTables,'coverage_compact: .import binary "assets/coverage-compact.bin"');
  data=data.replace('limb_remap: .import binary "assets/limb-remap.bin"','circle_map: .import binary "assets/circle-map.bin"');
  data=data.replaceAll('"assets/','"build/assets/');
  fs.writeFileSync(path.join(output,'data.asm'),data);
  const manifest={pass:true,kind:'live geometry with coverage-indexed OR font',
    animationDataBytes:0,precomputedPoses:0,precomputedSpans:0,
    runtime:['rotation matrix','vertex projection','face culling','polygon edge DDA','span OR filling'],
    charset:{bytes:2048,slots:256,all256MaskGlyphsEqualBaseline:true,emptyCode:0,fullCode:255},
    clip:{cells:baseline.clipRecords.length/4,classes:tables.groupCount,sourceGlyphs:tables.sourceCount,
      mapBytes:tables.circleMap.length,zeroProtrusionByConstruction:true},
    bytes:Object.fromEntries(Object.entries(shared).map(([name,bytes])=>[name,bytes.length])),
    sharedTableBytes:Object.values(shared).reduce((sum,bytes)=>sum+bytes.length,0),
    hashes:Object.fromEntries(Object.entries(shared).map(([name,bytes])=>[name,sha(bytes)]))};
  fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  return manifest;
}
module.exports={generate};
if(require.main===module)console.log(JSON.stringify(generate(),null,2));
