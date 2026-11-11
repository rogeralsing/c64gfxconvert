#!/usr/bin/env python3
"""Measure the actual assembled decoder for every stored glass-film transition.

This exercises native patch pointers and the final closing delta. Instruction
cycles exclude VIC steals, raster waits and scanout, so this is not an FPS proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

try:
    from py65.devices.mpu6502 import MPU
except ModuleNotFoundError:
    sys.path.insert(0, '/tmp/disco-sid-analysis-py65')
    from py65.devices.mpu6502 import MPU


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    native = args.native.resolve()
    storage = args.storage.resolve()
    build = json.loads((native / 'build.json').read_text())
    codec = 'literal' if build['variant'] == 'literal-front' else 'sparse'
    index = json.loads((storage / (codec + '-index.json')).read_text())
    references = (native / 'reference.frames').read_bytes()
    font = (native / 'font.bin').read_bytes()
    program = (native / 'player.prg').read_bytes()
    labels = {name: int(address, 16) for name, address in re.findall(
        r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)', (native / 'main.sym').read_text())}
    program_sha = hashlib.sha256(program).hexdigest()
    assert program_sha == build['hashes']['program']
    memory = [0xa5] * 65536
    load = int.from_bytes(program[:2], 'little')
    memory[load:load+len(program)-2] = program[2:]
    source_regions = build.get('sourceRegions') or [{
        'start': labels['animation'], 'end': labels['animation_end'], 'file': 'movie.bin'}]
    immutable = [(region['start'], (native / region['file']).read_bytes()) for region in source_regions]
    rows = []
    for record in index:
        source = record['fromPose']
        target = record['targetPose']
        memory[0x0400:0x07e8] = references[source*1000:(source+1)*1000]
        memory[0x07e8:0x0800] = [0xa5] * 24
        memory[labels['frame_index']] = source
        cpu = MPU(memory=memory, pc=labels['render_start'])
        for instruction in range(200000):
            if cpu.pc == labels['render_end']:
                break
            cpu.step()
        else:
            raise AssertionError(('Decoder did not return', source, target, cpu.pc))
        assert bytes(memory[0x0400:0x07e8]) == references[target*1000:(target+1)*1000], ('Screen', source, target)
        assert bytes(memory[0x07e8:0x0800]) == bytes([0xa5]) * 24, ('Screen overrun', source, target)
        assert bytes(memory[0x2000:0x2000+len(font)]) == font, ('Font changed', source, target)
        for address, expected in immutable:
            assert bytes(memory[address:address+len(expected)]) == expected, ('Film data changed', source, target, address)
        rows.append({'fromPose': source, 'targetPose': target, 'closing': record['closing'],
                     'payloadBytes': record['bytes'], 'instructionCycles': cpu.processorCycles,
                     'instructions': instruction})
    values = [row['instructionCycles'] for row in rows]
    report = {'pass': True, 'engine': 'py65 NMOS6502', 'programSha256': program_sha,
              'scope': 'Actual assembled render_start to render_end, excluding VIC steals, raster waits and scanout. Not native FPS.',
              'transitionsVerified': len(rows), 'closingTransitionsVerified': sum(row['closing'] for row in rows),
              'screenBytesCompared': len(rows)*1000, 'fontAndMovieUnchanged': True, 'noScreenOverrun': True,
              'renderInstructionCycles': {'min': min(values), 'mean': statistics.mean(values), 'max': max(values)},
              'frames': rows}
    output = (args.output or native / 'host-proof.json').resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'frames'}, indent=2))


if __name__ == '__main__':
    main()
