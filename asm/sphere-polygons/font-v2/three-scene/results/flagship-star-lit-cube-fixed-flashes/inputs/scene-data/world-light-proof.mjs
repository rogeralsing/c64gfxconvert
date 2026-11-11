import assert from "node:assert/strict";
import fs from "node:fs";
import crypto from "node:crypto";
import * as THREE from "/Users/rogerjohansson/.codex/worktrees/c64-sphere-font-publish-20261109/c64/asm/sphere-polygons/font-v2/three-scene/node_modules/three/build/three.webgpu.js";
import {config, createScene} from "../../three-scene/demo-world-lit-cube-loop.mjs";
const world=createScene(THREE), mesh=world.scene.getObjectByName("fixed-gray-cube");
const p=mesh.geometry.getAttribute("position"), n=mesh.geometry.getAttribute("normal");
const c=mesh.geometry.getAttribute("color"), point=new THREE.Vector3(), normal=new THREE.Vector3(), ray=new THREE.Vector3(), nm=new THREE.Matrix3();
const light=new THREE.Vector3(...config.lighting.position), color=new THREE.Color();
const groups=new Map();
for(let i=0;i<p.count;i++) {
 const a=[n.getX(i),n.getY(i),n.getZ(i)];
 assert.equal(a.filter(v=>Math.abs(v)===1).length,1);assert.equal(a.filter(v=>v===0).length,2);
 const key=a.join(","), distance=p.getX(i)**2+p.getY(i)**2+p.getZ(i)**2;
 if(!groups.has(key)||groups.get(key).distance>distance)groups.set(key,{id:i,distance});
}
assert.equal(groups.size,6);
const faces=Object.fromEntries([...groups].map(([key,{id}])=>[key,{vertexId:id,levels:[]} ]));
let maximumLightingError=0, maximumLinearLightingError=0;
for(let frame=1;frame<=96;frame++) {
 world.update(frame/25);assert.deepEqual(world.scene.userData.pose.lightPositionWorld,config.lighting.position);
 nm.getNormalMatrix(mesh.matrixWorld);
 for(const face of Object.values(faces)) {
  const i=face.vertexId;
  point.fromBufferAttribute(p,i).applyMatrix4(mesh.matrixWorld);normal.fromBufferAttribute(n,i).applyNormalMatrix(nm);
  ray.subVectors(light,point);const d=ray.length();ray.multiplyScalar(1/d);
  const lambert=Math.max(0,normal.dot(ray));
  const expected=Math.min(255,24+245*Math.pow(lambert,1.35)*Math.pow(100/d,1.2));
  const expectedLinear=new THREE.Color().setRGB(expected/255,expected/255,expected/255,THREE.SRGBColorSpace).r;
  maximumLinearLightingError=Math.max(maximumLinearLightingError,Math.abs(expectedLinear-c.getX(i)));
  const measured=color.setRGB(c.getX(i),c.getY(i),c.getZ(i)).convertLinearToSRGB().r*255;
  maximumLightingError=Math.max(maximumLightingError,Math.abs(expected-measured));face.levels.push(measured);
 }
}
assert(maximumLinearLightingError<0.0000001);
assert(maximumLightingError<0.02);
for(const face of Object.values(faces)) {
 face.minimum=Math.min(...face.levels);face.maximum=Math.max(...face.levels);
 assert(face.maximum-face.minimum>100,"Each local face must change lighting as it rotates");
}
world.update(1/25);const first=Float32Array.from(c.array),q=mesh.quaternion.toArray();
world.update(97/25);const last=Float32Array.from(c.array);
assert(last.every((value,i)=>Math.abs(value-first[i])<0.000001));
assert(mesh.quaternion.toArray().every((value,i)=>Math.abs(value-q[i])<0.000001||Math.abs(value+q[i])<0.000001));
const proof={passed:true,worldLightFixedAcross96Poses:true,light:config.lighting,
 sixDistinctFlatFaceNormals:true,localFaceLightingChangesWithRotation:true,maximumLightingErrorSRGB:maximumLightingError,maximumLinearLightingError,
 noMaterialTexture:mesh.material.map===null,sourceVertexColorsRecomputedPerPose:true,loopEndpointColorsMatch:true,
 faceCenterMeasurements:faces,sourceSha256:crypto.createHash("sha256").update(fs.readFileSync(new URL("../../three-scene/demo-world-lit-cube-loop.mjs",import.meta.url))).digest("hex")};
fs.writeFileSync(new URL("world-light-proof.json",import.meta.url),JSON.stringify(proof,null,2)+"\n");
console.log(JSON.stringify({...proof,faceCenterMeasurements:undefined}));
