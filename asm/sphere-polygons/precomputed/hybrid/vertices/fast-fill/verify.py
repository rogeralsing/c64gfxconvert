#!/usr/bin/env python3
"""Build and compare the isolated OR-span replacement on assembled 6502 code."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import statistics
import subprocess

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[3]
BUILD = HERE / 'build'
KICK = '/Users/rogerjohansson/.local/bin/kickass'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def symbols(path):
    return {name: int(value, 16) for name, value in
            re.findall(r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)', path.read_text())}


def build(name, raster):
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    for file in ('main.asm', 'geometry.asm'):
        shutil.copy2(BASE / file, output / file)
    shutil.copytree(BASE / 'assets', output / 'assets', dirs_exist_ok=True)
    (output / 'raster.asm').write_text(raster)
    result = subprocess.run(['rtk', 'proxy', KICK, 'main.asm', '-odir', str(output),
                             '-o', str(output / 'program.prg'), '-symbolfile'],
                            cwd=output, check=True, capture_output=True, text=True)
    return output, result.stdout


def call(cpu, address, start=None, end=None, capture=False):
    cpu.pc = address
    cpu.sp = 0xfd
    cpu.memory[0x1fe], cpu.memory[0x1ff] = 0xff, 0x01
    cycles = cpu.processorCycles
    span_cycles = 0
    samples = 0
    interiors = 0
    common_lengths = []
    while cpu.pc != 0x0200:
        if cpu.memory[cpu.pc] == 0:
            raise RuntimeError(f'BRK ${cpu.pc:04x}')
        if capture and cpu.pc == start:
            sample = cpu.memory[0x15]
            left, right = cpu.memory[0x1480 + sample], cpu.memory[0x1500 + sample]
            samples += 1
            if left < right:
                interiors += max(0, (right >> 3) - (left >> 3) - 1)
            if sample % 3 == 0 and sample + 2 < cpu.memory[0x14]:
                lefts = cpu.memory[0x1480+sample:0x1480+sample+3]
                rights = cpu.memory[0x1500+sample:0x1500+sample+3]
                common_lengths.append(max(0, (min(rights) >> 3) - (max(lefts) >> 3) - 1))
        in_span = start is not None and start <= cpu.pc < end
        before = cpu.processorCycles
        cpu.step()
        if in_span:
            span_cycles += cpu.processorCycles - before
    return cpu.processorCycles - cycles, span_cycles, samples, interiors, common_lengths


def execute(output, cases):
    from py65.devices.mpu6502 import MPU
    labels = symbols(output / 'main.sym')
    image = (output / 'program.prg').read_bytes()
    memory = [0xa5] * 65536
    load = int.from_bytes(image[:2], 'little')
    memory[load:load + len(image) - 2] = image[2:]
    memory[1] = 0x35
    cpu = MPU(memory=memory)
    rows = []
    for case in cases:
        cpu.memory[labels['model']] = 0
        for axis in ('yaw', 'pitch', 'roll'):
            cpu.memory[labels['angle_' + axis]] = case[axis]
        cpu.a = 0
        call(cpu, labels['select_model'])
        call(cpu, labels['prepare_matrix'])
        call(cpu, labels['project_vertices'])
        for field, address in [('projectedX', 0x1400), ('projectedY', 0x1440)]:
            assert bytes(cpu.memory[address:address+64]) == base64.b64decode(case[field])
        cycles, span_cycles, samples, interiors, common_lengths = call(cpu, labels['render_polygons'],
            labels['raster_fill_span'], labels['resolve_screen'], True)
        assert bytes(cpu.memory[0x1000:0x13e8]) == base64.b64decode(case['coverage']), case['id']
        cpu.memory[labels['back_screen_hi']] = 0x0c if case['id'] % 2 else 0x04
        call(cpu, labels['resolve_screen'])
        screen = cpu.memory[labels['back_screen_hi']] << 8
        assert bytes(cpu.memory[screen:screen+1000]) == base64.b64decode(case['screen']), case['id']
        rows.append({'id': case['id'], 'group': case['group'], 'rasterCycles': cycles,
                     'spanCycles': span_cycles, 'sampleSpans': samples,
                     'interiorCellVisits': interiors, 'commonInteriorLengths': common_lengths})
    return rows, labels, sha(image)


def main():
    BUILD.mkdir(exist_ok=True, parents=True)
    source = (BASE / 'raster.asm').read_text()
    kernel = (HERE / 'kernel.asm').read_text()
    candidate = re.sub(r'raster_fill_span:[\s\S]*?(?=resolve_screen:)', kernel + '\n', source, count=1)
    assert candidate != source
    baseline_dir, _ = build('baseline', source)
    candidate_dir, _ = build('candidate', candidate)
    trace_path = BASE / 'optimization/common/trace.cjs'
    trace = json.loads(subprocess.check_output(['rtk', 'proxy', 'node', str(trace_path), '32'], cwd=BASE, text=True))
    cases = [case for case in trace['cases'] if case['model'] == 0]
    baseline, old_labels, old_hash = execute(baseline_dir, cases)
    proposed, new_labels, new_hash = execute(candidate_dir, cases)
    groups = {}
    for group in sorted({'all'} | {row['group'] for row in baseline}):
        old = [row for row in baseline if group == 'all' or row['group'] == group]
        new = [row for row in proposed if group == 'all' or row['group'] == group]
        before = {field: statistics.mean(row[field] for row in old) for field in ('rasterCycles', 'spanCycles', 'sampleSpans', 'interiorCellVisits')}
        after = {field: statistics.mean(row[field] for row in new) for field in ('rasterCycles', 'spanCycles')}
        groups[group] = {'frames': len(old), 'baseline': before, 'candidate': after,
                         'rasterChangePercent': 100 * (after['rasterCycles'] / before['rasterCycles'] - 1),
                         'spanChangePercent': 100 * (after['spanCycles'] / before['spanCycles'] - 1)}
    report = {'pass': True, 'scope': 'Checker-only assembled NMOS 6502 replay. No VIC stalls, IRQs, presentation waiting, or native FPS claim.',
              'frames': len(cases), 'coverageBytesCompared': len(cases)*1000,
              'screenBytesCompared': len(cases)*1000, 'groups': groups,
              'baselineProgramSha256': old_hash, 'candidateProgramSha256': new_hash,
              'baselineRasterSha256': sha(source.encode()), 'kernelSha256': sha(kernel.encode()),
              'baselineSpanBytes': old_labels['resolve_screen']-old_labels['raster_fill_span'],
              'candidateSpanBytesIncludingTable': new_labels['resolve_screen']-new_labels['raster_fill_span'],
              'additionalZeroPageBytes': 0, 'startupCycles': 0, 'rows': proposed}
    common = [length for row in baseline if row['group'] == 'animation-0' for length in row['commonInteriorLengths']]
    report['commonThreeSampleInterior'] = {'completeRows': len(common),
        'cells': sum(common), 'histogram': {length: common.count(length) for length in sorted(set(common))},
        'meanCellsPerCompleteRow': statistics.mean(common)}
    (BUILD / 'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
