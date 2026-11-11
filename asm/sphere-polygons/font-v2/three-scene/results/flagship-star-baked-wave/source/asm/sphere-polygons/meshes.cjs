'use strict';

const dot = (a,b) => a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const subtract = (a,b) => a.map((value,axis)=>value-b[axis]);
const normalize = a => { const length=Math.hypot(...a); return a.map(value=>value/length); };
const roundSigned = value => value<0 ? -Math.floor(-value+.5) : Math.floor(value+.5);

function finish(name,vertices,faces,metadata={}) {
  for(const face of faces) {
    const points=face.indices.map(index=>vertices[index]);
    const center=[0,1,2].map(axis=>points.reduce((sum,p)=>sum+p[axis],0)/points.length);
    let area=[0,0,0];
    for(let i=0;i<points.length;i++) {
      const term=cross(points[i],points[(i+1)%points.length]);
      area=area.map((value,axis)=>value+term[axis]);
    }
    if(dot(area,center)<0) {
      face.indices=[face.indices[0],...face.indices.slice(1).reverse()];
      area=area.map(value=>-value);
    }
    face.normal=face.normal ? normalize(face.normal) : normalize(area);
    if(dot(face.normal,center)<0) face.normal=face.normal.map(value=>-value);
    face.normalQ6=face.normal.map(value=>roundSigned(value*64));
  }
  const verticesQ6=vertices.map(point=>point.map(value=>roundSigned(value*64)));
  const normalsQ6=faces.map(face=>face.normalQ6);
  const coordinateValues=[...new Set([...verticesQ6.flat(),...normalsQ6.flat()])].sort((a,b)=>a-b);
  return {name,vertices,verticesQ6,normalsQ6,faces,coordinateValues,vertexCount:vertices.length,faceCount:faces.length,...metadata};
}

function makeChecker() {
  const longitudeCount=12,latitudeBands=6,vertices=[[0,1,0]],faces=[];
  for(let band=1;band<latitudeBands;band++) {
    const theta=band*Math.PI/latitudeBands;
    for(let longitude=0;longitude<longitudeCount;longitude++) {
      const lambda=longitude*2*Math.PI/longitudeCount;
      vertices.push([Math.sin(theta)*Math.sin(lambda),Math.cos(theta),Math.sin(theta)*Math.cos(lambda)]);
    }
  }
  const south=vertices.length;vertices.push([0,-1,0]);
  const ring=(band,longitude)=>1+(band-1)*longitudeCount+(longitude%longitudeCount);
  for(let band=0;band<latitudeBands;band++) for(let longitude=0;longitude<longitudeCount;longitude++) {
    const next=(longitude+1)%longitudeCount;
    const indices=band===0 ? [0,ring(1,longitude),ring(1,next)]
      : band===latitudeBands-1 ? [ring(band,longitude),south,ring(band,next)]
      : [ring(band,longitude),ring(band,next),ring(band+1,next),ring(band+1,longitude)];
    faces.push({indices,color:(longitude+band)&1,kind:indices.length===3?'triangle':'quad',longitude,band});
  }
  return finish('checker',vertices,faces,{longitudeCount,latitudeBands});
}

function makeFootball() {
  // Port of c64demo/experiments/sprite-ball/model.py: hexagons() and
  // write_gap_topology(). Keep the same rounded center/tangent construction,
  // then retain every pentagonal gap instead of limiting surfaces to sprites.
  const phi=(1+Math.sqrt(5))/2,corners=[];
  for(const a of [-1,1])for(const b of [-1,1])corners.push([0,a,b*phi]);
  for(const a of [-1,1])for(const b of [-1,1])corners.push([a,b*phi,0]);
  for(const a of [-1,1])for(const b of [-1,1])corners.push([a*phi,0,b]);
  const weights=[[1,1,0],[1,0,1],[1,-1,1],[1,-1,0],[1,0,-1],[1,1,-1]];
  const rawVertices=[],vertexMap=new Map(),faces=[];
  const scale=24/Math.hypot(...corners[0]);
  function vertexIndex(point) {
    const key=point.join(',');
    if(!vertexMap.has(key)){vertexMap.set(key,rawVertices.length);rawVertices.push(point);}
    return vertexMap.get(key);
  }
  function adjacent(a,b) { const d=subtract(a,b);return Math.abs(dot(d,d)-4)<1e-6; }
  for(let a=0;a<corners.length;a++)for(let b=a+1;b<corners.length;b++)for(let c=b+1;c<corners.length;c++) {
    const triangle=[corners[a],corners[b],corners[c]];
    if(!adjacent(triangle[0],triangle[1])||!adjacent(triangle[0],triangle[2])||!adjacent(triangle[1],triangle[2]))continue;
    const center=[0,1,2].map(axis=>triangle.reduce((sum,p)=>sum+p[axis],0)/3);
    const basis=[center.map(value=>roundSigned(value*scale)),
      subtract(triangle[0],triangle[2]).map(value=>roundSigned(value*scale/3)),
      subtract(triangle[1],triangle[2]).map(value=>roundSigned(value*scale/3))];
    const indices=weights.map(weight=>vertexIndex([0,1,2].map(axis=>weight.reduce((sum,value,i)=>sum+value*basis[i][axis],0))));
    faces.push({indices,color:1,kind:'hexagon',normal:normalize(center)});
  }
  const edges=new Map();
  for(const face of faces)for(let i=0;i<face.indices.length;i++) {
    const a=face.indices[i],b=face.indices[(i+1)%face.indices.length],key=[a,b].sort((x,y)=>x-y).join(',');
    const edge=edges.get(key)||{a,b,count:0};edge.count++;edges.set(key,edge);
  }
  const boundary=new Map();
  for(const edge of edges.values())if(edge.count===1) {
    for(const [a,b]of [[edge.a,edge.b],[edge.b,edge.a]]) {
      if(!boundary.has(a))boundary.set(a,[]);boundary.get(a).push(b);
    }
  }
  const remaining=new Set(boundary.keys());
  while(remaining.size) {
    const first=Math.min(...remaining),indices=[first];let previous=-1,current=first;
    for(;;) {
      const following=boundary.get(current).find(index=>index!==previous);
      if(following===first)break;
      if(following===undefined||indices.includes(following))throw Error('Football gap is not a closed pentagon');
      indices.push(following);previous=current;current=following;
    }
    if(indices.length!==5)throw Error('Expected a five-sided football gap');
    for(const index of indices)remaining.delete(index);
    const center=[0,1,2].map(axis=>indices.reduce((sum,index)=>sum+rawVertices[index][axis],0));
    const normal=corners.reduce((best,value)=>dot(value,center)>dot(best,center)?value:best,corners[0]);
    faces.push({indices,color:0,kind:'pentagon',normal});
  }
  if(rawVertices.length!==60||faces.filter(f=>f.kind==='hexagon').length!==20||faces.filter(f=>f.kind==='pentagon').length!==12)throw Error('Football topology must contain 60 vertices, 20 hexagons and 12 pentagons');
  const radius=Math.max(...rawVertices.map(point=>Math.hypot(...point)));
  const vertices=rawVertices.map(point=>point.map(value=>value/radius));
  return finish('football',vertices,faces,{source:'c64demo/experiments/sprite-ball/model.py',sourceRadius:24,sourceVertices:rawVertices});
}

const checker=makeChecker(),football=makeFootball(),meshes={checker,football};
function getMesh(name) {
  if(typeof name==='object'&&name&&name.verticesQ6)return name;
  const mesh=meshes[name];if(!mesh)throw Error('Unknown polygon sphere mesh: '+name);return mesh;
}

module.exports={checker,football,meshes,getMesh,makeChecker,makeFootball,roundSigned};
