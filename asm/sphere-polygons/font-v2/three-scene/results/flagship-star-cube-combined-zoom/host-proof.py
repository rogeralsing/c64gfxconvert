import hashlib,json,math,pathlib,sys
sys.path.insert(0,'/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU
p=pathlib.Path(sys.argv[1]);l=json.loads((p/'labels.json').read_text());b=json.loads((p/'build.json').read_text())
prg=(p/'player.prg').read_bytes();font=(p/'font.bin').read_bytes()
refs=[(p/o['referenceFile']).read_bytes()for o in b['objects']]
raws=[(p/o['rowsFile']).read_bytes()for o in b['objects']]
indices=[(p/o['frameOffsetsFile']).read_bytes()for o in b['objects']]
zooms=[(p/o['zoomLutFile']).read_bytes()for o in b['objects']]
h=(p/'h-lut.bin').read_bytes();v=(p/'v-lut.bin').read_bytes()
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
def expected(obj,serial,mode,blank=(),crop=(10,6)):
 out=bytearray(1000);f=pose(serial)
 def glyph(o,frame,y,x):return 0 if o in blank else refs[o][frame*1000+y*40+x]
 if mode in(0,1,2,7):
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
 elif mode==6:
  xx,yy=crop
  for y in range(12):
   for x in range(20):
    c=glyph(obj,f,y+yy,x+xx)
    for q in range(4):out[(y*2+(q>>1))*40+x*2+(q&1)]=zooms[obj][c*4+q]
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
m[0xdc00]=255;m[0xdc02]=255;m[0xdc03]=0;m[l['keyboard_previous']]=0
assert m[0x7fff]==0
front,back=0x4800,0x4c00;records=[];cases=[]
oldstep,oldserial=0,0
for step in list(range(28))+[0]:
 obj,mode=script(step);oldobj,_=script(oldstep);serial=1 if obj!=oldobj else oldserial+1
 cases.append((step,serial,oldstep,oldserial,'sequence',(10,6)));oldstep,oldserial=step,serial
for obj in range(2):
 for mode in range(7):
  step=obj*12+(1 if mode==6 else mode*2)
  for center in([(10,6),(0,0),(20,0),(0,13),(20,13)]if mode==6 else[(10,6)]):
   for frame in range(1,49):
    serial=96+frame;cases.append((step,serial,step,serial-1,'pose',center))
 for mode in(1,2):
  for serial in range(1,25):cases.append((obj*12+mode*2,serial,obj*12+mode*2,serial-1,'history',(10,6)))
for step in(24,26):
 for frame in range(1,49):cases.append((step,96+frame,step,95+frame,'mixedpose',(10,6)))
for i,(step,serial,oldstep,oldserial,kind,center)in enumerate(cases):
 obj,mode=script(step);oldobj,oldmode=script(oldstep);transition=step!=oldstep
 m[l['zoom_x']],m[l['zoom_y']]=center;m.keys=set();m[l['keyboard_previous']]=0
 if mode==6 and not transition:m[l['flash_crop_x']],m[l['flash_crop_y']]=center
 m[l['object_id']]=oldobj;m[l['mode']]=oldmode;m[l['step_index']]=oldstep
 m[l['film_frame']]=pose(oldserial);put16('film_serial',oldserial)
 put16('mode_fields_left',0 if transition else duration(step));m[l['mode_due']]=int(transition)
 oldbg,oldfg=palette(oldstep);m[0xd020]=oldbg;m[0xd021]=oldbg;m[0xd800:0xdc00]=colors(oldstep)
 m[l['active_bg']]=oldbg;m[l['active_fg']]=oldfg;m[l['active_palette_index']]=oldstep%3;m[l['active_color_pattern']]=int(oldmode in(2,7))
 before=bytes(m[front:front+1024]);cpu.pc=l['prepare_start']
 setup=run('clear_start');clear=run('render_start',True);render=run('render_end',True)
 assert(m[l['next_step']],m[l['next_object']],m[l['next_mode']],m[l['next_film_frame']])==(step,obj,mode,pose(serial))
 assert m[l['next_serial']]+256*m[l['next_serial']+1]==serial
 crop=(m[l['latched_zoom_x']],m[l['latched_zoom_y']])
 if mode==6 and transition:
  ordinal=step//2;dx=([0,-3,2,-1,3,-2]*3)[:14];dy=([0,-2,0,2,-1,1]*3)[:14]
  assert crop==(max(0,min(20,center[0]+dx[ordinal])),max(0,min(13,center[1]+dy[ordinal])))
 else:assert crop==center
 assert m[l['source_step']]==1
 assert bytes(m[back:back+1000])==expected(obj,serial,mode,crop=crop),('image',i,step,serial,mode)
 count=1 if mode==0 else 10 if mode==1 else 2 if mode in(2,7)else 0
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
 assert m[0xd011]==(0x9f if mode in(3,5,6,8)else 0x9b)
 bg,fg=palette(step)
 assert(m[l['active_palette_index']],m[l['active_bg']],m[l['active_fg']],m[l['active_color_pattern']])==(step%3,bg,fg,int(mode in(2,7)))
 assert m[0xd020]==bg and m[0xd021]==bg and bytes(m[0xd800:0xdc00])==colors(step)
 if mode in(3,5,6,8):assert bytes(m[front+960:front+1000])==bytes(40)
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
  assert m[l['next_serial']]+256*m[l['next_serial']+1]==(1 if co!=obj else 124)
  assert m[l['source_step']]==1
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
# Fixed entry crops remain stable through everyflashfield despitecenterchanges.
for ordinal in range(14):
 step=ordinal*2+1;center=(10,6);dx=([0,-3,2,-1,3,-2]*3)[:14];dy=([0,-2,0,2,-1,1]*3)[:14]
 m[l['zoom_x']],m[l['zoom_y']]=center;m[l['next_mode']]=6;m[l['step_index']]=step-1;m[l['next_step']]=step
 call('latch_flash_crop',True)
 fixed=(max(0,min(20,center[0]+dx[ordinal])),max(0,min(13,center[1]+dy[ordinal])))
 assert(m[l['flash_center_x']],m[l['flash_center_y']])==center
 assert(m[l['flash_crop_x']],m[l['flash_crop_y']])==fixed
 for elapsed in range(25):
  m[l['step_index']]=step;put16('mode_fields_left',25-elapsed)
  m[l['zoom_x']]=(elapsed*3)%21;m[l['zoom_y']]=(elapsed*5)%14;call('latch_flash_crop',True)
  assert(m[l['flash_crop_x']],m[l['flash_crop_y']],m[l['latched_zoom_x']],m[l['latched_zoom_y']])==fixed+fixed
  assert(m[l['flash_center_x']],m[l['flash_center_y']])==center
 nextstep=((ordinal+1)%14)*2+1;nextordinal=nextstep//2
 m[l['next_step']]=nextstep;newcenter=(m[l['zoom_x']],m[l['zoom_y']]);call('latch_flash_crop')
 assert(m[l['flash_center_x']],m[l['flash_center_y']])==newcenter
 assert(m[l['flash_crop_x']],m[l['flash_crop_y']])==(max(0,min(20,newcenter[0]+dx[nextordinal])),max(0,min(13,newcenter[1]+dy[nextordinal])))
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
result=dict(passed=True,imagesVerified=len(records)+1,all48PosesBothObjectsExistingModes=True,all48PosesBothMixedModes=True,mixedBlankCases=blankCases,all28Phase501Or25FieldCountdownsAndWrapVerified=True,zoomSourceStep1NormalClockAndWrapVerified=True,zoomAll48PosesDefaultAndFourCorners=True,fixedCropAll25FieldsDespiteManualChanges=True,nextFlashUsesCurrentCenter=True,keyboardMatrixClampRepeatVerified=True,mixedCheckerPurpleGreen1024ParityVerified=True,mixedQuadrantsDiagonalHVCompositionVerified=True,allPalettesAndUniformRestoreVerified=True,preparationBudgetBoundsVerified=True,highPayloadBootCopyVerified=True,bootCopyCpuCycles=bootCopyCycles,reserved7fffByteRemainsZero=True,prgLoadAvoidsIoGap=True,repeatTransitionVerified=True,injectedIrqs=irqcalls,irqRegistersAndStatusPreserved=True,frontUnchangedDuringPreparation=True,sourceFontUnchanged=True,maximumPreparationCpuCycles=max(r['totalCpuCycles']for r in records),programSha256=hashlib.sha256(prg).hexdigest(),scope='Assembled6502 28phase rawspan player;normal-speed2xzoomflashes,synchronousmixedchecker,diagonalmixedquadrants,fixedentrycrops/WASD; noVIC/FPSclaim.',records=records)
(p/'host-proof.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items()if k!='records'},indent=2))
