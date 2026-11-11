'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const here=__dirname,sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const HOST=String.raw`import hashlib,json,math,pathlib,sys
sys.path.insert(0,'/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU
p=pathlib.Path(sys.argv[1]);l=json.loads((p/'labels.json').read_text());b=json.loads((p/'build.json').read_text())
prg=(p/'player.prg').read_bytes();ref=(p/'reference.frames').read_bytes();font=(p/'font.bin').read_bytes()
movie=(p/'rows.bin').read_bytes();h=(p/'h-lut.bin').read_bytes();v=(p/'v-lut.bin').read_bytes()
zoom=(p/'learned.lut').read_bytes()
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
def pose(t):return 0 if t<=0 else 1+(t-1)%96
def expected(serial,mode,crop=(10,6)):
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
for address in(0x4800,0x4c00):m[address:address+1024]=bytes(1024)
m[l['film_frame']]=0;put16('film_serial',0);put16('field_counter',0)
m[l['mode']]=6;m[l['next_mode']]=6;put16('mode_fields_left',501);m[l['mode_due']]=0
m[l['front_screen_hi']]=0x48;m[l['back_screen_hi']]=0x4c;m[l['frame_wait_fields']]=2
m[0xfffe]=l['field_irq']&255;m[0xffff]=l['field_irq']>>8
m[0xdc00]=255;m[0xdc02]=255;m[0xdc03]=0;m[l['keyboard_previous']]=0
assert all(expected(0,mode)==bytes(1000)for mode in range(7))
rawindex=(p/'frame-offsets16.bin').read_bytes()
front,back=0x4800,0x4c00;records=[];oldmode=6;order=[6,0,1,2,3,4,5]
sequence=[(serial,order[((serial-1)//250)%7],(10,6))for serial in range(1,1752)]
sequence += [(1920+frame,mode,crop)for mode in range(7)for crop in ([(10,6),(0,0),(20,0),(0,13),(20,13)]if mode==6 else[(10,6)])for frame in range(1,97)]
for i,(serial,mode,crop) in enumerate(sequence):
 if i>=1751:
  oldmode=(mode+6)%7;m[l['mode']]=oldmode
  for a in(0x4800,0x4c00):m[a:a+1024]=bytes([0xa5])*1000+bytes(24)
 m[l['film_frame']]=pose(serial-1);put16('film_serial',serial-1)
 m[l['zoom_x']],m[l['zoom_y']]=crop;m.keys=set()
 put16('mode_fields_left',0 if mode!=oldmode else 501);m[l['mode_due']]=int(mode!=oldmode)
 before=bytes(m[front:front+1024]);cpu.pc=l['prepare_start']
 setup=run('clear_start');clear=run('render_start',inject=True);render=run('render_end',inject=True)
 assert m[l['next_mode']]==mode and m[l['next_film_frame']]==pose(serial)
 assert bytes(m[back:back+1000])==expected(serial,mode,crop),('image',i,serial,mode,crop)
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
 for q,name in enumerate(['zoom_tl_lut','zoom_tr_lut','zoom_bl_lut','zoom_br_lut']):
  assert bytes(m[l[name]:l[name]+256])==zoom[q::4]
 records.append(dict(serial=serial,pose=pose(serial),mode=mode,transition=mode!=oldmode,
  crop=list(crop),setupCpuCycles=setup,clearCpuCycles=clear,renderCpuCycles=render,totalCpuCycles=setup+clear+render))
 cpu.pc=l['commit_start'];run('presented');front,back=back,front;oldmode=mode
 assert m[l['mode']]==mode and m[l['film_frame']]==pose(serial)
 assert m[l['front_screen_hi']]==front>>8 and m[0xd018]==(0x20 if front==0x4800 else 0x30)
 assert m[0xd011]==(0x9f if mode in(3,5,6)else 0x9b)
 if mode==6:assert(m[l['active_zoom_x']],m[l['active_zoom_y']])==crop
# Exercise the real 501-field IRQ countdown and select-next wrap independently
# of the image probes, whose presentation clock is intentionally synthetic.
l['host_return']=0x0300
def call(name,inject=False):
 cpu.stPushWord(0x02ff);cpu.pc=l[name];return run('host_return',inject)
for mode in range(7):
 m[l['mode']]=mode;call('reset_mode_clock');put16('field_counter',0)
 for field in range(1,502):
  cpu.pc=l['host_return'];cpu.p&=~4;cpu.irq();run('host_return')
  assert m[l['mode_due']]==int(field==501)
  assert m[l['mode_fields_left']]+256*m[l['mode_fields_left']+1]==501-field
 for left in(6,5,1,0):
  put16('mode_fields_left',left);call('select_next')
  assert m[l['next_mode']]==((mode+1)%7 if left<=5 else mode)
# Read real CIA matrix rows through a small pin-level bus model. No test-only
# hooks in the player: invoke its actual foreground scanner and IRQ paths.
for mode in range(6):
 m[l['mode']]=mode;put16('mode_fields_left',501);m[l['mode_due']]=0
 m[l['zoom_x']]=10;m[l['zoom_y']]=6;m[l['keyboard_previous']]=0;m.keys={'D'}
 cpu.pc=l['prepare_start'];run('keyboard_end',True)
 assert(m[l['zoom_x']],m[l['zoom_y']])==(10,6),'Input must not affect anothermode'
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
result=dict(passed=True,imagesVerified=len(records)+1,nominalSevenPhaseImagesVerified=1750,
 all97SourcePosesAllSevenModesVerified=True,zoom96PosesAtDefaultAndFourCorners=True,
 allSevenMode501FieldCountdownsAndWrapVerified=True,keyboardMatrixClampAndRepeatCases=key_cases,
 keyboardIgnoredInOtherSixModes=True,
 repeatTransitionVerified=True,injectedIrqs=irqcalls,
 irqRegistersAndStatusPreserved=True,frontUnchangedDuringPreparation=True,sourceFontAndLutsUnchanged=True,
 maximumPreparationCpuCycles=max(r['totalCpuCycles']for r in records),
 programSha256=hashlib.sha256(prg).hexdigest(),
 scope='Assembled6502 seven-mode rawspan suite, baseline semanticzoom, CIAWASD scanner/clamp/repeat, crop-latching andper-modeD011commit; noVIC/FPS claim.',records=records)
(p/'host-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items()if k!='records'},indent=2))
`;
function main(argv=process.argv.slice(2)){
 const opt=(n,d)=>{const i=argv.indexOf('--'+n);return i<0?d:argv[i+1];};
 const input=path.resolve(opt('input',path.join(here,'three-scene/results/flagship-star-row-film/original-pal-97')));
 const referencePath=path.resolve(opt('reference',path.join(here,'three-scene/results/flagship-star-ten-buffer/reference.frames')));
 const output=path.resolve(opt('output',path.join(here,'build/three-scene-flagship-star-span-zoom')));
 const lutSource=path.join(here,'three-scene/results/flagship-star-span-mirror-texture');
 const movie=fs.readFileSync(path.join(input,'rows.bin')),index=fs.readFileSync(path.join(input,'frame-offsets16.bin'));
 const font=fs.readFileSync(path.join(input,'font.bin')),reference=fs.readFileSync(referencePath);
 const wave=Buffer.from(Array.from({length:2400},(_,i)=>Math.round(4.5+4.5*Math.sin(2*Math.PI*(Math.floor(i/96)/24+(i%96)/96)))));
 const h=fs.readFileSync(path.join(lutSource,'h-lut.bin')),v=fs.readFileSync(path.join(lutSource,'v-lut.bin'));
 const zoomSource=path.join(here,'three-scene/results/char-zoom-study/learned.lut');
 const zoom=fs.readFileSync(zoomSource);
 const study=JSON.parse(fs.readFileSync(path.join(input,'study.json')));
 assert.equal(movie.length,22882);assert.equal(index.length,194);assert.equal(h.length+v.length,512);
 assert.equal(sha(movie),study.hashes.rows);assert.equal(sha(index),study.hashes.frameOffsets16);
 assert.equal(sha(font),'1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1');
 assert.equal(sha(reference),'5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c');
 assert.equal(sha(h),'8758e99a0a12a3295a674c3a806a3ca9160ee11b837493e9ca65d8f4d3f09ba8');
 assert.equal(sha(v),'7bd4a003ad2078ef6dcaa1fed00d230f17e8089575c4f356b5b91bc36f278234');
 assert.equal(sha(zoom),'37efc20a89731ff3a6b745bfb5e4083947649774b2fe63b56f0c2a4340b2dc21');
 assert(zoom.subarray(0,4).equals(Buffer.alloc(4)),'Blanksourceglyph must stay blank afterzoom');
 fs.mkdirSync(output,{recursive:true});
 for(const[n,b]of Object.entries({'rows.bin':movie,'movie.bin':movie,'frame-offsets16.bin':index,'font.bin':font,'reference.frames':reference,'h-lut.bin':h,'v-lut.bin':v,'wave-ages.bin':wave,'learned.lut':zoom}))fs.writeFileSync(path.join(output,n),b);
 for(const[q,name]of ['tl','tr','bl','br'].entries())fs.writeFileSync(path.join(output,`zoom-${name}.bin`),Buffer.from(Array.from({length:256},(_,c)=>zoom[c*4+q])));
 fs.writeFileSync(path.join(output,'host-proof.py'),HOST);
 fs.writeFileSync(path.join(output,'main.asm'),['.var movieData=LoadBinary("rows.bin")','.var indexData=LoadBinary("frame-offsets16.bin")',
  '.var waveData=LoadBinary("wave-ages.bin")','.var fontData=LoadBinary("font.bin")','.var hData=LoadBinary("h-lut.bin")','.var vData=LoadBinary("v-lut.bin")','.var zoomData=LoadBinary("learned.lut")',
  `.import source "${path.relative(output,path.join(here,'span-zoom-player.asm')).split(path.sep).join('/')}"`,''].join('\n'));
 const c=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',output,'-o',path.join(output,'player.prg'),'-symbolfile','-vicesymbols'],{cwd:output,stdio:'inherit'});
 assert.equal(c.status,0,'Assembler failed');const program=fs.readFileSync(path.join(output,'player.prg'));
 const labels=Object.fromEntries([...fs.readFileSync(path.join(output,'main.sym'),'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-f]+)/gi)].map(m=>[m[1],parseInt(m[2],16)]));
 fs.writeFileSync(path.join(output,'labels.json'),JSON.stringify(labels,null,2)+'\n');
 const absoluteIndex=Buffer.concat([Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))&255)),Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))>>8))]);
 fs.writeFileSync(path.join(output,'frame-pointers-absolute.bin'),absoluteIndex);
 const result={name:'span-zoom',storedFrames:97,nominalFps:25,nativeFps:null,minimumFieldsPerImage:2,
  modes:['normal','wave','checkerboard','vertical','horizontal','both','zoom'],startMode:6,modeOrder:[6,0,1,2,3,4,5],modeDurationFields:501,modeLookaheadFields:5,
  nominalModeSeconds:501*19656/985248,nominalSequenceSeconds:3507*19656/985248,
  geometry:{fullHeightModes:[0,1,2,4],centered192Modes:[3,5,6],fullHeightYScroll:3,centeredYScroll:7,
   vertical:{mode:3,sourceRows:12,sourceColumns:40,mirrorRow:'23-y',blankScreenRow:24,blackMarginsPixels:4},
   horizontal:{mode:4,sourceRows:25,sourceColumns:20,mirrorColumn:'39-x',blankScreenRow:null},
   both:{mode:5,sourceRows:12,sourceColumns:20,mirrorRow:'23-y',mirrorColumn:'39-x',blankScreenRow:24,blackMarginsPixels:4},
   zoom:{mode:6,sourceRows:12,sourceColumns:20,outputRows:24,outputColumns:40,defaultCrop:[10,6],cropXRange:[0,20],cropYRange:[0,13],blankScreenRow:24,blackMarginsPixels:4}},
  glyphContract:'Modes0..5 retainaccepted behavior. Zoom6 maps each originalrawsourcechar toTL/TR/BL/BR fromMATCHEDbaselinelearned1024BLUT; nofontorfilmchange. Fourdeinterleavedaligned256Bpages.',
  timingContract:'SevenmodesinONESINGLEPRG,start6then0..5repeat6. Globalfilm_serial continues;poses1..96repeat. Eachmode501PALfields,5-fieldlookahead,lowerborderD011+D018commit. ActualFPSandtimingnativemeasured.',
  zoom:{source:zoomSource,bytes:1024,sha256:sha(zoom),quadrantOrder:['TL','TR','BL','BR'],cropOffsets:'zoom_x/yuserstate;latched_zoom_x/ypendinghiddenimage;active_zoom_x/yfrontimage',
   controls:'WASDonlymode6;Wup,Aleft,Sdown,Dright. Clampx0..20,y0..13. Immediatekeychange,10PALfieldinitialhold,4fieldrepeat. Opposingkeys cancel.',
   cia:'OwnedidleDC00=ff,DC02=ff,DC03=00 initializedonce; scannerselectsFD/FBandrestoresPRAff; noKERNAL/otherinputconsumer.'},
  wave:{phases:96,formula:'round(4.5+4.5*sin(2*pi*(row/24+phase/96)))',phase:'serial%96',minimumHistorySerial:0},
  checker:{blockCharacters:4,A:'t',B:'max(0,t-48)',BParity:'((x>>2)^(y>>2))&1'},
  rowCache:{start:labels.row_cache,bytes:500,tables:10,rowsPerTable:25,pointerBytes:2,layout:'InterleavedabsoluteLE16row-headerpointers;slot*50+row*2',frameIds:labels.cache_frame_ids,validCount:labels.cache_table_count,
   slotContract:'Mode0onecurrenttable;mode1tenages0..9;mode2currentandage48. Modes3/4/5/6directheaders,validcount0. ONE500Bpoolreused.'},
  payloadBytes:22882,pointerBytes:194,totalFilmBytes:23076,fontBytes:2048,lutBytes:1536,mirrorLutBytes:512,zoomLutBytes:1024,workScreenBytes:2048,waveLutBytes:2400,historyImageBytes:0,rowCacheBytes:500,
  codeRegionBytes:labels.player_code_end-0x1000,zeroPageBytes:16,basicBytes:12,
  addresses:{code:0x1000,codeEnd:labels.player_code_end,font:0x4000,screens:[0x4800,0x4c00],front:0x4800,hidden:0x4c00,source:0x5000,sourceEnd:0x5000+movie.length},
  sourceRegions:[{file:'rows.bin',start:0x5000,end:0x5000+movie.length,sha256:sha(movie)},
   {file:'frame-pointers-absolute.bin',start:labels.frame_pointer_low,end:labels.frame_pointer_low+194,sha256:sha(absoluteIndex),layout:'97lowbytesfollowedby97highbytes'},
   {file:'h-lut.bin',start:labels.h_lut,end:labels.h_lut+256,sha256:sha(h)},
   {file:'v-lut.bin',start:labels.v_lut,end:labels.v_lut+256,sha256:sha(v)},
   ...['tl','tr','bl','br'].map(q=>({file:`zoom-${q}.bin`,start:labels[`zoom_${q}_lut`],end:labels[`zoom_${q}_lut`]+256,sha256:sha(fs.readFileSync(path.join(output,`zoom-${q}.bin`)))}))],
  lutSource,hashes:{program:sha(program),movie:sha(movie),frameOffsets16:sha(index),font:sha(font),reference:sha(reference),hLut:sha(h),vLut:sha(v),wave:sha(wave),zoom:sha(zoom)},
  memoryScope:'Singleplayer,twooutputscreens,one500Bpool,nohistory/canonicalimagesorpreviousframecopy. Coderegionincludespool/frameindex/LUTs/wavetable;donotdoublecount. ColorRAMseparate1024cells.'};
 result.mainRamBytes=result.codeRegionBytes+movie.length+2048+2048+16+12;result.colorRamCells=1024;
 const load=program.readUInt16LE(0);for(const r of result.sourceRegions)assert(program.subarray(2+r.start-load,2+r.end-load).equals(fs.readFileSync(path.join(output,r.file))),r.file);
 fs.writeFileSync(path.join(output,'build.json'),JSON.stringify(result,null,2)+'\n');
 const proof=spawnSync('rtk',['proxy','python3',path.join(output,'host-proof.py'),output],{stdio:'inherit'});assert.equal(proof.status,0,'6502hostproof failed');
 console.log(JSON.stringify({output,sha256:result.hashes.program,mainRamBytes:result.mainRamBytes},null,2));return result;
}
module.exports={main};if(require.main===module)main();
