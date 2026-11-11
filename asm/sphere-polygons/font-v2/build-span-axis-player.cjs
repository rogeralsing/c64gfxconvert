'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const here=__dirname,sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const HOST=String.raw`import hashlib,json,pathlib,sys
sys.path.insert(0,'/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU
p=pathlib.Path(sys.argv[1]);l=json.loads((p/'labels.json').read_text());b=json.loads((p/'build.json').read_text())
prg=(p/'player.prg').read_bytes();ref=(p/'reference.frames').read_bytes();font=(p/'font.bin').read_bytes()
movie=(p/'rows.bin').read_bytes();h=(p/'h-lut.bin').read_bytes();v=(p/'v-lut.bin').read_bytes()
m=[0xa5]*65536;load=int.from_bytes(prg[:2],'little');m[load:load+len(prg)-2]=prg[2:]
cpu=MPU(memory=m);irqcycles=0;irqcalls=0
def put16(name,n):m[l[name]]=n&255;m[l[name]+1]=(n>>8)&255
def run(label,inject=False):
 global irqcycles,irqcalls
 start=cpu.processorCycles;irq_before=irqcycles
 for steps in range(2000000):
  if cpu.pc==l[label]:return cpu.processorCycles-start-(irqcycles-irq_before)
  if inject and steps%137==136 and not(cpu.p&4):
   state=(cpu.pc,cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p);begin=cpu.processorCycles;cpu.irq()
   for _ in range(1000):
    if cpu.pc==state[0]:break
    cpu.step()
   else:raise AssertionError('IRQ return')
   assert(cpu.a,cpu.x,cpu.y,cpu.sp)==state[1:5]
   assert(cpu.p&0xcf)==(state[5]&0xcf)
   irqcycles+=cpu.processorCycles-begin;irqcalls+=1
  cpu.step()
 raise AssertionError(('limit',label,hex(cpu.pc)))
def pose(t):return 0 if t<=0 else 1+(t-1)%96
def expected(pose,mode):
 out=bytearray(1000)
 if mode==0:
  for y in range(12):
   for x in range(40):
    c=ref[pose*1000+y*40+x];out[y*40+x]=c;out[(23-y)*40+x]=v[c]
 else:
  for y in range(25):
   for x in range(20):
    c=ref[pose*1000+y*40+x];out[y*40+x]=c;out[y*40+39-x]=h[c]
 return bytes(out)
for address in(0x4800,0x4c00):m[address:address+1024]=bytes(1024)
m[l['film_frame']]=0;put16('film_serial',0);put16('field_counter',0)
m[l['mode']]=0;m[l['next_mode']]=0;put16('mode_fields_left',501);m[l['mode_due']]=0
m[l['front_screen_hi']]=0x48;m[l['back_screen_hi']]=0x4c;m[l['frame_wait_fields']]=2
m[0xfffe]=l['field_irq']&255;m[0xffff]=l['field_irq']>>8
assert expected(0,0)==bytes(1000) and expected(0,1)==bytes(1000)
front,back=0x4800,0x4c00;records=[];oldmode=0
sequence=[(serial,((serial-1)//250)%2)for serial in range(1,502)]
sequence += [(960+frame,mode)for mode in range(2)for frame in range(1,97)]
for i,(serial,mode) in enumerate(sequence):
 if i>=501:
  oldmode=1-mode;m[l['mode']]=oldmode
  for a in(0x4800,0x4c00):m[a:a+1024]=bytes([0xa5])*1000+bytes(24)
 m[l['film_frame']]=pose(serial-1);put16('film_serial',serial-1)
 put16('mode_fields_left',0 if mode!=oldmode else 501);m[l['mode_due']]=int(mode!=oldmode)
 before=bytes(m[front:front+1024]);cpu.pc=l['prepare_start']
 setup=run('clear_start');clear=run('render_start',inject=True);render=run('render_end',inject=True)
 assert m[l['next_mode']]==mode and m[l['next_film_frame']]==pose(serial)
 assert bytes(m[back:back+1000])==expected(pose(serial),mode),('image',i,serial,mode)
 assert bytes(m[back+1000:back+1024])==bytes(24)
 assert bytes(m[front:front+1024])==before
 assert bytes(m[0x4000:0x4800])==font and bytes(m[0x5000:0x5000+len(movie)])==movie
 assert bytes(m[l['h_lut']:l['h_lut']+256])==h and bytes(m[l['v_lut']:l['v_lut']+256])==v
 records.append(dict(serial=serial,pose=pose(serial),mode=mode,transition=mode!=oldmode,
  setupCpuCycles=setup,clearCpuCycles=clear,renderCpuCycles=render,totalCpuCycles=setup+clear+render))
 cpu.pc=l['commit_start'];run('presented');front,back=back,front;oldmode=mode
 assert m[l['mode']]==mode and m[l['film_frame']]==pose(serial)
 assert m[l['front_screen_hi']]==front>>8 and m[0xd018]==(0x20 if front==0x4800 else 0x30)
 assert m[0xd011]==(0x9f if mode==0 else 0x9b)
result=dict(passed=True,imagesVerified=len(records)+1,nominalTwoPhaseImagesVerified=500,
 all97SourcePosesBothModesVerified=True,repeatTransitionVerified=True,injectedIrqs=irqcalls,
 irqRegistersAndStatusPreserved=True,frontUnchangedDuringPreparation=True,sourceFontAndLutsUnchanged=True,
 maximumPreparationCpuCycles=max(r['totalCpuCycles']for r in records),
 programSha256=hashlib.sha256(prg).hexdigest(),
 scope='Assembled6502 directraw spans, V-only andH-only, sourcehalves untouched, per-modeD011 commit; noVIC/FPS claim.',records=records)
(p/'host-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items()if k!='records'},indent=2))
`;
function main(argv=process.argv.slice(2)){
 const opt=(n,d)=>{const i=argv.indexOf('--'+n);return i<0?d:argv[i+1];};
 const input=path.resolve(opt('input',path.join(here,'three-scene/results/flagship-star-row-film/original-pal-97')));
 const referencePath=path.resolve(opt('reference',path.join(here,'three-scene/results/flagship-star-ten-buffer/reference.frames')));
 const output=path.resolve(opt('output',path.join(here,'build/three-scene-flagship-star-span-axis')));
 const lutSource=path.join(here,'three-scene/results/flagship-star-span-mirror-texture');
 const movie=fs.readFileSync(path.join(input,'rows.bin')),index=fs.readFileSync(path.join(input,'frame-offsets16.bin'));
 const font=fs.readFileSync(path.join(input,'font.bin')),reference=fs.readFileSync(referencePath);
 const h=fs.readFileSync(path.join(lutSource,'h-lut.bin')),v=fs.readFileSync(path.join(lutSource,'v-lut.bin'));
 const study=JSON.parse(fs.readFileSync(path.join(input,'study.json')));
 assert.equal(movie.length,22882);assert.equal(index.length,194);assert.equal(h.length+v.length,512);
 assert.equal(sha(movie),study.hashes.rows);assert.equal(sha(index),study.hashes.frameOffsets16);
 assert.equal(sha(font),'1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1');
 assert.equal(sha(reference),'5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c');
 assert.equal(sha(h),'8758e99a0a12a3295a674c3a806a3ca9160ee11b837493e9ca65d8f4d3f09ba8');
 assert.equal(sha(v),'7bd4a003ad2078ef6dcaa1fed00d230f17e8089575c4f356b5b91bc36f278234');
 fs.mkdirSync(output,{recursive:true});
 for(const[n,b]of Object.entries({'rows.bin':movie,'movie.bin':movie,'frame-offsets16.bin':index,'font.bin':font,'reference.frames':reference,'h-lut.bin':h,'v-lut.bin':v}))fs.writeFileSync(path.join(output,n),b);
 fs.writeFileSync(path.join(output,'host-proof.py'),HOST);
 fs.writeFileSync(path.join(output,'main.asm'),['.var movieData=LoadBinary("rows.bin")','.var indexData=LoadBinary("frame-offsets16.bin")',
  '.var fontData=LoadBinary("font.bin")','.var hData=LoadBinary("h-lut.bin")','.var vData=LoadBinary("v-lut.bin")',
  `.import source "${path.relative(output,path.join(here,'span-axis-player.asm')).split(path.sep).join('/')}"`,''].join('\n'));
 const c=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',output,'-o',path.join(output,'player.prg'),'-symbolfile','-vicesymbols'],{cwd:output,stdio:'inherit'});
 assert.equal(c.status,0,'Assembler failed');const program=fs.readFileSync(path.join(output,'player.prg'));
 const labels=Object.fromEntries([...fs.readFileSync(path.join(output,'main.sym'),'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-f]+)/gi)].map(m=>[m[1],parseInt(m[2],16)]));
 fs.writeFileSync(path.join(output,'labels.json'),JSON.stringify(labels,null,2)+'\n');
 const absoluteIndex=Buffer.concat([Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))&255)),Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))>>8))]);
 fs.writeFileSync(path.join(output,'frame-pointers-absolute.bin'),absoluteIndex);
 const result={name:'span-axis',storedFrames:97,nominalFps:25,nativeFps:null,minimumFieldsPerImage:2,
  modes:['vertical','horizontal'],modeDurationFields:501,modeLookaheadFields:5,
  nominalModeSeconds:501*19656/985248,nominalSequenceSeconds:1002*19656/985248,
  geometry:{vertical:{mode:0,sourceRows:12,sourceColumns:40,mirrorRow:'23-y',yScroll:7,displayControl:0x1f,
    visibleTop:4,visibleBottom:195,blankScreenRow:24,blackTopMarginPixels:4,blackBottomMarginPixels:4},
   horizontal:{mode:1,sourceRows:25,sourceColumns:20,mirrorColumn:'39-x',yScroll:3,displayControl:0x1b,
    visibleTop:0,visibleBottom:199,blankScreenRow:null,blackTopMarginPixels:0,blackBottomMarginPixels:0}},
  glyphContract:'Vmode:top12rows×40original, bottom23-y usesV[c] only. Hmode:left20cols×25original,right39-x usesH[c]only. ReuseacceptedcorrectedBayeridentityLUTswithoutpolicychange.',
  timingContract:'Globalfilm_serial continuesacrossmodes; sourceposes1..96repeat. Prepareotheraxiswhen501-fieldtimer<=5, publishatdeadlineinlowerborder; D0119f/9b changeswithmode. ActualFPS/deadlinesnativemeasured.',
  payloadBytes:22882,pointerBytes:194,totalFilmBytes:23076,fontBytes:2048,lutBytes:512,workScreenBytes:2048,historyImageBytes:0,rowCacheBytes:0,
  codeRegionBytes:labels.player_code_end-0x1000,zeroPageBytes:10,basicBytes:12,
  addresses:{code:0x1000,codeEnd:labels.player_code_end,font:0x4000,screens:[0x4800,0x4c00],front:0x4800,hidden:0x4c00,source:0x5000,sourceEnd:0x5000+movie.length},
  sourceRegions:[{file:'rows.bin',start:0x5000,end:0x5000+movie.length,sha256:sha(movie)},
   {file:'frame-pointers-absolute.bin',start:labels.frame_pointer_low,end:labels.frame_pointer_low+194,sha256:sha(absoluteIndex),layout:'97lowbytesfollowedby97highbytes'},
   {file:'h-lut.bin',start:labels.h_lut,end:labels.h_lut+256,sha256:sha(h)},
   {file:'v-lut.bin',start:labels.v_lut,end:labels.v_lut+256,sha256:sha(v)}],
  lutSource,hashes:{program:sha(program),movie:sha(movie),frameOffsets16:sha(index),font:sha(font),reference:sha(reference),hLut:sha(h),vLut:sha(v)},
  memoryScope:'Twooutputscreens,nohistory/cache/previouscopy. Code regionincludes194Bframepointersand512BreusedLUTs; donotdoublecount. ColorRAMseparate1024cells.'};
 result.mainRamBytes=result.codeRegionBytes+movie.length+2048+2048+10+12;result.colorRamCells=1024;
 const load=program.readUInt16LE(0);for(const r of result.sourceRegions)assert(program.subarray(2+r.start-load,2+r.end-load).equals(fs.readFileSync(path.join(output,r.file))),r.file);
 fs.writeFileSync(path.join(output,'build.json'),JSON.stringify(result,null,2)+'\n');
 const proof=spawnSync('rtk',['proxy','python3',path.join(output,'host-proof.py'),output],{stdio:'inherit'});assert.equal(proof.status,0,'6502hostproof failed');
 console.log(JSON.stringify({output,sha256:result.hashes.program,mainRamBytes:result.mainRamBytes},null,2));return result;
}
module.exports={main};if(require.main===module)main();
