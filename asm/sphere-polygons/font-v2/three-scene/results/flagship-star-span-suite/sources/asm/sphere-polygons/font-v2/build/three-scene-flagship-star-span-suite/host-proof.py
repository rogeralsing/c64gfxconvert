import hashlib,json,math,pathlib,sys
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
def expected(serial,mode):
 out=bytearray(1000);f=pose(serial)
 if mode<3:
  for y in range(25):
   age=math.floor(4.5+4.5*math.sin(2*math.pi*(y/24+(serial%96)/96))+.5) if mode==1 else 0
   aa=pose(max(0,serial-age));bb=pose(max(0,serial-48))
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
 else:
  for y in range(12):
   for x in range(20):
    c=ref[f*1000+y*40+x];hc=h[c]
    out[y*40+x]=c;out[y*40+39-x]=hc
    out[(23-y)*40+x]=v[c];out[(23-y)*40+39-x]=v[hc]
 return bytes(out)
for address in(0x4800,0x4c00):m[address:address+1024]=bytes(1024)
m[l['film_frame']]=0;put16('film_serial',0);put16('field_counter',0)
m[l['mode']]=0;m[l['next_mode']]=0;put16('mode_fields_left',501);m[l['mode_due']]=0
m[l['front_screen_hi']]=0x48;m[l['back_screen_hi']]=0x4c;m[l['frame_wait_fields']]=2
m[0xfffe]=l['field_irq']&255;m[0xffff]=l['field_irq']>>8
assert all(expected(0,mode)==bytes(1000)for mode in range(6))
rawindex=(p/'frame-offsets16.bin').read_bytes()
front,back=0x4800,0x4c00;records=[];oldmode=0
sequence=[(serial,((serial-1)//250)%6)for serial in range(1,1502)]
sequence += [(1920+frame,mode)for mode in range(6)for frame in range(1,97)]
for i,(serial,mode) in enumerate(sequence):
 if i>=1501:
  oldmode=(mode+5)%6;m[l['mode']]=oldmode
  for a in(0x4800,0x4c00):m[a:a+1024]=bytes([0xa5])*1000+bytes(24)
 m[l['film_frame']]=pose(serial-1);put16('film_serial',serial-1)
 put16('mode_fields_left',0 if mode!=oldmode else 501);m[l['mode_due']]=int(mode!=oldmode)
 before=bytes(m[front:front+1024]);cpu.pc=l['prepare_start']
 setup=run('clear_start');clear=run('render_start',inject=True);render=run('render_end',inject=True)
 assert m[l['next_mode']]==mode and m[l['next_film_frame']]==pose(serial)
 assert bytes(m[back:back+1000])==expected(serial,mode),('image',i,serial,mode)
 count=1 if mode==0 else 10 if mode==1 else 2 if mode==2 else 0
 assert m[l['cache_table_count']]==count
 for slot in range(count):
  age=48 if mode==2 and slot else slot
  sourcepose=pose(max(0,serial-age))
  assert m[l['cache_frame_ids']+slot]==sourcepose
  offset=int.from_bytes(rawindex[sourcepose*2:sourcepose*2+2],'little')
  for row in range(25):
   addr=l['row_cache']+slot*50+row*2
   assert m[addr]+256*m[addr+1]==0x5000+offset,('cache',i,slot,row)
   offset+=2+movie[offset+1]
 assert bytes(m[back+1000:back+1024])==bytes(24)
 assert bytes(m[front:front+1024])==before
 assert bytes(m[0x4000:0x4800])==font and bytes(m[0x5000:0x5000+len(movie)])==movie
 assert bytes(m[l['h_lut']:l['h_lut']+256])==h and bytes(m[l['v_lut']:l['v_lut']+256])==v
 records.append(dict(serial=serial,pose=pose(serial),mode=mode,transition=mode!=oldmode,
  setupCpuCycles=setup,clearCpuCycles=clear,renderCpuCycles=render,totalCpuCycles=setup+clear+render))
 cpu.pc=l['commit_start'];run('presented');front,back=back,front;oldmode=mode
 assert m[l['mode']]==mode and m[l['film_frame']]==pose(serial)
 assert m[l['front_screen_hi']]==front>>8 and m[0xd018]==(0x20 if front==0x4800 else 0x30)
 assert m[0xd011]==(0x9f if mode in(3,5)else 0x9b)
result=dict(passed=True,imagesVerified=len(records)+1,nominalSixPhaseImagesVerified=1500,
 all97SourcePosesAllSixModesVerified=True,repeatTransitionVerified=True,injectedIrqs=irqcalls,
 irqRegistersAndStatusPreserved=True,frontUnchangedDuringPreparation=True,sourceFontAndLutsUnchanged=True,
 maximumPreparationCpuCycles=max(r['totalCpuCycles']for r in records),
 programSha256=hashlib.sha256(prg).hexdigest(),
 scope='Assembled6502 single-six-mode rawspan suite, cache/direct dispatch, axis/quadrant semantics andper-modeD011commit; noVIC/FPS claim.',records=records)
(p/'host-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items()if k!='records'},indent=2))
