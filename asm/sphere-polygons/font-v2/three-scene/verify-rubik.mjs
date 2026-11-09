import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';

// Owner boundary: actual GPU bytes and actual cubie meshes. No declared move
// angles, grid metadata, or scene state helper supplies the expected answer.
const here = path.dirname(fileURLToPath(import.meta.url));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const bit = (bytes, index) => (bytes[index >> 3] >> (7 - (index & 7))) & 1;
// First three seconds of the published checker entrance, before the new zoom.
const approvedFrames = 75;
const approvedHash = 'a62dcca0ede9fb20a6684b6c487856fc755400424428227e848be034c5b26644';
const times = {zoomStart:3, peak:4, morphEnd:5.4, revealEnd:6.2,
  topStart:6.3, topEnd:7.1, leftStart:7.35, leftEnd:9.1, end:10};
const epsilon = 2e-6;
function rank(x, y) {
  const pair = (a, b) => 2 * (a ^ b) + b;
  return 4 * pair(x & 1, y & 1) + pair((x >> 1) & 1, (y >> 1) & 1);
}
function close(actual, expected, label) {
  assert(Math.abs(actual - expected) <= epsilon, `${label}: ${actual} != ${expected}`);
}
function arrayClose(actual, expected, label) {
  assert.equal(actual.length, expected.length);
  for (let index = 0; index < actual.length; index++) close(actual[index], expected[index], `${label}[${index}]`);
}
function attributeHash(attribute) {
  const a = attribute.array;
  return sha(Buffer.from(a.buffer, a.byteOffset, a.byteLength));
}
function geometrySignature(geometry) {
  return JSON.stringify({attributes:Object.fromEntries(Object.entries(geometry.attributes).map(([key,value]) => [key,attributeHash(value)])),
    index:geometry.index ? attributeHash(geometry.index) : null, groups:geometry.groups});
}
function materialSignature(material) {
  const image = material.map?.image;
  return JSON.stringify({type:material.type, color:material.color?.toArray(), vertexColors:material.vertexColors,
    opacity:material.opacity, transparent:material.transparent, toneMapped:material.toneMapped,
    map:image ? {width:image.width,height:image.height,data:sha(image.data),colorSpace:material.map.colorSpace,
      min:material.map.minFilter,mag:material.map.magFilter,offset:material.map.offset.toArray()} : null});
}

async function verifyEntranceAndTransition(metadata, mask) {
  const THREE=await import('three/webgpu');
  const factory=await import(pathToFileURL(metadata.sceneSource).href);
  const world=await factory.createScene(THREE),width=metadata.width,height=metadata.height;
  const checker=world.scene.getObjectByName('morphing-sphere-cube'),root=world.scene.getObjectByName('rubik-cube');
  assert(checker?.isMesh&&root,'Actual checker and puzzle objects are required.');
  const cubies=[];root.traverse(object=>{if(/^cubie:/.test(object.name)&&object.isMesh)cubies.push(object);});
  assert.equal(cubies.length,27);
  await world.update(0);
  const sphere=Float64Array.from(checker.geometry.getAttribute('position').array);
  const radii=[];for(let at=0;at<sphere.length;at+=3)radii.push(Math.hypot(...sphere.subarray(at,at+3)));
  const radius=radii.reduce((a,b)=>a+b,0)/radii.length;
  assert(Math.max(...radii)-Math.min(...radii)<1e-4,'Initial actual geometry is not spherical.');
  const delta=new Float64Array(sphere.length),half=radius/Math.sqrt(3);let denominator=0;
  for(let at=0;at<sphere.length;at+=3){
    const maximum=Math.max(...Array.from(sphere.subarray(at,at+3),Math.abs));
    for(let axis=0;axis<3;axis++){delta[at+axis]=sphere[at+axis]/maximum*half-sphere[at+axis];denominator+=delta[at+axis]**2;}
  }
  function effectiveWeight(object){
    for(let parent=object;parent;parent=parent.parent)if(!parent.visible)return 0;
    const materials=Array.isArray(object.material)?object.material:[object.material];
    const color=materials.filter(material=>material.visible&&material.colorWrite!==false);
    for(const material of color)if(material.opacity<1-epsilon)assert(material.transparent,'A fade opacity must actually enable blending.');
    return Math.max(0,...color.map(material=>material.opacity));
  }
  const objects=[checker,...cubies],vector=new THREE.Vector3();
  async function snapshot(time,project=false){
    await world.update(time);world.scene.updateMatrixWorld(true);world.camera.updateMatrixWorld(true);
    assert(world.camera.isOrthographicCamera,'Zoom metric uses the actual orthographic projection.');
    const positions=checker.geometry.getAttribute('position');assert.equal(positions.array.length,sphere.length);
    let numerator=0;for(let at=0;at<sphere.length;at++)numerator+=(positions.array[at]-sphere[at])*delta[at];
    const morph=numerator/denominator;let residual=0;
    for(let at=0;at<sphere.length;at++)residual=Math.max(residual,Math.abs(positions.array[at]-sphere[at]-morph*delta[at]));
    const weights=objects.map(effectiveWeight),scale=checker.getWorldScale(new THREE.Vector3());
    const opticalScale=scale.x*Math.abs(world.camera.projectionMatrix.elements[0])*width/2;
    const result={time,morph,residual,opticalScale,weights,checkerMatrix:checker.matrixWorld.elements.slice(),rootMatrix:root.matrixWorld.elements.slice(),projected:{}};
    if(project)for(let item=0;item<objects.length;item++){
      if(weights[item]<1e-5)continue;
      const object=objects[item],attribute=object.geometry.getAttribute('position');
      const matrix=world.camera.projectionMatrix.clone().multiply(world.camera.matrixWorldInverse).multiply(object.matrixWorld);
      const values=[];
      for(let vertex=0;vertex<attribute.count;vertex++){vector.fromBufferAttribute(attribute,vertex).applyMatrix4(matrix);values.push((vector.x+1)*width/2,(1-vector.y)*height/2);}
      result.projected[object.name]=values;
    }
    return result;
  }
  const sampleTimes=[...new Set([...Array.from({length:157},(_,i)=>i/25),0,2.96,3,3.4,4,4.4,5.4,5.8,6.2])].sort((a,b)=>a-b);
  const samples=[];
  for(const time of sampleTimes){
    const sample=await snapshot(time);
    if(sample.weights[0]>1e-5){
      assert(sample.residual<5e-5,'Actual positions do not follow the sphere-to-cube morph.');
      if(time<=times.peak)close(sample.morph,0,'Sphere must remain unmorphed during zoom-in');
      if(time>=times.morphEnd)close(sample.morph,1,'Cube must be formed before the Rubik fade');
    }
    samples.push(sample);
  }
  const zoom=samples.filter(s=>s.time>=times.zoomStart&&s.time<=times.peak);
  const morph=samples.filter(s=>s.time>=times.peak&&s.time<=times.morphEnd);
  for(let i=1;i<zoom.length;i++)assert(zoom[i].opticalScale>=zoom[i-1].opticalScale-epsilon,'Actual zoom-in reversed.');
  let morphingWhileZoomingOut=0;
  for(let i=1;i<morph.length;i++){
    assert(morph[i].opticalScale<=morph[i-1].opticalScale+epsilon,'Morph zoom-out reversed.');
    assert(morph[i].morph>=morph[i-1].morph-epsilon,'Morph shape reversed.');
    if(morph[i].morph-morph[i-1].morph>1e-5){assert(morph[i].opticalScale<morph[i-1].opticalScale-epsilon,'Morph changed without actual zoom-out.');morphingWhileZoomingOut++;}
  }
  assert(morphingWhileZoomingOut>10);
  const peak=await snapshot(times.peak,true),vertices=peak.projected[checker.name];assert(vertices);
  const xs=vertices.filter((_,i)=>i%2===0),ys=vertices.filter((_,i)=>i%2===1);
  const bounds={left:Math.min(...xs),right:Math.max(...xs),top:Math.min(...ys),bottom:Math.max(...ys)};
  const peakFrame=Math.round(times.peak*metadata.fps),edges=[];
  const at=(x,y)=>bit(mask,peakFrame*width*height+y*width+x);
  if(Array.from({length:width},(_,x)=>at(x,0)).some(Boolean))edges.push('top');
  if(Array.from({length:width},(_,x)=>at(x,height-1)).some(Boolean))edges.push('bottom');
  if(Array.from({length:height},(_,y)=>at(0,y)).some(Boolean))edges.push('left');
  if(Array.from({length:height},(_,y)=>at(width-1,y)).some(Boolean))edges.push('right');
  assert(edges.length>0,'Actual peak sphere mask must reach a screen edge.');
  assert(bounds.left<0||bounds.right>width||bounds.top<0||bounds.bottom>height,'Actual peak sphere vertices must cross the screen boundary.');
  const fade=samples.filter(s=>s.time>=times.morphEnd&&s.time<=times.revealEnd);
  assert(fade.filter(s=>s.weights[0]>0.01&&s.weights[0]<0.99).length>=8,'Checker-to-Rubik appearance still cuts abruptly.');
  let largestOpacityStep=0;
  for(let i=0;i<fade.length;i++){
    const sample=fade[i],rubik=sample.weights.slice(1);
    for(const weight of rubik)close(weight,rubik[0],'All actual cubies must share the fade weight');
    close(sample.weights[0]+rubik[0],1,'Actual additive checker/Rubik weights must sum to one');
    if(sample.weights[0]>1e-5&&rubik[0]>1e-5)arrayClose(sample.checkerMatrix,sample.rootMatrix,'Both actual fade poses must coincide');
    if(i)for(let j=0;j<sample.weights.length;j++)largestOpacityStep=Math.max(largestOpacityStep,Math.abs(sample.weights[j]-fade[i-1].weights[j]));
  }
  assert(largestOpacityStep<0.12,'Actual fade changes too much in one rendered interval.');
  const boundaries=[];
  for(const time of [times.zoomStart,times.peak,times.morphEnd,times.revealEnd]){
    const before=await snapshot(time-1e-5,true),after=await snapshot(time+1e-5,true);
    let opacityJump=0,pixelJump=0;
    for(let i=0;i<before.weights.length;i++)opacityJump=Math.max(opacityJump,Math.abs(before.weights[i]-after.weights[i]));
    for(const [name,a]of Object.entries(before.projected))if(after.projected[name]){const b=after.projected[name];assert.equal(a.length,b.length);for(let i=0;i<a.length;i++)pixelJump=Math.max(pixelJump,Math.abs(a[i]-b[i]));}
    assert(opacityJump<0.002,`Appearance pops at ${time}s`);assert(pixelJump<0.025,`Actual projected pose jumps at ${time}s`);
    boundaries.push({time,opacityJump,maximumProjectedVertexJumpLogicalPixels:pixelJump});
  }
  const seekTimes=[0,2.96,3.4,4,4.4,5.4,5.8,6.2];
  for(const time of seekTimes){
    await world.update(9.96);const actual=await snapshot(time),baseline=samples.find(s=>s.time===time);assert(baseline);
    close(actual.morph,baseline.morph,'Backseek actual morphology');close(actual.opticalScale,baseline.opticalScale,'Backseek actual zoom');
    arrayClose(actual.weights,baseline.weights,'Backseek actual appearance');arrayClose(actual.checkerMatrix,baseline.checkerMatrix,'Backseek actual checker pose');arrayClose(actual.rootMatrix,baseline.rootMatrix,'Backseek actual Rubik pose');
  }
  return{pass:true,peakFrame,peakTime:times.peak,peakSphereMorph:peak.morph,peakPhysicalDiameter:2*radius*peak.opticalScale*2,
    actualProjectedBoundsLogicalPixels:bounds,actualMaskEdgesTouched:edges,morphingWhileZoomingOutSamples:morphingWhileZoomingOut,
    actualIntermediateFadeFrames:fade.filter(s=>s.weights[0]>0.01&&s.weights[0]<0.99).length,largestOpacityStep,boundaries,seekTimes,
    method:'Actual geometry fit, actual object/camera scale, projected vertices, material opacity, and GPU silhouette; no pose.morph or declared fade values.'};
}

async function verifyTurns(metadata) {
  const THREE = await import('three/webgpu');
  const factory = await import(pathToFileURL(metadata.sceneSource).href);
  const world = await factory.createScene(THREE);
  const root = world.scene.getObjectByName('rubik-cube');
  assert(root, 'The actual puzzle root is missing.');
  const cubies = [];
  root.traverse(object => {
    const match = /^cubie:(-1|0|1),(-1|0|1),(-1|0|1)$/.exec(object.name);
    if (match) {
      assert(object.isMesh, 'Cubie identity must belong to an actual rendered mesh.');
      cubies.push({object,id:object.name,home:match.slice(1).map(Number)});
    }
  });
  assert.equal(cubies.length, 27); assert.equal(new Set(cubies.map(c => c.id)).size, 27);
  const byId = new Map(cubies.map(c => [c.id,c]));
  function capture() {
    world.scene.updateMatrixWorld(true);
    const inverse = root.matrixWorld.clone().invert(), result = new Map();
    const geometries = new Map(), materials = new Map();
    for (const cubie of cubies) {
      const object = cubie.object, matrix = inverse.clone().multiply(object.matrixWorld);
      const position = new THREE.Vector3(), quaternion = new THREE.Quaternion(), scale = new THREE.Vector3();
      matrix.decompose(position,quaternion,scale);
      if (!geometries.has(object.geometry)) geometries.set(object.geometry,geometrySignature(object.geometry));
      const slots = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of slots) if (!materials.has(material)) materials.set(material,materialSignature(material));
      result.set(cubie.id,{matrix,position,quaternion,scale,
        appearance:JSON.stringify([geometries.get(object.geometry),slots.map(m => materials.get(m))])});
    }
    return result;
  }
  await world.update(times.topStart);
  assert(root.visible, 'The puzzle must be visible before its first turn.');
  const initial = capture(), ratios = [];
  for (const cubie of cubies) for (let axis = 0; axis < 3; axis++) if (cubie.home[axis]) {
    const ratio = initial.get(cubie.id).position.getComponent(axis) / cubie.home[axis];
    assert(ratio > 0); ratios.push(ratio);
  }
  const pitch = ratios.reduce((a,b) => a+b,0) / ratios.length;
  for (const ratio of ratios) close(ratio,pitch,'Initial cubic grid spacing');
  const identity = new THREE.Matrix4();
  for (const cubie of cubies) {
    const actual = initial.get(cubie.id);
    arrayClose(actual.position.toArray(),cubie.home.map(value => value*pitch),`${cubie.id} initial position`);
    arrayClose(new THREE.Matrix4().makeRotationFromQuaternion(actual.quaternion).elements,identity.elements,`${cubie.id} initial orientation`);
  }
  let stickerSlots = 0;
  for (const {object} of cubies) {
    assert.equal(object.geometry.type,'BoxGeometry');
    assert(Array.isArray(object.material) && object.material.length === 6);
    for (const material of object.material) {
      const hasColor = material.color.toArray().some(value => value > 0);
      const hasMapColor = !material.map || material.map.image.data.some((value,index) => index%4!==3 && value>0);
      stickerSlots += Number(hasColor && hasMapColor);
    }
  }
  assert.equal(stickerSlots,54,'A 3x3 puzzle needs 54 outward sticker faces.');
  const expected = (home,topAngle,leftAngle) => {
    const position = new THREE.Vector3(...home).multiplyScalar(pitch);
    let rotation = new THREE.Matrix4();
    if (home[1] === 1) { rotation.makeRotationY(topAngle); position.applyMatrix4(rotation); }
    // Membership is selected after the COMPLETE top move, not from home.x.
    const afterTopX = home[1] === 1 ? -home[2] : home[0];
    if (leftAngle !== 0 && afterTopX === -1) {
      const left = new THREE.Matrix4().makeRotationX(leftAngle);
      position.applyMatrix4(left); rotation.premultiply(left);
    }
    return {position,rotation};
  };
  function matrixFor(cubie,topAngle,leftAngle) {
    const pose = expected(cubie.home,topAngle,leftAngle);
    return new THREE.Matrix4().compose(pose.position,new THREE.Quaternion().setFromRotationMatrix(pose.rotation),initial.get(cubie.id).scale);
  }
  function angleFrom(actual,axis) {
    const m = new THREE.Matrix4().makeRotationFromQuaternion(actual.quaternion).elements;
    let angle = axis === 'y' ? Math.atan2(m[8],m[0]) : Math.atan2(m[6],m[5]);
    if (axis === 'x' && Math.abs(angle-Math.PI)<epsilon) angle=-Math.PI;
    return angle;
  }
  function direction(actual,axis,minimum,label) {
    const angle = angleFrom(actual,axis);
    assert(angle <= epsilon, `${label}: wrong positive rotation direction (${angle})`);
    assert(angle >= minimum-epsilon, `${label}: overshot requested turn (${angle})`);
    return angle;
  }
  function validate(time,actual) {
    let top = -Math.PI/2, left = 0;
    if (time <= times.topEnd) top = direction(actual.get('cubie:1,1,0'),'y',-Math.PI/2,'TOP_CW');
    if (time >= times.leftStart && time <= times.leftEnd) left = direction(actual.get('cubie:-1,0,0'),'x',-Math.PI,'LEFT_CCW');
    else if (time >= times.leftEnd) left=-Math.PI;
    for (const cubie of cubies) {
      const observed = actual.get(cubie.id);
      arrayClose(observed.matrix.elements,matrixFor(cubie,top,left).elements,`${cubie.id} at ${time}s`);
      assert.equal(observed.appearance,initial.get(cubie.id).appearance,`${cubie.id} sticker/geometry identity changed during a turn`);
    }
    return {top,left};
  }
  const topMid=(times.topStart+times.topEnd)/2, leftMid=(times.leftStart+times.leftEnd)/2;
  const anchors = new Map([[times.topStart,[0,0]],[topMid,[-Math.PI/4,0]],[times.topEnd,[-Math.PI/2,0]],
    [times.leftStart,[-Math.PI/2,0]],[leftMid,[-Math.PI/2,-Math.PI/2]],[times.leftEnd,[-Math.PI/2,-Math.PI]],[times.end,[-Math.PI/2,-Math.PI]]]);
  const samples = [...new Set([...Array.from({length:251},(_,i) => i/25).filter(t=>t>=times.topStart),...anchors.keys()])].sort((a,b)=>a-b);
  let previousTop=0, previousLeft=0;
  const anchorMeasurements=[];
  for (const time of samples) {
    await world.update(time); const actual=capture(), angles=validate(time,actual);
    if (time <= times.topEnd) {assert(angles.top<=previousTop+epsilon,'Top angle is not monotonic clockwise.');previousTop=angles.top;}
    if (time >= times.leftStart && time <= times.leftEnd) {assert(angles.left<=previousLeft+epsilon,'Left angle is not monotonic counterclockwise.');previousLeft=angles.left;}
    if (anchors.has(time)) {
      const [top,left]=anchors.get(time);close(angles.top,top,`Top requested angle at ${time}s`);close(angles.left,left,`Left requested angle at ${time}s`);
      anchorMeasurements.push({time,topRadians:angles.top,leftRadians:angles.left});
    }
  }
  await world.update(times.end); const final=capture();
  const finalPermutation=cubies.map(c => ({home:c.home,grid:final.get(c.id).position.toArray().map(value=>Math.round(value/pitch))}));
  assert.equal(new Set(finalPermutation.map(c=>c.grid.join(','))).size,27,'Final permutation overlaps cubies.');
  const seekTimes=[9.96,topMid,leftMid,times.topStart,times.leftEnd,times.leftStart,times.topEnd,leftMid];
  for (const time of seekTimes) {await world.update(time);const angles=validate(time,capture());if(anchors.has(time)){const pair=anchors.get(time);close(angles.top,pair[0],'Seek top angle');close(angles.left,pair[1],'Seek left angle');}}

  // Bounded negative control: create a coherent WRONG clockwise left half-turn
  // midpoint on real Three meshes, without modifying the scene module or flags.
  await world.update(leftMid);world.scene.updateMatrixWorld(true);
  const rootMatrix=root.matrixWorld.clone();
  for (const cubie of cubies) {
    const xAfterTop=cubie.home[1]===1?-cubie.home[2]:cubie.home[0];
    if(xAfterTop!==-1)continue;
    const desiredWorld=rootMatrix.clone().multiply(matrixFor(cubie,-Math.PI/2,Math.PI/2));
    const local=cubie.object.parent.matrixWorld.clone().invert().multiply(desiredWorld);
    cubie.object.matrixAutoUpdate=false;cubie.object.matrix.copy(local);cubie.object.matrixWorldNeedsUpdate=true;
  }
  let rejected=false,reason='';
  try {validate(leftMid,capture());} catch(error) {
    reason=error.message;rejected=/LEFT_CCW: wrong positive rotation direction/.test(reason);
  }
  assert(rejected,'Wrong-sign left-turn negative control was not rejected for its direction.');
  return {pass:true,cubies:27,outwardStickerSlots:stickerSlots,gridPitch:pitch,
    actualTransformSamples:samples.length,seekTimes,anchorMeasurements,
    top:{view:'+Y',direction:'clockwise',axis:'+Y',radians:-Math.PI/2,movingCubies:9},
    left:{view:'-X',direction:'counterclockwise',axis:'+X',radians:-Math.PI,movingCubies:9,selection:'current x=-1 after completed top turn'},
    stickerGeometryAndMaterialIdentityPreserved:true,finalPermutation,
    negativeControl:{wrongLeftClockwiseMidpointRejected:rejected,reason}};
}

export async function main(argv=process.argv.slice(2)) {
  const options={};
  for(let index=0;index<argv.length;index++) {
    const at=argv[index].indexOf('='),key=at<0?argv[index]:argv[index].slice(0,at);
    assert(['--input','--output','--baseline'].includes(key),`Unknown option ${key}`);
    options[key]=at<0?argv[++index]:argv[index].slice(at+1);assert(options[key],`Missing value for ${key}`);
  }
  assert(options['--input']&&options['--output'],'Use --input RAW --output REPORT.json [--baseline APPROVED.frames].');
  const input=path.resolve(options['--input']),output=path.resolve(options['--output']);
  const metadata=JSON.parse(fs.readFileSync(path.join(input,'metadata.json')));
  const {width,height,fps,frameCount}=metadata,pixels=width*height;
  assert.equal(width,160);assert.equal(height,100);assert.equal(fps,25);assert.equal(frameCount,250);
  assert.equal(metadata.bitOrder,'MSB-first');assert.equal(metadata.rowOrder,'top-to-bottom');assert.equal(metadata.quantization.mode,'ordered');
  assert.equal(metadata.renderer.browserUsed,false);assert.equal(metadata.renderer.canvasContextRequests,0);
  const movie=fs.readFileSync(path.resolve(input,metadata.framesFile)),rgba=fs.readFileSync(path.resolve(input,metadata.rgbaFile)),mask=fs.readFileSync(path.resolve(input,metadata.objectMaskFile));
  assert.equal(movie.length,pixels/8*frameCount);assert.equal(rgba.length,pixels*4*frameCount);assert.equal(mask.length,movie.length);
  assert.equal(sha(movie),metadata.hashes.frames);assert.equal(sha(rgba),metadata.hashes.rgba);assert.equal(sha(mask),metadata.hashes.objectMask);
  assert.equal(sha(fs.readFileSync(metadata.sceneSource)),metadata.sourceSha256);
  const prefix=movie.subarray(0,approvedFrames*pixels/8);assert.equal(sha(prefix),approvedHash,'The retained first75 entrance frames changed.');
  if(options['--baseline'])assert(prefix.equals(fs.readFileSync(path.resolve(options['--baseline'])).subarray(0,prefix.length)));
  let wrongBits=0,whiteOutsideMask=0,nonOpaquePixels=0,prefixIntermediatePixels=0,nonGrayscalePixels=0;
  const levels=new Uint32Array(256);
  for(let frame=0;frame<frameCount;frame++)for(let pixel=0;pixel<pixels;pixel++) {
    const index=frame*pixels+pixel,at=index*4,r=rgba[at],g=rgba[at+1],b=rgba[at+2],alpha=rgba[at+3];
    const luminance=(54*r+183*g+19*b)/256*alpha/255;
    const expected=Number(luminance >= (rank(pixel%width,Math.floor(pixel/width))+.5)*255/16),actual=bit(movie,index);
    wrongBits+=Number(expected!==actual);whiteOutsideMask+=Number(actual&&!bit(mask,index));nonOpaquePixels+=Number(alpha!==255);
    nonGrayscalePixels+=Number(r!==g||r!==b);levels[Math.round(luminance)]++;
    if(frame<approvedFrames)prefixIntermediatePixels+=Number(r!==g||r!==b||(r!==0&&r!==255));
  }
  assert.equal(wrongBits,0);assert.equal(whiteOutsideMask,0);assert.equal(nonOpaquePixels,0);assert.equal(prefixIntermediatePixels,0);
  const firstFrameBlack=movie.subarray(0,pixels/8).every(byte=>byte===0);assert(firstFrameBlack);
  const transition=await verifyEntranceAndTransition(metadata,mask);
  const turns=await verifyTurns(metadata);
  const report={pass:true,stage:'Three Rubik to ordered1-bit bitmap only',characterConversionRun:false,
    width,height,fps,frameCount,durationSeconds:frameCount/fps,sourceSha256:metadata.sourceSha256,
    bitmapSha256:sha(movie),rgbaSha256:sha(rgba),objectMaskSha256:sha(mask),
    approvedPrefix:{frames:approvedFrames,bitmapSha256:sha(prefix),unchanged:true},
    quantization:{mode:'ordered',pattern:'independent recursive4x4 Bayer',screenAnchored:true,rec709:[54,183,19],divisor:256},
    verification:{actualGpuReadback:metadata.verification.allFramesReadFromGPU,pixelsCompared:pixels*frameCount,
      wrongBits,whiteOutsideMask,nonOpaquePixels,prefixIntermediatePixels,nonGrayscalePixels,firstFrameBlack},
    luminanceLevels:Array.from(levels).flatMap((count,level)=>count?[{level,pixels:count}]:[]),transition,turns};
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({...report,luminanceLevels:undefined,turns:{...turns,finalPermutation:undefined}},null,2));
  return report;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href)main().catch(error=>{console.error(error);process.exitCode=1;});
