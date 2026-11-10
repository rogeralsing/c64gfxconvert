'use strict';
// Render the checker symmetry period offline with sub-byte angular precision.
// Playback remains a character movie; no geometry runs on the C64.
const assert=require('node:assert/strict');
const {BASE}=require('../common.cjs');
const {getMesh}=require(BASE+'/meshes.cjs');
const raster=require(BASE+'/raster.cjs');
const {createModel}=require(BASE+'/native-model.cjs');
function makeMotion(){
 const model=createModel(),mesh=getMesh('checker'),pitch=22*Math.PI/180,roll=12*Math.PI/180;
 const cp=Math.cos(pitch),sp=Math.sin(pitch),cr=Math.cos(roll),sr=Math.sin(roll);
 function frame(yawDegrees){
  const yaw=yawDegrees*Math.PI/180,cy=Math.cos(yaw),sy=Math.sin(yaw),x=new Uint8Array(64),y=new Uint8Array(64);
  mesh.vertices.forEach(([vx,vy,vz],i)=>{const rx=cy*vx+sy*vz,ry=sp*sy*vx+cp*vy-sp*cy*vz;x[i]=Math.floor(160+94*(cr*rx-sr*ry)+0.5+1e-10);y[i]=Math.floor(100-94*(sr*rx+cr*ry)+0.5+1e-10);});
  const faces=mesh.faces.map(face=>({...face,visible:(-cp*sy*face.normal[0]+sp*face.normal[1]+cp*cy*face.normal[2]) < -1e-10}));
  const coverage=raster.rasterize(x,y,faces,{tables:model.tables}).coverage;
  return model.resolve(coverage);
 }
 assert.deepEqual(frame(0),frame(60),'The 60-degree checker symmetry must close exactly.');
 const frames=Array.from({length:64},(_,i)=>frame(i*60/64));
 return{frames,motion:{kind:'fixed-axis-symmetry-loop',yawDegreesPerFrame:60/64,pitchDegrees:22,rollDegrees:12,symmetryPeriodDegrees:60,frames:64,fullRevolutionFrames:384,fullRevolutionSecondsAt50Fps:7.68,subByteAnglePrecision:true,loopEndpointMatches:true}};
}
module.exports={makeMotion};
