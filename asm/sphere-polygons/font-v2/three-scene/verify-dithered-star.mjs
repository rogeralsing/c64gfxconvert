import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {gpuProof,previews} from './verify-solid-star.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const bit=(data,pixel)=>(data[pixel>>3]>>(7-(pixel&7)))&1;
// Independent rank construction; the exporter uses a literal Bayer array.
const rank=(x,y)=>{const pair=(a,b)=>2*(a^b)+b;return 4*pair(x&1,y&1)+pair((x>>1)&1,(y>>1)&1);};

function grayscalePreview(input,output,loop) {
  const script=`
from pathlib import Path
from PIL import Image,ImageDraw
import json,sys
p=Path(sys.argv[1]);o=Path(sys.argv[2]);start=int(sys.argv[3]);count=int(sys.argv[4]);m=json.loads((p/'metadata.json').read_text())
gray=(p/m['rgbaFile']).read_bytes();bits=(p/m['framesFile']).read_bytes();w=m['width'];h=m['height'];rgba=w*h*4;stride=w*h//8
indices=sorted(set(start+min(count-1,round(count*f)) for f in (0,.25,.5,.68,.79,1)))
sheet=Image.new('RGB',(640,len(indices)*224));draw=ImageDraw.Draw(sheet)
for row,index in enumerate(indices):
 y=row*224;draw.text((5,y+5),f'Actual GPU grayscale / frame {index}',fill='white');draw.text((325,y+5),'Independent ordered 1-bit export',fill='white')
 a=Image.frombytes('RGBA',(w,h),gray[index*rgba:(index+1)*rgba]).convert('RGB')
 b=Image.frombytes('1',(w,h),bits[index*stride:(index+1)*stride]).convert('RGB')
 sheet.paste(a.resize((320,200),Image.Resampling.NEAREST),(0,y+24));sheet.paste(b.resize((320,200),Image.Resampling.NEAREST),(320,y+24))
sheet.save(o/'grayscale-vs-bitmap.png')
`;
  execFileSync('rtk',['proxy','python3','-c',script,input,output,String(loop.startFrame),String(loop.frameCount)],{stdio:'pipe'});
}

export async function main(argv=process.argv.slice(2)) {
  const options={};for(let i=0;i<argv.length;i+=2){assert(['--input','--output'].includes(argv[i]));options[argv[i]]=argv[i+1];}
  const input=path.resolve(options['--input']||path.join(here,'../build/three-scene-dithered-star/render'));
  const file=path.resolve(options['--output']||path.join(input,'../verification.json')),output=path.dirname(file);
  fs.mkdirSync(output,{recursive:true});fs.rmSync(file,{force:true});
  const metadata=JSON.parse(fs.readFileSync(path.join(input,'metadata.json')));
  assert.equal(metadata.width,160);assert.equal(metadata.height,100);assert.equal(metadata.fps,25);
  assert(Number.isInteger(metadata.frameCount)&&metadata.frameCount>1&&metadata.frameCount<=255);
  assert.equal(metadata.quantization.mode,'ordered');assert.equal(metadata.renderer.browserUsed,false);
  assert.equal(metadata.renderer.canvasContextRequests,0);assert.equal(metadata.verification.allFramesReadFromGPU,true);
  assert.equal(metadata.verification.deterministicSampleTimes,true);
  assert.equal(sha(fs.readFileSync(metadata.sceneSource)),metadata.sourceSha256);
  for(const dependency of metadata.sourceDependencies||[])assert.equal(sha(fs.readFileSync(dependency.source)),dependency.sha256);
  const movie=fs.readFileSync(path.join(input,metadata.framesFile)),rgba=fs.readFileSync(path.join(input,metadata.rgbaFile));
  const mask=fs.readFileSync(path.join(input,metadata.objectMaskFile)),pixels=metadata.width*metadata.height;
  assert.equal(movie.length,metadata.frameCount*pixels/8);assert.equal(rgba.length,metadata.frameCount*pixels*4);assert.equal(mask.length,movie.length);
  assert.equal(sha(movie),metadata.hashes.frames);assert.equal(sha(rgba),metadata.hashes.rgba);assert.equal(sha(mask),metadata.hashes.objectMask);
  let wrongBits=0,nonGrayscale=0,nonOpaque=0,whiteOutsideMask=0,objectPixels=0,intermediateObjectPixels=0,objectGraySum=0;
  const histogram=Array(256).fill(0),whitePixels=[];
  for(let frame=0;frame<metadata.frameCount;frame++) {
    let whites=0;
    for(let y=0;y<metadata.height;y++)for(let x=0;x<metadata.width;x++) {
      const pixel=frame*pixels+y*metadata.width+x,at=pixel*4,gray=rgba[at],actual=bit(movie,pixel),inside=bit(mask,pixel);
      nonGrayscale+=Number(gray!==rgba[at+1]||gray!==rgba[at+2]);nonOpaque+=Number(rgba[at+3]!==255);
      wrongBits+=Number(actual!==Number(gray>=(rank(x,y)+.5)*255/16));whiteOutsideMask+=Number(actual&&!inside);whites+=actual;
      if(inside){objectPixels++;histogram[gray]++;objectGraySum+=gray;intermediateObjectPixels+=Number(gray>0&&gray<255);}
    }
    whitePixels.push(whites);
  }
  assert.equal(nonGrayscale,0);assert.equal(nonOpaque,0);assert.equal(wrongBits,0);assert.equal(whiteOutsideMask,0);
  assert.equal(whitePixels[0],0);assert(whitePixels.slice(1).every(value=>value>0));
  const levels=histogram.flatMap((count,gray)=>count?[gray]:[]);
  assert(levels.length>=3&&Math.max(...levels)-Math.min(...levels)>=32,'Actual star readback lacks meaningful grayscale shading');
  assert(intermediateObjectPixels>objectPixels*.5,'Most of the opaque star must use intermediate gray before export');
  const proof=await gpuProof(metadata,rgba,mask,output,{fixedFacetColors:false});
  assert(proof.fullRotation&&proof.fullRotation.maximumFacetColorStep<.2,'Facet colors change abruptly between frames');
  previews(input,output,proof.loop);grayscalePreview(input,output,proof.loop);
  const result={pass:true,stage:'Opaque grayscale star to ordered bitmap',characterConversionRun:false,
    sourceSha256:metadata.sourceSha256,sourceDependencies:metadata.sourceDependencies||[],bitmapSha256:sha(movie),
    rgbaSha256:sha(rgba),objectMaskSha256:sha(mask),width:metadata.width,height:metadata.height,
    physicalPreviewPixels:[320,200],fps:metadata.fps,frameCount:metadata.frameCount,
    quantization:{mode:'screen-fixed 4x4 Bayer',pixelsCompared:metadata.frameCount*pixels,wrongBits,nonGrayscale,nonOpaque,whiteOutsideMask,whitePixels},
    grayscale:{objectPixels,intermediateObjectPixels,minimum:Math.min(...levels),maximum:Math.max(...levels),
      mean:objectGraySum/objectPixels,distinctLevels:levels.length,histogram},
    ...proof,previews:{grayscaleAndBitmap:'grayscale-vs-bitmap.png',contact:'solid-star-bitmap-contact.png',loop:'solid-star-bitmap.gif',loopTimingAndPixelsVerified:true}};
  fs.writeFileSync(file,JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({...result,screenFit:undefined,quantization:{...result.quantization,whitePixels:undefined},grayscale:{...result.grayscale,histogram:undefined}},null,2));
  return result;
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)main().then(()=>process.exit(0),error=>{console.error(error);process.exit(1);});
