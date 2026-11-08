#!/usr/bin/env python3
"""Compare assembled raster kernels with persistent state and exact char output."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess

BASE = Path(__file__).resolve().parents[2]
COMMON = Path(__file__).resolve().parent

def sha(data):
    return hashlib.sha256(data).hexdigest()

def labels(path):
    return {name:int(value,16) for name,value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)",path.read_text())}

def call(cpu, address, a=None):
    cpu.pc = address
    cpu.sp = 0xfd
    cpu.memory[0x1fe], cpu.memory[0x1ff] = 0xff, 0x01
    if a is not None:
        cpu.a = a
    start = cpu.processorCycles
    steps = 0
    while cpu.pc != 0x0200:
        if cpu.memory[cpu.pc] == 0:
            raise RuntimeError(f'BRK trap at ${cpu.pc:04x}')
        cpu.step()
        steps += 1
        if steps > 1000000:
            raise RuntimeError(f'Kernel failed to return at ${cpu.pc:04x}')
    return cpu.processorCycles - start

def execute(program, symbol_file, cases):
    from py65.devices.mpu6502 import MPU
    symbols = labels(symbol_file)
    image = program.read_bytes()
    memory = [0xa5] * 65536
    start = int.from_bytes(image[:2], 'little')
    memory[start:start+len(image)-2] = image[2:]
    memory[1] = 0x35
    for first in (0x0400,0x0c00):
        memory[first:first+1024] = [0]*1024
    cpu = MPU(memory=memory)
    fixed_font = bytes(memory[0x2000:0x2800])
    fixed_assets = bytes(memory[0x4000:0xbfb0])
    init_cycles = call(cpu,symbols['delta_init']) if 'delta_init' in symbols else 0
    rows = []
    for case in cases:
        cpu.memory[symbols['model']] = case['model']
        for name in ('yaw','pitch','roll'):
            cpu.memory[symbols['angle_'+name]] = case[name]
        call(cpu,symbols['select_model'],case['model'])
        call(cpu,symbols['prepare_matrix'])
        call(cpu,symbols['project_vertices'])
        for name, address in [('projectedX',0x1400),('projectedY',0x1440)]:
            expected = base64.b64decode(case[name])
            if bytes(cpu.memory[address:address+64]) != expected:
                raise AssertionError(f'Native geometry differs at {case["id"]}: {name}')
        try:
            raster_cycles = call(cpu,symbols['render_polygons'])
        except RuntimeError as error:
            raise RuntimeError(f'Case {case["id"]}, {case["group"]}, model {case["model"]}, '
                               f'angles {case["yaw"]}/{case["pitch"]}/{case["roll"]}: {error}') from error
        actual = bytes(cpu.memory[0x1000:0x13e8])
        expected = base64.b64decode(case['coverage'])
        if actual != expected:
            first = next(i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b)
            raise AssertionError(f'Coverage differs at case {case["id"]} {case["group"]}, cell {first}: {actual[first]}/{expected[first]}')
        back = 0x0c00 if case['id']%2==0 else 0x0400
        cpu.memory[symbols['back_screen_hi']] = back>>8
        resolve_cycles = call(cpu,symbols['resolve_screen'])
        actual = bytes(cpu.memory[back:back+1000])
        expected = base64.b64decode(case['screen'])
        if actual != expected:
            first = next(i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b)
            raise AssertionError(f'Screen differs at case {case["id"]}, cell {first}: {actual[first]}/{expected[first]}')
        if bytes(cpu.memory[0x2000:0x2800]) != fixed_font:
            raise AssertionError('Fixed font changed')
        if bytes(cpu.memory[0x4000:0xbfb0]) != fixed_assets:
            raise AssertionError('Static geometry/lookup assets changed')
        rows.append({key:case[key] for key in ('id','group','model','yaw','pitch','roll')} | {
            'raster_cycles':raster_cycles,'resolve_cycles':resolve_cycles,'combined_cycles':raster_cycles+resolve_cycles})
    return {'program_sha256':sha(image),'init_cycles':init_cycles,'coverage_bytes_checked':1000*len(rows),
            'screen_bytes_checked':1000*len(rows),'frames':len(rows),'rows':rows}

def aggregate(rows):
    return {key:{'min':min(r[key] for r in rows),'mean':statistics.mean(r[key] for r in rows),
                 'max':max(r[key] for r in rows)} for key in ('raster_cycles','resolve_cycles','combined_cycles')}

def main(args):
    output = args.variant.resolve()/'build'
    output.mkdir(exist_ok=True,parents=True)
    trace_path = COMMON/'build'/f'trace-{args.frames}.json'
    trace_path.parent.mkdir(exist_ok=True,parents=True)
    current_inputs = json.loads(subprocess.check_output(['node',str(COMMON/'trace.cjs'),str(args.frames)],text=True,cwd=BASE))
    raw = json.dumps(current_inputs,separators=(',',':')).encode()
    trace_path.write_bytes(raw)
    trace_hash = sha(raw)
    baseline_path = COMMON/'build'/f'baseline-{trace_hash[:16]}.json'
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())
        if baseline['program_sha256'] != sha((BASE/'build/polygon-spheres.prg').read_bytes()):
            raise AssertionError('Cached baseline program hash differs')
    else:
        baseline = execute(BASE/'build/polygon-spheres.prg',BASE/'build/main.sym',current_inputs['cases'])
        temporary = baseline_path.with_suffix(f'.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(baseline,indent=2)+'\n')
        temporary.replace(baseline_path)
    report = {'pass':False,'strategy':args.variant.name,'measurement':'Assembled NMOS 6502 replay; excludes VIC stalls, IRQs, geometry and presentation waiting.',
              'trace_sha256':trace_hash,'inputs':current_inputs['inputs'],'baseline_program_sha256':baseline['program_sha256']}
    try:
        candidate = execute(output/'variant.prg',output/'main.sym',current_inputs['cases'])
        report.update({'candidate_program_sha256':candidate['program_sha256'],'init_cycles':candidate['init_cycles'],
                       'frames':candidate['frames'],'coverage_bytes_checked':candidate['coverage_bytes_checked'],
                       'screen_bytes_checked':candidate['screen_bytes_checked'],'groups':{},'rows':candidate['rows']})
        for group in ['all','animation-0','animation-1','jumps-pauses','single-axis','model-switch']:
            reference = [r for r in baseline['rows'] if group=='all' or r['group']==group]
            proposed = [r for r in candidate['rows'] if group=='all' or r['group']==group]
            old,new = aggregate(reference),aggregate(proposed)
            report['groups'][group]={'frames':len(proposed),'baseline':old,'candidate':new,
                'raster_change_percent':100*(new['raster_cycles']['mean']/old['raster_cycles']['mean']-1),
                'combined_change_percent':100*(new['combined_cycles']['mean']/old['combined_cycles']['mean']-1)}
        report['pass'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (output/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'pass':report['pass'],'strategy':report['strategy'],'frames':report['frames'],
        'candidate_program_sha256':report['candidate_program_sha256'],
        'groups':{name:{'raster_change_percent':group['raster_change_percent'],
                        'combined_change_percent':group['combined_change_percent']}
                  for name,group in report['groups'].items()}},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',required=True,type=Path)
    parser.add_argument('--frames',default=64,type=int)
    args=parser.parse_args()
    if not 4<=args.frames<=256:
        parser.error('--frames must be 4..256')
    main(args)
