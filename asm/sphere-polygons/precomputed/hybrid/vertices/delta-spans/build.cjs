'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../../../..'),source=path.join(__dirname,'../span-atlas/build/assets'),out=path.join(__dirname,'build'),assets=path.join(out,'assets');
fs.mkdirSync(assets,{recursive:true});const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const movie=fs.readFileSync(path.join(source,'spans.sa64'));
assert.equal(sha(movie),'127c8f6e14d44c76de7acc3ebf22a57f76e8067df3cc30bc98a1a29d5227c162');
const atlas=require('../span-atlas/generate.cjs'),model=require(path.join(root,'native-model.cjs')).createModel(),decoded=atlas.deserialize(movie);
for(const frame of decoded.frames){const occupied=new Uint8Array(1000);for(const face of frame){const masks=atlas.coverageFor([face],model.tables);for(let cell=0;cell<1000;cell++){assert.equal(occupied[cell]&masks[cell],0,'XOR certificate requires disjoint endpoint probes');occupied[cell]|=masks[cell];}}}
fs.writeFileSync(path.join(assets,'spans.sa64'),movie);
const names=['font','sample-row-lo','sample-row-hi','left-masks','right-masks','full-masks','glyph-lut','glyph-compact','limb-remap'];
for(const name of names)fs.copyFileSync(path.join(root,'assets',name+'.bin'),path.join(assets,name+'.bin'));
const clips=fs.readFileSync(path.join(root,'assets/clip-records.bin')),lo=Buffer.alloc(1024,255),hi=Buffer.alloc(1024,255);
for(let p=0;p<clips.length;p+=4){const cell=clips.readUInt16LE(p),base=clips.readUInt16LE(p+2);lo[cell]=base&255;hi[cell]=base>>>8;}
fs.writeFileSync(path.join(assets,'clip-lo.bin'),lo);fs.writeFileSync(path.join(assets,'clip-hi.bin'),hi);
const result=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',out,'-o',path.join(out,'player.prg'),'-debugdump','-debug','-symbolfile','-vicesymbols'],{cwd:__dirname,stdio:'inherit'});
if(result.status!==0)process.exit(result.status||1);
fs.writeFileSync(path.join(out,'certificate.json'),JSON.stringify({pass:true,frames:64,probesChecked:512000,maxEndpointOverlap:1,xorValidOnlyForCertifiedSource:true,movieSha256:sha(movie),tableBytes:names.reduce((n,name)=>n+fs.statSync(path.join(assets,name+'.bin')).size,0)+2048,prgSha256:sha(fs.readFileSync(path.join(out,'player.prg')))},null,2)+'\n');
