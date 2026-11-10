'use strict';
// The stored SA64 span film and fill kernel are shared with the baseline.
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const here=__dirname,root=path.resolve(here,'../../../..'),output=path.join(here,'build/assets');
if(!fs.existsSync(path.join(here,'../build/assets/reference.bin')))require('../generate.cjs').generate();
if(!fs.existsSync(path.join(here,'../span-atlas/build/assets/spans.sa64')))require('../span-atlas/generate.cjs').generate();
require('./assets.cjs').generate(output);
const original=fs.readFileSync(path.join(root,'raster.asm'),'utf8');
const prefix=original.slice(0,original.indexOf('render_polygons:'));
const render=fs.readFileSync(path.join(here,'render.asm'),'utf8');
const originalKernel=fs.readFileSync(path.join(here,'../fast-fill/kernel.asm'),'utf8');
const needle='adc #>coverage';
if(originalKernel.split(needle).length!==2)throw Error('Expected one coverage base in shared fast-fill kernel');
const kernel=originalKernel.replace(needle,'adc back_screen_hi');
const resolve=fs.readFileSync(path.join(here,'resolve.asm'),'utf8');
fs.writeFileSync(path.join(here,'build/abi.asm'),prefix);
fs.writeFileSync(path.join(here,'build/raster.asm'),render+'\n'+kernel+'\n'+resolve);
process.stdout.write(execFileSync('rtk',['proxy','/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',path.join(here,'build'),'-o',path.join(here,'build/player.prg'),'-debugdump','-debug','-symbolfile','-vicesymbols'],{cwd:here,encoding:'utf8'}));
