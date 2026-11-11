import hashlib,json,pathlib,sys
sys.path.insert(0,'/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU
p=pathlib.Path(sys.argv[1]);l=json.loads((p/'labels.json').read_text());b=json.loads((p/'build.json').read_text())
prg=(p/'player.prg').read_bytes();ref=(p/'reference.frames').read_bytes();font=(p/'font.bin').read_bytes()
movie=(p/'rows.bin').read_bytes();h=(p/'h-lut.bin').read_bytes();v=(p/'v-lut.bin').read_bytes()
m=[0xa5]*65536;load=int.from_bytes(prg[:2],'little');m[load:load+len(prg)-2]=prg[2:]
cpu=MPU(memory=m);irqcycles=0;irqcalls=0;raw_reads=0
def run(label,inject=False):
 global irqcycles,irqcalls,raw_reads
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
def expected(pose):
 out=bytearray(1000)
 for y in range(12):
  for x in range(20):
   c=ref[pose*1000+y*40+x];hc=h[c]
   out[y*40+x]=c;out[y*40+39-x]=hc
   out[(23-y)*40+x]=v[c];out[(23-y)*40+39-x]=v[hc]
 return bytes(out)
for address in(0x4800,0x4c00):m[address:address+1024]=bytes(1024)
m[l['film_frame']]=0;m[l['film_serial']]=0;m[l['film_serial']+1]=0
m[l['front_screen_hi']]=0x48;m[l['back_screen_hi']]=0x4c
m[l['frame_wait_fields']]=2;m[l['field_counter']]=0;m[l['field_counter']+1]=0
m[0xfffe]=l['field_irq']&255;m[0xffff]=l['field_irq']>>8
assert expected(0)==bytes(1000)
front,back=0x4800,0x4c00;records=[]
for serial in range(1,290):
 pose=1+(serial-1)%96
 before=bytes(m[front:front+1024]);cpu.pc=l['prepare_start']
 setup=run('clear_start');clear=run('render_start',inject=True);render=run('render_end',inject=True)
 assert m[l['next_film_frame']]==pose
 assert bytes(m[back:back+1000])==expected(pose),('image',serial,pose)
 assert bytes(m[back+1000:back+1024])==bytes(24)
 assert bytes(m[front:front+1024])==before
 assert bytes(m[0x4000:0x4800])==font
 assert bytes(m[0x5000:0x5000+len(movie)])==movie
 assert bytes(m[l['h_lut']:l['h_lut']+256])==h and bytes(m[l['v_lut']:l['v_lut']+256])==v
 records.append(dict(serial=serial,pose=pose,setupCpuCycles=setup,clearCpuCycles=clear,renderCpuCycles=render,totalCpuCycles=setup+clear+render))
 cpu.pc=l['commit_start'];run('presented');front,back=back,front
 assert m[l['film_frame']]==pose and m[l['front_screen_hi']]==front>>8
 assert m[0xd018]==(0x20 if front==0x4800 else 0x30)
result=dict(passed=True,imagesVerified=290,implicitBlankVerified=True,uniqueSourceFramesVerified=97,
 loopClosingsVerified=3,injectedIrqs=irqcalls,irqRegistersAndStatusPreserved=True,
 frontUnchangedDuringPreparation=True,sourceFontAndLutsUnchanged=True,
 maximumPreparationCpuCycles=max(r['totalCpuCycles'] for r in records),
 programSha256=hashlib.sha256(prg).hexdigest(),
 scope='Assembled6502 directTLspan reads andfour glyph writes. Host proves charactercells; native proof must verifyYSCROLL7 plus4pxmargins and actualFPS.',records=records)
(p/'host-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
