'use strict';
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const here=__dirname,root=path.resolve(here,'..');
require('./assets.cjs').generate();
// Keep the original runtime matrix, projection and face-culling implementation.
fs.copyFileSync(path.join(root,'geometry.asm'),path.join(here,'build/geometry.asm'));
process.stdout.write(execFileSync('rtk',['proxy','/Users/rogerjohansson/.local/bin/kickass','main.asm',
  '-odir',path.join(here,'build'),'-o',path.join(here,'build/player.prg'),
  '-debugdump','-debug','-symbolfile','-vicesymbols'],{cwd:here,encoding:'utf8'}));
