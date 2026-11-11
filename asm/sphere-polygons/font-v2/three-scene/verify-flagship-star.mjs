import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {create, globals} from 'webgpu';

const here=path.dirname(fileURLToPath(import.meta.url));
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const bit=(data,pixel)=>(data[pixel>>3]>>(7-(pixel&7)))&1;
const vertexKey=point=>point.map(value=>Math.round(value*1e5)).join(',');

function topology(geometry) {
  const attribute=geometry.getAttribute('position'),index=geometry.getIndex();
  const points=Array.from({length:attribute.count},(_,i)=>[attribute.getX(i),attribute.getY(i),attribute.getZ(i)]);
  const unique=[...new Map(points.map(point=>[vertexKey(point),point])).values()];
  const corners=unique.filter(point=>point.every(value=>Math.abs(value)>1e-5));
  const tips=unique.filter(point=>point.filter(value=>Math.abs(value)<1e-5).length===2);
  assert.equal(unique.length,14);assert.equal(corners.length,8);assert.equal(tips.length,6);
  const h=Math.abs(corners[0][0]),radius=Math.max(...tips.flat().map(Math.abs));
  assert(corners.every(point=>point.every(value=>Math.abs(Math.abs(value)-h)<1e-5)));
  assert.equal(new Set(tips.map(vertexKey)).size,6);
  for(let axis=0;axis<3;axis++)for(const sign of [-1,1])assert(tips.some(point=>
    point.every((value,component)=>Math.abs(value-(component===axis?sign*radius:0))<1e-5)));
  assert(h<15&&radius>30&&radius/h>3,'Arms must be longer and slimmer than the h15/R30 envelope');
  const order=index?Array.from(index.array):Array.from({length:points.length},(_,i)=>i);
  assert.equal(order.length,72);
  const edges=new Map();let signedVolume=0;
  for(let i=0;i<order.length;i+=3) {
    const triangle=order.slice(i,i+3).map(vertex=>points[vertex]);
    const [a,b,c]=triangle,u=b.map((value,axis)=>value-a[axis]),v=c.map((value,axis)=>value-a[axis]);
    assert(Math.hypot(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])>1e-8);
    assert.equal(triangle.filter(point=>tips.some(tip=>vertexKey(tip)===vertexKey(point))).length,1);
    signedVolume+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6;
    for(const [p,q]of [[a,b],[b,c],[c,a]]) {
      const first=vertexKey(p),second=vertexKey(q),key=[first,second].sort().join('|');
      const previous=edges.get(key)||{count:0,winding:0};previous.count++;previous.winding+=first<second?1:-1;edges.set(key,previous);
    }
  }
  assert.equal(edges.size,36);assert([...edges.values()].every(edge=>edge.count===2&&edge.winding===0));
  assert(signedVolume>0);
  assert(Math.abs(signedVolume-8*h*h*radius)<0.1,'Closed star volume differs from its six-pyramid construction');
  return {vertices:14,triangles:24,edges:36,eulerCharacteristic:2,closed:true,oppositeEdgeWindings:true,
    cubeHalfExtent:h,tipDistance:radius,armLength:radius-h,tipToHalfExtentRatio:radius/h,
    previous:{cubeHalfExtent:10,tipDistance:30,armLength:20,ratio:3},signedVolume,
    axisTips:tips,annotations:geometry.userData};
}

async function gpuProof(metadata,rgba,mask,output,options={}) {
  const factory=await import(pathToFileURL(metadata.sceneSource).href);
  const loop=factory.config.loop;
  assert(loop&&Number.isInteger(loop.startFrame)&&loop.startFrame===1&&Number.isInteger(loop.frameCount)&&loop.frameCount>1);
  assert.equal(loop.startFrame+loop.frameCount,metadata.frameCount);
  assert.equal((metadata.sourceDependencies||[]).length,(factory.config.sourceDependencies||[]).length);
  for(const [index,declared]of (factory.config.sourceDependencies||[]).entries())assert.equal(
    metadata.sourceDependencies[index].source,path.resolve(path.dirname(metadata.sceneSource),declared));
  const previousGlobals=new Map(Object.keys(globals).map(key=>[key,Object.getOwnPropertyDescriptor(globalThis,key)]));
  Object.assign(globalThis,globals);
  const previousNavigator=Object.getOwnPropertyDescriptor(globalThis,'navigator'),previousSelf=Object.getOwnPropertyDescriptor(globalThis,'self');
  const gpu=create(['backend=metal']);
  Object.defineProperty(globalThis,'navigator',{value:{gpu,userAgent:'Node.js Dawn Metal'},configurable:true});
  Object.defineProperty(globalThis,'self',{value:{requestAnimationFrame:()=>1,cancelAnimationFrame(){}},configurable:true});
  let device,renderer,target;
  try {
    const adapter=await gpu.requestAdapter();assert(adapter);device=await adapter.requestDevice();
    const THREE=await import('three/webgpu');
    const {width,height,fps,frameCount}=metadata,frameSize=width*height*4;
    const canvas={width,height,style:{},addEventListener(){},removeEventListener(){},getContext(){throw Error('Offscreen GPU only');}};
    renderer=new THREE.WebGPURenderer({device,canvas,antialias:false});renderer.setSize(width,height,false);
    target=new THREE.RenderTarget(width,height,{type:THREE.UnsignedByteType,format:THREE.RGBAFormat,depthBuffer:true});
    target.texture.colorSpace=THREE.SRGBColorSpace;renderer.setRenderTarget(target);await renderer.init();
    const world=await factory.createScene(THREE),objects=[];
    world.scene.traverse(object=>{if(object.isMesh||object.isLine||object.isPoints||object.isSprite)objects.push(object);});
    assert.equal(objects.length,1,'The scene must contain only the solid star');
    const star=objects[0];assert(star.isMesh&&star.name==='solid-star');
    const materials=Array.isArray(star.material)?star.material:[star.material];
    assert(materials.every(material=>material.isMeshBasicMaterial&&!material.transparent&&material.opacity===1&&
      material.depthWrite&&material.depthTest&&!material.wireframe&&!material.transmission));
    const mesh=topology(star.geometry),matrices=[];
    const read=async()=>{renderer.render(world.scene,world.camera);return Buffer.from(await renderer.readRenderTargetPixelsAsync(target,0,0,width,height));};
    const capture=async frame=>{await world.update(frame/fps);return read();};
    const endpointFrame=loop.startFrame+loop.frameCount,twoPeriodFrame=loop.startFrame+loop.frameCount*2;
    const start=await capture(loop.startFrame),endpoint=await capture(endpointFrame),twoPeriods=await capture(twoPeriodFrame);
    assert(start.equals(rgba.subarray(loop.startFrame*frameSize,(loop.startFrame+1)*frameSize)));assert(endpoint.equals(start));assert(twoPeriods.equals(start));
    for(const frame of [...new Set([loop.startFrame,...[.25,.5,.75].map(fraction=>loop.startFrame+Math.floor(loop.frameCount*fraction)),frameCount-1])]) {
      const image=await capture(frame);assert(image.equals(rgba.subarray(frame*frameSize,(frame+1)*frameSize)));
      star.updateMatrixWorld(true);matrices.push(star.matrixWorld.elements.slice());
    }
    const movement=Math.max(...matrices.flatMap(matrix=>matrix.map((value,index)=>Math.abs(value-matrices[0][index]))));
    assert(movement>0.1,'The star must move through its loop');
    const shadeGrays=world.scene.userData.calibration.shadeGrays;
    const light=new THREE.Vector3(...world.scene.userData.calibration.lightDirectionWorld);
    const normalAttribute=star.geometry.getAttribute('normal');
    const facetNormals=Array.from({length:materials.length},(_,index)=>new THREE.Vector3().fromBufferAttribute(normalAttribute,index*3));
    const shadingContract=[];
    for(const frame of [...new Set([loop.startFrame,...[.2,.4,.6,.8].map(fraction=>loop.startFrame+Math.floor(loop.frameCount*fraction))])]) {
      await world.update(frame/fps);star.updateMatrixWorld(true);
      const srgbToLinear=value=>value<=0.04045?value/12.92:Math.pow((value+0.055)/1.055,2.4);
      const observed=materials.map((material,index)=>{
        const rotated=facetNormals[index].clone().applyQuaternion(star.quaternion);
        const facing=rotated.dot(light);
        const level=Math.max(0,Math.min(shadeGrays.length-1,Math.round((facing*0.5+0.5)*(shadeGrays.length-1))));
        return {index,expected:srgbToLinear(shadeGrays[level]/255),got:material.color.r};
      });
      for(const entry of observed)assert(Math.abs(entry.expected-entry.got)<2e-3,
        `Facet ${entry.index} deviates from the declared light rule at frame ${frame}`);
      shadingContract.push({frame,facetsChecked:observed.length,maxDeviation:Math.max(...observed.map(entry=>Math.abs(entry.expected-entry.got)))});
    }
    let fullRotation=null;
    if(/tumbling/i.test(metadata.name))assert(Array.isArray(factory.config.turnsPerLoop),'Full tumbling requires an explicit three-axis rotation contract');
    if(factory.config.turnsPerLoop) {
      const turns=factory.config.turnsPerLoop,order=factory.config.rotationOrder;
      assert.equal(turns.length,3);assert(turns.every(value=>Number.isInteger(value)&&Math.abs(value)>=1));
      assert(['XYZ','XZY','YXZ','YZX','ZXY','ZYX'].includes(order));
      const poses=[],orientations=[],fixedColors=materials.map(material=>material.color.toArray());let base=null;
      const requireFixedColors=options.fixedFacetColors!==false;
      let previousColors=fixedColors,maximumFacetColorStep=0;
      for(let step=0;step<=loop.frameCount+1;step++) {
        await world.update((loop.startFrame+step)/fps);star.updateMatrixWorld(true);
        const pose=world.scene.userData.pose,angles=pose.eulerUnwrapped;
        const colors=materials.map(material=>material.color.toArray());
        if(requireFixedColors)assert.deepEqual(colors,fixedColors,'Fixed facets changed paint during rotation');
        else {
          if(step)for(let material=0;material<colors.length;material++)for(let channel=0;channel<3;channel++) {
            maximumFacetColorStep=Math.max(maximumFacetColorStep,Math.abs(colors[material][channel]-previousColors[material][channel]));
          }
          previousColors=colors;
        }
        assert(Array.isArray(angles)&&angles.length===3&&angles.every(Number.isFinite));
        assert.equal(pose.rotationOrder,order);assert(Array.isArray(pose.baseOrientation)&&pose.baseOrientation.length===4);
        if(!base)base=pose.baseOrientation.slice();else assert.deepEqual(pose.baseOrientation,base);
        const expected=new THREE.Quaternion().fromArray(base).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(...angles,order)));
        assert(star.quaternion.angleTo(expected)<1e-6,'Unwrapped XYZ angles do not drive the actual mesh orientation');
        poses.push(angles.slice());orientations.push(star.quaternion.clone());
      }
      const net=poses[loop.frameCount].map((value,axis)=>value-poses[0][axis]);
      net.forEach((value,axis)=>assert(Math.abs(value-turns[axis]*2*Math.PI)<1e-7&&Math.abs(value)>=2*Math.PI-1e-7));
      assert(orientations[0].angleTo(orientations[loop.frameCount])<1e-7);
      const increments=[];
      for(let i=1;i<orientations.length;i++) {
        const delta=orientations[i].clone().multiply(orientations[i-1].clone().invert()).normalize();
        if(delta.w<0){delta.x*=-1;delta.y*=-1;delta.z*=-1;delta.w*=-1;}
        const sine=Math.hypot(delta.x,delta.y,delta.z),angle=2*Math.atan2(sine,delta.w);
        increments.push(sine?[delta.x,delta.y,delta.z].map(value=>value*angle/sine):[0,0,0]);
      }
      const jump=(a,b)=>Math.hypot(...a.map((value,axis)=>value-b[axis]));
      const ordinaryJumps=increments.slice(1,loop.frameCount).map((value,index)=>jump(value,increments[index]));
      const boundaryJump=jump(increments[loop.frameCount],increments[loop.frameCount-1]);
      assert(boundaryJump<=Math.max(...ordinaryJumps)*1.05+1e-8,'Angular velocity jumps at the repeat boundary');
      const steps=increments.slice(0,loop.frameCount).map(value=>Math.hypot(...value));
      assert(Math.max(...steps)<0.2,'The three-axis path has an abrupt per-frame orientation jump');
      const transformedAxes=[[1,0,0],[0,1,0],[0,0,1]].map((axis,index)=>{
        const vectors=orientations.slice(0,loop.frameCount).map(quaternion=>new THREE.Vector3(...axis).applyQuaternion(quaternion).toArray());
        const ranges=[0,1,2].map(component=>({min:Math.min(...vectors.map(vector=>vector[component])),max:Math.max(...vectors.map(vector=>vector[component]))}));
        const frontFacingSamples=vectors.filter(vector=>vector[2]>.25).length,rearFacingSamples=vectors.filter(vector=>vector[2]<-.25).length;
        assert(frontFacingSamples>0&&rearFacingSamples>0,'Every actual local axis must rotate through front and rear views');
        return {axis:'XYZ'[index],worldComponentRanges:ranges,frontFacingSamples,rearFacingSamples};
      });
      fullRotation={rotationOrder:order,turnsPerLoop:net.map(value=>value/(2*Math.PI)),baseOrientation:base,
        actualMeshMatchesReconstructedAngles:true,netRadians:net,
        transformedAxes,fixedFacetColorsThroughoutLoop:requireFixedColors,maximumFacetColorStep,
        maximumOrientationChangeFromStart:Math.max(...orientations.map(value=>orientations[0].angleTo(value))),
        angularStepRadians:{min:Math.min(...steps),mean:steps.reduce((sum,value)=>sum+value,0)/steps.length,max:Math.max(...steps)},
        boundaryAngularVelocityVectorDifference:boundaryJump*fps,
        largestOrdinaryAngularVelocityVectorDifference:Math.max(...ordinaryJumps)*fps,
        angularVelocityContinuousAtLoop:true};
    }
    let touchingBorder=0;const bounds=[];
    for(let frame=loop.startFrame;frame<frameCount;frame++) {
      let left=width,top=height,right=-1,bottom=-1;
      for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(bit(mask,frame*width*height+y*width+x)) {
        left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x);bottom=Math.max(bottom,y);
        touchingBorder+=Number(x===0||x===width-1||y===0||y===height-1);
      }
      assert(right>=left&&bottom>=top);bounds.push([left,top,right+1,bottom+1]);
    }
    assert.equal(touchingBorder,0,'The longer arms are clipped by the screen');
    return {scene:{renderableObjects:1,meshName:star.name,opaque:true,noBall:true,noGlass:true,noWireframe:true,shaded:true},mesh,
      shadingContract:{rule:'facet gray = shadeGrays[round((rotatedNormal.dot(light)*0.5+0.5)*(levels-1))]',samples:shadingContract},
      screenFit:{touchingBorderPixels:0,logicalBoundsPerFrame:bounds},movement:{maximumMatrixDifference:movement},
      ...(fullRotation?{fullRotation}:{}),
      loop:{...loop,endpointFrame,unwrappedEndpointFrame:twoPeriodFrame,
        endpointMatchesStart:true,unwrappedPeriodMatchesStart:true,rgbaSha256:sha(start)}};
  } finally {
    target?.dispose();renderer?.dispose();device?.destroy();
    if(previousNavigator)Object.defineProperty(globalThis,'navigator',previousNavigator);else delete globalThis.navigator;
    if(previousSelf)Object.defineProperty(globalThis,'self',previousSelf);else delete globalThis.self;
    for(const [key,descriptor]of previousGlobals){if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];}
  }
}

function previews(input,output,loop) {
  const script=`
from pathlib import Path
from PIL import Image,ImageDraw
import sys,json
p=Path(sys.argv[1]);o=Path(sys.argv[2]);start=int(sys.argv[3]);count=int(sys.argv[4]);m=json.loads((p/'metadata.json').read_text());bits=(p/m['framesFile']).read_bytes();stride=m['frameBytes']
def frame(i):return Image.frombytes('1',(m['width'],m['height']),bits[i*stride:(i+1)*stride]).convert('RGB').resize((320,200),Image.Resampling.NEAREST)
sheet=Image.new('RGB',(960,448));draw=ImageDraw.Draw(sheet)
for slot,index in enumerate([start+round((count-1)*fraction/5) for fraction in range(6)]):
 x=(slot%3)*320;y=(slot//3)*224;draw.text((x+5,y+5),f'Flaggskeppsstarja / frame {index}',fill='white');sheet.paste(frame(index),(x,y+24))
sheet.save(o/'flagship-star-bitmap-contact.png')
frames=[frame(i) for i in range(start,start+count)];frames[0].save(o/'flagship-star-bitmap.gif',save_all=True,append_images=frames[1:],duration=40,loop=0,optimize=False,disposal=1)
with Image.open(o/'flagship-star-bitmap.gif') as gif:
 elapsed=0
 for i in range(gif.n_frames):
  gif.seek(i);duration=gif.info['duration'];assert duration%40==0
  for offset in range(duration//40):assert gif.convert('RGB').tobytes()==frames[elapsed//40+offset].tobytes()
  elapsed+=duration
 assert elapsed==count*40
`;
  execFileSync('rtk',['proxy','python3','-c',script,input,output,String(loop.startFrame),String(loop.frameCount)],{stdio:'pipe'});
}

export async function main(argv=process.argv.slice(2)) {
  const options={};for(let i=0;i<argv.length;i+=2){assert(['--input','--output'].includes(argv[i]));options[argv[i]]=argv[i+1];}
  const input=path.resolve(options['--input']||path.join(here,'../build/three-scene-flagship-star/render'));
  const file=path.resolve(options['--output']||path.join(input,'../verification.json')),output=path.dirname(file);
  fs.mkdirSync(output,{recursive:true});fs.rmSync(file,{force:true});
  const metadata=JSON.parse(fs.readFileSync(path.join(input,'metadata.json')));
  assert.equal(metadata.width,160);assert.equal(metadata.height,100);assert.equal(metadata.fps,25);
  assert(Number.isInteger(metadata.frameCount)&&metadata.frameCount>1&&metadata.frameCount<=255);
  assert.equal(metadata.quantization.mode,'ordered');
  const factoryConfig = await import(pathToFileURL(metadata.sceneSource).href);
  const shadeGrays = factoryConfig.config.star.shadeGrays;
  assert(Array.isArray(shadeGrays)&&shadeGrays.length>=3);
  const allowedGrays = new Set(shadeGrays.flatMap(value=>[value-1,value,value+1]));
  assert.equal(metadata.renderer.browserUsed,false);assert.equal(metadata.renderer.canvasContextRequests,0);
  assert.equal(metadata.verification.allFramesReadFromGPU,true);assert.equal(metadata.verification.deterministicSampleTimes,true);
  assert.equal(sha(fs.readFileSync(metadata.sceneSource)),metadata.sourceSha256);
  for(const dependency of metadata.sourceDependencies||[])assert.equal(sha(fs.readFileSync(dependency.source)),dependency.sha256);
  const bitmap=fs.readFileSync(path.join(input,metadata.framesFile)),rgba=fs.readFileSync(path.join(input,metadata.rgbaFile));
  const mask=fs.readFileSync(path.join(input,metadata.objectMaskFile));
  const bayer4=[0,8,2,10,12,4,14,6,3,11,1,9,15,7,13,5];
  const pixelsPerFrame=metadata.width*metadata.height,frameBytes=pixelsPerFrame/8;
  assert.equal(bitmap.length,metadata.frameCount*frameBytes);assert.equal(rgba.length,metadata.frameCount*pixelsPerFrame*4);assert.equal(mask.length,bitmap.length);
  assert.equal(sha(bitmap),metadata.hashes.frames);assert.equal(sha(rgba),metadata.hashes.rgba);assert.equal(sha(mask),metadata.hashes.objectMask);
  let wrongBits=0,nonBinary=0,nonOpaque=0,whiteOutsideMask=0;const whitePixels=[];
  for(let frame=0;frame<metadata.frameCount;frame++) {
    let whites=0;
    for(let pixel=0;pixel<pixelsPerFrame;pixel++) {
      const absolute=frame*pixelsPerFrame+pixel,at=absolute*4,gray=rgba[at];
      const bx=pixel%metadata.width,by=(pixel/metadata.width)|0,bayerCut=(bayer4[(by&3)*4+(bx&3)]+0.5)*255/16;
      nonBinary+=Number(!allowedGrays.has(gray)||gray!==rgba[at+1]||gray!==rgba[at+2]);
      nonOpaque+=Number(rgba[at+3]!==255);const actual=bit(bitmap,absolute);
      wrongBits+=Number(actual!==Number(gray>=bayerCut));whiteOutsideMask+=Number(actual&&!bit(mask,absolute));whites+=actual;
    }
    whitePixels.push(whites);
  }
  assert.equal(nonBinary,0);assert.equal(nonOpaque,0);assert.equal(wrongBits,0);assert.equal(whiteOutsideMask,0);
  assert.equal(whitePixels[0],0);assert(whitePixels.slice(1).every(value=>value>0));
  const proof=await gpuProof(metadata,rgba,mask,output);previews(input,output,proof.loop);
  const result={pass:true,stage:'Flagship star GPU bitmap',characterConversionRun:false,
    sourceSha256:metadata.sourceSha256,sourceDependencies:metadata.sourceDependencies||[],bitmapSha256:sha(bitmap),
    rgbaSha256:sha(rgba),objectMaskSha256:sha(mask),width:metadata.width,height:metadata.height,physicalPreviewPixels:[320,200],fps:metadata.fps,frameCount:metadata.frameCount,
    quantization:{mode:'orderedBayer4x4',sourceLevels:shadeGrays,pixelsCompared:metadata.frameCount*pixelsPerFrame,wrongBits,nonBinary,nonOpaque,whiteOutsideMask,whitePixels},
    ...proof,previews:{contact:'flagship-star-bitmap-contact.png',loop:'flagship-star-bitmap.gif',loopTimingAndPixelsVerified:true}};
  fs.writeFileSync(file,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({...result,screenFit:undefined,quantization:{...result.quantization,whitePixels:undefined}},null,2));return result;
}

if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)main().then(()=>process.exit(0),error=>{console.error(error);process.exit(1);});

// Shared scene/geometry/rotation checks; each entry point owns its quantizer contract.
export {gpuProof,previews};
