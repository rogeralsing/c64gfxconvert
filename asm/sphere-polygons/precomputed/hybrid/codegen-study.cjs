'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const common=require('./common.cjs'),fill=require('./fill.cjs').codecs,edges=[...require('./edges.cjs').codecs,...require('./edge-maps.cjs').codecs];
const HELPER_BASE=0x2800,INIT_BASE=0x2a00,CODE_BASE=0x3000;
const word=n=>Buffer.from([n&255,n>>>8]);
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');

function rowHelpers(){
 const out=[];
 for(const bank of[0x0c00,0x0400])for(let row=0;row<25;row++) {
  const address=bank+row*40;
  // STA absolute,Y; INY; DEX; BNE back seven bytes; RTS.
  out.push(0x99,address&255,address>>>8,0xc8,0xca,0xd0,0xf9,0x60);
 }
 assert.equal(out.length,400);return Uint8Array.from(out);
}

function clearScreens(){
 const out=[0xa9,0,0xa2,0];
 for(const page of[4,5,6,7,12,13,14,15])out.push(0x9d,0,page);
 out.push(0xe8,0xd0,0xe5,0x60);assert.equal(out.length,32);return Uint8Array.from(out);
}

function generateFrame(screen,index,{rows=false}={}){
 assert.equal(screen.length,1000);const selected=common.layouts.circle.indices,active=new Set(selected),groups=new Map();
 for(let cell=0;cell<1000;cell++)if(!active.has(cell))assert.equal(screen[cell],0,'Outside circle must start and remain black');
 for(const cell of selected){const glyph=screen[cell];if(!groups.has(glyph))groups.set(glyph,[]);groups.get(glyph).push(cell);}
 const bank=index&1?0x0400:0x0c00,out=[];let directStores=0,helperCalls=0;
 const store=cell=>{const address=bank+cell;out.push(0x8d,address&255,address>>>8);directStores++;};
 for(const glyph of Array.from(groups.keys()).sort((a,b)=>a-b)) {
  out.push(0xa9,glyph);const cells=groups.get(glyph);
  if(!rows){for(const cell of cells)store(cell);continue;}
  for(let first=0;first<cells.length;){
   const start=cells[first],row=Math.floor(start/40);let end=first+1;
   while(end<cells.length&&cells[end]===cells[end-1]+1&&Math.floor(cells[end]/40)===row)end++;
   const count=end-first;
   if(7<3*count){const helper=HELPER_BASE+((index&1)*25+row)*8;out.push(0xa2,count,0xa0,start%40,0x20,helper&255,helper>>>8);helperCalls++;}
   else for(let i=first;i<end;i++)store(cells[i]);
   first=end;
  }
 }
 out.push(0x60);return{bytes:Uint8Array.from(out),glyphGroups:groups.size,directStores,helperCalls,bank};
}

function archive(frames,{rows=false}={}){
 const generated=frames.map((screen,index)=>generateFrame(screen,index,{rows})),helpers=rows?rowHelpers():new Uint8Array(),init=clearScreens(),count=frames.length;
 // Three-byte file offsets are charged because the generated archive may be
 // larger than the C64 address space. A live loader/dispatcher is not provided.
 const header=Buffer.from([67,71,54,52,1,rows?1:0,count&255,count>>>8,helpers.length&255,helpers.length>>>8,3,init.length]),table=Buffer.alloc(count*3);
 let offset=header.length+helpers.length+init.length+table.length;
 for(let i=0;i<count;i++){table.writeUIntLE(offset,i*3,3);offset+=generated[i].bytes.length;}
 const bytes=Buffer.concat([header,Buffer.from(helpers),Buffer.from(init),table,...generated.map(g=>Buffer.from(g.bytes))]);assert.equal(bytes.length,offset);
 return{bytes,generated,frameCodeBytes:generated.reduce((sum,g)=>sum+g.bytes.length,0),helperBytes:helpers.length,initBytes:init.length,offsetTableBytes:table.length,headerBytes:header.length};
}

function hc64(frames){
 assert.equal(edges[5].name,'edges-map-raw-circle');const layout=common.layouts.circle;
 const parts=[Buffer.from([72,67,54,52,1,40,25,frames.length&255,frames.length>>>8,2,1,5]),Buffer.from(layout.metadata)];
 for(const frame of frames){const f=fill[1].encode(frame,layout.indices),e=edges[5].encode(frame);parts.push(word(f.length),word(e.length),Buffer.from(f),Buffer.from(e));}
 return Buffer.concat(parts);
}

function labelFile(filename){if(!fs.existsSync(filename))return null;return Object.fromEntries(Array.from(fs.readFileSync(filename,'utf8').matchAll(/\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)/g),m=>[m[1],parseInt(m[2],16)]));}
function decoderBudgets(){
 const player=path.join(__dirname,'player'),result=[];
 for(const name of['compact','fused','unrolled']) {
  const labels=labelFile(path.join(player,name,'build','main.sym'));if(!labels)continue;
  let control,layoutCode=0,lookup=0;
  if(name==='compact')control=labels.compact_code_end-labels.start;
  else if(name==='fused'){control=labels.control_end-labels.start;layoutCode=labels.kernels_end-0x9000;lookup=2048;}
  else{control=labels.core_end-labels.start;layoutCode=labels.unrolled_end-0x3000;lookup=labels.fill_tables_end-labels.fill_tables;}
  if(![control,layoutCode,lookup].every(Number.isFinite))continue;
  result.push({name,controlBytes:control,sharedLayoutCodeBytes:layoutCode,lookupBytes:lookup,decoderBytes:control+layoutCode+lookup,basicStubBytes:13});
 }
 return result;
}

const PYTHON=String.raw`import json,pathlib,statistics,hashlib,sys
from py65.devices.mpu6502 import MPU
manifest=json.loads(pathlib.Path(sys.argv[1]).read_text())
reference=pathlib.Path(manifest['reference']).read_bytes()
font=pathlib.Path(manifest['font']).read_bytes()
results=[]
for item in manifest['archives']:
 raw=pathlib.Path(item['file']).read_bytes()
 assert raw[:4]==b'CG64' and raw[4]==1 and raw[10]==3
 count=int.from_bytes(raw[6:8],'little');helper_size=int.from_bytes(raw[8:10],'little');init_size=raw[11]
 helpers=raw[12:12+helper_size];init=raw[12+helper_size:12+helper_size+init_size];table=12+helper_size+init_size
 offsets=[int.from_bytes(raw[table+i*3:table+i*3+3],'little') for i in range(count)]
 memory=[0xa5]*65536;memory[0x2000:0x2800]=font;memory[0x2800:0x2800+helper_size]=helpers
 memory[0x2a00:0x2a00+init_size]=init
 cpu=MPU(memory=memory);cycles=[];checked=0
 cpu.pc=0x2a00;cpu.sp=0xfd;memory[0x1fe]=0xff;memory[0x1ff]=1;before_init=cpu.processorCycles
 for instruction in range(100000):
  if cpu.pc==0x0200:break
  cpu.step()
 else:raise AssertionError('Generated screen initialization did not return')
 init_cycles=cpu.processorCycles-before_init
 for bank in[0x0400,0x0c00]:assert bytes(memory[bank:bank+1024])==bytes(1024)
 for sequence in range(count+1):
  frame=sequence%count;stop=offsets[frame+1] if frame+1<count else len(raw);code=raw[offsets[frame]:stop]
  memory[0x3000:0x3000+len(code)]=code
  target=0x0400 if frame&1 else 0x0c00;other=0x0c00 if frame&1 else 0x0400;before=bytes(memory[other:other+1000])
  cpu.pc=0x3000;cpu.sp=0xfd;memory[0x1fe]=0xff;memory[0x1ff]=1;started=cpu.processorCycles
  for instruction in range(100000):
   if cpu.pc==0x0200:break
   cpu.step()
  else:raise AssertionError('Generated routine did not return')
  expected=reference[frame*item['step']*1000:(frame*item['step']+1)*1000]
  assert bytes(memory[target:target+1000])==expected,(item['file'],frame)
  assert bytes(memory[other:other+1000])==before
  assert bytes(memory[0x2000:0x2800])==font
  assert bytes(memory[0x2800:0x2800+helper_size])==helpers
  cycles.append(cpu.processorCycles-started);checked+=1000
 results.append({'name':item['name'],'frames':count,'executions':count+1,'screenBytesChecked':checked,'wrapVerified':True,'initializationCyclesOnce':init_cycles,'cycles':{'min':min(cycles),'mean':statistics.mean(cycles),'max':max(cycles)}})
out={'pass':True,'measurement':'Assembled instruction execution only; no code load/overlay, VIC stalls, IRQs or presentation. Not native FPS.','results':results}
pathlib.Path(manifest['output']).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
`;

function study(){
 const corpus=common.getCorpus(),all=corpus.models.checker,outdir=path.join(__dirname,'build');fs.mkdirSync(outdir,{recursive:true});
 const reference=path.join(outdir,'codegen-reference-checker-256.bin');fs.writeFileSync(reference,Buffer.concat(all.map(frame=>Buffer.from(frame))));
 const report={pass:false,scope:'Bounded A/B generated-code size study; not a global macro optimum or live player',fontBytes:2048,inputHashes:corpus.inputHashes,archiveHeaderBytes:12,offsetBytesPerFrame:3,helperBase:HELPER_BASE,initializationBase:INIT_BASE,executionBase:CODE_BASE,decoders:decoderBudgets(),results:[]},archives=[];
 for(const step of[4,1]){
  const frames=all.filter((_,i)=>i%step===0),count=frames.length,movie=hc64(frames),movieFile=path.join(outdir,`codegen-hc64-checker-${count}.hc64`);fs.writeFileSync(movieFile,movie);
  require('./container.cjs').deserialize(movie).forEach((screen,i)=>assert.deepEqual(screen,frames[i],'HC64 comparison must decode the identical original-motion frame'));
  for(const rows of[false,true]){
   const name=rows?'shared-row-fill':'grouped-direct-sta',packed=archive(frames,{rows}),file=path.join(outdir,`codegen-${count}-${name}.bin`);fs.writeFileSync(file,packed.bytes);
   const sizes=packed.generated.map(g=>g.bytes.length),row={name,frames:count,step,archiveBytes:packed.bytes.length,frameCodeBytes:packed.frameCodeBytes,sharedHelperBytes:packed.helperBytes,sharedInitCodeBytes:packed.initBytes,offsetTableBytes:packed.offsetTableBytes,headerBytes:packed.headerBytes,minFrameCodeBytes:Math.min(...sizes),meanFrameCodeBytes:sizes.reduce((a,b)=>a+b,0)/count,maxFrameCodeBytes:Math.max(...sizes),directStores:packed.generated.reduce((sum,g)=>sum+g.directStores,0),helperCalls:packed.generated.reduce((sum,g)=>sum+g.helperCalls,0),hc64Bytes:movie.length,sizeRelativeToHc64:packed.bytes.length/movie.length,archiveSha256:sha(packed.bytes),file};
   row.hc64WithDecoder=report.decoders.map(d=>({name:d.name,bytes:movie.length+d.decoderBytes+d.basicStubBytes,generatedCodeDifference:packed.bytes.length-(movie.length+d.decoderBytes+d.basicStubBytes)}));
   report.results.push(row);archives.push({name:name+'-'+count,file,step});
  }
 }
 const pythonFile=path.join(outdir,'codegen-py65.py'),manifestFile=path.join(outdir,'codegen-execution.json'),proofFile=path.join(outdir,'codegen-py65-proof.json');fs.writeFileSync(pythonFile,PYTHON);fs.writeFileSync(manifestFile,JSON.stringify({reference,font:path.join(common.BASE,'assets/font.bin'),archives,output:proofFile},null,2)+'\n');
 const proof=spawnSync('rtk',['proxy','env','PYTHONPATH=/tmp/disco-sid-analysis-py65','python3',pythonFile,manifestFile],{encoding:'utf8'});
 if(proof.status!==0)throw Error(proof.stderr||proof.stdout||'py65 execution failed');report.nativeInstructionProof=JSON.parse(fs.readFileSync(proofFile,'utf8'));report.pass=true;
 const file=path.join(outdir,'codegen-report.json');fs.writeFileSync(file,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({pass:true,report:file,decoders:report.decoders,results:report.results,proof:report.nativeInstructionProof},null,2));return report;
}

module.exports={rowHelpers,clearScreens,generateFrame,archive,hc64,study};
if(require.main===module)study();
