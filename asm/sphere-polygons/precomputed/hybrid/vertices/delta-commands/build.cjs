'use strict';
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const here=__dirname,root=path.resolve(here,'../../../..'),output=path.join(here,'build/assets');fs.mkdirSync(output,{recursive:true});
process.stdout.write(execFileSync('rtk',['proxy','node',path.join(here,'study.cjs')],{encoding:'utf8'}));
const original=fs.readFileSync(path.join(root,'raster.asm'),'utf8');fs.writeFileSync(path.join(here,'build/abi.asm'),original.slice(0,original.indexOf('render_polygons:')));
const fill=fs.readFileSync(path.join(here,'../fast-fill/kernel.asm'),'utf8');fs.writeFileSync(path.join(here,'build/fill.asm'),fill+'\nraster_mask_bases:\n.for(var row=0;row<25;row++){.byte 0,8,16}\n');
for(const name of['font','glyph-lut','glyph-compact','limb-remap','sample-row-lo','sample-row-hi','left-masks','right-masks'])fs.copyFileSync(path.join(root,'assets',name+'.bin'),path.join(output,name+'.bin'));
const records=fs.readFileSync(path.join(root,'assets/clip-records.bin')),classes=Buffer.alloc(1024);
for(let p=0;p<records.length;p+=4){const cell=records.readUInt16LE(p),base=records.readUInt16LE(p+2);if(base%148)throw Error('Invalid class base');classes[cell]=1+base/148;}
fs.writeFileSync(path.join(output,'clip-cell-classes.bin'),classes);
process.stdout.write(execFileSync('rtk',['proxy','/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',path.join(here,'build'),'-o',path.join(here,'build/player.prg'),'-debugdump','-debug','-symbolfile','-vicesymbols'],{cwd:here,encoding:'utf8'}));
