import json,math,pathlib,sys,hashlib,statistics
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
