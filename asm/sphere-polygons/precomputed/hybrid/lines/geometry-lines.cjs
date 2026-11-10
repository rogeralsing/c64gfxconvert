'use strict';

// Scene-independent direction/phase masks, not captured strings of glyphs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { BASE, layouts, expandFill } = require('../common.cjs');
const { getMesh } = require(path.join(BASE, 'meshes.cjs'));
const { createModel } = require(path.join(BASE, 'native-model.cjs'));
const { makeMotion } = require('../player/motion.cjs');
const fillCodec = require('../fill.cjs').codecs.find(codec => codec.name === 'wildcard-packbits');
const mesh = getMesh('checker');
const whiteFaces = mesh.faces.filter(face => face.color);
const counts = Uint8Array.from(whiteFaces, face => face.indices.length);
const PROBES = [[1,1],[4,1],[6,1],[1,4],[6,4],[1,6],[4,6],[6,6]];
const modulo = (n, m) => ((n % m) + m) % m;
const word = n => Buffer.from([n & 255, n >>> 8]);
const stats = values => ({ mean: values.reduce((a,b) => a+b, 0)/values.length, min: Math.min(...values), max: Math.max(...values), total: values.reduce((a,b) => a+b, 0) });

function createTables(q = 8, glyphLut) {
  if (![8,16].includes(q)) throw new Error('Bounded experiment supports only Q8 and Q16 slope/phase grids.');
  const size = (2*q+1)*q*2*3, ge = new Uint8Array(size), eq = new Uint8Array(size);
  for (let n=-q;n<=q;n++) for (let phase=0;phase<q;phase++) for (let axis=0;axis<2;axis++) for (let relative=-1;relative<=1;relative++) {
    const index=(((n+q)*q+phase)*2+axis)*3+relative+1;
    PROBES.forEach(([x,y],bit) => {
      const major=axis?y:x, minor=(axis?x:y)+relative*8;
      const d=q*minor-n*major-phase*8;
      if(d>=0)ge[index]|=1<<bit;
      if(d===0)eq[index]|=1<<bit;
    });
  }
  return { q, ge, eq, glyphLut, bytes: ge.length+eq.length+(glyphLut?glyphLut.length:0) };
}

function projectSmoothFrame(index) {
  const yaw=index*60/64*Math.PI/180,pitch=22*Math.PI/180,roll=12*Math.PI/180;
  const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),cr=Math.cos(roll),sr=Math.sin(roll);
  const points=mesh.vertices.map(([vx,vy,vz]) => {
    const rx=cy*vx+sy*vz,ry=sp*sy*vx+cp*vy-sp*cy*vz;
    return [Math.floor(160+94*(cr*rx-sr*ry)+.5+1e-10),Math.floor(100-94*(sr*rx+cr*ry)+.5+1e-10)];
  });
  const visible=whiteFaces.map(face => -cp*sy*face.normal[0]+sp*face.normal[1]+cp*cy*face.normal[2] < -1e-10);
  return { points, visible };
}

function lineDescriptor(a,b,areaSign,q) {
  const dx=b[0]-a[0],dy=b[1]-a[1];
  if(!dx&&!dy) throw new Error('A zero-length projected edge cannot define a half-plane.');
  const axis=Number(Math.abs(dy)>Math.abs(dx));
  const major0=axis?a[1]:a[0],major1=axis?b[1]:b[0],minor0=axis?a[0]:a[1],minor1=axis?b[0]:b[1];
  const n=Math.max(-q,Math.min(q,Math.round((minor1-minor0)/(major1-major0)*q)));
  const midMajor=(major0+major1)/16,midMinor=(minor0+minor1)/16;
  let u=Math.floor(midMajor),v,phase;
  for(let attempt=0;attempt<4;attempt++) {
    const intercept=midMinor-n/q*(midMajor-u);
    v=Math.floor(intercept);phase=Math.round((intercept-v)*q);
    if(phase===q){phase=0;v++;}
    const limit=axis?40:25;
    if(v>=0&&v<limit)break;
    u+=(v<0?1:-1)*Math.sign(n);
  }
  const x=axis?v:u,y=axis?u:v;
  assert(x>=0&&x<40&&y>=0&&y<25,'Line anchor must fit a screen cell.');
  const nx=-dy*areaSign,ny=dx*areaSign;
  const positive=Number((axis?nx:ny)>0),include=Number(nx>0||(nx===0&&ny>0));
  return { q,n,phase,axis,positive,include,u,v,anchor:y*40+x };
}

function encodeDescriptor(line) {
  const code=line.anchor|(line.phase<<10)|((line.n+line.q)<<14)|(line.axis<<20)|(line.positive<<21)|(line.include<<22);
  return Uint8Array.of(code&255,(code>>>8)&255,code>>>16);
}

function decodeDescriptor(payload,index,q) {
  const code=payload[index]|(payload[index+1]<<8)|(payload[index+2]<<16),anchor=code&1023;
  const axis=(code>>>20)&1,phase=(code>>>10)&15,n=((code>>>14)&63)-q;
  assert(anchor<1000&&phase<q&&n>=-q&&n<=q&&!(code&0x800000));
  const x=anchor%40,y=Math.floor(anchor/40);
  return {q,n,phase,axis,positive:(code>>>21)&1,include:(code>>>22)&1,u:axis?y:x,v:axis?x:y,anchor};
}

function maskAt(line,tileX,tileY,tables) {
  const major=line.axis?tileY:tileX,minor=line.axis?tileX:tileY;
  const p=line.phase+line.n*(major-line.u),shift=Math.floor(p/tables.q),phase=modulo(p,tables.q),relative=minor-line.v-shift;
  let ge,eq;
  if(relative < -1){ge=0;eq=0;}
  else if(relative > 1){ge=255;eq=0;}
  else {const i=(((line.n+tables.q)*tables.q+phase)*2+line.axis)*3+relative+1;ge=tables.ge[i];eq=tables.eq[i];}
  return line.positive ? (line.include?ge:ge&~eq) : (line.include?(~ge|eq)&255:(~ge)&255);
}

// A reusable line drawer: phase advances by slope each major character step.
// Returned partial cells include mask and the isolated-line font choice.
function lineGlyphSequence(line,tables,majorStart=0,length=40) {
  const result=[];
  for(let major=majorStart;major<majorStart+length;major++) {
    const p=line.phase+line.n*(major-line.u),base=line.v+Math.floor(p/tables.q);
    for(let relative=-1;relative<=1;relative++) {
      const minor=base+relative,x=line.axis?minor:major,y=line.axis?major:minor;
      if(x<0||x>=40||y<0||y>=25)continue;
      const mask=maskAt(line,x,y,tables);
      if(mask!==0&&mask!==255)result.push({cell:y*40+x,mask,glyph:tables.glyphLut?tables.glyphLut[mask]:undefined});
    }
  }
  return result;
}

function encodeFrame(index,q) {
  const geometry=projectSmoothFrame(index),parts=[new Uint8Array(5)];
  let lines=0;
  whiteFaces.forEach((face,faceIndex) => {
    if(!geometry.visible[faceIndex])return;
    parts[0][faceIndex>>>3]|=1<<(faceIndex&7);
    const p=face.indices.map(i=>geometry.points[i]);
    const area=p.reduce((sum,a,i)=>{const b=p[(i+1)%p.length];return sum+a[0]*b[1]-a[1]*b[0];},0),sign=area<0?-1:1;
    for(let edge=0;edge<p.length;edge++){parts.push(encodeDescriptor(lineDescriptor(p[edge],p[(edge+1)%p.length],sign,q)));lines++;}
  });
  return {packet:Buffer.concat(parts.map(p=>Buffer.from(p))),lines};
}

function encodeFiniteFrame(index,q) {
  const geometry=projectSmoothFrame(index),parts=[new Uint8Array(5)];let lines=0;
  whiteFaces.forEach((face,faceIndex) => {
    if(!geometry.visible[faceIndex])return;
    parts[0][faceIndex>>>3]|=1<<(faceIndex&7);
    const p=face.indices.map(i=>geometry.points[i]);
    const area=p.reduce((sum,a,i)=>{const b=p[(i+1)%p.length];return sum+a[0]*b[1]-a[1]*b[0];},0),sign=area<0?-1:1;
    for(let edge=0;edge<p.length;edge++) {
      const a=p[edge],b=p[(edge+1)%p.length],line=lineDescriptor(a,b,sign,q);
      const major0=line.axis?a[1]:a[0],major1=line.axis?b[1]:b[0];
      const before=line.u-Math.floor(Math.min(major0,major1)/8)+1;
      const after=Math.floor(Math.max(major0,major1)/8)-line.u+1;
      assert(before>=0&&before<=15&&after>=0&&after<=15);
      parts.push(encodeDescriptor(line),Uint8Array.of(before|(after<<4)));lines++;
    }
  });
  return {packet:Buffer.concat(parts.map(p=>Buffer.from(p))),lines};
}

function decodeEdgeOnly(packet,tables,baseFill,faceCounts=counts,indices=layouts.circle.indices,clip) {
  const coverage=new Uint8Array(1000),allCandidates=new Set(),selected=new Set(indices),faces=[];
  const ops={sequenceMaskLookups:0,ownerPlaneMaskLookups:0,ownerCells:0,candidateCells:0};
  let read=Math.ceil(faceCounts.length/8);
  for(let face=0;face<faceCounts.length;face++) {
    if(!((packet[face>>>3]>>>(face&7))&1))continue;
    const lines=[];
    for(let edge=0;edge<faceCounts[face];edge++) {
      assert(read+4<=packet.length);const line=decodeDescriptor(packet,read,tables.q),bounds=packet[read+3];read+=4;
      line.majorStart=line.u-(bounds&15);line.majorLength=(bounds&15)+(bounds>>>4)+1;lines.push(line);
    }
    const faceCandidates=new Set();
    for(const line of lines) {
      ops.sequenceMaskLookups+=line.majorLength*3;
      for(const entry of lineGlyphSequence(line,tables,line.majorStart,line.majorLength))if(selected.has(entry.cell))faceCandidates.add(entry.cell);
    }
    let minX=40,minY=25,maxX=-1,maxY=-1;
    // Endpoint bounds are deliberately one character wider than the segment.
    // They also bound possible solid contributions at another face's edge cell.
    for(const line of lines)for(const major of [line.majorStart,line.majorStart+line.majorLength-1]) {
      const minor=line.v+Math.floor((line.phase+line.n*(major-line.u))/tables.q);
      const x=line.axis?minor:major,y=line.axis?major:minor;
      minX=Math.min(minX,x-1);maxX=Math.max(maxX,x+1);minY=Math.min(minY,y-1);maxY=Math.max(maxY,y+1);
    }
    faces.push({lines,minX,maxX,minY,maxY});
    for(const cell of faceCandidates)allCandidates.add(cell);
  }
  assert.equal(read,packet.length);
  // Every white owner whose finite bounds reach a candidate contributes. This
  // preserves shared vertices and overlapping boundary cells without allowing
  // a later glyph write to erase an earlier white contribution.
  for(const {lines,minX,maxX,minY,maxY} of faces) {
    for(const cell of allCandidates) {
      let mask=255;const x=cell%40,y=Math.floor(cell/40);
      if(x<minX||x>maxX||y<minY||y>maxY)continue;
      for(const line of lines){mask&=maskAt(line,x,y,tables);ops.ownerPlaneMaskLookups++;if(!mask)break;}
      coverage[cell]|=mask;ops.ownerCells++;
    }
  }
  const glyphs=resolveCoverage(coverage,tables.glyphLut),screen=Uint8Array.from(baseFill);
  for(const cell of allCandidates)screen[cell]=glyphs[cell];
  if(clip)clipScreen(screen,clip);
  ops.candidateCells=allCandidates.size;
  return {screen,coverage,candidateCells:[...allCandidates].sort((a,b)=>a-b),ops};
}

function decodeCoverage(packet,tables,faceCounts=counts,indices=layouts.circle.indices,ops) {
  const coverage=new Uint8Array(1000);let read=Math.ceil(faceCounts.length/8);
  for(let face=0;face<faceCounts.length;face++) {
    if(!((packet[face>>>3]>>>(face&7))&1))continue;
    const lines=[];
    for(let edge=0;edge<faceCounts[face];edge++){assert(read+3<=packet.length);lines.push(decodeDescriptor(packet,read,tables.q));read+=3;}
    for(const cell of indices) {
      let mask=255;const x=cell%40,y=Math.floor(cell/40);
      for(const line of lines){mask&=maskAt(line,x,y,tables);if(ops)ops.maskLookups++;if(!mask)break;}
      coverage[cell]|=mask;
    }
  }
  assert.equal(read,packet.length);
  return coverage;
}

function resolveCoverage(coverage,glyphLut,clip) {
  const screen=Uint8Array.from(coverage,mask=>glyphLut[mask]);
  if(clip)clipScreen(screen,clip);
  return screen;
}

function clipScreen(screen,clip) {
  for(let p=0;p<clip.records.length;p+=4){const cell=clip.records[p]|(clip.records[p+1]<<8),base=clip.records[p+2]|(clip.records[p+3]<<8);screen[cell]=clip.remap[base+clip.compact[screen[cell]]];}
  return screen;
}

function encodePatches(predicted,target) {
  const parts=[],positions=[];
  for(let cell=0;cell<1000;cell++)if(predicted[cell]!==target[cell]){positions.push(cell);parts.push(cell&255,cell>>>8,target[cell]);}
  return {packet:Buffer.from([positions.length&255,positions.length>>>8,...parts]),positions};
}

function applyPatches(screen,packet) {
  const result=Uint8Array.from(screen),count=packet[0]|(packet[1]<<8);assert.equal(packet.length,2+3*count);
  for(let i=0;i<count;i++){const p=2+i*3,cell=packet[p]|(packet[p+1]<<8);assert(cell<1000);result[cell]=packet[p+2];}
  return result;
}

// A deliberately small experiment wire format. Font glyph pixels are the same
// external fixed 2048-byte font used by every player; all selection data is here.
function serializeMovie({tables,faceCounts,layoutMetadata,clip,frames}) {
  assert(faceCounts.length<256&&layoutMetadata.length===50&&frames.length<256);
  const header=Buffer.alloc(18);header.write('GL64',0,'ascii');header[4]=1;header[5]=tables.q;
  header[6]=Number(Boolean(clip));header[7]=frames.length;header[8]=faceCounts.length;header[9]=25;
  header.writeUInt16LE(tables.ge.length,10);header.writeUInt16LE(tables.eq.length,12);
  header.writeUInt16LE(clip?clip.remap.length:0,14);header.writeUInt16LE(clip?clip.records.length:0,16);
  const parts=[header,faceCounts,layoutMetadata,tables.glyphLut,tables.ge,tables.eq];
  if(clip)parts.push(clip.compact,clip.remap,clip.records);
  for(const frame of frames)parts.push(word(frame.lines.length),word(frame.fill.length),word(frame.patches.length),frame.lines,frame.fill,frame.patches);
  return Buffer.concat(parts.map(part=>Buffer.from(part)));
}

function decodeMovie(payload) {
  const packet=Buffer.from(payload);assert.equal(packet.toString('ascii',0,4),'GL64');assert.equal(packet[4],1);
  const q=packet[5],useClip=packet[6],frameCount=packet[7],faceCount=packet[8],rows=packet[9];
  assert([8,16].includes(q)&&useClip<=1&&rows===25);
  const geLength=packet.readUInt16LE(10),eqLength=packet.readUInt16LE(12),remapLength=packet.readUInt16LE(14),recordsLength=packet.readUInt16LE(16);
  let read=18;
  const take=length=>{assert(read+length<=packet.length,'Truncated GL64 payload.');const part=packet.subarray(read,read+length);read+=length;return part;};
  const faceCounts=take(faceCount),metadata=take(rows*2),indices=[];
  for(let row=0;row<rows;row++){const start=metadata[row*2],count=metadata[row*2+1];assert(start+count<=40);for(let x=start;x<start+count;x++)indices.push(row*40+x);}
  const glyphLut=take(256),ge=take(geLength),eq=take(eqLength),expected=(2*q+1)*q*2*3;
  assert.equal(ge.length,expected);assert.equal(eq.length,expected);
  const tables={q,ge,eq,glyphLut},clip=useClip?{compact:take(256),remap:take(remapLength),records:take(recordsLength)}:null;
  if(!useClip)assert.equal(remapLength+recordsLength,0);else assert.equal(recordsLength%4,0);
  const frames=[],predictions=[];
  for(let frame=0;frame<frameCount;frame++) {
    const lengths=take(6),lineLength=lengths.readUInt16LE(0),fillLength=lengths.readUInt16LE(2),patchLength=lengths.readUInt16LE(4);
    const lines=take(lineLength),fill=take(fillLength),patches=take(patchLength);
    const baseFill=expandFill(fillCodec.decode(fill,indices.length),indices);
    const predicted=decodeEdgeOnly(lines,tables,baseFill,faceCounts,indices,clip).screen;
    predictions.push(predicted);frames.push(applyPatches(predicted,patches));
  }
  assert.equal(read,packet.length,'Trailing GL64 payload bytes.');
  return {frames,predictions,q,indices,faceCounts,tables,clip,bytesRead:read};
}

function qualityMasks() {
  const outside=new Uint8Array(8000);let area=0;
  for(let cell=0;cell<1000;cell++)for(let y=0;y<8;y++)for(let x=0;x<8;x++) {
    const sx=(cell%40)*8+x,sy=Math.floor(cell/40)*8+y;
    if((sx-160)**2+(sy-100)**2>94**2)outside[cell*8+y]|=128>>>x;
    else area++;
  }
  return {outside,area};
}
const quality=qualityMasks();
function difference(predicted,target,font) {
  let characters=0,dots=0,spill=0;
  for(let cell=0;cell<1000;cell++)for(let row=0;row<8;row++) {
    let b=font[predicted[cell]*8+row]&quality.outside[cell*8+row];for(;b;b&=b-1)spill++;
  }
  for(let cell=0;cell<1000;cell++)if(predicted[cell]!==target[cell]) {
    characters++;
    for(let row=0;row<8;row++){let b=font[predicted[cell]*8+row]^font[target[cell]*8+row];for(;b;b&=b-1)dots++;}
  }
  return {characters,dots,spill,screenDotFraction:dots/64000,ballDotFraction:dots/quality.area};
}

function study(output=path.join(__dirname,'build')) {
  fs.mkdirSync(output,{recursive:true});
  const model=createModel(),motion=makeMotion(),font=model.assets.font,glyphLut=model.assets.glyphLut;
  const layout=layouts.circle,clip={compact:model.assets.compact,remap:model.assets.remap,records:model.assets.clipRecords};
  const fillPackets=motion.frames.map(screen=>fillCodec.encode(screen,layout.indices));
  const fillScreens=fillPackets.map(packet=>expandFill(fillCodec.decode(packet,layout.indices.length),layout.indices));
  const report={scope:'Host-only mathematical line rasterizer and serialized descriptors. No native timing, code-size or FPS claim.',
    motion:motion.motion,frames:64,wire:{lineBytes:3,visibilityBytesPerFrame:5,frameLengthBytes:6,sharedHeaderBytes:18,whiteFaceCountsBytes:36,layoutMetadataBytes:50,glyphLutBytes:256,fontBytesSeparate:2048,patches:'LE16 count, then LE16 cell + glyph byte per changed cell'},
    cornerRule:'AND every white polygon half-plane, then OR white polygons. Strict/inclusive ties are explicit descriptor bits.',
    runtimeRule:'8-bit character masks only; no full-resolution bitmap and no 64-dot glyph search. Edge-only mode evaluates finite line candidates, ANDs each bounding white owner at those cells, and ORs the contributions over decoded binary fill. Full-polygon modes are comparison baselines.',
    configurations:[],qualityAreaDots:quality.area,sharedClipBytes:clip.compact.length+clip.remap.length+clip.records.length};
  fs.writeFileSync(path.join(output,'reference.bin'),Buffer.concat(motion.frames.map(f=>Buffer.from(f))));
  fs.writeFileSync(path.join(output,'font.bin'),font);fs.writeFileSync(path.join(output,'glyph-lut.bin'),glyphLut);
  fs.writeFileSync(path.join(output,'white-face-counts.bin'),counts);fs.writeFileSync(path.join(output,'layout.bin'),layout.metadata);
  fs.writeFileSync(path.join(output,'fill-packets.bin'),Buffer.concat(fillPackets.flatMap(p=>[word(p.length),p])));
  for(const q of[8,16]) {
    const tables=createTables(q,glyphLut),encoded=Array.from({length:64},(_,i)=>encodeFrame(i,q)),operations=[];
    fs.writeFileSync(path.join(output,`q${q}-ge.bin`),tables.ge);fs.writeFileSync(path.join(output,`q${q}-eq.bin`),tables.eq);
    fs.writeFileSync(path.join(output,`q${q}-descriptors.bin`),Buffer.concat(encoded.flatMap(f=>[word(f.packet.length),f.packet])));
    const coverages=encoded.map(f=>{const ops={maskLookups:0};const coverage=decodeCoverage(f.packet,tables,counts,layout.indices,ops);operations.push(ops.maskLookups);return coverage;});
    for(const storedFill of[false,true])for(const useClip of[false,true]) {
      const label=`q${q}-${storedFill?'fill':'polygon'}-${useClip?'clip':'raw'}`,predictions=[],patches=[],rows=[];
      for(let frame=0;frame<64;frame++) {
        const lineScreen=resolveCoverage(coverages[frame],glyphLut,useClip?clip:null);
        let predicted=lineScreen;
        if(storedFill){predicted=Uint8Array.from(fillScreens[frame]);for(const cell of layout.indices)if(coverages[frame][cell]!==0&&coverages[frame][cell]!==255)predicted[cell]=lineScreen[cell];}
        const delta=encodePatches(predicted,motion.frames[frame]);assert.deepEqual(applyPatches(predicted,delta.packet),motion.frames[frame]);
        predictions.push(predicted);patches.push(delta.packet);
        rows.push({frame,lines:encoded[frame].lines,lineBytes:encoded[frame].packet.length,fillBytes:storedFill?fillPackets[frame].length:0,patchBytes:delta.packet.length,...difference(predicted,motion.frames[frame],font)});
      }
      const shared=18+36+50+256+tables.ge.length+tables.eq.length+(useClip?report.sharedClipBytes:0);
      const frameBytes=rows.map(row=>6+row.lineBytes+row.fillBytes+row.patchBytes),approxFrameBytes=rows.map(row=>6+row.lineBytes+row.fillBytes+2);
      const config={name:label,q,storedFill,useClip,sharedBytes:shared,lookupBytes:tables.ge.length+tables.eq.length,
        lines:stats(rows.map(r=>r.lines)),linePacketBytes:stats(rows.map(r=>r.lineBytes)),exactFrameBytes:stats(frameBytes),
        approximateFrameBytes:stats(approxFrameBytes),changedCharacters:stats(rows.map(r=>r.characters)),differentGlyphDots:stats(rows.map(r=>r.dots)),approximateSpillDots:stats(rows.map(r=>r.spill)),
        exactTotalBytes:shared+frameBytes.reduce((a,b)=>a+b,0),approximateTotalBytes:shared+approxFrameBytes.reduce((a,b)=>a+b,0),
        exactWithFontBytes:shared+frameBytes.reduce((a,b)=>a+b,0)+2048,maskLookupsPerFrame:stats(operations),exactRoundTrip:true,rows};
      report.configurations.push(config);
      fs.writeFileSync(path.join(output,label+'-prediction.bin'),Buffer.concat(predictions.map(p=>Buffer.from(p))));
      fs.writeFileSync(path.join(output,label+'-patches.bin'),Buffer.concat(patches.flatMap(p=>[word(p.length),p])));
    }
    const finite=Array.from({length:64},(_,i)=>encodeFiniteFrame(i,q));
    fs.writeFileSync(path.join(output,`q${q}-finite-descriptors.bin`),Buffer.concat(finite.flatMap(f=>[word(f.packet.length),f.packet])));
    for(const useClip of[false,true]) {
      const label=`q${q}-edge-${useClip?'clip':'raw'}`,predictions=[],patches=[],rows=[],ops=[];
      for(let frame=0;frame<64;frame++) {
        const rendered=decodeEdgeOnly(finite[frame].packet,tables,fillScreens[frame],counts,layout.indices,useClip?clip:null);
        const delta=encodePatches(rendered.screen,motion.frames[frame]);
        const exact=applyPatches(rendered.screen,delta.packet);
        assert.deepEqual(exact,motion.frames[frame]);assert.equal(difference(exact,motion.frames[frame],font).spill,0);
        predictions.push(rendered.screen);patches.push(delta.packet);ops.push(rendered.ops);
        rows.push({frame,lines:finite[frame].lines,lineBytes:finite[frame].packet.length,fillBytes:fillPackets[frame].length,patchBytes:delta.packet.length,...difference(rendered.screen,motion.frames[frame],font)});
      }
      const shared=18+36+50+256+tables.ge.length+tables.eq.length+(useClip?report.sharedClipBytes:0);
      const frameBytes=rows.map(row=>6+row.lineBytes+row.fillBytes+row.patchBytes),approxFrameBytes=rows.map(row=>6+row.lineBytes+row.fillBytes+2);
      const config={name:label,q,storedFill:true,useClip,edgeOnly:true,finiteBoundsBytesPerLine:1,sharedBytes:shared,lookupBytes:tables.ge.length+tables.eq.length,
        lines:stats(rows.map(r=>r.lines)),linePacketBytes:stats(rows.map(r=>r.lineBytes)),exactFrameBytes:stats(frameBytes),approximateFrameBytes:stats(approxFrameBytes),
        changedCharacters:stats(rows.map(r=>r.characters)),differentGlyphDots:stats(rows.map(r=>r.dots)),approximateSpillDots:stats(rows.map(r=>r.spill)),
        exactTotalBytes:shared+frameBytes.reduce((a,b)=>a+b,0),approximateTotalBytes:shared+approxFrameBytes.reduce((a,b)=>a+b,0),
        maskLookupsPerFrame:stats(ops.map(o=>o.sequenceMaskLookups+o.ownerPlaneMaskLookups)),candidateCells:stats(ops.map(o=>o.candidateCells)),exactRoundTrip:true,rows};
      const movieFrames=finite.map((frame,i)=>({lines:frame.packet,fill:fillPackets[i],patches:patches[i]}));
      const exactMovie=serializeMovie({tables,faceCounts:counts,layoutMetadata:layout.metadata,clip:useClip?clip:null,frames:movieFrames});
      const approximateMovie=serializeMovie({tables,faceCounts:counts,layoutMetadata:layout.metadata,clip:useClip?clip:null,frames:movieFrames.map(frame=>({...frame,patches:Uint8Array.of(0,0)}))});
      const decodedExact=decodeMovie(exactMovie),decodedApproximate=decodeMovie(approximateMovie);
      assert.equal(exactMovie.length,config.exactTotalBytes);assert.equal(approximateMovie.length,config.approximateTotalBytes);
      for(let frame=0;frame<64;frame++){assert.deepEqual(decodedExact.frames[frame],motion.frames[frame]);assert.deepEqual(decodedExact.predictions[frame],predictions[frame]);assert.deepEqual(decodedApproximate.frames[frame],predictions[frame]);}
      config.serializedRoundTrip=true;config.serializedExactBytes=exactMovie.length;config.serializedApproximateBytes=approximateMovie.length;
      config.exactMovieSha256=crypto.createHash('sha256').update(exactMovie).digest('hex');
      fs.writeFileSync(path.join(output,label+'-exact.gl64'),exactMovie);fs.writeFileSync(path.join(output,label+'-approximate.gl64'),approximateMovie);
      report.configurations.push(config);
      fs.writeFileSync(path.join(output,label+'-prediction.bin'),Buffer.concat(predictions.map(p=>Buffer.from(p))));
      fs.writeFileSync(path.join(output,label+'-patches.bin'),Buffer.concat(patches.flatMap(p=>[word(p.length),p])));
    }
  }
  report.configurations.sort((a,b)=>a.exactTotalBytes-b.exactTotalBytes);
  report.inputHashes=Object.fromEntries(['geometry-lines.cjs','../player/motion.cjs','../../../raster.cjs','../../../meshes.cjs','../../../native-model.cjs','../fill.cjs','../common.cjs'].map(file=>{const target=path.resolve(__dirname,file);return[file,crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')];}));
  report.inputHashes['font.bin']=crypto.createHash('sha256').update(font).digest('hex');
  report.inputHashes['reference.bin']=crypto.createHash('sha256').update(Buffer.concat(motion.frames.map(frame=>Buffer.from(frame)))).digest('hex');
  fs.writeFileSync(path.join(output,'geometry-report.json'),JSON.stringify(report,null,2)+'\n');
  return report;
}

module.exports={createTables,projectSmoothFrame,lineDescriptor,encodeDescriptor,decodeDescriptor,maskAt,lineGlyphSequence,encodeFrame,encodeFiniteFrame,decodeCoverage,decodeEdgeOnly,resolveCoverage,encodePatches,applyPatches,serializeMovie,decodeMovie,study};
if(require.main===module){const r=study();console.log(JSON.stringify({scope:r.scope,edgeOnly:r.configurations.filter(c=>c.edgeOnly).map(c=>({name:c.name,lookupBytes:c.lookupBytes,exactTotalBytes:c.exactTotalBytes,approximateTotalBytes:c.approximateTotalBytes,linePacketMean:c.linePacketBytes.mean,changedCharacters:c.changedCharacters,spill:c.approximateSpillDots,maskLookups:c.maskLookupsPerFrame,candidateCells:c.candidateCells}))},null,2));}
