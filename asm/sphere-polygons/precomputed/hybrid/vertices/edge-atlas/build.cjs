'use strict';
// Compose the fixed PV64 driver + exact edge atlas + unchanged selected filler.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
const parent=path.resolve(__dirname,'..'),baseline=path.join(parent,'player'),out=path.join(__dirname,'build'),src=path.join(out,'src');
const report=require('./generate.cjs').generate();fs.mkdirSync(src,{recursive:true});
const replace=(text,from,to)=>{assert(text.includes(from),from);return text.replace(from,to);};
let main=fs.readFileSync(path.join(baseline,'main.asm'),'utf8');
main=replace(main,'.label current_face_index = $4b','.label current_face_index = $4b\n.label atlas_record_ptr = $4c');
main=replace(main,'* = $3000 "PV64 character polygon player"','* = $2800 "PV64 exact edge-atlas player"');
main=replace(main,'player_code_end <= $4000','player_code_end <= $3000');
main=replace(main,'* = $4000 "Character raster lookup assets"','* = $3000 "Remaining character raster assets"\nraster_assets_start:');
for(const name of['ratio_q','ratio_r','ratio_row_lo','ratio_row_hi','sample_y','sample_gap']){
 main=main.replace(new RegExp('^'+name+': \\.import binary [^\\n]+\\n','m'),'');
}
const setup=`    ldx frame_index
    txa
    asl
    tax
    lda atlas_frame_offsets,x
    clc
    adc #<atlas_records
    sta atlas_record_ptr
    lda atlas_frame_offsets+1,x
    adc #>atlas_records
    sta atlas_record_ptr+1
`;
main=replace(main,'    cpx #5\n    bne !visible_byte-\n    rts','    cpx #5\n    bne !visible_byte-\n'+setup+'    rts');
main=replace(main,'animation_end:\n',`edge_atlas:\n    .import binary "${path.join(out,'edge-atlas.ea64')}"\nanimation_end:\n.label atlas_frame_offsets = edge_atlas+16\n.label atlas_pool = edge_atlas+${report.poolOffset}\n.label atlas_records = edge_atlas+${report.recordsOffset}\n`);
main=main.replaceAll('../build/assets/',path.join(parent,'build/assets')+'/');
let raster=fs.readFileSync(path.join(baseline,'raster.asm'),'utf8');
let a=raster.indexOf('raster_edge:\n'),b=raster.indexOf('raster_fill_span:\n');assert(a>=0&&b>a);
raster=raster.slice(0,a)+fs.readFileSync(path.join(__dirname,'edge.asm'),'utf8')+'\n'+raster.slice(b);
a=raster.indexOf('raster_fill_span:\n');b=raster.indexOf('resolve_screen:\n');
raster=raster.slice(0,a)+fs.readFileSync(path.join(parent,'fast-fill/kernel.asm'),'utf8')+'\n'+raster.slice(b);
raster=replace(raster,'    cmp raster_first\n    bne !has_samples+\n    rts','    cmp raster_first\n    beq !consume_edges+');
raster=replace(raster,'    lda #0\n    sta raster_edge_index\n!edge:','!consume_edges:\n    lda #0\n    sta raster_edge_index\n!edge:');
fs.writeFileSync(path.join(src,'main.asm'),main);fs.writeFileSync(path.join(src,'raster.asm'),raster);
const command=process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass';
const built=spawnSync('rtk',['proxy',command,'main.asm','-odir',out,'-o',path.join(out,'player.prg'),'-debugdump','-debug','-symbolfile','-vicesymbols'],{cwd:src,stdio:'inherit'});
if(built.status!==0)process.exit(built.status||1);
const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
fs.writeFileSync(path.join(out,'composition.json'),JSON.stringify({driverSha256:sha(path.join(baseline,'main.asm')),baselineRasterSha256:sha(path.join(baseline,'raster.asm')),edgeKernelSha256:sha(path.join(__dirname,'edge.asm')),fillKernelSha256:sha(path.join(parent,'fast-fill/kernel.asm')),prgSha256:sha(path.join(out,'player.prg')),removedUnusedTableBytes:8470,retainedRasterAndFontAssetBytes:12489,...report},null,2)+'\n');
