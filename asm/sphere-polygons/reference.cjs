'use strict';

function facesOf(projected) {
  return (Array.isArray(projected)?projected:projected.faces).filter(face=>face.visible!==false&&face.points&&face.points.length>=3);
}

// An independent even-odd ray-crossing point test. No scanline spans, coverage
// signatures or character-font decisions enter this reference evaluator.
function contains(points,x,y,ops) {
  let inside=false;
  for(let i=0;i<points.length;i++) {
    const a=points[i],b=points[(i+1)%points.length],cross=(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]);
    if(ops)ops.edgeTests++;
    if(Math.abs(cross)<1e-9&&x>=Math.min(a[0],b[0])-1e-9&&x<=Math.max(a[0],b[0])+1e-9&&y>=Math.min(a[1],b[1])-1e-9&&y<=Math.max(a[1],b[1])+1e-9)return true;
    if((a[1]>y)!==(b[1]>y)&&x<a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))inside=!inside;
  }
  return inside;
}

function bounds(points) {
  return{left:Math.min(...points.map(p=>p[0])),right:Math.max(...points.map(p=>p[0])),top:Math.min(...points.map(p=>p[1])),bottom:Math.max(...points.map(p=>p[1]))};
}

function projectedReference(projected,{width=320,height=200,pixelOffset=0}={}) {
  const pixels=new Uint8Array(width*height),inside=new Uint8Array(width*height),ops={pixelTests:0,edgeTests:0};
  const faces=facesOf(projected);
  for(const face of faces) {
    const b=bounds(face.points),x0=Math.max(0,Math.ceil(b.left-pixelOffset)),x1=Math.min(width-1,Math.floor(b.right-pixelOffset));
    const y0=Math.max(0,Math.ceil(b.top-pixelOffset)),y1=Math.min(height-1,Math.floor(b.bottom-pixelOffset));
    for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++) {
      ops.pixelTests++;
      if(!contains(face.points,x+pixelOffset,y+pixelOffset,ops))continue;
      const index=y*width+x;inside[index]=1;
      // Visible faces of the convex meshes share only edges. White wins at
      // exact shared boundaries, matching the union of white sample spans.
      if(face.color)pixels[index]=1;
    }
  }
  return{pixels,inside,area:inside.reduce((sum,value)=>sum+value,0),ops,visibleFaces:faces.length,whiteFaces:faces.filter(f=>f.color).length};
}

function reconstruct(screen,font) {
  const pixels=new Uint8Array(64000);
  for(let cell=0;cell<1000;cell++)for(let y=0;y<8;y++)for(let x=0;x<8;x++)pixels[(Math.floor(cell/40)*8+y)*320+(cell%40)*8+x]=(font.glyphs[screen[cell]].rows[y]>>>(7-x))&1;
  return pixels;
}

function compare(screen,font,reference,{cx=160,cy=100,radius=94,pixelOffset=0}={}) {
  const pixels=reconstruct(screen,font);let errors=0,polygonSpill=0,circleSpill=0;
  for(let y=0;y<200;y++)for(let x=0;x<320;x++) {
    const i=y*320+x;
    if(pixels[i]!==reference.pixels[i])errors++;
    if(pixels[i]&&!reference.inside[i])polygonSpill++;
    if(pixels[i]&&(x+pixelOffset-cx)**2+(y+pixelOffset-cy)**2>radius*radius)circleSpill++;
  }
  return{errors,error:errors/Math.max(1,reference.area),polygonSpill,circleSpill,usedGlyphs:new Set(screen).size};
}

module.exports={facesOf,bounds,contains,projectedReference,reconstruct,compare};

if(require.main===module) {
  const args=process.argv.slice(2),yaw=Number(args[1]),pitch=Number(args[2]);
  if(args.length<4||args.length>5||!['checker','football'].includes(args[0])||!Number.isInteger(yaw)||!Number.isInteger(pitch)||(args[4]&&args[4]!=='--float')) {
    console.error('Usage: node reference.cjs checker|football YAW PITCH OUTPUT [--float]');process.exitCode=1;
  }else {
    const geometry=require('./geometry.cjs'),projection=args[4]?geometry.projectFloat:geometry.project;
    require('node:fs').writeFileSync(require('node:path').resolve(args[3]),projectedReference(projection(args[0],yaw,pitch)).pixels);
  }
}
