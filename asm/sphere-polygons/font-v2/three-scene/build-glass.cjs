'use strict';

// Keep bitmap inspection and character packing as separate explicit stages.
// The approved bitmap is matched to the already shipped immutable 256-glyph
// font, then played by the existing literal-delta decoder without opcode edits.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const {packMovie}=require('../build-scene-player.cjs');
const here=__dirname,parent=path.dirname(here);
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const json=file=>JSON.parse(fs.readFileSync(file));
const write=(file,value)=>fs.writeFileSync(file,JSON.stringify(value,null,2)+'\n');

function main(argv=process.argv.slice(2)) {
  const options={};
  for(let i=0;i<argv.length;i++) {
    const [key,inline]=argv[i].split('=');
    assert(['--output','--characters','--font','--codec','--scene'].includes(key),'Unknown option '+key);
    if(key==='--characters'){assert(inline===undefined);options[key]=true;continue;}
    options[key]=inline??argv[++i];assert(options[key],'Missing value for '+key);
  }
  const output=path.resolve(options['--output']||path.join(parent,'build/three-scene-glass'));
  const raw=path.join(output,'render'),preview=path.join(output,'preview');
  const source=path.resolve(options['--scene']||path.join(here,'demo-glass.mjs'));
  const verificationFile=path.join(output,'verification.json');
  const font=path.resolve(options['--font']||path.join(here,'results/rubik-raw/font.bin'));
  const codec=options['--codec']||'literal';
  assert(['literal','sparse'].includes(codec));
  function run(executable,file,args) {
    const result=spawnSync('rtk',['proxy',executable,path.join(parent,file),...args],
      {encoding:'utf8',maxBuffer:8*1024*1024});
    if(result.error)throw result.error;
    if(result.status!==0)throw Error(file+'\n'+result.stdout+result.stderr);
  }
  const node=(file,args)=>run(process.execPath,file,args);
  const python=(file,args)=>run(process.env.PYTHON||'python3',file,args);
  fs.mkdirSync(output,{recursive:true});
  if(!options['--characters']) {
    node('three-scene/export.mjs',['--scene',source,'--output',raw,'--quantize','ordered','--write-rgba','--write-mask']);
    node('three-scene/verify-glass.mjs',['--input',raw,'--output',verificationFile]);
    python('three-scene/export-bitmap-media.py',['--input',raw,'--output',preview]);
    const result={pass:true,stage:'bitmap-only',characterConversionRun:false,output,
      verification:verificationFile,gif:path.join(preview,'bitmap.gif')};
    write(path.join(output,'pipeline.json'),result);console.log(JSON.stringify(result,null,2));return result;
  }

  assert(fs.existsSync(verificationFile),'Build and inspect the bitmap before character conversion.');
  const verification=json(verificationFile),metadata=json(path.join(raw,'metadata.json'));
  assert.equal(verification.pass,true,'Independent bitmap verification must pass.');
  assert.equal(metadata.sourceSha256,sha(fs.readFileSync(source)),'Scene changed; rebuild and inspect its bitmap.');
  assert.equal(path.resolve(metadata.sceneSource),source,'The selected scene differs from the exported entry point.');
  for(const dependency of metadata.sourceDependencies||[]) {
    assert(path.isAbsolute(dependency.source));
    assert.equal(sha(fs.readFileSync(dependency.source)),dependency.sha256,'Imported scene changed; rebuild its bitmap.');
  }
  assert.equal(metadata.width,160);assert.equal(metadata.height,100);assert.equal(metadata.fps,25);
  for(const [file,hash]of [[metadata.framesFile,metadata.hashes.frames],
    [metadata.rgbaFile,metadata.hashes.rgba],[metadata.objectMaskFile,metadata.hashes.objectMask]]) {
    assert(file&&hash);assert.equal(sha(fs.readFileSync(path.resolve(raw,file))),hash,'Bitmap export changed.');
  }
  node('three-scene/verify-glass.mjs',['--input',raw,'--output',verificationFile]);
  const fresh=json(verificationFile),loop=fresh.loop;
  assert(loop&&Number.isInteger(loop.startFrame)&&loop.startFrame>0&&Number.isInteger(loop.frameCount));
  assert.equal(loop.startFrame+loop.frameCount,metadata.frameCount);
  assert.equal(loop.endpointMatchesStart,true,'The separately rendered loop endpoint must match.');
  assert.equal(loop.unwrappedPeriodMatchesStart,true,'The complete period must reproduce its initial bitmap.');
  const fontBytes=fs.readFileSync(font);assert.equal(fontBytes.length,2048,'Use the existing fixed256-glyph font.');
  const characters=path.join(output,'characters'),storage=path.join(output,'storage'),native=path.join(output,'native');
  const matchingArguments=['--frames',path.join(raw,metadata.framesFile),'--metadata',path.join(raw,'metadata.json'),
    '--output',characters,'--font',font,'--font-start-frame','0'];
  node('bitmap-to-chars.cjs',matchingArguments);
  let matchingMask=path.join(raw,metadata.objectMaskFile),outlineMatching=null;
  if(fresh.outline) {
    const ringFile=path.join(output,fresh.outline.ringMaskFile),rings=fs.readFileSync(ringFile);
    assert.equal(sha(rings),fresh.outline.ringMaskSha256);
    const originalMask=fs.readFileSync(matchingMask);
    assert.equal(rings.length,originalMask.length);
    const countRingWhites=()=>{
      const screens=fs.readFileSync(path.join(characters,'reference.frames'));
      const perFrame=[];
      for(let frame=0;frame<metadata.frameCount;frame++) {
        let whites=0;
        for(let y=0;y<200;y++)for(let x=0;x<320;x++) {
          const logical=frame*16000+(y>>1)*160+(x>>1);
          if(!((rings[logical>>3]>>(7-(logical&7)))&1))continue;
          const code=screens[frame*1000+(y>>3)*40+(x>>3)];
          whites+=(fontBytes[code*8+(y&7)]>>(7-(x&7)))&1;
        }
        perFrame.push(whites);
      }
      return {physicalWhitePixels:perFrame.reduce((sum,value)=>sum+value,0),perFrame};
    };
    const before=countRingWhites();
    if(before.physicalWhitePixels) {
      const constrained=Buffer.from(originalMask);
      for(let i=0;i<constrained.length;i++)constrained[i]&=~rings[i];
      matchingMask=path.join(output,'character-outline-mask.frames');fs.writeFileSync(matchingMask,constrained);
      node('bitmap-to-chars.cjs',[...matchingArguments,'--mask',matchingMask]);
    }
    const after=countRingWhites();assert.equal(after.physicalWhitePixels,0,'Character matching filled the opaque black outline');
    outlineMatching={ringMaskSha256:sha(rings),matchingMaskFile:matchingMask,matchingMaskSha256:sha(fs.readFileSync(matchingMask)),
      stricterMaskApplied:before.physicalWhitePixels>0,before,after,
      method:'Keep the measured opaque black annulus forbidden to white glyph pixels; the font and bitmap are unchanged.'};
    write(path.join(output,'outline-matching-adjustment.json'),outlineMatching);
  }
  assert(fs.readFileSync(path.join(characters,'font.bin')).equals(fontBytes),'The static font changed.');
  const sceneFile=path.join(characters,'scene.json'),metadataFile=path.join(characters,'metadata.json');
  const scene=json(sceneFile),chars=json(metadataFile);
  assert.equal(chars.verification.firstFrameEmpty,true,'The existing player starts from a blank frame.');
  assert.equal(chars.frameCount,metadata.frameCount);
  const loopMetadata={startFrame:loop.startFrame,frameCount:loop.frameCount};
  scene.loop=loopMetadata;scene.introSeconds=loopMetadata.startFrame/25;
  chars.loop=loopMetadata;chars.introSeconds=scene.introSeconds;
  chars.verification.noClosingPatch=false;
  chars.verification.loopEndpointMatchesStart=true;chars.verification.loopUnwrappedPeriodMatchesStart=true;
  chars.verification.loopBitmapReceipt=verificationFile;
  write(sceneFile,scene);write(metadataFile,chars);
  const playback=[{op:'play',startFrame:0,frameCount:loopMetadata.startFrame,repeat:1},
    {op:'play',startFrame:loopMetadata.startFrame,frameCount:loopMetadata.frameCount,repeat:'forever'},{op:'hold'}];
  const playbackPreview=playback.map(command=>command.repeat==='forever'?{...command,repeat:2}:command);
  const script=path.join(characters,'playback.json'),previewScript=path.join(characters,'playback-preview.json');
  write(script,playback);write(previewScript,playbackPreview);
  const auditFile=path.join(output,'character-audit.json');
  node('audit-bitmap-chars.cjs',['--frames',path.join(raw,metadata.framesFile),'--metadata',path.join(raw,'metadata.json'),
    '--characters',characters,'--mask',matchingMask,'--output',auditFile]);
  python('three-scene/verify-glass-chars.py',['--input',output]);
  node('measure-scene.cjs',['--input='+characters,'--output='+storage,'--codec='+codec]);
  const study=json(path.join(storage,'study.json')),audit=json(auditFile);
  assert.equal(audit.pass,true);assert.equal(audit.objectMask.outputWhiteOutsideObject,0);
  node('build-scene-preview.cjs',['--scene-dir',characters,'--output-dir',preview,
    '--summary-file',path.join(storage,'study.json'),'--playback-script',previewScript,'--scene-source',source,'--basename','glass-c64']);
  python('export-scene-media.py',['--scene-dir',characters,'--output-dir',preview,
    '--playback-script',previewScript,'--basename','glass-c64']);
  python('three-scene/glass-compare.py',['--characters',characters,'--output',preview]);
  let packing;
  try {
    const movie=fs.readFileSync(path.join(storage,codec+'.bin'));
    const index=json(path.join(storage,codec+'-index.json'));
    const packed=packMovie(movie,index,codec==='literal'?0x1700:0x1400);
    packing={fits:true,capacityBytes:packed.capacity,payloadBytes:movie.length,unusedBytes:packed.capacity-movie.length};
  } catch(error) {
    packing={fits:false,payloadBytes:study.formats[codec].payloadBytes,reason:error.message};
  }
  let build=null;
  const variant=codec==='literal'?'literal-front':'sparse-front';
  if(packing.fits) {
    node('build-scene-player.cjs',['--input',storage,'--output',native,'--script',script,'--codec',codec]);
    build=json(path.join(native,variant,'build.json'));
    python('three-scene/glass-host-proof.py',['--native',path.join(native,variant),'--storage',storage]);
  }
  const result={pass:true,stage:build?'character film and native PRG':'character film exceeds current RAM pools',
    characterConversionRun:true,nativeBuilt:Boolean(build),output,bitmapVerification:verificationFile,
    characterOpticsVerification:path.join(output,'character-visibility.json'),
    ...(outlineMatching?{outlineMatching}:{}),
    codec,variant,staticFont:{file:font,glyphs:256,sha256:sha(fontBytes),modified:false},
    storedFrames:chars.frameCount,loop:loopMetadata,nominalFps:25,script:playback,packing,
    formats:Object.fromEntries(Object.entries(study.formats).map(([name,record])=>[name,{payloadBytes:record.payloadBytes,
      pointerBytes:record.pointerTableBytes,animationAndFontBytes:record.totalAnimationAndFontBytes}])),
    quality:{wholeFramePixelErrorFraction:audit.wholeImage.errorFraction,
      activeBoundsPixelErrorFraction:audit.activeBounds.errorFraction,
      objectPixelErrorFraction:audit.objectMask.errorFraction,outputWhiteOutsideObject:audit.objectMask.outputWhiteOutsideObject,
      nonuniformTileMeanPixelError:audit.nonuniformTiles.meanMismatchedPixels,audit:auditFile},
    ...(build?{program:path.join(native,variant,'player.prg'),programSha256:build.hashes.program,
      payloadBytes:build.payloadBytes,meaningfulLoadedBytes:build.meaningfulLoadedBytes,
      hostProof:path.join(native,variant,'host-proof.json')}:{}),
    html:path.join(preview,'glass-c64.html'),gif:path.join(preview,'glass-c64.gif'),
    comparison:path.join(preview,'glass-source-comparison.png'),nativeTimingMeasured:false};
  write(path.join(output,'player-pipeline.json'),result);write(path.join(output,'pipeline.json'),result);
  console.log(JSON.stringify(result,null,2));return result;
}

module.exports={main};
if(require.main===module)main();
