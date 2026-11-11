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
`;
function main(argv=process.argv.slice(2)){
 const opt=(n,d)=>{const i=argv.indexOf('--'+n);return i<0?d:argv[i+1];};
 const input=path.resolve(opt('input',path.join(here,'three-scene/results/flagship-star-row-film/original-pal-97')));
 const referencePath=path.resolve(opt('reference',path.join(here,'three-scene/results/flagship-star-ten-buffer/reference.frames')));
 const output=path.resolve(opt('output',path.join(here,'build/three-scene-flagship-star-span-mirror-texture')));
 const movie=fs.readFileSync(path.join(input,'rows.bin')),index=fs.readFileSync(path.join(input,'frame-offsets16.bin'));
 const font=fs.readFileSync(path.join(input,'font.bin')),reference=fs.readFileSync(referencePath);
 const study=JSON.parse(fs.readFileSync(path.join(input,'study.json')));
 assert.equal(movie.length,22882);assert.equal(index.length,194);
 assert.equal(sha(movie),study.hashes.rows);assert.equal(sha(index),study.hashes.frameOffsets16);
 assert.equal(sha(font),'1560bd74d24feb0684505f714c5b3e2854b352306efde79b89621ef959e629b1');
 assert.equal(sha(reference),'5c245453149adfa4bafd433efa50b606a614ff3264eac46f0c5a0906bc9b698c');
 const pop=Array.from({length:256},(_,n)=>n.toString(2).replaceAll('0','').length);
 const reverse=n=>parseInt(n.toString(2).padStart(8,'0').split('').reverse().join(''),2);
 const nearest=target=>{let best=0,error=65;for(let c=0;c<256;c++){let diff=0;for(let r=0;r<8;r++)diff+=pop[target[r]^font[c*8+r]];if(diff<error){best=c;error=diff;}}return best;};
 const h=Buffer.from(Array.from({length:256},(_,c)=>nearest(Array.from({length:8},(_,r)=>reverse(font[c*8+r])))));
 const v=Buffer.from(Array.from({length:256},(_,c)=>nearest(Array.from({length:8},(_,r)=>font[c*8+7-r]))));
 assert.equal(sha(h),'f172251c6f9f53fc97fca07c104228e19891e051745336023a5643371513dfaa');
 assert.equal(sha(v),'f61d85daa6c97d926bd9d2f81425d925460412142112d8e2c14430288646b502');
 const oldH=Buffer.from(h),oldV=Buffer.from(v);
 // Ordered dither describes a uniform tone in screen coordinates. Reflecting
 // its phase can make literal Hamming matching choose a solid diagonal glyph.
 // Recognize only complete canonical Bayer tone masks; preserve every other
 // glyph's existing geometric reflection and nearest-match fallback.
 const ranks=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5];
 const toneMasks=new Map();
 for(let level=0;level<=16;level++){
  const bitmap=Buffer.from(Array.from({length:8},(_,y)=>{
   let bits=0;for(let x=0;x<8;x++)if(ranks[(y>>1)*4+(x>>1)]<level)bits|=1<<(7-x);
   return bits;
  }));toneMasks.set(bitmap.toString('hex'),level);
 }
 const classified=[];
 for(let code=0;code<256;code++){
  const level=toneMasks.get(font.subarray(code*8,code*8+8).toString('hex'));
  if(level!==undefined){classified.push({code,level,oldH:oldH[code],oldV:oldV[code]});h[code]=code;v[code]=code;}
 }
 const expectedChanges=[193,200,205,206,216,220,228];
 const changedH=Array.from({length:256},(_,c)=>c).filter(c=>h[c]!==oldH[c]);
 const changedV=Array.from({length:256},(_,c)=>c).filter(c=>v[c]!==oldV[c]);
 assert.equal(classified.length,9);
 assert.deepEqual(changedH,expectedChanges);assert.deepEqual(changedV,expectedChanges);
 const nonuniform=classified.filter(({level})=>level>0&&level<16);
 const oldToneFailures=nonuniform.reduce((n,{code})=>n+Number(oldH[code]!==code)+Number(oldV[code]!==code),0);
 const newToneFailures=nonuniform.reduce((n,{code})=>n+Number(h[code]!==code)+Number(v[code]!==code),0);
 assert.equal(oldToneFailures,14);assert.equal(newToneFailures,0);
 for(let c=0;c<256;c++)if(!expectedChanges.includes(c)){assert.equal(h[c],oldH[c]);assert.equal(v[c],oldV[c]);}
 fs.mkdirSync(output,{recursive:true});
 for(const[n,b]of Object.entries({'rows.bin':movie,'movie.bin':movie,'frame-offsets16.bin':index,'font.bin':font,'reference.frames':reference,'h-lut.bin':h,'v-lut.bin':v}))fs.writeFileSync(path.join(output,n),b);
 fs.writeFileSync(path.join(output,'host-proof.py'),HOST);
 fs.writeFileSync(path.join(output,'main.asm'),['.var movieData=LoadBinary("rows.bin")','.var indexData=LoadBinary("frame-offsets16.bin")',
  '.var fontData=LoadBinary("font.bin")','.var hData=LoadBinary("h-lut.bin")','.var vData=LoadBinary("v-lut.bin")',
  `.import source "${path.relative(output,path.join(here,'span-mirror-player.asm')).split(path.sep).join('/')}"`,''].join('\n'));
 const c=spawnSync('rtk',['proxy',process.env.KICKASS||'/Users/rogerjohansson/.local/bin/kickass','main.asm','-odir',output,'-o',path.join(output,'player.prg'),'-symbolfile','-vicesymbols'],{cwd:output,stdio:'inherit'});
 assert.equal(c.status,0,'Assembler failed');const program=fs.readFileSync(path.join(output,'player.prg'));
 const labels=Object.fromEntries([...fs.readFileSync(path.join(output,'main.sym'),'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-f]+)/gi)].map(m=>[m[1],parseInt(m[2],16)]));
 fs.writeFileSync(path.join(output,'labels.json'),JSON.stringify(labels,null,2)+'\n');
 const absoluteIndex=Buffer.concat([Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))&255)),Buffer.from(Array.from({length:97},(_,i)=>(0x5000+index.readUInt16LE(i*2))>>8))]);
 fs.writeFileSync(path.join(output,'frame-pointers-absolute.bin'),absoluteIndex);
 const result={name:'span-mirror',storedFrames:97,nominalFps:25,nativeFps:null,minimumFieldsPerImage:2,
  geometry:{columns:40,rows:25,sourceTopLeftColumns:20,sourceTopLeftRows:12,mirroredRows:24,blankScreenRow:24,
   mirrorColumn:'39-x',mirrorRow:'23-y',yScroll:7,firstFetchRaster:55,visiblePixelTop:4,visiblePixelBottom:195,
   blackTopMarginPixels:4,blackBottomMarginPixels:4,verticalAxisPixels:100},
  glyphContract:'TL=c;TR=H[c];BL=V[c];BR=V[H[c]]. Two256BLUTs. Exactcanonical4x4Bayerthresholdmasks expanded2x2 preserveidentity(screen-anchor dither); everyotherglyphkeepsnearestHammingreflectionwithlowestcode tie. Fontunchanged; geometricapproximation accepted.',
  texturePolicy:{classifier:'Exact8x8 bitmap equality to Bayer4 threshold0..16 expanded2x2, canonicalphaseonly. No fuzzy/period/phase-shift matching.',bayerRanks:ranks,classified,changedH,changedV},
  sourceAccess:'Only12TLrowheaders andrawglyphsx<20are read. Remainderofeachoriginalrow is skipped arithmetically usingitslength. Wholeoriginalfilm/index remainunchanged.',
  payloadBytes:22882,pointerBytes:194,totalFilmBytes:23076,fontBytes:2048,lutBytes:512,workScreenBytes:2048,historyImageBytes:0,rowCacheBytes:0,
  codeRegionBytes:labels.player_code_end-0x1000,zeroPageBytes:14,basicBytes:12,
  addresses:{code:0x1000,codeEnd:labels.player_code_end,font:0x4000,screens:[0x4800,0x4c00],front:0x4800,hidden:0x4c00,source:0x5000,sourceEnd:0x5000+movie.length},
  sourceRegions:[{file:'rows.bin',start:0x5000,end:0x5000+movie.length,sha256:sha(movie)},
   {file:'frame-pointers-absolute.bin',start:labels.frame_pointer_low,end:labels.frame_pointer_low+194,sha256:sha(absoluteIndex),layout:'97lowbytesfollowedby97highbytes'},
   {file:'h-lut.bin',start:labels.h_lut,end:labels.h_lut+256,sha256:sha(h)},
   {file:'v-lut.bin',start:labels.v_lut,end:labels.v_lut+256,sha256:sha(v)}],
  hashes:{program:sha(program),movie:sha(movie),frameOffsets16:sha(index),font:sha(font),reference:sha(reference),hLut:sha(h),vLut:sha(v)},
  memoryScope:'Twooutputscreensonly;nocache/historyimages. Code regionincludes194Bframepointersand512BmirrorLUTs; donotcountthemtwice. SeparateColorRAM1024cells. Noidlebyteoverwriteorfontchange.'};
 result.mainRamBytes=result.codeRegionBytes+movie.length+2048+2048+14+12;result.colorRamCells=1024;
 const load=program.readUInt16LE(0);for(const r of result.sourceRegions)assert(program.subarray(2+r.start-load,2+r.end-load).equals(fs.readFileSync(path.join(output,r.file))),r.file);
 const baselinePath=path.resolve(opt('baseline',path.join(here,'build/three-scene-flagship-star-span-mirror/player.prg')));
 const baseline=fs.readFileSync(baselinePath);
 assert.equal(sha(baseline),'add6e800968b3520b4eb3ff1b098b350ddd1e09dee6af4115615c67fe1a79b5a');
 assert.equal(program.length,baseline.length);
 const allowed=new Map([...changedH.map(c=>[labels.h_lut+c,{axis:'H',code:c,old:oldH[c],next:h[c]}]),
  ...changedV.map(c=>[labels.v_lut+c,{axis:'V',code:c,old:oldV[c],next:v[c]}])]);
 const differences=[];
 for(let i=2;i<program.length;i++)if(program[i]!==baseline[i]){
  const address=load+i-2,expected=allowed.get(address);assert(expected,`Unexpected program difference at${address.toString(16)}`);
  assert.equal(baseline[i],expected.old);assert.equal(program[i],expected.next);
  differences.push({address,...expected});
 }
 assert.equal(differences.length,14);
 const regression={passed:true,baselinePath,oldProgramSha256:sha(baseline),newProgramSha256:sha(program),
  oldTonePolicyPassed:false,oldToneFailures,newTonePolicyPassed:true,newToneFailures,
  classifiedGlyphs:9,nonuniformToneGlyphs:7,unchangedEntriesPerLut:249,lutBytes:512,
  changedH,changedV,differences,allOtherProgramBytesUnchanged:true,
  rendererUnchanged:true,fontUnchanged:true,rowsUnchanged:true,frameIndexUnchanged:true,geometryUnchanged:true};
 fs.writeFileSync(path.join(output,'lut-regression.json'),JSON.stringify(regression,null,2)+'\n');
 fs.writeFileSync(path.join(output,'build.json'),JSON.stringify(result,null,2)+'\n');
 const proof=spawnSync('rtk',['proxy','python3',path.join(output,'host-proof.py'),output],{stdio:'inherit'});assert.equal(proof.status,0,'6502hostproof failed');
 console.log(JSON.stringify({output,sha256:result.hashes.program,mainRamBytes:result.mainRamBytes,lutBytes:512},null,2));return result;
}
module.exports={main};if(require.main===module)main();
