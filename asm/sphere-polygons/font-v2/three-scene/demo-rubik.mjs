// Reuse the approved entrance, then operate on27 physical cubie meshes.
import {config as approvedConfig, createScene as createApprovedScene} from './demo.mjs';

export const timeline = Object.freeze({entranceEnd:3, zoomPeak:4, morphStart:4, morphEnd:5.4,
  rubikBlendStart:5.4, rubikBlendEnd:6.2, peakDiameter:270, cubeDiameter:96});
export const moves = Object.freeze([
  Object.freeze({name:'upper-clockwise', axis:'y', layer:1, quarterTurns:-1, start:6.3, end:7.1}),
  Object.freeze({name:'left-counterclockwise-twice', axis:'x', layer:-1, quarterTurns:-2, start:7.35, end:9.1}),
]);

const grayContrast = 1.15;
const faces = Object.freeze([
  {id:'R', axis:0, sign:1, normal:[1,0,0], gray:176},
  {id:'L', axis:0, sign:-1, normal:[-1,0,0], gray:112},
  {id:'U', axis:1, sign:1, normal:[0,1,0], gray:208},
  {id:'D', axis:1, sign:-1, normal:[0,-1,0], gray:48},
  {id:'F', axis:2, sign:1, normal:[0,0,1], gray:144},
  {id:'B', axis:2, sign:-1, normal:[0,0,-1], gray:80},
]);
export const config = Object.freeze({
  ...approvedConfig,
  name:'checker-to-rubik', title:'Schackboll till Rubiks kub',
  description:'Schackbollen zoomas nära och blir en kub under utzoomningen. Kuben tonas mjukt till en 3 × 3-kub. Övre lagret vrids 90° medurs sett ovanifrån, sedan vänstra lagret 180° moturs sett från vänster.',
  durationSeconds:10, grayContrast, approvedPrefixFrames:75,
  phaseLabels:{...approvedConfig.phaseLabels, zoom:'Sfären zoomas in', 'zoom-morph':'Zoomar ut och blir kub',
    'rubik-reveal':'Tonas till Rubiks kub', 'upper-turn':'Övre lagret 90° medurs',
    'upper-hold':'Övre vridningen klar', 'left-turn':'Vänstra lagret 180° moturs', 'rubik-hold':'Båda vridningarna klara'},
  moves, timeline,
  faceIdentitySRGB:Object.fromEntries(faces.map(face=>[face.id,face.gray])),
  moveConvention:'Högerhänta kubkoordinater: medurs sett från +Y är en negativ Y-rotation; moturs sett från −X är en negativ X-rotation.',
});

const clamp = value => Math.max(0,Math.min(1,value));
const smooth = value => value*value*(3-2*value);
const interpolate = (start,end,startRate,endRate,progress,duration) => {
  const p2=progress*progress,p3=p2*progress;
  return (2*p3-3*p2+1)*start+(p3-2*p2+progress)*startRate*duration
    +(-2*p3+3*p2)*end+(p3-p2)*endRate*duration;
};
const angles = t => ({yaw:0.5+0.9*t+0.18*Math.sin(1.4*t),pitch:0.35+1.2*t,
  roll:0.15+0.75*t+0.22*Math.sin(1.1*t)});
const identity = [1,0,0,0,1,0,0,0,1];
const contrast = value => Math.max(0,Math.min(255,128+(value-128)*grayContrast));
function multiply(a,b) {
  const result=Array(9).fill(0);
  for(let row=0;row<3;row++)for(let column=0;column<3;column++)for(let k=0;k<3;k++)result[row*3+column]+=a[row*3+k]*b[k*3+column];
  return result;
}
function rotate(matrix,position) {
  return [0,1,2].map(row=>matrix[row*3]*position[0]+matrix[row*3+1]*position[1]+matrix[row*3+2]*position[2]);
}
function exactTurn(move) {
  // Both requested moves use negative right-handed rotations. Integer
  // quarter-turn matrices avoid coordinate drift and preserve cubie identity.
  const quarter=move.axis==='y'?[0,0,-1,0,1,0,1,0,0]:[1,0,0,0,0,1,0,-1,0];
  let result=identity.slice();
  for(let turn=0;turn<-move.quarterTurns;turn++)result=multiply(quarter,result);
  return result;
}
function stateAt(time,homes) {
  const states=homes.map(home=>({home,grid:home.slice(),orientation:identity.slice()}));
  let active=null,completedMoves=0;
  for(const move of moves) {
    const axis=move.axis==='x'?0:1;
    if(time>=move.end) {
      const rotation=exactTurn(move);
      for(const state of states)if(state.grid[axis]===move.layer) {
        state.grid=rotate(rotation,state.grid);state.orientation=multiply(rotation,state.orientation);
      }
      completedMoves++;
    } else if(time>move.start) {
      const progress=smooth(clamp((time-move.start)/(move.end-move.start)));
      active={...move,progress,angle:move.quarterTurns*Math.PI/2*progress,axisIndex:axis};
      break;
    } else break;
  }
  return {states,active,completedMoves};
}

function stickerTexture(THREE) {
  const size=32,pixels=new Uint8Array(size*size*4);
  for(let y=0;y<size;y++)for(let x=0;x<size;x++) {
    const at=(y*size+x)*4,value=x===0||y===0||x===size-1||y===size-1?0:255;
    pixels[at]=pixels[at+1]=pixels[at+2]=value;pixels[at+3]=255;
  }
  const texture=new THREE.DataTexture(pixels,size,size,THREE.RGBAFormat,THREE.UnsignedByteType);
  texture.name='rubik-sticker-black-border';texture.colorSpace=THREE.SRGBColorSpace;
  texture.minFilter=texture.magFilter=THREE.NearestFilter;texture.generateMipmaps=false;texture.needsUpdate=true;
  return texture;
}

export function createScene(THREE) {
  const approved=createApprovedScene(THREE), original=approved.scene.getObjectByName('morphing-sphere-cube');
  const originalGeometry=original.geometry, originalPositions=originalGeometry.getAttribute('position');
  const spherePositions=Float32Array.from(originalPositions.array);
  const sphereNormals=Float32Array.from(originalGeometry.getAttribute('normal').array);
  approved.update(5);
  const cubePositions=Float32Array.from(originalPositions.array);
  const settledQuaternion=new THREE.Quaternion().setFromEuler(new THREE.Euler(0.55,0.68,0,'ZXY'));
  const settleStart=angles(timeline.morphStart), settleDuration=timeline.morphEnd-timeline.morphStart;
  const settleRates={yaw:0.9+0.252*Math.cos(1.4*timeline.morphStart),pitch:1.2,
    roll:0.75+0.242*Math.cos(1.1*timeline.morphStart)};
  const settleEnd={yaw:0.68+2*Math.PI,pitch:0.55+2*Math.PI,roll:0};
  // The old surface and Rubik front surface are blended over black in linear
  // light. A depth-only cubie pass prevents rear plastic/stickers contributing.
  original.material.transparent=true;original.material.depthTest=false;original.material.depthWrite=false;
  original.renderOrder=0;
  const halfSide=24/Math.sqrt(3),pitch=2*halfSide/3;
  const geometry=new THREE.BoxGeometry(1,1,1);
  geometry.name='rubik-unit-cubie';
  const colors=new Float32Array(geometry.getAttribute('position').count*3),normal=geometry.getAttribute('normal'),uv=geometry.getAttribute('uv');
  for(let vertex=0;vertex<normal.count;vertex++) {
    const values=[normal.getX(vertex),normal.getY(vertex),normal.getZ(vertex)];
    const face=faces.find(face=>values[face.axis]===face.sign);
    const low=contrast(face.gray-10)/255,high=contrast(face.gray+10)/255;
    const lowLinear=new THREE.Color().setRGB(low,low,low,THREE.SRGBColorSpace).r;
    const highLinear=new THREE.Color().setRGB(high,high,high,THREE.SRGBColorSpace).r;
    const q=(uv.getX(vertex)+1-uv.getY(vertex))/2;
    const light=(1-q)*highLinear+q*lowLinear;
    colors.fill(light,vertex*3,vertex*3+3);
  }
  geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));
  const sticker=new THREE.MeshBasicMaterial({color:0xffffff,map:stickerTexture(THREE),vertexColors:true,toneMapped:false,
    transparent:true,opacity:0,blending:THREE.AdditiveBlending,depthWrite:false,depthFunc:THREE.LessEqualDepth});
  sticker.name='rubik-sticker-gradient';
  const plastic=new THREE.MeshBasicMaterial({color:0x000000,toneMapped:false,transparent:true,opacity:0,
    blending:THREE.AdditiveBlending,depthWrite:false,depthFunc:THREE.LessEqualDepth});plastic.name='rubik-black-plastic';
  const depthMaterial=new THREE.MeshBasicMaterial({color:0xffffff,colorWrite:false,depthWrite:true});
  depthMaterial.name='rubik-depth-only';
  const root=new THREE.Group();root.name='rubik-cube';root.visible=false;
  approved.scene.add(root);
  const homes=[],cubies=[];
  for(let x=-1;x<=1;x++)for(let y=-1;y<=1;y++)for(let z=-1;z<=1;z++) {
    const home=[x,y,z],stickerFaces=faces.filter(face=>home[face.axis]===face.sign);
    const mesh=new THREE.Mesh(geometry,faces.map(face=>home[face.axis]===face.sign?sticker:plastic));
    mesh.name=`cubie:${x},${y},${z}`;
    mesh.userData.home=home.slice();
    mesh.userData.stickers=stickerFaces.map(face=>({id:face.id,normal:face.normal.slice(),graySRGB:face.gray}));
    mesh.renderOrder=1;
    const depth=new THREE.Mesh(geometry,depthMaterial);depth.name=`depth-only:${mesh.name}`;depth.renderOrder=-1;
    mesh.add(depth);
    homes.push(home);cubies.push(mesh);root.add(mesh);
  }
  const orientationMatrix=new THREE.Matrix4(),turnQuaternion=new THREE.Quaternion();
  const axisX=new THREE.Vector3(1,0,0),axisY=new THREE.Vector3(0,1,0);
  function update(time) {
    const t=Math.max(0,Math.min(config.durationSeconds,Number.isFinite(time)?time:0));
    approved.update(Math.min(t,timeline.entranceEnd));
    let diameter=approved.scene.userData.pose.diameter,centerX=approved.scene.userData.pose.centerX,centerY=approved.scene.userData.pose.centerY;
    if(t>timeline.entranceEnd&&t<timeline.zoomPeak) {
      const p=(t-timeline.entranceEnd)/(timeline.zoomPeak-timeline.entranceEnd);
      diameter=interpolate(96,timeline.peakDiameter,92/3,0,p,timeline.zoomPeak-timeline.entranceEnd);
      centerX=210-50*smooth(p);centerY=100;
    } else if(t>=timeline.zoomPeak) {
      const p=smooth(clamp((t-timeline.zoomPeak)/(timeline.morphEnd-timeline.zoomPeak)));
      diameter=timeline.peakDiameter+(timeline.cubeDiameter-timeline.peakDiameter)*p;
      centerX=160+50*p;centerY=100;
    }
    const morph=smooth(clamp((t-timeline.morphStart)/(timeline.morphEnd-timeline.morphStart)));
    // Always restore the positions explicitly: approved.update() caches its own
    // morph and would otherwise retain our later geometry after a backward seek.
    if(morph===0)originalPositions.array.set(spherePositions);
    else if(morph===1)originalPositions.array.set(cubePositions);
    else for(let at=0;at<originalPositions.array.length;at++)originalPositions.array[at]=spherePositions[at]+(cubePositions[at]-spherePositions[at])*morph;
    originalPositions.needsUpdate=true;
    if(morph===0){originalGeometry.getAttribute('normal').array.set(sphereNormals);originalGeometry.getAttribute('normal').needsUpdate=true;}
    else originalGeometry.computeVertexNormals();
    originalGeometry.computeBoundingSphere();
    original.position.set((centerX-160)/2,(100-centerY)/2,0);original.scale.setScalar(diameter/96);
    let rotation=angles(t);
    if(t>=timeline.morphStart&&t<timeline.morphEnd) {
      const p=(t-timeline.morphStart)/settleDuration;
      rotation=Object.fromEntries(['yaw','pitch','roll'].map(axis=>[axis,
        interpolate(settleStart[axis],settleEnd[axis],settleRates[axis],0,p,settleDuration)]));
    }
    if(t>=timeline.morphEnd)original.quaternion.copy(settledQuaternion);
    else original.rotation.set(rotation.pitch,rotation.yaw,rotation.roll,'ZXY');
    root.position.copy(original.position);root.scale.copy(original.scale);root.quaternion.copy(original.quaternion);
    const reveal=smooth(clamp((t-timeline.rubikBlendStart)/(timeline.rubikBlendEnd-timeline.rubikBlendStart)));
    original.material.opacity=1-reveal;sticker.opacity=plastic.opacity=reveal;
    original.visible=t>0&&t<timeline.rubikBlendEnd;root.visible=t>timeline.rubikBlendStart;
    const {states,active,completedMoves}=stateAt(t,homes),bodySize=pitch-0.5*reveal;
    if(active)turnQuaternion.setFromAxisAngle(active.axis==='x'?axisX:axisY,active.angle);
    const activeIds=[];
    for(let index=0;index<cubies.length;index++) {
      const mesh=cubies[index],state=states[index],m=state.orientation;
      mesh.position.set(state.grid[0]*pitch,state.grid[1]*pitch,state.grid[2]*pitch);
      orientationMatrix.set(m[0],m[1],m[2],0,m[3],m[4],m[5],0,m[6],m[7],m[8],0,0,0,0,1);
      mesh.quaternion.setFromRotationMatrix(orientationMatrix);mesh.scale.setScalar(bodySize);
      const moving=active&&state.grid[active.axisIndex]===active.layer;
      if(moving){mesh.position.applyQuaternion(turnQuaternion);mesh.quaternion.premultiply(turnQuaternion);activeIds.push(mesh.name);}
      mesh.userData.grid=state.grid.slice();mesh.userData.orientation=state.orientation.slice();
      mesh.userData.activeTurn=moving?{axis:active.axis,angle:active.angle,progress:active.progress}:null;
    }
    if(t>=timeline.entranceEnd) {
      const phase=t<timeline.zoomPeak?'zoom':t<timeline.morphEnd?'zoom-morph':t<moves[0].start?'rubik-reveal'
        :t<moves[0].end?'upper-turn':t<moves[1].start?'upper-hold':t<moves[1].end?'left-turn':'rubik-hold';
      approved.scene.userData.pose={...approved.scene.userData.pose,time:t,phase,rubik:t>=timeline.rubikBlendStart,completedMoves,
        diameter,centerX,centerY,morph,rubikBlend:reveal,
        activeMove:active?.name??null,activeAngle:active?.angle??0,activeCubies:activeIds,
        readableOrientationSettled:t>=timeline.morphEnd,upperDirection:'medurs sett ovanifrån',leftDirection:'moturs sett från vänster'};
    }
    approved.scene.updateMatrixWorld(true);
  }
  update(0);
  return {scene:approved.scene,camera:approved.camera,update};
}
