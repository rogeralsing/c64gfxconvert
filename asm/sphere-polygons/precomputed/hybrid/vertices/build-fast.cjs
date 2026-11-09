'use strict';
// Compose the unchanged PV64 driver/edge renderer with the isolated fast filler.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const baseline=path.join(__dirname,'player'),kernel=path.join(__dirname,'fast-fill/kernel.asm');
const output=path.join(__dirname,'fast-player/build'),source=path.join(output,'src');
fs.mkdirSync(source,{recursive:true});
let raster=fs.readFileSync(path.join(baseline,'raster.asm'),'utf8');
const start=raster.indexOf('raster_fill_span:'),stop=raster.indexOf('resolve_screen:');
assert(start>=0&&stop>start);
raster=raster.slice(0,start)+fs.readFileSync(kernel,'utf8')+'\n'+raster.slice(stop);
const assetDirectory=path.join(__dirname,'build/assets')+'/';
const main=fs.readFileSync(path.join(baseline,'main.asm'),'utf8').replaceAll('../build/assets/',assetDirectory);
fs.writeFileSync(path.join(source,'main.asm'),main);fs.writeFileSync(path.join(source,'raster.asm'),raster);
const command=process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass';
const built=spawnSync('rtk',['proxy',command,'main.asm','-odir',output,'-o',path.join(output,'player.prg'),'-debugdump','-debug','-symbolfile','-vicesymbols'],{cwd:source,stdio:'inherit'});
if(built.status!==0)process.exit(built.status||1);
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
fs.writeFileSync(path.join(output,'composition.json'),JSON.stringify({driverSha256:sha(path.join(baseline,'main.asm')),baselineRasterSha256:sha(path.join(baseline,'raster.asm')),fillKernelSha256:sha(kernel),prgSha256:sha(path.join(output,'player.prg')),change:'Only raster_fill_span..resolve_screen is replaced; the remainder is the baseline driver and exact edge/resolve renderer.'},null,2)+'\n');
