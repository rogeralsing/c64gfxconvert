'use strict';

// This build-time proof examines coefficient matrices only. It never generates
// vertex trajectories, coverage buffers, character screens or animation frames.
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const geometry=require('./geometry.cjs');
const {meshes}=require('./meshes.cjs');

const OUTER_RADIUS=101;
const AXIS_STATES=256;

function certify() {
  let maximumEigenvalue=0,maximumPose=null,maximumCoefficient=0,matrices=0;
  for(let yaw=0;yaw<AXIS_STATES;yaw++)for(let pitch=0;pitch<AXIS_STATES;pitch++)for(let roll=0;roll<AXIS_STATES;roll++) {
    // Use the actual geometry API, so changes to matrix arithmetic cannot
    // silently diverge from a duplicated faster rotation implementation.
    const m=geometry.matrix(yaw,pitch,roll);
    const {xx,xy,xz,yx,yy,yz}=m;
    for(const value of [xx,xy,xz,yx,yy,yz]) {
      if(!Number.isInteger(value)||Math.abs(value)>127)throw Error('Projection coefficient is not a signed byte');
      maximumCoefficient=Math.max(maximumCoefficient,Math.abs(value));
    }
    const a=xx*xx+xy*xy+xz*xz,d=yx*yx+yy*yy+yz*yz,b=xx*yx+xy*yy+xz*yz;
    // Most matrices cannot exceed the current maximum. The positive-semidefinite
    // test avoids a square root for those cases without retaining pose tables.
    if(a>maximumEigenvalue||d>maximumEigenvalue||(maximumEigenvalue-a)*(maximumEigenvalue-d)<b*b) {
      const eigenvalue=(a+d+Math.sqrt((a-d)*(a-d)+4*b*b))/2;
      if(eigenvalue>maximumEigenvalue) {
        maximumEigenvalue=eigenvalue;
        maximumPose={yaw,pitch,roll,xx,xy,xz,yx,yy,yz};
      }
    }
    matrices++;
  }

  // The norm argument needs ordinary nearest-integer coordinate products.
  // Check that contract for every used coordinate and possible coefficient.
  const coordinates=new Set(Object.values(meshes).flatMap(mesh=>mesh.verticesQ6.flat()));
  let productChecks=0;
  for(const coordinate of coordinates)for(let coefficient=-maximumCoefficient;coefficient<=maximumCoefficient;coefficient++) {
    const ideal=coordinate*coefficient*geometry.RADIUS/4096;
    const actual=geometry.product(coordinate,coefficient);
    if(Math.abs(actual-ideal)>.500000000001)throw Error('Static-coordinate product exceeds the half-unit rounding bound');
    productChecks++;
  }

  const models={};
  for(const mesh of Object.values(meshes)) {
    const vertexNormSquared=Math.max(...mesh.verticesQ6.map(point=>point.reduce((sum,value)=>sum+value*value,0)));
    const bound=geometry.RADIUS*Math.sqrt(maximumEigenvalue*vertexNormSquared)/4096+Math.SQRT2*1.5;
    models[mesh.name]={
      maximumVertexQ6NormSquared:vertexNormSquared,
      certifiedProjectedRadiusUpperBound:bound,
      integerOuterRadius:Math.ceil(bound),
      withinOuterRadius:bound<OUTER_RADIUS
    };
  }
  return {
    kind:'complete-three-axis-coefficient-operator-bound',
    pass:Object.values(models).every(model=>model.withinOuterRadius),
    outerRadius:OUTER_RADIUS,
    projectionRadiusParameter:geometry.RADIUS,
    anglesPerAxis:AXIS_STATES,
    matricesInspected:matrices,
    largestXYOperatorNormSquared:maximumEigenvalue,
    largestXYOperatorNorm:Math.sqrt(maximumEigenvalue),
    operatorMaximumPose:maximumPose,
    maximumAbsoluteCoefficient:maximumCoefficient,
    coordinateProductChecks:productChecks,
    models,
    reasoning:'For each of all 256^3 actual quantized rotation matrices, calculate the largest eigenvalue of A*A^T for its two projection rows. Cauchy bounds the projection of every mesh vertex. Three independently rounded coordinate products add at most 1.5 units per axis, so add sqrt(2)*1.5 to the radial bound. Saturation toward valid screen limits cannot increase radial distance. The certified bound is below outer radius 101, which is below 128; full and partial dot products therefore remain within signed-byte range.',
    sourceHashes:Object.fromEntries(['geometry.cjs','geometry.asm','meshes.cjs'].map(file=>[
      file,crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname,file))).digest('hex')
    ]))
  };
}

if(require.main===module) {
  if(process.argv.length>3) {
    console.error('Usage: node bound-certificate.cjs [OUTPUT.json]');
    process.exitCode=1;
  }else {
    try {
      const report=certify();
      const output=path.resolve(process.argv[2]||path.join(__dirname,'build/projection-bounds-roll.json'));
      fs.mkdirSync(path.dirname(output),{recursive:true});
      fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
      console.log(JSON.stringify({pass:report.pass,matrices:report.matricesInspected,outerRadius:report.outerRadius,models:report.models,output}));
      if(!report.pass)process.exitCode=1;
    }catch(error) {
      console.error('bound-certificate: '+error.message);
      process.exitCode=1;
    }
  }
}

module.exports={certify};
