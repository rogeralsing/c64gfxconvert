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
zooms=[(p/o['zoomLutFile']).read_bytes()for o in b['objects']]
movie=(p/'rows.bin').read_bytes();h=(p/'h-lut.bin').read_bytes();v=(p/'v-lut.bin').read_bytes()
class Bus(list):
 keys=set()
 def __getitem__(self,address):
  if address==0xdc01 and super().__getitem__(0xdc03)==0:
   selected=super().__getitem__(0xdc00);value=255
   for key,row,bit in [('W',1,1),('A',1,2),('S',1,5),('D',2,2)]:
    if key in self.keys and not(selected&(1<<row)):value&=~(1<<bit)
   return value
  return super().__getitem__(address)
m=Bus([0xa5]*65536);load=int.from_bytes(prg[:2],'little');m[load:load+len(prg)-2]=prg[2:]
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
def pose(t):return 0 if t<=0 else 1+(t-1)%48
def expected(obj,serial,mode,crop=(10,6)):
 out=bytearray(1000);f=pose(serial);ref=refs[obj];zoom=zooms[obj]
 if mode<3:
  for y in range(25):
   age=math.floor(4.5+4.5*math.sin(2*math.pi*(y/24+(serial%48)/48))+.5) if mode==1 else 0
   aa=pose(max(0,serial-age));bb=pose(max(0,serial-24))
   for x in range(40):
    use=bb if mode==2 and ((x//4)^(y//4))&1 else aa
    out[y*40+x]=ref[use*1000+y*40+x]
 elif mode==3:
  for y in range(12):
   for x in range(40):
    c=ref[f*1000+y*40+x];out[y*40+x]=c;out[(23-y)*40+x]=v[c]
 elif mode==4:
  for y in range(25):
   for x in range(20):
    c=ref[f*1000+y*40+x];out[y*40+x]=c;out[y*40+39-x]=h[c]
 elif mode==5:
  for y in range(12):
   for x in range(20):
    c=ref[f*1000+y*40+x];hc=h[c]
    out[y*40+x]=c;out[y*40+39-x]=hc
    out[(23-y)*40+x]=v[c];out[(23-y)*40+39-x]=v[hc]
 else:
  xx,yy=crop
  for y in range(12):
   for x in range(20):
    c=ref[f*1000+(yy+y)*40+xx+x]
    for q in range(4):out[(y*2+(q>>1))*40+x*2+(q&1)]=zoom[c*4+q]
 return bytes(out)
cpu.pc=l['copy_high_start'];bootCopyCycles=run('copy_high_end')
assert bytes(m[0xe000:0xe000+b['highStagingBytes']])==(p/'movie-high.bin').read_bytes()
for address in(0x4800,0x4c00):m[address:address+1024]=bytes(1024)
m[l['film_frame']]=0;put16('film_serial',0);put16('field_counter',0)
m[l['mode']]=0;m[l['next_mode']]=0;m[l['object_id']]=0;m[l['next_object']]=0
m[l['step_index']]=0;m[l['next_step']]=0;put16('mode_fields_left',501);m[l['mode_due']]=0
m[l['front_screen_hi']]=0x48;m[l['back_screen_hi']]=0x4c;m[l['frame_wait_fields']]=2
m[0xfffe]=l['field_irq']&255;m[0xffff]=l['field_irq']>>8
m[0xdc00]=255;m[0xdc02]=255;m[0xdc03]=0;m[l['keyboard_previous']]=0
assert m[0x7fff]==0
assert all(expected(obj,0,mode)==bytes(1000)for obj in range(2)for mode in range(7))
def script(step):return step//12,6 if step&1 else (step%12)//2
def palette(step):return[(15,11),(10,4),(13,5)][step%3]
def duration(step):return 25 if step&1 else 501
front,back=0x4800,0x4c00;records=[];cases=[]
oldstep,oldserial=0,0
for step in list(range(24))+[0]:
 obj,mode=script(step);oldobj,_=script(oldstep)
 serial=1 if obj!=oldobj else oldserial+(2 if mode==6 else 1)
 cases.append((step,serial,(10,6),oldstep,oldserial,'sequence'))
 oldstep,oldserial=step,serial
for obj in range(2):
 for mode in range(7):
  step=obj*12+(1 if mode==6 else mode*2)
  for crop in([(10,6),(0,0),(20,0),(0,13),(20,13)]if mode==6 else[(10,6)]):
   for frame in range(1,49):
    serial=96+frame;cases.append((step,serial,crop,step,serial-(2 if mode==6 else 1),'pose'))
 for mode in(1,2):
  step=obj*12+mode*2
  for serial in range(1,25):cases.append((step,serial,(10,6),step,serial-1,'history'))
for i,(step,serial,center,oldstep,oldserial,kind) in enumerate(cases):
 obj,mode=script(step);oldobj,oldmode=script(oldstep)
 m[l['object_id']]=oldobj;m[l['mode']]=oldmode;m[l['step_index']]=oldstep
 m[l['film_frame']]=pose(oldserial);put16('film_serial',oldserial)
 m[l['zoom_x']],m[l['zoom_y']]=center;m.keys=set();m[l['keyboard_previous']]=0
 transition=step!=oldstep
 put16('mode_fields_left',0 if transition else duration(step));m[l['mode_due']]=int(transition)
 oldbg,oldfg=palette(oldstep);m[0xd020]=oldbg;m[0xd021]=oldbg;m[0xd800:0xdc00]=[oldfg]*1024
 m[l['active_bg']]=oldbg;m[l['active_fg']]=oldfg;m[l['active_palette_index']]=oldstep%3
 before=bytes(m[front:front+1024]);cpu.pc=l['prepare_start']
 setup=run('clear_start');clear=run('render_start',inject=True);render=run('render_end',inject=True)
 assert(m[l['next_step']],m[l['next_object']],m[l['next_mode']],m[l['next_film_frame']])==(step,obj,mode,pose(serial))
 assert m[l['next_serial']]+256*m[l['next_serial']+1]==serial
 crop=(m[l['latched_zoom_x']],m[l['latched_zoom_y']]);assert crop==center
 assert m[l['latched_pan_phase']]==0
 assert bytes(m[back:back+1000])==expected(obj,serial,mode,crop),('image',i,obj,serial,mode,crop)
 count=1 if mode==0 else 10 if mode==1 else 2 if mode==2 else 0
 assert m[l['cache_table_count']]==count
 for slot in range(count):
  age=24 if mode==2 and slot else slot;sourcepose=pose(max(0,serial-age))
  assert m[l['cache_frame_ids']+slot]==sourcepose
  frameoff=int.from_bytes(indices[obj][sourcepose*2:sourcepose*2+2],'little');offset=frameoff
  for row in range(25):
   addr=l['row_cache']+slot*50+row*2
   assert m[addr]+256*m[addr+1]==b['objects'][obj]['frameAddresses'][sourcepose]+offset-frameoff,('cache',i,obj,slot,row)
   offset+=2+raws[obj][offset+1]
 assert bytes(m[back+1000:back+1024])==bytes(24)
 assert bytes(m[front:front+1024])==before
 assert(m[l['object_id']],m[l['step_index']])==(oldobj,oldstep),'Visiblephase changed beforecommit'
 assert m[0xd020]==oldbg and m[0xd021]==oldbg and bytes(m[0xd800:0xdc00])==bytes([oldfg])*1024
 assert bytes(m[0x4000:0x4800])==font and m[0x7fff]==0
 for region in b['sourceRegions']:
  assert bytes(m[region['start']:region['end']])==(p/region['file']).read_bytes(),('immutable',region['file'])
 record=dict(object=obj,serial=serial,pose=pose(serial),mode=mode,step=step,kind=kind,transition=transition,
  crop=list(crop),setupCpuCycles=setup,clearCpuCycles=clear,renderCpuCycles=render,totalCpuCycles=setup+clear+render)
 assert record['totalCpuCycles']<=b['preparationBudgets'][obj][mode]*18456,('budget',record)
 cpu.pc=l['commit_start'];commit=run('presented');front,back=back,front
 record['commitCpuCycles']=commit;records.append(record)
 assert(m[l['object_id']],m[l['mode']],m[l['step_index']],m[l['film_frame']])==(obj,mode,step,pose(serial))
 assert m[l['front_screen_hi']]==front>>8 and m[0xd018]==(0x20 if front==0x4800 else 0x30)
 assert m[0xd011]==(0x9f if mode in(3,5,6)else 0x9b)
 bg,fg=palette(step)
 assert(m[l['active_palette_index']],m[l['active_bg']],m[l['active_fg']])==(step%3,bg,fg)
 assert m[0xd020]==bg and m[0xd021]==bg and bytes(m[0xd800:0xdc00])==bytes([fg])*1024
 assert m[l['active_pan_phase']]==0
 if mode==6:assert(m[l['active_zoom_x']],m[l['active_zoom_y']])==crop
 if transition:assert commit<6500,('Palettecommit mustfinish beforefirstactive51',commit)
# Execute all24real phase countdowns and data-dependent transition windows.
l['host_return']=0x0300
def call(name,inject=False):
 cpu.stPushWord(0x02ff);cpu.pc=l[name];return run('host_return',inject)
for step in range(24):
 obj,mode=script(step);m[l['object_id']]=obj;m[l['mode']]=mode;m[l['step_index']]=step
 call('reset_mode_clock');put16('field_counter',0);fields=duration(step)
 for field in range(1,fields+1):
  cpu.pc=l['host_return'];cpu.p&=~4;cpu.irq();run('host_return')
  assert m[l['mode_due']]==int(field==fields)
  assert m[l['mode_fields_left']]+256*m[l['mode_fields_left']+1]==fields-field
 candidate=(step+1)%24;nextobj,nextmode=script(candidate)
 margin=b['preparationBudgets'][obj][mode]+b['preparationBudgets'][nextobj][nextmode]-1
 for left in(margin+1,margin,1,0):
  put16('mode_fields_left',left);put16('film_serial',123);m[l['film_frame']]=pose(123);call('select_next')
  chosen=candidate if left<=margin else step;co,cm=script(chosen)
  assert(m[l['next_step']],m[l['next_mode']],m[l['next_object']],m[l['transition_margin']])==(chosen,cm,co,margin)
  assert m[l['next_serial']]+256*m[l['next_serial']+1]==(1 if co!=obj else 123+(2 if cm==6 else 1))
# Pan tables and latching are independently computed from field time, including
# phasesnotnecessarilydisplayed when the following base image is preparedearly.
for center in[(10,6),(0,0),(20,0),(0,13),(20,13)]:
 for phase in range(25):
  m[l['zoom_x']],m[l['zoom_y']]=center;m[l['next_mode']]=6;m[l['step_index']]=1;m[l['next_step']]=1
  put16('mode_fields_left',25-phase);call('latch_flash_crop',True)
  dx=math.floor(3*math.sin(2*math.pi*phase/25)+.5);dy=math.floor(2*math.sin(4*math.pi*phase/25)+.5)
  assert(m[l['latched_pan_phase']],m[l['latched_zoom_x']],m[l['latched_zoom_y']])==(phase,max(0,min(20,center[0]+dx)),max(0,min(13,center[1]+dy)))
  assert(m[l['zoom_x']],m[l['zoom_y']])==center
# Read real CIA matrix rows through a small pin-level bus model. No test-only
# hooks in the player: invoke its actual foreground scanner and IRQ paths.
for mode in range(6):
 step=mode*2;m[l['step_index']]=step;m[l['object_id']]=0;m[l['mode']]=mode
 put16('mode_fields_left',501);m[l['mode_due']]=0
 m[l['zoom_x']]=10;m[l['zoom_y']]=6;m[l['keyboard_previous']]=0;m.keys={'D'}
 cpu.pc=l['prepare_start'];run('keyboard_end',True)
 assert(m[l['zoom_x']],m[l['zoom_y']])==(11,6),'WASDcenter remainsadjustablebetweenflashes'
key_cases=0
for key,dx,dy in [('W',0,-1),('A',-1,0),('S',0,1),('D',1,0)]:
 for x,y in[(10,6),(0,0),(20,13)]:
  m[l['zoom_x']]=x;m[l['zoom_y']]=y;m[l['keyboard_previous']]=0;m.keys={key};put16('field_counter',20)
  call('poll_zoom_keyboard',True);expected_xy=(max(0,min(20,x+dx)),max(0,min(13,y+dy)))
  assert(m[l['zoom_x']],m[l['zoom_y']])==expected_xy
  assert(m[0xdc00],m[0xdc02],m[0xdc03])==(255,255,0)
  call('poll_zoom_keyboard');assert(m[l['zoom_x']],m[l['zoom_y']])==expected_xy
  put16('field_counter',29);call('poll_zoom_keyboard');assert(m[l['zoom_x']],m[l['zoom_y']])==expected_xy
  put16('field_counter',30);call('poll_zoom_keyboard')
  expected_xy=(max(0,min(20,expected_xy[0]+dx)),max(0,min(13,expected_xy[1]+dy)))
  assert(m[l['zoom_x']],m[l['zoom_y']])==expected_xy
  put16('field_counter',33);call('poll_zoom_keyboard');assert(m[l['zoom_x']],m[l['zoom_y']])==expected_xy
  put16('field_counter',34);call('poll_zoom_keyboard')
  expected_xy=(max(0,min(20,expected_xy[0]+dx)),max(0,min(13,expected_xy[1]+dy)))
  assert(m[l['zoom_x']],m[l['zoom_y']])==expected_xy;key_cases+=1
m.keys={'W','S','A','D'};m[l['zoom_x']]=10;m[l['zoom_y']]=6;m[l['keyboard_previous']]=0
call('poll_zoom_keyboard');assert(m[l['zoom_x']],m[l['zoom_y']])==(10,6)
m.keys=set();call('poll_zoom_keyboard');assert m[l['keyboard_previous']]==0
result=dict(passed=True,imagesVerified=len(records)+1,bothObjectsAll48PosesAllSevenModesVerified=True,zoom48PosesAtDefaultAndFourCornersBothObjects=True,
 bothObjectHandoffsResetToPose1WithoutBlank=True,all24Phase501Or25FieldCountdownsAndWrapVerified=True,keyboardMatrixClampAndRepeatCases=key_cases,
 keyboardCenterAdjustableInBaseModes=True,paletteChangesOnlyAtPhaseCommit=True,
 panAll25PhasesAndClampsVerified=True,reserved7fffByteRemainsZero=True,preparationBudgetBoundsVerified=True,
 highPayloadBootCopyVerified=True,bootCopyCpuCycles=bootCopyCycles,prgLoadAvoidsIoGap=True,
 repeatTransitionVerified=True,injectedIrqs=irqcalls,
 irqRegistersAndStatusPreserved=True,frontUnchangedDuringPreparation=True,sourceFontAndLutsUnchanged=True,
 maximumPreparationCpuCycles=max(r['totalCpuCycles']for r in records),
 programSha256=hashlib.sha256(prg).hexdigest(),
 scope='Assembled6502 base/flash24phase script;501/25fieldclocks,two-stepflash,field-sinecrop,phaseColorRAMcommit,budgetwindows,7fffreservationandbootcopy; noVIC/FPS claim.',records=records)
(p/'host-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items()if k!='records'},indent=2))
`;
function main(argv=process.argv.slice(2)){
 const opt=(n,d)=>{const i=argv.indexOf('--'+n);return i<0?d:argv[i+1];};
 const input=path.resolve(opt('input',path.join(here,'build/three-scene-star-ball-flash-data')));
 const output=path.resolve(opt('output',path.join(here,'build/three-scene-star-ball-flash')));
 const lutSource=path.join(here,'three-scene/results/flagship-star-span-mirror-texture');
 const h=fs.readFileSync(path.join(lutSource,'h-lut.bin')),v=fs.readFileSync(path.join(lutSource,'v-lut.bin'));
 assert.equal(sha(h),'8758e99a0a12a3295a674c3a806a3ca9160ee11b837493e9ca65d8f4d3f09ba8');
 assert.equal(sha(v),'7bd4a003ad2078ef6dcaa1fed00d230f17e8089575c4f356b5b91bc36f278234');
 const objects=['star','ball'].map((name,id)=>{
  const dir=path.join(input,name),read=f=>fs.readFileSync(path.join(dir,f));
  const rows=read('rows.bin'),index=read('frame-offsets16.bin'),font=read('font.bin'),reference=read('reference.frames'),zoom=read('learned.lut');
  assert.equal(index.length,98);assert.equal(reference.length,49000);assert.equal(zoom.length,1024);
  assert.equal(sha(font),'1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1');
  assert(zoom.subarray(0,4).equals(Buffer.alloc(4)));
  for(let f=0;f<49;f++){
   let at=index.readUInt16LE(f*2);const decoded=Buffer.alloc(1000);
   for(let y=0;y<25;y++){const x=rows[at++],length=rows[at++];assert(x+length<=40);rows.copy(decoded,y*40+x,at,at+length);at+=length;}
   assert.equal(at,f===48?rows.length:index.readUInt16LE((f+1)*2));
   assert(decoded.equals(reference.subarray(f*1000,(f+1)*1000)),`${name}rawframe${f}`);
  }
  return{id,name,dir,rows,index,font,reference,zoom,frameAddresses:[],segments:[]};
 });
 assert(objects[0].font.equals(objects[1].font));const font=objects[0].font;
 assert.equal(sha(objects[0].zoom),'37efc20a89731ff3a6b745bfb5e4083947649774b2fe63b56f0c2a4340b2dc21');
 assert.equal(sha(objects[1].rows),'40ea14723a5de4d97388bc2350f48902ec6164cb18504f5b842ec9d69bc10b34');
 assert.equal(sha(objects[1].reference),'29ea385b669783f0776c870eb9d3bd40f416287836d3a8f88ccbb56949d3ba8c');
 assert.equal(sha(objects[1].zoom),'6701ffee0ef8d438814211732436a4c79c144864d909380220832323e0f37fb3');
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
 const budgets=[[2,3,3,2,2,2,2],[3,4,5,2,2,2,2]];
 const pan=Buffer.from([...Array.from({length:25},(_,i)=>Math.round(3*Math.sin(2*Math.PI*i/25))&255),...Array.from({length:25},(_,i)=>Math.round(2*Math.sin(4*Math.PI*i/25))&255)]);
 const frameAddresses=objects.flatMap(o=>o.frameAddresses);
 const absoluteIndex=Buffer.concat([Buffer.from(frameAddresses.map(a=>a&255)),Buffer.from(frameAddresses.map(a=>a>>8))]);
 const wave=Buffer.from(Array.from({length:1200},(_,i)=>Math.round(4.5+4.5*Math.sin(2*Math.PI*(Math.floor(i/48)/24+(i%48)/48)))));
 fs.mkdirSync(output,{recursive:true});
 const write=(n,b)=>fs.writeFileSync(path.join(output,n),b);
 for(const[n,b]of Object.entries({'movie.bin':movie,'rows.bin':movie,'movie-low.bin':lowMovie,'movie-high.bin':highMovie,'font.bin':font,'h-lut.bin':h,'v-lut.bin':v,'wave-ages.bin':wave,'frame-pointers-absolute.bin':absoluteIndex,'pan.bin':pan,'preparation-budgets.bin':Buffer.from(budgets.flat())}))write(n,b);
 write('pan-dx.bin',pan.subarray(0,25));write('pan-dy.bin',pan.subarray(25));
 for(const o of objects){
  write(`${o.name}-rows.bin`,o.rows);write(`${o.name}-frame-offsets16.bin`,o.index);write(`${o.name}-reference.frames`,o.reference);write(`${o.name}-learned.lut`,o.zoom);
  for(const[q,name]of ['tl','tr','bl','br'].entries())write(`${o.name}-zoom-${name}.bin`,Buffer.from(Array.from({length:256},(_,c)=>o.zoom[c*4+q])));
 }
 write('host-proof.py',HOST);
 write('main.asm',['.var lowMovieData=LoadBinary("movie-low.bin")','.var highMovieData=LoadBinary("movie-high.bin")',
  '.var absoluteIndexData=LoadBinary("frame-pointers-absolute.bin")','.var waveData=LoadBinary("wave-ages.bin")',
  '.var panData=LoadBinary("pan.bin")','.var budgetData=LoadBinary("preparation-budgets.bin")','.var fontData=LoadBinary("font.bin")','.var hData=LoadBinary("h-lut.bin")','.var vData=LoadBinary("v-lut.bin")',
  '.var zoomData=LoadBinary("star-learned.lut")','.var ballZoomData=LoadBinary("ball-learned.lut")',
  `.import source "${path.relative(output,path.join(here,'span-flash-player.asm')).split(path.sep).join('/')}"`,''].join('\n'));
 const c=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',output,'-o',path.join(output,'player.prg'),'-symbolfile','-vicesymbols'],{cwd:output,stdio:'inherit'});
 assert.equal(c.status,0,'Assembler failed');const program=fs.readFileSync(path.join(output,'player.prg'));
 const labels=Object.fromEntries([...fs.readFileSync(path.join(output,'main.sym'),'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-f]+)/gi)].map(m=>[m[1],parseInt(m[2],16)]));
 write('labels.json',JSON.stringify(labels,null,2)+'\n');
 const asset=o=>({id:o.id,name:o.name,rowsFile:`${o.name}-rows.bin`,frameOffsetsFile:`${o.name}-frame-offsets16.bin`,referenceFile:`${o.name}-reference.frames`,zoomLutFile:`${o.name}-learned.lut`,
  storedFrames:49,animatedPoses:48,originalPoseMap:[0,...Array.from({length:48},(_,i)=>i*2+1)],sourceStart:o.frameAddresses[0],sourceEnd:o.segments.at(-1).end,frameAddresses:o.frameAddresses,segments:o.segments,
  hashes:{rows:sha(o.rows),offsets:sha(o.index),reference:sha(o.reference),zoom:sha(o.zoom),font:sha(o.font)}});
 const sourceRegions=[{file:'movie-low.bin',start:0x5000,end:0x5000+lowMovie.length,sha256:sha(lowMovie)},
  {file:'movie-high.bin',start:0xe000,end:0xe000+highMovie.length,loadStart:labels.high_movie_staging,sha256:sha(highMovie)},
  {file:'frame-pointers-absolute.bin',start:labels.frame_pointer_low,end:labels.frame_pointer_low+196,sha256:sha(absoluteIndex),layout:'98lowbytesfollowedby98highbytes;49perobject'},
  {file:'h-lut.bin',start:labels.h_lut,end:labels.h_lut+256,sha256:sha(h)},{file:'v-lut.bin',start:labels.v_lut,end:labels.v_lut+256,sha256:sha(v)}];
 for(const o of objects)for(const q of ['tl','tr','bl','br']){
  const label=o.id?`zoom_ball_${q}_lut`:`zoom_${q}_lut`,file=`${o.name}-zoom-${q}.bin`;
  sourceRegions.push({file,start:labels[label],end:labels[label]+256,sha256:sha(fs.readFileSync(path.join(output,file)))});
 }
 const result={name:'span-star-ball-flash',objects:objects.map(asset),storedFrames:98,animatedPosesPerObject:48,
  nominalFps:25,nativeFps:null,minimumFieldsPerImage:2,startObject:0,startMode:0,startStep:0,modes:['normal','wave','checkerboard','vertical','horizontal','both','zoom'],
  phaseScript:Array.from({length:24},(_,step)=>({step,object:Math.floor(step/12),mode:step&1?6:Math.floor((step%12)/2),fields:step&1?25:501,palette:step%3,sourceStep:step&1?2:1})),baseDurationFields:501,flashDurationFields:25,preparationBudgets:budgets,transitionLookahead:'currentObjectModeBudget+nextObjectModeBudget-1',palettes:[{bg:15,border:15,fg:11},{bg:10,border:10,fg:4},{bg:13,border:13,fg:5}],
  nominalModeSeconds:501*19656/985248,nominalSequenceSeconds:6312*19656/985248,
  objectClock:'Eachobject48sourceposesrepeat;staroddoriginalposesdoublephysicalspeed. Objectlocalfilm_serial/frame/phaseadvances1/baseimageand2/flashimage;onlyfinalflash(step11/23)→othernormal0resetstopose1/serial1/phase1. No blankobjecthandoff. WASDcenterpersists.',
  geometry:{fullHeightModes:[0,1,2,4],centered192Modes:[3,5,6],fullHeightYScroll:3,centeredYScroll:7,
   vertical:{mode:3,sourceRows:12,sourceColumns:40,mirrorRow:'23-y',blankScreenRow:24,blackMarginsPixels:4},horizontal:{mode:4,sourceRows:25,sourceColumns:20,mirrorColumn:'39-x'},
   both:{mode:5,sourceRows:12,sourceColumns:20,mirrorRow:'23-y',mirrorColumn:'39-x',blankScreenRow:24,blackMarginsPixels:4},
   zoom:{mode:6,sourceRows:12,sourceColumns:20,outputRows:24,outputColumns:40,defaultCrop:[10,6],cropXRange:[0,20],cropYRange:[0,13],blankScreenRow:24,blackMarginsPixels:4}},
  zoom:{bytesPerObject:1024,quadrantOrder:['TL','TR','BL','BR'],cropOffsets:'zoom_x/yuserstate;latched_zoom_x/ypending;active_zoom_x/yfront',controls:'WASDallmodesadjustspersistentcenter;onlyflashimageryusesit. Immediatechange10fieldinitialhold4fieldrepeat;clampx0..20/y0..13;opposingkeyscancel',pan:{phases:25,dx:'round(3*sin(2*pi*p/25))',dy:'round(2*sin(4*pi*p/25))',phase:'entryflash0,else 25-mode_fields_leftclamped24',files:['pan-dx.bin','pan-dy.bin']},cia:'OwnedDC00ff/DC02ff/DC0300;FD/FBscanrestoresPRAff'},
  wave:{phases:48,formula:'round(4.5+4.5*sin(2*pi*(row/24+phase/48)))',phase:'objectLocalSerial%48',minimumHistorySerial:0},checker:{blockCharacters:4,A:'t',B:'max(0,t-24)',BParity:'((x>>2)^(y>>2))&1'},
  rowCache:{start:labels.row_cache,bytes:500,tables:10,rowsPerTable:25,pointerBytes:2,layout:'InterleavedabsoluteLE16row-headerpointers;slot*50+row*2',frameIds:labels.cache_frame_ids,validCount:labels.cache_table_count,slotContract:'0current;1tenages0..9;2current/age24;3..6directnocache'},
  payloadBytes:movie.length,physicalPayloadStorageBytes:lowMovie.length+highMovie.length,packingPaddingBytes:lowMovie.length+highMovie.length-movie.length,reservedIdleAddress:0x7fff,reservedIdleValue:0,pointerBytes:196,totalFilmBytes:movie.length+196,fontBytes:2048,lutBytes:2560,mirrorLutBytes:512,zoomLutBytes:2048,workScreenBytes:2048,waveLutBytes:1200,rowCacheBytes:500,historyImageBytes:0,
  codeRegionBytes:labels.player_code_end-0x1000,highStagingBytes:highMovie.length,zeroPageBytes:16,basicBytes:12,
  addresses:{code:0x1000,codeEnd:labels.player_code_end,highStaging:labels.high_movie_staging,highStagingEnd:labels.high_movie_staging_end,font:0x4000,screens:[0x4800,0x4c00],front:0x4800,hidden:0x4c00,source:0x5000,sourceEnd:0x5000+lowMovie.length,highSource:0xe000,highSourceEnd:0xe000+highMovie.length},
  sourceRegions,input,colorCommit:{foregroundCells:1024,onlyAtPhaseChange:true,unroll:16,iterations:64,deadlineRaster:51,scope:'SEIlowerborderafterfieldIRQ,fillthenBGborderandD018switchbeforenextactive51'},hashes:{program:sha(program),movie:sha(movie),font:sha(font),absoluteIndex:sha(absoluteIndex),hLut:sha(h),vLut:sha(v),wave:sha(wave)},
  memoryScope:'OnePRG,twoobjectssequentially,onefont,twooutputs,one500Bpool,nohistoryimages/decompression/copypriorframe. Wholeframesnevercrossreserved7fff=0norI/O;highblobstagedbelowfontandbootcopiedafter01=35. PRGloadendsbelowD000. Codeincludespointers/pool/LUTs/pan/budgets;highstagingandphysicalpackingpaddingcountedseparately;ColorRAMseparate.'};
 result.mainRamBytes=result.codeRegionBytes+result.highStagingBytes+result.physicalPayloadStorageBytes+2048+2048+16+12;result.colorRamCells=1024;
 const load=program.readUInt16LE(0);assert(load+program.length-2<=0xd000,'PRGmustnotloadI/Ogap');
 for(const r of sourceRegions){const address=r.loadStart??r.start;assert(program.subarray(2+address-load,2+address-load+r.end-r.start).equals(fs.readFileSync(path.join(output,r.file))),r.file);}
 write('build.json',JSON.stringify(result,null,2)+'\n');
 const proof=spawnSync('rtk',['proxy','python3',path.join(output,'host-proof.py'),output],{stdio:'inherit'});assert.equal(proof.status,0,'6502hostproof failed');
 console.log(JSON.stringify({output,sha256:result.hashes.program,mainRamBytes:result.mainRamBytes,highStagingBytes:result.highStagingBytes},null,2));return result;
}
module.exports={main};if(require.main===module)main();
