'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const here=__dirname;
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const HOST=String.raw`import json,math,pathlib,sys,hashlib,statistics
sys.path.insert(0,'/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU
p=pathlib.Path(sys.argv[1]); probe=len(sys.argv)>2
b=json.loads((p/'build.json').read_text()); l=json.loads((p/'labels.json').read_text())
prg=(p/'player.prg').read_bytes(); ref=(p/'reference.frames').read_bytes()
font=(p/'font.bin').read_bytes(); movie=(p/'movie.bin').read_bytes()
m=[0xa5]*65536; load=int.from_bytes(prg[:2],'little');m[load:load+len(prg)-2]=prg[2:]
cpu=MPU(memory=m); irqcycles=0;irqcalls=0
def put16(name,value):m[l[name]]=value&255;m[l[name]+1]=(value>>8)&255
def run(label,inject=False):
 global irqcycles,irqcalls
 start=cpu.processorCycles;before=irqcycles
 for steps in range(3000000):
  if cpu.pc==l[label]:return cpu.processorCycles-start-(irqcycles-before)
  if inject and steps%211==210 and not(cpu.p&4):
   state=(cpu.pc,cpu.a,cpu.x,cpu.y,cpu.sp,cpu.p);s=cpu.processorCycles
   cpu.irq()
   for _ in range(1000):
    if cpu.pc==state[0]:break
    cpu.step()
   else:raise AssertionError('IRQ return')
   assert(cpu.a,cpu.x,cpu.y,cpu.sp)==state[1:5]
   assert(cpu.p&0xcf)==(state[5]&0xcf)
   irqcycles+=cpu.processorCycles-s;irqcalls+=1
  cpu.step()
 raise AssertionError(('limit',label,hex(cpu.pc)))
def call(label):
 cpu.pc=l[label];cpu.sp=0xfd;m[0x1fe]=0xff;m[0x1ff]=0xfe
 endpoint=l.get('_return');l['_return']=0xff00;run('_return')
def pose(serial):return 0 if serial<=0 else 1+(serial-1)%96
def expect(serial,mode):
 out=bytearray(1000);phase=serial%96
 for y in range(25):
  age=math.floor(4.5+4.5*math.sin(2*math.pi*(y/24+phase/96))+.5) if mode==1 else 0
  a=pose(max(0,serial-age));bb=pose(max(0,serial-48))
  for x in range(40):
   f=bb if mode==2 and ((x//4)^(y//4))&1 else a
   out[y*40+x]=ref[f*1000+y*40+x]
 return bytes(out)
for address in(0x4800,0x4c00):m[address:address+1024]=bytes(1024)
m[l['mode']]=0;m[l['film_frame']]=0;m[l['phase']]=0
m[l['front_screen_hi']]=0x48;m[l['back_screen_hi']]=0x4c
put16('film_serial',0);put16('field_counter',0);put16('mode_fields_left',501)
m[l['mode_due']]=0;m[l['frame_wait_fields']]=2
m[0xfffe]=l['field_irq']&255;m[0xffff]=l['field_irq']>>8

rawindex=(p/'frame-offsets16.bin').read_bytes()
records=[];front=0x4800;back=0x4c00;oldmode=0
sequence=[(serial,((serial-1)//250)%3) for serial in range(1,752)]
if probe:sequence +=[(96*10+frame,mode) for mode in range(3) for frame in range(1,97)]
for i,(serial,mode) in enumerate(sequence):
 if i>=751:
  oldmode=(mode+2)%3;m[l['mode']]=oldmode
  for addr in(0x4800,0x4c00):m[addr:addr+1024]=bytes([0xa5])*1000+bytes(24)
 m[l['next_mode']]=mode;m[l['next_film_frame']]=pose(serial)
 m[l['next_phase']]=serial%96;put16('next_serial',serial)
 before=bytes(m[front:front+1024]);cpu.pc=l['clear_start']
 clear=run('clear_end',inject=(i<4 or mode!=oldmode))
 cache=run('render_start',inject=(i<4 or mode!=oldmode))
 render=run('render_end',inject=(i<4 or mode!=oldmode))
 actual=bytes(m[back:back+1000]);expected=expect(serial,mode)
 count=10 if mode==1 else 2 if mode==2 else 1
 assert m[l['cache_table_count']]==count
 for slot in range(count):
  age=48 if mode==2 and slot else slot
  sourcepose=pose(max(0,serial-age))
  assert m[l['cache_frame_ids']+slot]==sourcepose
  offset=int.from_bytes(rawindex[sourcepose*2:sourcepose*2+2],'little')
  for row in range(25):
   addr=l['row_cache']+slot*50+row*2
   pointer=m[addr]+256*m[addr+1]
   assert pointer==0x5000+offset,('cache',i,slot,row,pointer,offset)
   offset+=2+movie[offset+1]
 assert actual==expected,('frame',i,serial,mode,[(n,a,e) for n,(a,e) in enumerate(zip(actual,expected)) if a!=e][:8])
 assert bytes(m[front:front+1024])==before,('front',i)
 assert bytes(m[back+1000:back+1024])==bytes(24)
 assert bytes(m[0x4000:0x4800])==font
 assert bytes(m[0x5000:0x5000+len(movie)])==movie
 records.append(dict(serial=serial,mode=mode,transition=mode!=oldmode,clearCpuCycles=clear,cacheCpuCycles=cache,renderCpuCycles=render,totalCpuCycles=clear+cache+render))
 # Exercise the real lower-border commit; field timing itself is native proof.
 cpu.pc=l['commit_start'];run('presented');front,back=back,front;oldmode=mode
 assert m[l['mode']]==mode and m[l['film_frame']]==pose(serial)
 assert m[l['front_screen_hi']]==front>>8 and m[0xd018]==(0x20 if front==0x4800 else 0x30)
result=dict(passed=True,framesVerified=len(records),nominalThreePhaseFramesVerified=750,repeatTransitionVerified=True,
 injectedIrqs=irqcalls,irqRegistersAndStatusPreserved=True,sourceAndFontUnchanged=True,
 frontUnchangedDuringPreparation=True,programSha256=hashlib.sha256(prg).hexdigest(),
 maximumPreparationCpuCycles=max(r['totalCpuCycles'] for r in records),
 maximumTransitionCpuCycles=max(r['totalCpuCycles'] for r in records if r['transition']),
 records=records)
(p/('preparation-proof.json' if probe else 'host-proof.json')).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
`;
function main(argv=process.argv.slice(2)){
 const opt=(n,d)=>{const i=argv.indexOf('--'+n);return i<0?d:argv[i+1];};
 const input=path.resolve(opt('input',path.join(here,'three-scene/results/flagship-star-row-film/original-pal-97')));
 const referencePath=path.resolve(opt('reference',path.join(here,'three-scene/results/flagship-star-ten-buffer/reference.frames')));
 const output=path.resolve(opt('output',path.join(here,'build/three-scene-flagship-star-span-effects')));
 const movie=fs.readFileSync(path.join(input,'rows.bin'));
 const index=fs.readFileSync(path.join(input,'frame-offsets16.bin'));
 const font=fs.readFileSync(path.join(input,'font.bin'));const reference=fs.readFileSync(referencePath);
 const study=JSON.parse(fs.readFileSync(path.join(input,'study.json')));
 assert.equal(movie.length,22882);assert.equal(index.length,194);
 assert.equal(sha(movie),study.hashes.rows);assert.equal(sha(index),study.hashes.frameOffsets16);
 assert.equal(sha(font),'1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1');
 assert.equal(sha(reference),'5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c');
 const wave=Buffer.from(Array.from({length:2400},(_,i)=>Math.round(4.5+4.5*Math.sin(2*Math.PI*(Math.floor(i/96)/24+(i%96)/96)))));
 fs.mkdirSync(output,{recursive:true});
 for(const[n,b]of Object.entries({'movie.bin':movie,'rows.bin':movie,'frame-offsets16.bin':index,'font.bin':font,'reference.frames':reference,'wave-ages.bin':wave}))fs.writeFileSync(path.join(output,n),b);
 fs.writeFileSync(path.join(output,'host-proof.py'),HOST);
 fs.writeFileSync(path.join(output,'main.asm'),[
  '.var movieData=LoadBinary("movie.bin")','.var indexData=LoadBinary("frame-offsets16.bin")',
  '.var fontData=LoadBinary("font.bin")','.var waveData=LoadBinary("wave-ages.bin")',
  `.import source "${path.relative(output,path.join(here,'span-effects-player.asm')).split(path.sep).join('/')}"`,''].join('\n'));
 const c=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',output,'-o',path.join(output,'player.prg'),'-symbolfile','-vicesymbols'],{cwd:output,stdio:'inherit'});
 assert.equal(c.status,0,'Assembler failed');const program=fs.readFileSync(path.join(output,'player.prg'));
 const labels=Object.fromEntries([...fs.readFileSync(path.join(output,'main.sym'),'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-f]+)/gi)].map(m=>[m[1],parseInt(m[2],16)]));
 fs.writeFileSync(path.join(output,'labels.json'),JSON.stringify(labels,null,2)+'\n');
 const absoluteIndex=Buffer.concat([Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))&255)),Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))>>8))]);
 fs.writeFileSync(path.join(output,'frame-pointers-absolute.bin'),absoluteIndex);
 const result={name:'span-effects',format:'Independent25rows/frame: X8,length8,rawCharacters[length]; onlyleading/trailingzero omitted; internalzeros literal.',
  storedFrames:97,encodedFrames:97,nominalFps:25,nativeFps:null,modes:['normal','wave','checkerboard'],
  modeDurationFields:501,nominalModeSeconds:501*19656/985248,nominalSequenceSeconds:1503*19656/985248,modeLookaheadFields:5,
  phaseContract:'Globalcommittedfilm_serial incrementsonce/image;1..96sourceposesrepeat. Wavephase=serial%96, age=round(4.5+4.5*sin(2*pi*(row/24+phase/96))), A=max(0,t-age). CheckerA=t,B=max(0,t-48). Fixed4x4-char checker odd parity selectsB.',
  timingContract:'Prepare nextmode whenmode_fields_left<=5; waitfordeadline501. Everyframe begins immediatelyafterpreviouspublication andfullyclears+drawshidden. ActualFPS/modeintervalsnativemeasured.',
  rowCache:{start:labels.row_cache,bytes:500,tables:10,rowsPerTable:25,pointerBytes:2,layout:'InterleavedabsoluteLE16 row-header pointers; slot*50+row*2',frameIds:labels.cache_frame_ids,validCount:labels.cache_table_count,
   slotContract:'Normal1tablecurrent; wave10tablesages0..9; checker2tablescurrentandage48. Same500Bpoolreused. Allvalidtablesrebuiltfromrawheadersperimage.',pointerMeaning:'AddressesX,lengthheader,notrawdata',blankPose:0},
  payloadBytes:22882,pointerBytes:194,totalFilmBytes:23076,fontBytes:2048,workScreenBytes:2048,waveLutBytes:2400,
  codeRegionBytes:labels.player_code_end-0x1000,zeroPageBytes:11,basicBytes:12,
  addresses:{code:0x1000,codeEnd:labels.player_code_end,font:0x4000,screens:[0x4800,0x4c00],front:0x4800,hidden:0x4c00,source:0x5000,sourceEnd:0x5000+movie.length},
  sourceRegions:[{file:'movie.bin',start:0x5000,end:0x5000+movie.length,sha256:sha(movie)},
   {file:'frame-pointers-absolute.bin',start:labels.frame_pointer_low,end:labels.frame_pointer_low+194,sha256:sha(absoluteIndex),layout:'97absolutelowsfollowedby97absolutehighs;derivedfromunchangedframe-offsets16.bin'}],
  immutableInputHashes:{rows:sha(movie),frameOffsets16:sha(index),font:sha(font),reference:sha(reference)},
  hashes:{program:sha(program),movie:sha(movie),font:sha(font),reference:sha(reference),wave:sha(wave)},
  memoryScope:'Twooutputscreens,one500Bpointerpool,10frameIDs. Code regionincludespointerpool/frameindex/waveLUT; donotcountthemtwice. ColorRAMseparate1024cells. Nofullhistoryimages, nopreviousframecopy, norowdependencies.'};
 result.mainRamBytes=result.codeRegionBytes+movie.length+2048+2048+11+12;result.colorRamCells=1024;
 const load=program.readUInt16LE(0);for(const r of result.sourceRegions)assert(program.subarray(2+r.start-load,2+r.end-load).equals(fs.readFileSync(path.join(output,r.file))),r.file);
 fs.writeFileSync(path.join(output,'build.json'),JSON.stringify(result,null,2)+'\n');
 for(const arg of ['probe','']){const r=spawnSync('rtk',['proxy','python3',path.join(output,'host-proof.py'),output,...(arg?[arg]:[])],{stdio:'inherit'});assert.equal(r.status,0,'6502hostproof failed');}
 const proof=JSON.parse(fs.readFileSync(path.join(output,'preparation-proof.json')));
 result.hostPreparationTiming={maximumCpuCycles:proof.maximumPreparationCpuCycles,palFieldCpuBudget:18456,threeFieldBudget:55368,fitsThreeFieldsCpuBudget:proof.maximumPreparationCpuCycles<=55368};
 fs.writeFileSync(path.join(output,'build.json'),JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify({output,sha256:result.hashes.program,mainRamBytes:result.mainRamBytes,hostPreparationTiming:result.hostPreparationTiming},null,2));return result;
}
module.exports={main};if(require.main===module)main();
