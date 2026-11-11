'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const here=__dirname,sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const HOST=String.raw`import hashlib,json,math,pathlib,sys
sys.path.insert(0,'/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU
p=pathlib.Path(sys.argv[1]);l=json.loads((p/'labels.json').read_text());b=json.loads((p/'build.json').read_text())
prg=(p/'player.prg').read_bytes();font=(p/'font.bin').read_bytes()
refs=[(p/o['referenceFile']).read_bytes()for o in b['objects']]
raws=[(p/o['rowsFile']).read_bytes()for o in b['objects']]
indices=[(p/o['frameOffsetsFile']).read_bytes()for o in b['objects']]
h=(p/'h-lut.bin').read_bytes();v=(p/'v-lut.bin').read_bytes()
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
   else:raise AssertionError('IRQreturn')
   assert(cpu.a,cpu.x,cpu.y,cpu.sp)==state[1:5]
   assert(cpu.p&0xcf)==(state[5]&0xcf)
   irqcycles+=cpu.processorCycles-begin;irqcalls+=1
  cpu.step()
 raise AssertionError(('limit',label,hex(cpu.pc)))
def pose(t):return 0 if t<=0 else 1+(t-1)%48
def script(step):
 if step<24:return step//12,6 if step&1 else(step%12)//2
 return 0,{24:7,25:6,26:8,27:6}[step]
def palette(step):return[(15,11),(10,4),(13,5)][step%3]
def duration(step):return 25 if step&1 else 501
def colors(step):
 _,mode=script(step)
 if mode in(2,7):return bytes(4 if not((((i%40)//4)^((i//40)//4))&1)else 5 for i in range(1024))
 return bytes([palette(step)[1]])*1024
def expected(obj,serial,mode,blank=()):
 out=bytearray(1000);f=pose(serial)
 def glyph(o,frame,y,x):return 0 if o in blank else refs[o][frame*1000+y*40+x]
 if mode in(0,1,2,6,7):
  for y in range(25):
   age=math.floor(4.5+4.5*math.sin(2*math.pi*(y/24+(serial%48)/48))+.5)if mode==1 else 0
   aa=pose(max(0,serial-age));bb=pose(max(0,serial-24))
   for x in range(40):
    parity=((x//4)^(y//4))&1
    source=parity if mode==7 else obj
    frame=f if mode==7 else bb if mode==2 and parity else aa
    out[y*40+x]=glyph(source,frame,y,x)
 elif mode==3:
  for y in range(12):
   for x in range(40):
    c=glyph(obj,f,y,x);out[y*40+x]=c;out[(23-y)*40+x]=v[c]
 elif mode==4:
  for y in range(25):
   for x in range(20):
    c=glyph(obj,f,y,x);out[y*40+x]=c;out[y*40+39-x]=h[c]
 elif mode==5:
  for y in range(12):
   for x in range(20):
    c=glyph(obj,f,y,x);hc=h[c]
    out[y*40+x]=c;out[y*40+39-x]=hc;out[(23-y)*40+x]=v[c];out[(23-y)*40+39-x]=v[hc]
 else:
  for y in range(12):
   for x in range(20):
    star=glyph(0,f,y,x);cube=glyph(1,f,y,x)
    out[y*40+x]=star;out[y*40+39-x]=h[cube]
    out[(23-y)*40+x]=v[cube];out[(23-y)*40+39-x]=v[h[star]]
 return bytes(out)
cpu.pc=l['copy_high_start'];bootCopyCycles=run('copy_high_end')
assert bytes(m[0xe000:0xe000+b['highStagingBytes']])==(p/'movie-high.bin').read_bytes()
if not b['highStagingBytes']:assert bytes(m[0xe000:0xfffa])==bytes([0xa5])*(0xfffa-0xe000)
for addr in(0x4800,0x4c00):m[addr:addr+1024]=bytes(1024)
m[l['front_screen_hi']]=0x48;m[l['back_screen_hi']]=0x4c
m[0xfffe]=l['field_irq']&255;m[0xffff]=l['field_irq']>>8
assert m[0x7fff]==0
front,back=0x4800,0x4c00;records=[];cases=[]
oldstep,oldserial=0,0
for step in list(range(28))+[0]:
 obj,mode=script(step);oldobj,_=script(oldstep);serial=1 if obj!=oldobj else oldserial+(2 if mode==6 else 1)
 cases.append((step,serial,oldstep,oldserial,'sequence'));oldstep,oldserial=step,serial
for obj in range(2):
 for mode in range(7):
  step=obj*12+(1 if mode==6 else mode*2)
  for frame in range(1,49):
   serial=96+frame;cases.append((step,serial,step,serial-(2 if mode==6 else 1),'pose'))
 for mode in(1,2):
  for serial in range(1,25):cases.append((obj*12+mode*2,serial,obj*12+mode*2,serial-1,'history'))
for step in(24,26):
 for frame in range(1,49):cases.append((step,96+frame,step,95+frame,'mixedpose'))
for i,(step,serial,oldstep,oldserial,kind)in enumerate(cases):
 obj,mode=script(step);oldobj,oldmode=script(oldstep);transition=step!=oldstep
 m[l['object_id']]=oldobj;m[l['mode']]=oldmode;m[l['step_index']]=oldstep
 m[l['film_frame']]=pose(oldserial);put16('film_serial',oldserial)
 put16('mode_fields_left',0 if transition else duration(step));m[l['mode_due']]=int(transition)
 oldbg,oldfg=palette(oldstep);m[0xd020]=oldbg;m[0xd021]=oldbg;m[0xd800:0xdc00]=colors(oldstep)
 m[l['active_bg']]=oldbg;m[l['active_fg']]=oldfg;m[l['active_palette_index']]=oldstep%3;m[l['active_color_pattern']]=int(oldmode in(2,7))
 before=bytes(m[front:front+1024]);cpu.pc=l['prepare_start']
 setup=run('clear_start');clear=run('render_start',True);render=run('render_end',True)
 assert(m[l['next_step']],m[l['next_object']],m[l['next_mode']],m[l['next_film_frame']])==(step,obj,mode,pose(serial))
 assert m[l['next_serial']]+256*m[l['next_serial']+1]==serial
 assert bytes(m[back:back+1000])==expected(obj,serial,mode),('image',i,step,serial,mode)
 count=1 if mode in(0,6)else 10 if mode==1 else 2 if mode in(2,7)else 0
 assert m[l['cache_table_count']]==count
 for slot in range(count):
  age=0 if mode==7 else 24 if mode==2 and slot else slot
  sourceobj=slot if mode==7 else obj;sourcepose=pose(max(0,serial-age))
  assert(m[l['cache_object_ids']+slot],m[l['cache_frame_ids']+slot])==(sourceobj,sourcepose)
  frameoff=int.from_bytes(indices[sourceobj][sourcepose*2:sourcepose*2+2],'little');offset=frameoff
  for row in range(25):
   addr=l['row_cache']+slot*50+row*2
   assert m[addr]+256*m[addr+1]==b['objects'][sourceobj]['frameAddresses'][sourcepose]+offset-frameoff,('cache',i,slot,row)
   offset+=2+raws[sourceobj][offset+1]
 assert bytes(m[back+1000:back+1024])==bytes(24)and bytes(m[front:front+1024])==before
 assert(m[l['object_id']],m[l['step_index']])==(oldobj,oldstep)
 assert m[0xd020]==oldbg and m[0xd021]==oldbg and bytes(m[0xd800:0xdc00])==colors(oldstep)
 assert bytes(m[0x4000:0x4800])==font and m[0x7fff]==0
 for region in b['sourceRegions']:assert bytes(m[region['start']:region['end']])==(p/region['file']).read_bytes(),region['file']
 record=dict(object=obj,serial=serial,pose=pose(serial),mode=mode,step=step,kind=kind,transition=transition,setupCpuCycles=setup,clearCpuCycles=clear,renderCpuCycles=render,totalCpuCycles=setup+clear+render)
 assert record['totalCpuCycles']<=b['preparationBudgets'][obj][mode]*18456,('budget',record)
 cpu.pc=l['commit_start'];commit=run('presented');front,back=back,front;record['commitCpuCycles']=commit;records.append(record)
 assert(m[l['object_id']],m[l['mode']],m[l['step_index']],m[l['film_frame']])==(obj,mode,step,pose(serial))
 assert m[l['front_screen_hi']]==front>>8 and m[0xd018]==(0x20 if front==0x4800 else 0x30)
 assert m[0xd011]==(0x9f if mode in(3,5,8)else 0x9b)
 bg,fg=palette(step)
 assert(m[l['active_palette_index']],m[l['active_bg']],m[l['active_fg']],m[l['active_color_pattern']])==(step%3,bg,fg,int(mode in(2,7)))
 assert m[0xd020]==bg and m[0xd021]==bg and bytes(m[0xd800:0xdc00])==colors(step)
 if mode in(3,5,8):assert bytes(m[front+960:front+1000])==bytes(40)
 if transition:assert commit<6500,commit
l['host_return']=0x0300
def call(name,inject=False):
 cpu.stPushWord(0x02ff);cpu.pc=l[name];return run('host_return',inject)
for step in range(28):
 obj,mode=script(step);m[l['object_id']]=obj;m[l['mode']]=mode;m[l['step_index']]=step
 call('reset_mode_clock');put16('field_counter',0);fields=duration(step)
 for field in range(1,fields+1):
  cpu.pc=l['host_return'];cpu.p&=~4;cpu.irq();run('host_return')
  assert m[l['mode_due']]==int(field==fields)
  assert m[l['mode_fields_left']]+256*m[l['mode_fields_left']+1]==fields-field
 candidate=(step+1)%28;nextobj,nextmode=script(candidate)
 margin=b['preparationBudgets'][obj][mode]+b['preparationBudgets'][nextobj][nextmode]-1
 for left in(margin+1,margin,1,0):
  put16('mode_fields_left',left);put16('film_serial',123);m[l['film_frame']]=pose(123);call('select_next')
  chosen=candidate if left<=margin else step;co,cm=script(chosen)
  assert(m[l['next_step']],m[l['next_mode']],m[l['next_object']],m[l['transition_margin']])==(chosen,cm,co,margin)
  assert m[l['next_serial']]+256*m[l['next_serial']+1]==(1 if co!=obj else 123+(2 if cm==6 else 1))
# Existing independent blank0frames exercise each mixed source alone andboth.
# Only their pointer input is redirected inRAM, restored before immutableguards.
blankCases=0
for mode in(7,8):
 for blank in((),(0,),(1,),(0,1)):
  saved=[]
  for obj in blank:
   index=obj*49+1;low=l['frame_pointer_low']+index;high=l['frame_pointer_high']+index
   saved.append((low,m[low],high,m[high]));address=b['objects'][obj]['frameAddresses'][0]
   m[low]=address&255;m[high]=address>>8
  m[l['next_mode']]=mode;m[l['next_object']]=0;m[l['lookup_object']]=0;m[l['next_film_frame']]=1;put16('next_serial',1)
  before=bytes(m[front:front+1024]);call('clear_back')
  if mode==7:call('build_cache')
  call('render_mixed_checker'if mode==7 else'render_mixed_quadrants',True)
  assert bytes(m[back:back+1000])==expected(0,1,mode,blank),('mixedblank',mode,blank)
  assert bytes(m[front:front+1024])==before
  for low,a,high,c in saved:m[low]=a;m[high]=c
  for region in b['sourceRegions']:assert bytes(m[region['start']:region['end']])==(p/region['file']).read_bytes()
  blankCases+=1
result=dict(passed=True,imagesVerified=len(records)+1,all48PosesBothObjectsExistingModes=True,all48PosesBothMixedModes=True,mixedBlankCases=blankCases,all28Phase501Or25FieldCountdownsAndWrapVerified=True,normalSizeFlashSourceStep2WrapVerified=True,mixedCheckerPurpleGreen1024ParityVerified=True,mixedQuadrantsDiagonalHVCompositionVerified=True,allPalettesAndUniformRestoreVerified=True,preparationBudgetBoundsVerified=True,highPayloadBootCopyVerified=True,bootCopyCpuCycles=bootCopyCycles,reserved7fffByteRemainsZero=True,prgLoadAvoidsIoGap=True,repeatTransitionVerified=True,injectedIrqs=irqcalls,irqRegistersAndStatusPreserved=True,frontUnchangedDuringPreparation=True,sourceFontUnchanged=True,maximumPreparationCpuCycles=max(r['totalCpuCycles']for r in records),programSha256=hashlib.sha256(prg).hexdigest(),scope='Assembled6502 28phase rawspan player;normal-size2stepflashes,synchronousmixedchecker,diagonalmixedquadrants,nozoom/crop/keyboard; noVIC/FPSclaim.',records=records)
(p/'host-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items()if k!='records'},indent=2))
`;
// One alternate binary-input fixture covers the opposite boot-copy branch.
// It compiles the actual player unchanged; no runtime test flag or patched code.
function proveAlternateBoot(output,actualHighBytes){
 const dir=path.join(output,'boot-copy-fixture');fs.mkdirSync(dir,{recursive:true});
 const bytes=Buffer.from(Array.from({length:actualHighBytes?0:257},(_,i)=>(i*73+19)&255));
 fs.writeFileSync(path.join(dir,'high.bin'),bytes);
 let wrapper=fs.readFileSync(path.join(output,'main.asm'),'utf8').replace(/LoadBinary\("([^"]+)"\)/g,(_,file)=>`LoadBinary(${JSON.stringify(path.resolve(output,file))})`);
 wrapper=wrapper.replace(/^\.var highMovieData=.*$/m,`.var highMovieData=LoadBinary(${JSON.stringify(path.join(dir,'high.bin'))})`)
  .replace(/^\.import source .*$/m,`.import source ${JSON.stringify(path.join(here,'span-combined-player.asm'))}`);
 fs.writeFileSync(path.join(dir,'main.asm'),wrapper);
 const assembled=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',dir,'-o',path.join(dir,'player.prg'),'-symbolfile'],{cwd:dir,stdio:'inherit'});
 assert.equal(assembled.status,0,'Bootfixture assembly failed');
 const labels=Object.fromEntries([...fs.readFileSync(path.join(dir,'main.sym'),'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-f]+)/gi)].map(m=>[m[1],parseInt(m[2],16)]));
 fs.writeFileSync(path.join(dir,'labels.json'),JSON.stringify(labels));
 const proof=String.raw`import hashlib,json,pathlib,sys
sys.path.insert(0,'/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU
p=pathlib.Path(sys.argv[1]);l=json.loads((p/'labels.json').read_text());prg=(p/'player.prg').read_bytes();expected=(p/'high.bin').read_bytes()
m=[0xa5]*65536;load=int.from_bytes(prg[:2],'little');m[load:load+len(prg)-2]=prg[2:];before=bytes(m)
assert load+len(prg)-2<0xd000
cpu=MPU(memory=m);cpu.pc=l['copy_high_start']
for _ in range(2000000):
 if cpu.pc==l['copy_high_end']:break
 cpu.step()
else:raise AssertionError('Bootcopy didnotterminate')
assert bytes(m[0xe000:0xe000+len(expected)])==expected
allowed=set(range(2,6))|set(range(l['high_copy_left'],l['high_copy_left']+2))|set(range(0xe000,0xe000+len(expected)))
for address in range(65536):
 if before[address]!=m[address]:assert address in allowed,('Unexpectedbootwrite',hex(address))
result=dict(passed=True,highBytes=len(expected),cpuCycles=cpu.processorCycles,exactBytesAndNoOutsideWrites=True,programSha256=hashlib.sha256(prg).hexdigest())
(p/'proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
`;
 fs.writeFileSync(path.join(dir,'prove.py'),proof);
 const checked=spawnSync('rtk',['proxy','python3',path.join(dir,'prove.py'),dir],{stdio:'inherit'});
 assert.equal(checked.status,0,'Bootfixture CPU proof failed');
 return JSON.parse(fs.readFileSync(path.join(dir,'proof.json')));
}
function main(argv=process.argv.slice(2)){
 const opt=(n,d)=>{const i=argv.indexOf('--'+n);return i<0?d:argv[i+1];};
 const input=path.resolve(opt('input',path.join(here,'build/three-scene-star-lit-cube-data')));
 const output=path.resolve(opt('output',path.join(here,'build/three-scene-star-cube-combined')));
 const dataLockPath=opt('data-lock',path.join(input,'manifest.json')),dataLockBytes=dataLockPath?fs.readFileSync(path.resolve(dataLockPath)):null;
 const dataLock=dataLockBytes?JSON.parse(dataLockBytes):null;
 assert.equal(sha(dataLockBytes),'6906d3db5f89ef1e20255467ef1c88cc6eaee3cb32752d5eb1ed8cdb9bfcfba3');
 if(dataLock){
  assert.equal(dataLock.passed,true);assert.equal(dataLock.dataComplete,true);
  assert.equal(dataLock.fontSha256,'1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1');
 }
 const lutSource=path.join(here,'three-scene/results/flagship-star-span-mirror-texture');
 const h=fs.readFileSync(path.join(lutSource,'h-lut.bin')),v=fs.readFileSync(path.join(lutSource,'v-lut.bin'));
 assert.equal(sha(h),'8758e99a0a12a3295a674c3a806a3ca9160ee11b837493e9ca65d8f4d3f09ba8');
 assert.equal(sha(v),'7bd4a003ad2078ef6dcaa1fed00d230f17e8089575c4f356b5b91bc36f278234');
 const objects=['star','cube'].map((name,id)=>{
  const dir=path.join(input,name),read=f=>fs.readFileSync(path.join(dir,f));
  const rows=read('rows.bin'),index=read('frame-offsets16.bin'),font=read('font.bin'),reference=read('reference.frames'),zoom=read('learned.lut');
  assert.equal(index.length,98);assert.equal(reference.length,49000);assert.equal(zoom.length,1024);
  assert.equal(sha(font),'1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1');
  assert(zoom.subarray(0,4).equals(Buffer.alloc(4)));
  if(dataLock){
   const lock=dataLock.objects.find(o=>o.object===name);assert.equal(lock?.passed,true);
   for(const[key,bytes]of Object.entries({rows,index,reference,font,zoomLut:zoom}))assert.equal(sha(bytes),lock.hashes[key],`${name} ${key} differs from frozen data lock`);
  }
  for(let f=0;f<49;f++){
   let at=index.readUInt16LE(f*2);const decoded=Buffer.alloc(1000);
   for(let y=0;y<25;y++){const x=rows[at++],length=rows[at++];assert(x+length<=40);rows.copy(decoded,y*40+x,at,at+length);at+=length;}
   assert.equal(at,f===48?rows.length:index.readUInt16LE((f+1)*2));
   assert(decoded.equals(reference.subarray(f*1000,(f+1)*1000)),`${name}rawframe${f}`);
  }
  return{id,name,dir,rows,index,font,reference,frameAddresses:[],segments:[]};
 });
 assert(objects[0].font.equals(objects[1].font));const font=objects[0].font;
 const oldref=fs.readFileSync(path.join(here,'three-scene/results/flagship-star-ten-buffer/reference.frames'));
 for(let f=1;f<49;f++)assert(objects[0].reference.subarray(f*1000,(f+1)*1000).equals(oldref.subarray((f*2-1)*1000,f*2*1000)));
 const lowImage=Buffer.alloc(0x8000),highImage=Buffer.alloc(0x1ffa);let address=0x5000,inHigh=false,lowEnd=0x5000,highEnd=0xe000;
 for(const object of objects)for(let f=0;f<49;f++){
  const logicalStart=object.index.readUInt16LE(f*2),logicalEnd=f===48?object.rows.length:object.index.readUInt16LE((f+1)*2);
  const bytes=object.rows.subarray(logicalStart,logicalEnd);
  if(!inHigh&&address<0x8000&&address+bytes.length>0x7fff)address=0x8000;
  if(!inHigh&&address+bytes.length>0xd000){address=0xe000;inHigh=true;}
  assert(address+bytes.length<=(inHigh?0xfffa:0xd000),'Wholeframes mustfit permittedsourceRAM');
  assert(!(address<=0x7fff&&address+bytes.length>0x7fff),'Idlebyte7fff mustnotbelongtoaframe');
  object.frameAddresses.push(address);
  bytes.copy(inHigh?highImage:lowImage,address-(inHigh?0xe000:0x5000));
  if(inHigh)highEnd=address+bytes.length;else lowEnd=address+bytes.length;
  const last=object.segments.at(-1);
  if(last&&last.end===address){last.end+=bytes.length;last.logicalEnd=logicalEnd;}
  else object.segments.push({start:address,end:address+bytes.length,logicalStart,logicalEnd});
  address+=bytes.length;
 }
 const lowMovie=lowImage.subarray(0,lowEnd-0x5000),highMovie=highImage.subarray(0,highEnd-0xe000),movie=Buffer.concat(objects.map(o=>o.rows));
 assert.equal(lowMovie[0x7fff-0x5000],0);
 const budgets=[[2,3,3,2,2,2,2,4,2],[2,3,4,2,2,2,2,4,2]];
 const stepModes=Array.from({length:28},(_,step)=>step<24?(step&1?6:Math.floor((step%12)/2)):[7,6,8,6][step-24]);
 const stepObjects=Array.from({length:28},(_,step)=>step<24?Math.floor(step/12):0);
 const frameAddresses=objects.flatMap(o=>o.frameAddresses);
 const absoluteIndex=Buffer.concat([Buffer.from(frameAddresses.map(a=>a&255)),Buffer.from(frameAddresses.map(a=>a>>8))]);
 const wave=Buffer.from(Array.from({length:1200},(_,i)=>Math.round(4.5+4.5*Math.sin(2*Math.PI*(Math.floor(i/48)/24+(i%48)/48)))));
 fs.mkdirSync(output,{recursive:true});
 const write=(n,b)=>fs.writeFileSync(path.join(output,n),b);
 if(dataLockBytes)write('input-data-lock.json',dataLockBytes);
 for(const[n,b]of Object.entries({'movie.bin':movie,'rows.bin':movie,'movie-low.bin':lowMovie,'movie-high.bin':highMovie,'font.bin':font,'h-lut.bin':h,'v-lut.bin':v,'wave-ages.bin':wave,'frame-pointers-absolute.bin':absoluteIndex,'step-mode.bin':Buffer.from(stepModes),'step-object.bin':Buffer.from(stepObjects),'preparation-budgets.bin':Buffer.from(budgets.flat())}))write(n,b);
 for(const o of objects){
  write(`${o.name}-rows.bin`,o.rows);write(`${o.name}-frame-offsets16.bin`,o.index);write(`${o.name}-reference.frames`,o.reference);
 }
 write('host-proof.py',HOST);
 write('main.asm',['.var lowMovieData=LoadBinary("movie-low.bin")','.var highMovieData=LoadBinary("movie-high.bin")',
  '.var absoluteIndexData=LoadBinary("frame-pointers-absolute.bin")','.var waveData=LoadBinary("wave-ages.bin")',
  '.var stepModeData=LoadBinary("step-mode.bin")','.var stepObjectData=LoadBinary("step-object.bin")','.var budgetData=LoadBinary("preparation-budgets.bin")','.var fontData=LoadBinary("font.bin")','.var hData=LoadBinary("h-lut.bin")','.var vData=LoadBinary("v-lut.bin")',
  `.import source "${path.relative(output,path.join(here,'span-combined-player.asm')).split(path.sep).join('/')}"`,''].join('\n'));
 const c=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',output,'-o',path.join(output,'player.prg'),'-symbolfile','-vicesymbols'],{cwd:output,stdio:'inherit'});
 assert.equal(c.status,0,'Assembler failed');const program=fs.readFileSync(path.join(output,'player.prg'));
 const labels=Object.fromEntries([...fs.readFileSync(path.join(output,'main.sym'),'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-f]+)/gi)].map(m=>[m[1],parseInt(m[2],16)]));
 write('labels.json',JSON.stringify(labels,null,2)+'\n');
 const asset=o=>({id:o.id,name:o.name,rowsFile:`${o.name}-rows.bin`,frameOffsetsFile:`${o.name}-frame-offsets16.bin`,referenceFile:`${o.name}-reference.frames`,
  storedFrames:49,animatedPoses:48,originalPoseMap:[0,...Array.from({length:48},(_,i)=>i*2+1)],sourceStart:o.frameAddresses[0],sourceEnd:o.segments.at(-1).end,frameAddresses:o.frameAddresses,segments:o.segments,
  hashes:{rows:sha(o.rows),offsets:sha(o.index),reference:sha(o.reference),font:sha(o.font)},
  ...(dataLock?{provenance:dataLock.objects.find(entry=>entry.object===o.name).provenance}: {})});
 const sourceRegions=[{file:'movie-low.bin',start:0x5000,end:0x5000+lowMovie.length,sha256:sha(lowMovie)},
  ...(highMovie.length?[{file:'movie-high.bin',start:0xe000,end:0xe000+highMovie.length,loadStart:labels.high_movie_staging,sha256:sha(highMovie)}]:[]),
  {file:'frame-pointers-absolute.bin',start:labels.frame_pointer_low,end:labels.frame_pointer_low+196,sha256:sha(absoluteIndex),layout:'98lowbytesfollowedby98highbytes;49perobject'},
  {file:'h-lut.bin',start:labels.h_lut,end:labels.h_lut+256,sha256:sha(h)},{file:'v-lut.bin',start:labels.v_lut,end:labels.v_lut+256,sha256:sha(v)}];
 const result={name:'span-star-cube-combined',objects:objects.map(asset),storedFrames:98,animatedPosesPerObject:48,
  nominalFps:25,nativeFps:null,minimumFieldsPerImage:2,startObject:0,startMode:0,startStep:0,modes:['normal','wave','checkerboard','vertical','horizontal','both','flash','mixed-checker','mixed-quadrants'],
  phaseScript:Array.from({length:28},(_,step)=>({step,object:stepObjects[step],mode:stepModes[step],fields:step&1?25:501,palette:step%3,sourceStep:stepModes[step]===6?2:1})),baseDurationFields:501,flashDurationFields:25,preparationBudgets:budgets,transitionLookahead:'currentPrimaryObjectModeBudget+nextPrimaryObjectModeBudget-1',palettes:[{bg:15,border:15,fg:11},{bg:10,border:10,fg:4},{bg:13,border:13,fg:5}],
  nominalModeSeconds:501*19656/985248,nominalSequenceSeconds:7364*19656/985248,
  objectClock:'48poses/object. Base+mixedimagesadvancelocalserial1;normal-sizeflash6advances2. Primaryobjectchangeonlyresetsframe/serial/phase1. Step23→24cube→starresets1;27→0sameSTARcontinues. Mixed7/8samplebothobjectsatsamenext_film_frame.',
  geometry:{fullHeightModes:[0,1,2,4,6,7],centered192Modes:[3,5,8],fullHeightYScroll:3,centeredYScroll:7,
   vertical:{mode:3,sourceRows:12,sourceColumns:40,mirrorRow:'23-y',blankScreenRow:24},horizontal:{mode:4,sourceRows:25,sourceColumns:20,mirrorColumn:'39-x'},
   both:{mode:5,sourceRows:12,sourceColumns:20,mirrorRow:'23-y',mirrorColumn:'39-x',blankScreenRow:24},
   flash:{mode:6,sourceRows:25,sourceColumns:40,outputRows:25,outputColumns:40,scale:1,sourceStep:2},
   mixedChecker:{mode:7,sourceRows:25,sourceColumns:40,sourceA:'starcurrent',sourceB:'cubecurrent',parity:'((x>>2)^(y>>2))&1',foregroundA:4,foregroundB:5},
   mixedQuadrants:{mode:8,sourceRows:12,sourceColumns:20,outputRows:24,outputColumns:40,TL:'star[c]',TR:'H[cube[c]]',BL:'V[cube[c]]',BR:'V[H[star[c]]]',blankScreenRow:24,blackMarginsPixels:4}},
  wave:{phases:48,formula:'round(4.5+4.5*sin(2*pi*(row/24+phase/48)))',phase:'objectLocalSerial%48',minimumHistorySerial:0},checker:{blockCharacters:4,A:'t',B:'max(0,t-24)',BParity:'((x>>2)^(y>>2))&1'},
  rowCache:{start:labels.row_cache,bytes:500,tables:10,rowsPerTable:25,pointerBytes:2,layout:'InterleavedabsoluteLE16row-headerpointers;slot*50+row*2',frameIds:labels.cache_frame_ids,validCount:labels.cache_table_count,objectIds:labels.cache_object_ids,slotContract:'0and6oneprimarycurrent;1tenprimaryages0..9;2primarycurrent/age24;7starcurrent/cubecurrent;3/4/5/8directnocache'},
  payloadBytes:movie.length,physicalPayloadStorageBytes:lowMovie.length+highMovie.length,packingPaddingBytes:lowMovie.length+highMovie.length-movie.length,reservedIdleAddress:0x7fff,reservedIdleValue:0,pointerBytes:196,totalFilmBytes:movie.length+196,fontBytes:2048,lutBytes:512,mirrorLutBytes:512,workScreenBytes:2048,waveLutBytes:1200,rowCacheBytes:500,historyImageBytes:0,
  codeRegionBytes:labels.player_code_end-0x1000,highStagingBytes:highMovie.length,zeroPageBytes:16,basicBytes:12,
  addresses:{code:0x1000,codeEnd:labels.player_code_end,highStaging:labels.high_movie_staging,highStagingEnd:labels.high_movie_staging_end,font:0x4000,screens:[0x4800,0x4c00],front:0x4800,hidden:0x4c00,source:0x5000,sourceEnd:0x5000+lowMovie.length,highSource:0xe000,highSourceEnd:0xe000+highMovie.length},
  sourceRegions,input,...(dataLock?{inputDataLock:{file:'input-data-lock.json',source:path.resolve(dataLockPath),sha256:sha(dataLockBytes)}}:{}),
  colorCommit:{foregroundCells:1024,onlyAtPhaseChange:true,uniformUnroll:16,uniformIterations:64,checkerStores:256,checkerIterations:4,checkerColors:[4,5],checkerParity:'(((position%40)>>2)^(Math.floor(position/40)>>2))&1',patternFlag:'next_color_pattern/active_color_pattern:1iffmode2or7',deadlineRaster:51,scope:'SEIlowerborderafterfieldIRQ,fillthenBGborderandD018switchbeforenextactive51'},hashes:{program:sha(program),movie:sha(movie),font:sha(font),absoluteIndex:sha(absoluteIndex),hLut:sha(h),vLut:sha(v),wave:sha(wave)},
  memoryScope:'OnePRG,twoobjectssequentially,onefont,twooutputs,one500Bpool,nohistoryimages/decompression/copypriorframe. Wholeframesnevercrossreserved7fff=0norI/O;highblobstagedbelowfontandbootcopiedafter01=35. PRGloadendsbelowD000. Codeincludespointers/pool/mirrorLUTs/script/budgets;NozoomLUT/crop/input/history;highstagingandphysicalpackingpaddingcountedseparately;ColorRAMseparate.'};
 result.mainRamBytes=result.codeRegionBytes+result.highStagingBytes+result.physicalPayloadStorageBytes+2048+2048+16+12;result.colorRamCells=1024;
 const load=program.readUInt16LE(0);assert(load+program.length-2<=0xd000,'PRGmustnotloadI/Ogap');
 for(const r of sourceRegions){const address=r.loadStart??r.start;assert(program.subarray(2+address-load,2+address-load+r.end-r.start).equals(fs.readFileSync(path.join(output,r.file))),r.file);}
 write('build.json',JSON.stringify(result,null,2)+'\n');
 const proof=spawnSync('rtk',['proxy','python3',path.join(output,'host-proof.py'),output],{stdio:'inherit'});assert.equal(proof.status,0,'6502hostproof failed');
 const alternateBoot=proveAlternateBoot(output,highMovie.length);
 const bootProof={passed:true,actualHighBytes:highMovie.length,actualProgram:result.hashes.program,alternate:alternateBoot,zeroAndNonzeroCasesVerified:true};
 fs.writeFileSync(path.join(output,'boot-copy-proof.json'),JSON.stringify(bootProof,null,2)+'\n');
 const hostProof=JSON.parse(fs.readFileSync(path.join(output,'host-proof.json')));hostProof.bootZeroAndNonzeroCasesVerified=true;
 fs.writeFileSync(path.join(output,'host-proof.json'),JSON.stringify(hostProof,null,2)+'\n');
 result.bootProof={file:'boot-copy-proof.json',zeroAndNonzeroCasesVerified:true};write('build.json',JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify({output,sha256:result.hashes.program,mainRamBytes:result.mainRamBytes,highStagingBytes:result.highStagingBytes},null,2));return result;
}
module.exports={main};if(require.main===module)main();
