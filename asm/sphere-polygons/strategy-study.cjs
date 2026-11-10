'use strict';
const reference=require('./reference.cjs');
const math=require('../sphere-math/math-font.cjs');
const POSITIONS=[1,4,6];

function probesFor(count=8) {
  const probes=[];
  for(let y=0;y<3;y++)for(let x=0;x<3;x++)if(count===9||x!==1||y!==1)probes.push({x:POSITIONS[x],y:POSITIONS[y],row:y,column:x,bit:1<<probes.length});
  return probes;
}

function createProbeLut(font,count=8) {
  const probes=probesFor(count),signatures=font.glyphs.map(glyph=>probes.reduce((bits,p)=>bits|(((glyph.rows[p.y]>>>(7-p.x))&1)?p.bit:0),0));
  const bytes=new Uint8Array(1<<count);
  for(let bits=0;bits<bytes.length;bits++) {
    let best=Infinity,index=0;const density=math.popcount32(bits)/count;
    for(let glyph=0;glyph<font.count;glyph++) {
      const error=math.popcount32(bits^signatures[glyph])*100+Math.abs(font.glyphs[glyph].coverage-density);
      if(error<best){best=error;index=glyph;}
    }
    bytes[bits]=index;
  }
  return{bytes,probes,count,sourceGlyphs:Array.from(new Set(bytes)).sort((a,b)=>a-b)};
}

function createCircleClipper(font,lut,{cx=160,cy=100,radius=94,pixelOffset=0}={}) {
  const classes=[],indices=new Map(),tileClass=new Int16Array(1000);tileClass.fill(-1);
  for(let cell=0;cell<1000;cell++) {
    const x=(cell%40)*8,y=Math.floor(cell/40)*8;let lo=0,hi=0;
    for(let py=0;py<8;py++)for(let px=0;px<8;px++)if((x+px+pixelOffset-cx)**2+(y+py+pixelOffset-cy)**2<=radius*radius) {
      const bit=py*8+px;if(bit<32)lo|=1<<bit;else hi|=1<<(bit-32);
    }
    lo>>>=0;hi>>>=0;if(lo===0xffffffff&&hi===0xffffffff)continue;
    const allowed=[];
    for(let glyph=0;glyph<font.count;glyph++)if(((font.glyphs[glyph].lo&~lo)|(font.glyphs[glyph].hi&~hi))===0)allowed.push(glyph);
    const key=allowed.join(',');if(!indices.has(key)){indices.set(key,classes.length);classes.push(allowed);}tileClass[cell]=indices.get(key);
  }
  const compact=new Uint8Array(256);compact.fill(255);lut.sourceGlyphs.forEach((glyph,index)=>{compact[glyph]=index;});
  const bytes=new Uint8Array(classes.length*lut.sourceGlyphs.length);
  for(let group=0;group<classes.length;group++)for(let source=0;source<lut.sourceGlyphs.length;source++) {
    const original=font.glyphs[lut.sourceGlyphs[source]];let best=65,index=0;
    for(const glyph of classes[group]) {
      const candidate=font.glyphs[glyph],error=math.popcount32(original.lo^candidate.lo)+math.popcount32(original.hi^candidate.hi);
      if(error<best){best=error;index=glyph;}
    }
    bytes[group*lut.sourceGlyphs.length+source]=index;
  }
  return{classes:classes.length,bytes,compact,tileClass,tableBytes:bytes.length+compact.length,remap(screen){
    const output=Uint8Array.from(screen);
    for(let cell=0;cell<1000;cell++)if(tileClass[cell]>=0)output[cell]=bytes[tileClass[cell]*lut.sourceGlyphs.length+compact[screen[cell]]];
    return output;
  }};
}

function edgeContains(points,x,y,ops) {
  let inside=false;
  for(let i=0;i<points.length;i++) {
    const a=points[i],b=points[(i+1)%points.length],cross=(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]);ops.edgeTests++;
    if(Math.abs(cross)<1e-9&&x>=Math.min(a[0],b[0])-1e-9&&x<=Math.max(a[0],b[0])+1e-9&&y>=Math.min(a[1],b[1])-1e-9&&y<=Math.max(a[1],b[1])+1e-9)return true;
    // Use cross-product signs instead of ray-intersection division. Even-odd
    // parity also handles almost edge-on faces folded by Q3 quantization.
    if((a[1]>y)!==(b[1]>y)&&((b[1]>a[1]&&cross>0)||(b[1]<a[1]&&cross<0)))inside=!inside;
  }
  return inside;
}

function createStrategy({font=math.generateFont(256),probeCount=8,circleClip=true,geometry={}}={}) {
  const lut=createProbeLut(font,probeCount),clipper=circleClip?createCircleClipper(font,lut,geometry):null;
  const finish=(coverage,ops)=>{
    let screen=Uint8Array.from(coverage,bits=>lut.bytes[bits]);
    if(clipper)screen=clipper.remap(screen);
    return{screen,coverage,ops};
  };
  function renderSpans(projected) {
    const coverage=probeCount===8?new Uint8Array(1000):new Uint16Array(1000);
    const ops={faceCount:0,scanlineEdgeTests:0,intersections:0,spanCellTests:0,probeTests:0,coverageWrites:0};
    for(const face of reference.facesOf(projected)) {
      if(!face.color)continue;ops.faceCount++;
      const bounds=reference.bounds(face.points),row0=Math.max(0,Math.floor(bounds.top/8)),row1=Math.min(24,Math.floor(bounds.bottom/8));
      for(let row=row0;row<=row1;row++)for(let sampleY=0;sampleY<3;sampleY++) {
        const y=row*8+POSITIONS[sampleY];if(y<bounds.top||y>bounds.bottom)continue;
        let left=Infinity,right=-Infinity;
        for(let edge=0;edge<face.points.length;edge++) {
          const a=face.points[edge],b=face.points[(edge+1)%face.points.length];ops.scanlineEdgeTests++;
          if(y<Math.min(a[1],b[1])||y>Math.max(a[1],b[1]))continue;
          if(a[1]===b[1]){left=Math.min(left,a[0],b[0]);right=Math.max(right,a[0],b[0]);continue;}
          const x=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]);ops.intersections++;left=Math.min(left,x);right=Math.max(right,x);
        }
        if(!Number.isFinite(left))continue;
        const col0=Math.max(0,Math.floor(left/8)),col1=Math.min(39,Math.floor(right/8));
        for(let column=col0;column<=col1;column++) {
          const index=row*40+column;let bits=0;ops.spanCellTests++;
          for(const p of lut.probes)if(p.row===sampleY) {
            const x=column*8+p.x;ops.probeTests++;
            if(x>=left-1e-9&&x<=right+1e-9)bits|=p.bit;
          }
          if(bits){coverage[index]|=bits;ops.coverageWrites++;}
        }
      }
    }
    return finish(coverage,ops);
  }
  function renderPoints(projected) {
    const coverage=probeCount===8?new Uint8Array(1000):new Uint16Array(1000),ops={faceCount:0,bboxCells:0,probeTests:0,edgeTests:0,coverageWrites:0};
    for(const face of reference.facesOf(projected)) {
      if(!face.color)continue;ops.faceCount++;
      const bounds=reference.bounds(face.points),x0=Math.max(0,Math.floor(bounds.left/8)),x1=Math.min(39,Math.floor(bounds.right/8));
      const y0=Math.max(0,Math.floor(bounds.top/8)),y1=Math.min(24,Math.floor(bounds.bottom/8));
      for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++) {
        let bits=0;ops.bboxCells++;
        for(const p of lut.probes){ops.probeTests++;if(edgeContains(face.points,x*8+p.x,y*8+p.y,ops))bits|=p.bit;}
        if(bits){coverage[y*40+x]|=bits;ops.coverageWrites++;}
      }
    }
    return finish(coverage,ops);
  }
  return{font,lut,clipper,probeCount,coverageBytes:probeCount===8?1000:2000,tableBytes:lut.bytes.length+(clipper?clipper.tableBytes:0),renderSpans,renderPoints};
}

function study(mesh,geometry,{poses=16,pitch=24}={}) {
  const strategies=[8,9].map(probeCount=>createStrategy({probeCount}));
  const rows=[];
  for(let pose=0;pose<poses;pose++) {
    const yaw=Math.floor(pose*256/poses),projected=geometry.project(mesh,yaw,pitch),floating=geometry.projectFloat(mesh,yaw,pitch);
    const refs={quantized:reference.projectedReference(projected),floating:reference.projectedReference(floating)};
    const result={yaw,pitch,faces:refs.quantized.visibleFaces,whiteFaces:refs.quantized.whiteFaces,methods:[]};
    for(const strategy of strategies) {
      const start=performance.now(),span=strategy.renderSpans(projected),milliseconds=performance.now()-start;
      const points=strategy.renderPoints(projected);let sampleDifferences=0;
      for(let i=0;i<1000;i++)sampleDifferences+=span.coverage[i]!==points.coverage[i];
      result.methods.push({probes:strategy.probeCount,quantized:reference.compare(span.screen,strategy.font,refs.quantized),floating:reference.compare(span.screen,strategy.font,refs.floating),spanOps:span.ops,pointOps:points.ops,sampleDifferences,hostMilliseconds:milliseconds});
    }
    rows.push(result);
  }
  return{mesh:mesh.name||mesh.kind||'mesh',poses,pitch,strategies:strategies.map(s=>{
    const methods=rows.map(r=>r.methods.find(m=>m.probes===s.probeCount)),mean=fn=>methods.reduce((sum,m)=>sum+fn(m),0)/poses;
    return{probes:s.probeCount,lutBytes:s.lut.bytes.length,sourceGlyphs:s.lut.sourceGlyphs.length,clipClasses:s.clipper?s.clipper.classes:0,tableBytes:s.tableBytes,coverageBytes:s.coverageBytes,meanQuantizedError:mean(m=>m.quantized.error),meanFloatingError:mean(m=>m.floating.error),maxCircleSpill:Math.max(...methods.map(m=>m.quantized.circleSpill)),sampleDifferences:methods.reduce((sum,m)=>sum+m.sampleDifferences,0),meanSpanEdgeTests:mean(m=>m.spanOps.scanlineEdgeTests),meanSpanProbeTests:mean(m=>m.spanOps.probeTests),meanPointEdgeTests:mean(m=>m.pointOps.edgeTests),meanPointProbeTests:mean(m=>m.pointOps.probeTests)};
  }),rows};
}

module.exports={probesFor,createProbeLut,createCircleClipper,createStrategy,study};
if(require.main===module) {
  const meshes=require('./meshes.cjs'),geometry=require('./geometry.cjs');
  const names=process.argv[2]?[process.argv[2]]:['checker','football'],poses=Number(process.argv[3]||16);
  for(const name of names) {
    const result=study(meshes.getMesh(name),geometry,{poses});
    console.log(JSON.stringify({mesh:name,poses:result.poses,pitch:result.pitch,strategies:result.strategies},null,2));
  }
}
