'use strict';

const {getMesh,roundSigned}=require('./meshes.cjs');
const CENTER_X=160,CENTER_Y=100,RADIUS=94;
const signed=value=>{value&=255;return value<128?value:value-256;};
const sine=angle=>roundSigned(64*Math.sin((angle&255)*2*Math.PI/256));
const quarterSquare=value=>Math.floor(signed(value)**2/256);
const multiply=(a,b)=>signed(quarterSquare(a+b)-quarterSquare(a-b));

function matrix(yaw,pitch,roll=0) {
  const sy=sine(yaw),cy=sine(yaw+64),sp=sine(pitch),cp=sine(pitch+64);
  const base={xx:cy,xy:0,xz:sy,yx:multiply(sp,sy),yy:cp,yz:-multiply(sp,cy),
    zx:-multiply(cp,sy),zy:sp,zz:multiply(cp,cy)};
  if(!(roll&255))return base;
  const sr=sine(roll),cr=sine(roll+64);
  return {...base,
    xx:signed(multiply(cr,base.xx)-multiply(sr,base.yx)),
    xy:signed(-multiply(sr,base.yy)),
    xz:signed(multiply(cr,base.xz)-multiply(sr,base.yz)),
    yx:signed(multiply(sr,base.xx)+multiply(cr,base.yx)),
    yy:multiply(cr,base.yy),
    yz:signed(multiply(sr,base.xz)+multiply(cr,base.yz))
  };
}

function product(coordinate,coefficient) {
  return signed(roundSigned(coordinate*signed(coefficient)*RADIUS/4096));
}

function coordinateValues(models) {
  if(!Array.isArray(models))models=[models];
  return [...new Set(models.flatMap(model=>getMesh(model).coordinateValues))].sort((a,b)=>a-b);
}

function productPages(values) {
  const bytes=new Uint8Array(values.length*256);
  values.forEach((coordinate,page)=>{for(let coefficient=0;coefficient<256;coefficient++)bytes[page*256+coefficient]=product(coordinate,coefficient)&255;});
  return bytes;
}

function assembleResult(mesh,x,y,depths) {
  const visible=Uint8Array.from(depths,depth=>Number(depth<0));
  const faces=mesh.faces.map((face,index)=>({...face,index,visible:Boolean(visible[index]),depth:depths[index],points:face.indices.map(vertex=>[x[vertex],y[vertex]])}));
  return {mesh,projectedX:x,projectedY:y,x,y,faceDepths:depths,visible,faces};
}

function project(model,yaw=0,pitch=0,roll=0) {
  const mesh=getMesh(model),m=matrix(yaw,pitch,roll),x=new Uint8Array(64),y=new Uint8Array(64);
  for(let vertex=0;vertex<mesh.verticesQ6.length;vertex++) {
    const [vx,vy,vz]=mesh.verticesQ6[vertex];
    // Saturation prevents positive X overflow from wrapping across the screen.
    // Such rounded vertices lie outside the radius-94 visible circle; its
    // character-safe contour table still owns the final display boundary.
    x[vertex]=Math.max(0,Math.min(255,CENTER_X+product(vx,m.xx)+product(vy,m.xy)+product(vz,m.xz)));
    y[vertex]=Math.max(0,Math.min(199,CENTER_Y-product(vx,m.yx)-product(vy,m.yy)-product(vz,m.yz)));
  }
  const depths=Int8Array.from(mesh.normalsQ6,([nx,ny,nz])=>signed(product(nx,m.zx)+product(ny,m.zy)+product(nz,m.zz)));
  return {...assembleResult(mesh,x,y,depths),matrix:m};
}

function projectFloat(model,yaw=0,pitch=0,roll=0) {
  const mesh=getMesh(model),ya=(yaw&255)*2*Math.PI/256,pa=(pitch&255)*2*Math.PI/256,ra=(roll&255)*2*Math.PI/256;
  const cy=Math.cos(ya),sy=Math.sin(ya),cp=Math.cos(pa),sp=Math.sin(pa);
  const cr=Math.cos(ra),sr=Math.sin(ra);
  const x=new Float64Array(64),y=new Float64Array(64);
  for(let vertex=0;vertex<mesh.vertices.length;vertex++) {
    const [vx,vy,vz]=mesh.vertices[vertex];
    const rx=cy*vx+sy*vz,ry=sp*sy*vx+cp*vy-sp*cy*vz;
    x[vertex]=CENTER_X+RADIUS*(cr*rx-sr*ry);
    y[vertex]=CENTER_Y-RADIUS*(sr*rx+cr*ry);
  }
  const depths=Float64Array.from(mesh.faces,face=>{
    const [nx,ny,nz]=face.normal;return RADIUS*(-cp*sy*nx+sp*ny+cp*cy*nz);
  });
  return assembleResult(mesh,x,y,depths);
}

module.exports={CENTER_X,CENTER_Y,RADIUS,signed,sine,multiply,matrix,product,coordinateValues,productPages,project,projectFloat};
