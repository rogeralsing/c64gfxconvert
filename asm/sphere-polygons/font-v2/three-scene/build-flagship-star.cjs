'use strict';
// A separate opaque/binary scene pipeline. Existing font, codecs and player
// are reused; no glass, ball, transmission or outline controls are involved.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const {packMovie}=require('../build-scene-player.cjs');
const here=__dirname,parent=path.dirname(here),sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const json=file=>JSON.parse(fs.readFileSync(file)),write=(file,value)=>fs.writeFileSync(file,JSON.stringify(value,null,2)+'\n');

function main(argv=process.argv.slice(2)) {
  const options={};for(let i=0;i<argv.length;i++) {
    const [key,inline]=argv[i].split('=');assert(['--output','--characters','--font','--scene'].includes(key),'Unknown option '+key);
    if(key==='--characters'){assert(inline===undefined);options[key]=true;continue;}
    options[key]=inline??argv[++i];assert(options[key]);
  }
  const output=path.resolve(options['--output']||path.join(parent,'build/three-scene-flagship-star'));
  const source=path.resolve(options['--scene']||path.join(here,'demo-flagship-star.mjs'));
  const raw=path.join(output,'render'),preview=path.join(output,'preview');
  const verificationFile=path.join(output,'verification.json');
  function run(executable,file,args) {
    const result=spawnSync('rtk',['proxy',executable,path.join(parent,file),...args],{encoding:'utf8',maxBuffer:8*1024*1024});
    if(result.error)throw result.error;if(result.status!==0)throw Error(file+'\n'+result.stdout+result.stderr);
  }
  const node=(file,args)=>run(process.execPath,file,args),python=(file,args)=>run(process.env.PYTHON||'python3',file,args);
  fs.mkdirSync(output,{recursive:true});
  if(!options['--characters']) {
    node('three-scene/export.mjs',['--scene',source,'--output',raw,'--quantize','ordered','--write-rgba','--write-mask']);
    node('three-scene/verify-flagship-star.mjs',['--input',raw,'--output',verificationFile]);
    const result={pass:true,stage:'Flagship star bitmap only',characterConversionRun:false,verification:verificationFile,
      contact:path.join(output,'flagship-star-bitmap-contact.png'),gif:path.join(output,'flagship-star-bitmap.gif')};
    write(path.join(output,'pipeline.json'),result);console.log(JSON.stringify(result,null,2));return result;
  }
  assert(fs.existsSync(verificationFile),'Verify and inspect the opaque bitmap before character conversion.');
  const metadata=json(path.join(raw,'metadata.json')),verification=json(verificationFile);
  assert.equal(verification.pass,true);assert.equal(path.resolve(metadata.sceneSource),source);
  assert.equal(sha(fs.readFileSync(source)),metadata.sourceSha256);
  for(const dependency of metadata.sourceDependencies||[])assert.equal(sha(fs.readFileSync(dependency.source)),dependency.sha256);
  for(const [file,hash]of [[metadata.framesFile,metadata.hashes.frames],[metadata.rgbaFile,metadata.hashes.rgba],
    [metadata.objectMaskFile,metadata.hashes.objectMask]])assert.equal(sha(fs.readFileSync(path.join(raw,file))),hash);
  node('three-scene/verify-flagship-star.mjs',['--input',raw,'--output',verificationFile]);
  const proof=json(verificationFile),loop=proof.loop;
  assert.equal(loop.endpointMatchesStart,true);assert.equal(loop.unwrappedPeriodMatchesStart,true);
  const font=path.resolve(options['--font']||path.join(here,'universal-font.bin'));
  const fontBytes=fs.readFileSync(font);assert.equal(fontBytes.length,2048);
  const characters=path.join(output,'characters'),storage=path.join(output,'storage'),native=path.join(output,'native');
  node('bitmap-to-chars.cjs',['--frames',path.join(raw,metadata.framesFile),'--metadata',path.join(raw,'metadata.json'),
    '--output',characters,'--font',font,'--font-start-frame','0','--fixed-font']);
  assert(fs.readFileSync(path.join(characters,'font.bin')).equals(fontBytes));
  const scene=json(path.join(characters,'scene.json')),chars=json(path.join(characters,'metadata.json'));
  const loopMetadata={startFrame:loop.startFrame,frameCount:loop.frameCount};
  assert.equal(chars.verification.firstFrameEmpty,true);
  scene.loop=loopMetadata;chars.loop=loopMetadata;scene.introSeconds=chars.introSeconds=loop.startFrame/25;
  chars.verification.noClosingPatch=false;chars.verification.loopEndpointMatchesStart=true;
  chars.verification.loopUnwrappedPeriodMatchesStart=true;
  write(path.join(characters,'scene.json'),scene);write(path.join(characters,'metadata.json'),chars);
  const script=[{op:'play',startFrame:0,frameCount:loop.startFrame,repeat:1},
    {op:'play',startFrame:loop.startFrame,frameCount:loop.frameCount,repeat:'forever'},{op:'hold'}];
  const previewScript=script.map(command=>command.repeat==='forever'?{...command,repeat:2}:command);
  const scriptFile=path.join(characters,'playback.json'),previewScriptFile=path.join(characters,'playback-preview.json');
  write(scriptFile,script);write(previewScriptFile,previewScript);
  const auditFile=path.join(output,'character-audit.json');
  node('audit-bitmap-chars.cjs',['--frames',path.join(raw,metadata.framesFile),'--metadata',path.join(raw,'metadata.json'),
    '--characters',characters,'--mask',path.join(raw,metadata.objectMaskFile),'--output',auditFile]);
  const audit=json(auditFile);assert.equal(audit.pass,true);assert.equal(audit.objectMask.outputWhiteOutsideObject,0);
  assert.equal(audit.uniformTiles.failures.length,0,'Every full/empty source tile must remain exact');
  node('measure-scene.cjs',['--input='+characters,'--output='+storage,'--codec=literal']);
  const study=json(path.join(storage,'study.json'));
  node('build-scene-preview.cjs',['--scene-dir',characters,'--output-dir',preview,'--summary-file',path.join(storage,'study.json'),
    '--playback-script',previewScriptFile,'--scene-source',source,'--basename','flagship-star-c64']);
  python('export-scene-media.py',['--scene-dir',characters,'--output-dir',preview,'--playback-script',previewScriptFile,'--basename','flagship-star-c64']);
  python('three-scene/glass-compare.py',['--characters',characters,'--output',preview]);
  const comparison=path.join(preview,'flagship-star-source-comparison.png');
  fs.renameSync(path.join(preview,'glass-source-comparison.png'),comparison);
  let packing,build=null;
  try {
    const movie=fs.readFileSync(path.join(storage,'literal.bin')),index=json(path.join(storage,'literal-index.json'));
    const packed=packMovie(movie,index,0x1700);
    packing={fits:true,payloadBytes:movie.length,capacityBytes:packed.capacity,unusedBytes:packed.capacity-movie.length};
  }catch(error){packing={fits:false,payloadBytes:study.formats.literal.payloadBytes,reason:error.message};}
  if(packing.fits) {
    node('build-scene-player.cjs',['--input',storage,'--output',native,'--script',scriptFile,'--codec','literal']);
    build=json(path.join(native,'literal-front/build.json'));
    python('three-scene/glass-host-proof.py',['--native',path.join(native,'literal-front'),'--storage',storage]);
  }
  const result={pass:true,stage:build?'Flagship star character film and PRG':'Flagship film exceeds native RAM pools',
    characterConversionRun:true,nativeBuilt:Boolean(build),output,bitmapVerification:verificationFile,
    sourceSha256:metadata.sourceSha256,storedFrames:chars.frameCount,loop:loopMetadata,nominalFps:25,packing,
    staticFont:{file:font,glyphs:256,sha256:sha(fontBytes),modified:false},
    fullyFilledTilesExactlyPreserved:audit.uniformTiles.filled,emptyTilesExactlyPreserved:audit.uniformTiles.empty,
    quality:{activeBoundsPixelErrorFraction:audit.activeBounds.errorFraction,wholeFramePixelErrorFraction:audit.wholeImage.errorFraction,
      outputWhiteOutsideObject:0,nonuniformTileMeanPixelError:audit.nonuniformTiles.meanMismatchedPixels,audit:auditFile},
    ...(build?{program:path.join(native,'literal-front/player.prg'),programSha256:build.hashes.program,
      payloadBytes:build.payloadBytes,meaningfulLoadedBytes:build.meaningfulLoadedBytes,
      hostProof:path.join(native,'literal-front/host-proof.json')}:{}),
    html:path.join(preview,'flagship-star-c64.html'),gif:path.join(preview,'flagship-star-c64.gif'),comparison,nativeTimingMeasured:false};
  write(path.join(output,'pipeline.json'),result);write(path.join(output,'player-pipeline.json'),result);
  console.log(JSON.stringify(result,null,2));return result;
}
module.exports={main};
if(require.main===module)main();
