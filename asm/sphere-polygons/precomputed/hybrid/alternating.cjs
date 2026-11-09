'use strict';

const BLACK=0,WHITE=15;
const TYPE={RUN:1,CONTINUE:2,EDGE:3,LITERAL:4,TOGGLE:5,PAIR:6};

function inputBytes(values) {
  if(!(values instanceof Uint8Array)&&!Array.isArray(values))throw new TypeError('Expected byte values');
  for(const value of values)if(!Number.isInteger(value)||value<0||value>255)throw new RangeError('Character values must be bytes');
  return values instanceof Uint8Array?values:Uint8Array.from(values);
}

function runLengths(values) {
  const n=values.length,black=new Uint16Array(n+1),white=new Uint16Array(n+1),edge=new Uint16Array(n+1);
  for(let i=n-1;i>=0;i--) {
    black[i]=values[i]===BLACK?black[i+1]+1:0;
    white[i]=values[i]===WHITE?white[i+1]+1:0;
    edge[i]=values[i]!==BLACK&&values[i]!==WHITE?edge[i+1]+1:0;
  }
  return{black,white,edge};
}

// Every frame starts with black as the current fill. Positive-output choices
// are computed first; at most one zero-output toggle can improve either state.
function encodeValues(input,{literals=true,strictPairs=false,edgeOnlyStrict=false}={}) {
  const values=inputBytes(input),n=values.length,runs=runLengths(values);
  if(n>65535)throw new RangeError('This codec accepts at most 65535 output values');
  const costs=[new Uint32Array(n+1),new Uint32Array(n+1)];
  const types=[new Uint8Array(n),new Uint8Array(n)];
  const lengths=[new Uint16Array(n),new Uint16Array(n)];
  const edgeCounts=[new Uint16Array(n),new Uint16Array(n)];
  const literalCosts=[new Uint32Array(n+1),new Uint32Array(n+1)];
  const literalLengths=[new Uint16Array(n+1),new Uint16Array(n+1)];
  const queues=[new Uint32Array(n+1),new Uint32Array(n+1)],heads=[0,0],tails=[0,0];
  const literalLimit=strictPairs?255:256;
  for(let i=n-1;i>=0;i--) {
    // Sliding minima of j+cost[j] make unrestricted literal choices linear
    // rather than quadratic in the maximum packet length.
    for(let state=0;state<2;state++) {
      const index=i+1,value=index+costs[state][index],queue=queues[state];
      while(tails[state]>heads[state]) {
        const last=queue[tails[state]-1];if(last+costs[state][last]<=value)break;tails[state]--;
      }
      queue[tails[state]++]=index;
      while(heads[state]<tails[state]&&queue[heads[state]]>i+literalLimit)heads[state]++;
      const best=queue[heads[state]];literalCosts[state][i]=best-i+costs[state][best];literalLengths[state][i]=best-i;
    }
    const direct=[Infinity,Infinity];
    for(let state=0;state<2;state++) {
      let best=Infinity,bestType=0,bestLength=0,bestEdges=0,bestOutput=-1;
      function choose(cost,type,length=0,edges=0) {
        const output=length+edges;
        if(cost<best||(cost===best&&output>bestOutput)) {
          best=cost;bestType=type;bestLength=length;bestEdges=edges;bestOutput=output;
        }
      }
      const matching=state?runs.white[i]:runs.black[i];
      if(strictPairs) {
        for(let length=1;length<=Math.min(255,matching);length++)choose(2+costs[1-state][i+length],TYPE.PAIR,length,0);
        if(!edgeOnlyStrict) {
          for(let length=0;length<=Math.min(255,matching);length++) {
            const after=i+length;if(after===n)continue;
            choose(2+literalCosts[1-state][after],TYPE.PAIR,length,literalLengths[1-state][after]);
          }
        }else if(matching<=255) {
          const after=i+matching,available=Math.min(255,runs.edge[after]);
          for(let edges=1;edges<=available;edges++)choose(2+edges+costs[1-state][after+edges],TYPE.PAIR,matching,edges);
        }
      }else {
        for(let length=1;length<=Math.min(254,matching);length++)choose(1+costs[1-state][i+length],TYPE.RUN,length);
        if(matching>=255)choose(1+costs[state][i+255],TYPE.CONTINUE,255);
        if(runs.edge[i])choose(2+costs[state][i+1],TYPE.EDGE,1);
        if(literals)choose(3+literalCosts[state][i],TYPE.LITERAL,literalLengths[state][i]);
      }
      direct[state]=best;costs[state][i]=best;types[state][i]=bestType;lengths[state][i]=bestLength;edgeCounts[state][i]=bestEdges;
    }
    for(let state=0;state<2;state++)if(2+direct[1-state]<direct[state]) {
      costs[state][i]=2+direct[1-state];types[state][i]=TYPE.TOGGLE;lengths[state][i]=0;edgeCounts[state][i]=0;
    }
  }
  const bytes=[];let position=0,state=0;
  while(position<n) {
    const type=types[state][position],length=lengths[state][position],edges=edgeCounts[state][position];
    if(type===TYPE.TOGGLE){bytes.push(0,0);state=1-state;continue;}
    if(type===TYPE.RUN){bytes.push(length);position+=length;state=1-state;continue;}
    if(type===TYPE.CONTINUE){bytes.push(255);position+=255;continue;}
    if(type===TYPE.EDGE){bytes.push(0,values[position++]);continue;}
    if(type===TYPE.LITERAL){bytes.push(0,15,length&255);for(let j=0;j<length;j++)bytes.push(values[position+j]);position+=length;continue;}
    if(type===TYPE.PAIR){bytes.push(length,edges);position+=length;for(let j=0;j<edges;j++)bytes.push(values[position+j]);position+=edges;state=1-state;continue;}
    throw new Error('No legal encoding transition');
  }
  if(bytes.length!==costs[0][0])throw new Error('Encoded byte count differs from dynamic-programming cost');
  return Uint8Array.from(bytes);
}

// This parser does not use encoder transitions, run lengths, or DP tables.
function decodeValues(input,outputLength=1000,{strictPairs=false}={}) {
  const payload=inputBytes(input);
  if(!Number.isInteger(outputLength)||outputLength<0||outputLength>65535)throw new RangeError('Invalid output length');
  const output=new Uint8Array(outputLength);let source=0,target=0,fill=BLACK;
  function byte() {if(source>=payload.length)throw new Error('Truncated alternating payload');return payload[source++];}
  function emitRun(count) {if(target+count>outputLength)throw new Error('Run exceeds output length');output.fill(fill,target,target+count);target+=count;}
  function emitLiteral(count,edgesOnly) {
    if(source+count>payload.length||target+count>outputLength)throw new Error('Literal exceeds payload or output length');
    for(let i=0;i<count;i++) {
      const value=byte();if(edgesOnly&&(value===BLACK||value===WHITE))throw new Error('Binary character in edge-only block');
      output[target++]=value;
    }
  }
  while(target<outputLength) {
    if(strictPairs) {
      const run=byte(),edges=byte();emitRun(run);fill^=15;emitLiteral(edges,false);continue;
    }
    const token=byte();
    if(token===255){emitRun(255);continue;}
    if(token!==0){emitRun(token);fill^=15;continue;}
    const tag=byte();
    if(tag===0){fill^=15;continue;}
    if(tag===15){const count=byte();emitLiteral(count===0?256:count,false);continue;}
    if(target>=outputLength)throw new Error('Edge exceeds output length');
    output[target++]=tag;
  }
  if(source!==payload.length)throw new Error('Trailing bytes after complete frame');
  return output;
}

function requireScreen(screen) {
  const values=inputBytes(screen);if(values.length!==1000)throw new RangeError('A full character screen must contain 1000 bytes');return values;
}
function encode(screen,options={}) {return encodeValues(requireScreen(screen),options);}
function decode(payload) {return decodeValues(payload,1000);}

const variants=[
  {name:'alternating-dp-literals',encode:(screen)=>encode(screen),decode,encodeValues:(values)=>encodeValues(values),decodeValues:(payload,length)=>decodeValues(payload,length),frameHeaderBytes:0,globalMetadataBytes:0},
  {name:'alternating-dp-edge-only',encode:(screen)=>encode(screen,{literals:false}),decode,encodeValues:(values)=>encodeValues(values,{literals:false}),decodeValues:(payload,length)=>decodeValues(payload,length),frameHeaderBytes:0,globalMetadataBytes:0},
  {name:'alternating-strict-pairs',encode:(screen)=>encode(screen,{strictPairs:true}),decode:(payload)=>decodeValues(payload,1000,{strictPairs:true}),encodeValues:(values)=>encodeValues(values,{strictPairs:true}),decodeValues:(payload,length)=>decodeValues(payload,length,{strictPairs:true}),frameHeaderBytes:0,globalMetadataBytes:0},
  {name:'alternating-strict-edge-only',encode:(screen)=>encode(screen,{strictPairs:true,edgeOnlyStrict:true}),decode:(payload)=>decodeValues(payload,1000,{strictPairs:true}),encodeValues:(values)=>encodeValues(values,{strictPairs:true,edgeOnlyStrict:true}),decodeValues:(payload,length)=>decodeValues(payload,length,{strictPairs:true}),frameHeaderBytes:0,globalMetadataBytes:0}
];

function syntheticChecks() {
  const repairSpace=new Uint8Array(1000);repairSpace.set([0,0,37,0,15,15,15,15,15,15,15,15]);
  const repairFull=new Uint8Array(1000).fill(15);repairFull.set([15,15,37,15,0,0,0,0,0,0,0,0]);
  const screens=[new Uint8Array(1000),new Uint8Array(1000).fill(15),new Uint8Array(1000).fill(1),Uint8Array.from({length:1000},(_,i)=>i&1?15:0),Uint8Array.from({length:1000},(_,i)=>i%256),Uint8Array.from({length:1000},(_,i)=>i<255?0:i<510?15:i<800?37:0),repairSpace,repairFull];
  const results=[];
  for(const variant of variants) {
    const lengths=[];
    for(const screen of screens) {
      const payload=variant.encode(screen),output=variant.decode(payload);
      if(output.length!==1000||output.some((value,index)=>value!==screen[index]))throw new Error('Synthetic roundtrip failed: '+variant.name);
      lengths.push(payload.length);
    }
    results.push({name:variant.name,bytes:lengths});
  }
  return results;
}

async function reportCorpus() {
  const fs=require('node:fs'),path=require('node:path');
  const common=require('./common.cjs'),corpus=await common.getCorpus();
  const report={kind:'Independent full-screen frames; all grammar bytes counted, no hidden dictionaries or frame headers',inputHashes:corpus.inputHashes,synthetic:syntheticChecks(),models:{}};
  for(const[model,frames]of Object.entries(corpus.models)) {
    report.models[model]=[];
    for(const variant of variants) {
      const sizes=[];let compared=0;
      for(const screen of frames) {
        const payload=variant.encode(screen),decoded=variant.decode(payload);
        if(decoded.some((value,index)=>value!==screen[index]))throw new Error('Corpus roundtrip failed: '+model+'/'+variant.name+'/'+sizes.length);
        sizes.push(payload.length);compared+=screen.length;
      }
      const serializedBytes=sizes.reduce((sum,size)=>sum+size,0),framingBytes=frames.length*2,sharedHeaderBytes=12;
      report.models[model].push({name:variant.name,frames:frames.length,serializedBytes,framingBytes,sharedHeaderBytes,containerBytesExcludingFont:serializedBytes+framingBytes+sharedHeaderBytes,withFontBytes:serializedBytes+framingBytes+sharedHeaderBytes+corpus.fontBytes,minBytes:Math.min(...sizes),meanBytes:serializedBytes/sizes.length,maxBytes:Math.max(...sizes),frameSizes:sizes,comparedBytes:compared});
    }
  }
  const output=path.join(__dirname,'build','alternating-report.json');fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({report:output,synthetic:report.synthetic,models:Object.fromEntries(Object.entries(report.models).map(([name,rows])=>[name,rows.map(({frameSizes,...summary})=>summary)]))},null,2));
  return report;
}

module.exports={encode,decode,encodeValues,decodeValues,variants,syntheticChecks,reportCorpus};
if(require.main===module)reportCorpus().catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});
