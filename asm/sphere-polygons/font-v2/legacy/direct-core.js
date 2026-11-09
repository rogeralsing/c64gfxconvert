(function (root) {
  'use strict';
  const CAMERA = 3.2, WIDTH = 320, HEIGHT = 200;
  const geometries = new Map();
  const silhouettes = new WeakMap();

  function bitCount(value) {
    value >>>= 0;
    value -= (value >>> 1) & 0x55555555;
    value = (value & 0x33333333) + ((value >>> 2) & 0x33333333);
    return (((value + (value >>> 4)) & 0x0f0f0f0f) * 0x01010101) >>> 24;
  }

  function prepareSilhouette(font, radius) {
    let byRadius = silhouettes.get(font);
    if (!byRadius) { byRadius = new Map(); silhouettes.set(font, byRadius); }
    if (byRadius.has(radius)) return byRadius.get(radius);
    const tiles = [], masks = new Map(), g = geometry(radius);
    for (const index of g.tiles) {
      const tile = g.tileData[index];
      if (tile.status !== 'edge') continue;
      let lo = 0, hi = 0;
      // Geometry-only setup: sample the exact circle at native pixel centers.
      // These masks constrain font choices; they are never painted over a frame.
      for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
        const dx = tile.x + x + 0.5 - WIDTH / 2, dy = tile.y + y + 0.5 - HEIGHT / 2;
        if (dx * dx + dy * dy > radius * radius) continue;
        const bit = y * 8 + x;
        if (bit < 32) lo |= 1 << bit;
        else hi |= 1 << (bit - 32);
      }
      lo >>>= 0; hi >>>= 0;
      const key = lo + ':' + hi;
      let remap = masks.get(key);
      if (!remap) {
        const allowed = [];
        for (let code = 0; code < font.glyphs.length; code++) {
          const glyph = font.glyphs[code];
          if (((glyph.lo & ~lo) | (glyph.hi & ~hi)) === 0) allowed.push(code);
        }
        if (!allowed.length) throw Error('The fixed font needs an empty glyph for silhouette constraints.');
        remap = new Uint8Array(font.glyphs.length);
        for (let code = 0; code < font.glyphs.length; code++) {
          const source = font.glyphs[code];
          if (((source.lo & ~lo) | (source.hi & ~hi)) === 0) { remap[code] = code; continue; }
          const targetLo = source.lo & lo, targetHi = source.hi & hi;
          let best = allowed[0], bestError = 65;
          for (const candidate of allowed) {
            const glyph = font.glyphs[candidate];
            const error = bitCount(glyph.lo ^ targetLo) + bitCount(glyph.hi ^ targetHi);
            if (error < bestError) { best = candidate; bestError = error; }
          }
          remap[code] = best;
        }
        masks.set(key, remap);
      }
      tiles.push({ index, remap });
    }
    const prepared = {
      tiles, radius, uniqueMasks: masks.size,
      tableBytes: masks.size * font.glyphs.length,
      indexBytes: tiles.length * 2
    };
    byRadius.set(radius, prepared);
    return prepared;
  }

  function constrainToSilhouette(screen, font, radius) {
    // Renderers start with a zeroed screen and write only active sphere tiles.
    // Runtime changes character codes only. No source pixels or bitmap clipping.
    const prepared = prepareSilhouette(font, radius);
    let changes = 0;
    for (const tile of prepared.tiles) {
      const before = screen[tile.index], after = tile.remap[before];
      if (before !== after) changes++;
      screen[tile.index] = after;
    }
    return { lookups: prepared.tiles.length, changes, tableBytes: prepared.tableBytes, indexBytes: prepared.indexBytes };
  }

  function geometry(radius) {
    if (geometries.has(radius)) return geometries.get(radius);
    const focal = radius * Math.sqrt(CAMERA * CAMERA - 1);
    const tiles = [], tileData = new Array(1000), points = new Map();
    for (let ty=0;ty<25;ty++) for(let tx=0;tx<40;tx++) {
      const x=tx*8, y=ty*8, cx=x+4, cy=y+4;
      const left=x+.5-160, right=x+7.5-160, top=y+.5-100, bottom=y+7.5-100;
      const nearX=left>0?left:right<0?right:0, nearY=top>0?top:bottom<0?bottom:0;
      const farX=Math.max(Math.abs(left),Math.abs(right)), farY=Math.max(Math.abs(top),Math.abs(bottom));
      if(nearX*nearX+nearY*nearY>radius*radius)continue;
      const status=farX*farX+farY*farY<=radius*radius?'inside':'edge';
      const index=ty*40+tx;
      tiles.push(index);tileData[index]={x,y,cx,cy,status,index};
    }
    const result={radius,focal,tiles,tileData,points};
    geometries.set(radius,result);return result;
  }

  function createScene(state) {
    const g=geometry(state.radius);
    const ops={rayQueries:0,raySolves:0,samples:0,uvCalls:0,trigCalls:0,planeTests:0,tableReads:0};
    const yaw=state.angle, pitch=state.tilt*Math.PI/180;
    const sy=Math.sin(yaw),cy=Math.cos(yaw),sx=Math.sin(pitch),cx=Math.cos(pitch);
    const rx=[cy,0,-sy],ry=[sx*sy,cx,sx*cy],rz=[cx*sy,-sx,cx*cy];
    const bands=state.checks/2, planes=[];
    for(let j=0;j<state.checks/2;j++) {
      const lambda=-Math.PI+j*2*Math.PI/state.checks, a=Math.cos(lambda),b=Math.sin(lambda);
      planes.push({nx:a*rx[0]-b*rz[0],ny:a*rx[1]-b*rz[1],nz:a*rx[2]-b*rz[2],c:0,kind:'longitude'});
    }
    for(let j=1;j<bands;j++) {
      const c=Math.sin(-Math.PI/2+j*Math.PI/bands);
      planes.push({nx:ry[0],ny:ry[1],nz:ry[2],c,kind:'latitude'});
    }
    function point(x,y) {
      ops.rayQueries++;
      const key=x+':'+y;
      if(g.points.has(key))return g.points.get(key);
      ops.raySolves++;
      const u=(x-160)/g.focal,v=(100-y)/g.focal,a=1+u*u+v*v;
      const d=CAMERA*CAMERA-a*(CAMERA*CAMERA-1);
      let p=null;
      if(d>=0) {
        const t=(CAMERA-Math.sqrt(d))/a;
        p={px:t*u,py:t*v,pz:CAMERA-t};
      }
      g.points.set(key,p);return p;
    }
    function sampleSign(p) {
      if(!p)return 0;
      if(state.solid)return 1;
      let bit=1;
      for(const plane of planes) {
        ops.planeTests++;
        bit^=Number(plane.nx*p.px+plane.ny*p.py+plane.nz*p.pz>=plane.c);
      }
      return bit;
    }
    function checkAt(x,y) {ops.samples++;return sampleSign(point(x,y));}
    function uvAt(x,y) {
      ops.uvCalls++;const p=point(x,y);
      if(!p)return{u:0,v:0,inside:false,px:0,py:0,pz:0};
      const ox=rx[0]*p.px+rx[2]*p.pz;
      const oy=ry[0]*p.px+ry[1]*p.py+ry[2]*p.pz;
      const oz=rz[0]*p.px+rz[1]*p.py+rz[2]*p.pz;
      ops.trigCalls+=2;
      return{u:(Math.atan2(ox,oz)+Math.PI)*state.checks/(2*Math.PI),v:(Math.asin(Math.max(-1,Math.min(1,oy)))+Math.PI/2)*bands/Math.PI,inside:true,...p};
    }
    return{camera:CAMERA,focal:g.focal,radius:state.radius,tiles:g.tiles,tile:i=>g.tileData[i],point,checkAt,uvAt,sampleSign,planes,ops,state};
  }

  // This independent evaluator is reserved for measurement. Direct methods
  // cannot read its output; they receive only createScene's scalar geometry API.
  function reference(state) {
    const pixels=new Uint8Array(64000),inside=new Uint8Array(64000);
    const focal=state.radius*Math.sqrt(CAMERA*CAMERA-1);
    const sy=Math.sin(state.angle),cy=Math.cos(state.angle),pitch=state.tilt*Math.PI/180;
    const sx=Math.sin(pitch),cx=Math.cos(pitch),bands=state.checks/2;
    let area=0;
    for(let y=0;y<200;y++)for(let x=0;x<320;x++) {
      const i=y*320+x,dx=(x+.5-160)/focal,dy=(100-y-.5)/focal;
      const a=1+dx*dx+dy*dy,discriminant=CAMERA*CAMERA-a*(CAMERA*CAMERA-1);
      if(discriminant<0)continue;
      inside[i]=1;area++;
      if(state.solid){pixels[i]=1;continue;}
      const t=(CAMERA-Math.sqrt(discriminant))/a,px=t*dx,py=t*dy,pz=CAMERA-t;
      const ox=cy*px-sy*pz,oy=cx*py+sx*(sy*px+cy*pz),oz=-sx*py+cx*(sy*px+cy*pz);
      const u=(Math.atan2(ox,oz)+Math.PI)*state.checks/(2*Math.PI);
      const v=(Math.asin(Math.max(-1,Math.min(1,oy)))+Math.PI/2)*bands/Math.PI;
      pixels[i]=(Math.floor(u)^Math.floor(v))&1;
    }
    return{pixels,inside,area};
  }
  function reconstruct(screen,font) {
    const pixels=new Uint8Array(64000);
    for(let ty=0;ty<25;ty++)for(let tx=0;tx<40;tx++) {
      const glyph=font.glyphs[screen[ty*40+tx]];
      if(!glyph)throw Error('Glyph index outside font');
      for(let y=0;y<8;y++)for(let x=0;x<8;x++) pixels[(ty*8+y)*320+tx*8+x]=(glyph.rows[y]>>>(7-x))&1;
    }
    return pixels;
  }
  function compare(screen,font,ref) {
    const pixels=reconstruct(screen,font);let errors=0,spill=0;
    const used=new Set(screen);
    for(let i=0;i<64000;i++)if(pixels[i]!==ref.pixels[i]){errors++;if(!ref.inside[i])spill++;}
    return{pixels,errors,spill,error:errors/Math.max(1,ref.area),used:used.size};
  }
  const api={createScene,reference,reconstruct,compare,prepareSilhouette,constrainToSilhouette};
  root.DirectCore=api;root.DirectMethods=root.DirectMethods||{};
  if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
