#!/usr/bin/env python3
"""Exercise the assembled OR-font player over 64 frames and the loop wrap.

The independent baseline coverage/screens detect native pointer, accumulation,
clear and silhouette-remap mistakes; the asset reference checks final codes.
Cycle counts exclude VIC stalls and raster waiting, and are not native FPS.
"""
import hashlib
import json
from pathlib import Path
import re
import statistics
from py65.devices.mpu6502 import MPU

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'


def main():
    labels = {name: int(value, 16) for name, value in re.findall(
        r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)', (BUILD / 'main.sym').read_text())}
    prg = (BUILD / 'player.prg').read_bytes()
    assets = BUILD / 'assets'
    baseline = HERE.parent / 'build/assets'
    original_screens = (baseline / 'reference.bin').read_bytes()
    original_font = (baseline / 'font.bin').read_bytes()
    coverages = (baseline / 'coverage-reference.bin').read_bytes()
    screens = (assets / 'reference.bin').read_bytes()
    font = (assets / 'font.bin').read_bytes()
    movie = (assets / 'spans.sa64').read_bytes()
    clips = (assets / 'clip-records.bin').read_bytes()
    clipped_cells = {int.from_bytes(clips[i:i+2], 'little') for i in range(0, len(clips), 4)}
    memory = [0xa5] * 65536
    load = int.from_bytes(prg[:2], 'little')
    memory[load:load+len(prg)-2] = prg[2:]
    immutable = bytes(memory[labels['raster_assets_start']:labels['animation_end']])
    unused_coverage = bytes(memory[0x1000:0x1400])
    cpu = MPU(memory=memory, pc=labels['start'])
    stages = {name: [] for name in ('decode', 'clear', 'face_edges', 'face_fill', 'resolve', 'render')}
    starts = {}
    faces = {3: 0, 4: 0}
    frame = 0
    previous_front = None
    frame_rows = []
    for instruction in range(30000000):
        for name in stages:
            if cpu.pc == labels[name+'_start']:
                assert name not in starts, (name, 'duplicate start')
                starts[name] = cpu.processorCycles
            if cpu.pc == labels[name+'_end']:
                assert name in starts, name
                stages[name].append(cpu.processorCycles-starts.pop(name))
        current = memory[labels['frame_index']]
        if cpu.pc == labels['render_start']:
            front = memory[labels['front_screen_hi']] << 8
            previous_front = bytes(memory[front:front+1024])
        if cpu.pc == labels['face_edges_start']:
            count = memory[labels['raster_vertex_count']]
            index = memory[labels['current_face_index']]
            assert count in (3, 4)
            assert (memory[0x1580+(index >> 3)] >> (index & 7)) & 1
            faces[count] += 1
        if cpu.pc == labels['resolve_start']:
            back = memory[labels['back_screen_hi']] << 8
            assert bytes(memory[back:back+1000]) == coverages[current*1000:(current+1)*1000], ('direct OR coverage', current)
        if cpu.pc == labels['render_end']:
            front = memory[labels['front_screen_hi']] << 8
            assert bytes(memory[front:front+1024]) == previous_front, ('front modified', current)
            assert bytes(memory[0x1000:0x1400]) == unused_coverage, ('separate coverage written', current)
        if cpu.pc == labels['wait_raster']:
            low = memory[0x100+((cpu.sp+1) & 255)]
            high = memory[0x100+((cpu.sp+2) & 255)]
            cpu.sp = (cpu.sp+2) & 255
            cpu.pc = ((low | (high << 8))+1) & 65535
            continue
        if cpu.pc == labels['frame_done']:
            assert current == frame % 64
            assert memory[labels['frame_counter']] | (memory[labels['frame_counter']+1] << 8) == frame+1
            front = memory[labels['front_screen_hi']] << 8
            output = bytes(memory[front:front+1000])
            assert output == screens[current*1000:(current+1)*1000], ('screen codes', current)
            assert bytes(memory[0x2000:0x2800]) == font
            assert bytes(memory[labels['raster_assets_start']:labels['animation_end']]) == immutable
            assert bytes(memory[labels['animation']:labels['animation_end']]) == movie
            error = 0
            differing_cells = 0
            reference = original_screens[current*1000:(current+1)*1000]
            for position, (code, original_code) in enumerate(zip(output, reference)):
                actual = font[code*8:code*8+8]
                expected = original_font[original_code*8:original_code*8+8]
                difference = sum((a ^ b).bit_count() for a, b in zip(actual, expected))
                if position not in clipped_cells:
                    assert difference == 0, ('unclipped bitmap', current, position, difference)
                error += difference
                differing_cells += difference != 0
            frame_rows.append({'frame': current, 'renderCycles': stages['render'][-1],
                               'silhouettePixelDifference': error, 'silhouetteDifferingCells': differing_cells})
            frame += 1
            if frame == 66:
                break
        cpu.step()
    else:
        raise AssertionError('Native player did not complete 64 frames plus loop wrap')
    assert len(stages['face_edges']) == len(stages['face_fill']) == sum(faces.values())
    assert not starts
    summary = lambda values: dict(samples=len(values), min=min(values), mean=statistics.mean(values), max=max(values))
    manifest = json.loads((assets / 'manifest.json').read_text())
    report = {
        'pass': True, 'frames': frame, 'loopWraps': 1,
        'screenCodeBytesChecked': frame*1000, 'directCoverageBytesChecked': frame*1000,
        'allUnclippedPixelsIdenticalToBaseline': True,
        'hiddenScreenOnlyWrites': True, 'separateCoverageWorkspaceUntouched': True,
        'fontAndAllAssetsImmutable': True,
        'visibleTriangleCalls': faces[3], 'visibleQuadCalls': faces[4],
        'measurement': 'Assembled NMOS6502 instruction cycles; no VIC stalls or raster wait. Not native FPS.',
        'stages': {name: summary(values) for name, values in stages.items()},
        'first64RenderCycles': summary([row['renderCycles'] for row in frame_rows[:64]]),
        'first64SilhouettePixelDifference': summary([row['silhouettePixelDifference'] for row in frame_rows[:64]]),
        'codeBytes': labels['player_code_end']-labels['start'],
        'sharedRasterTableBytes': manifest['sharedTableBytes']-2048,
        'fontBytes': 2048, 'movieBytes': len(movie),
        'assetAlignmentPaddingBytes': labels['raster_assets_start']-labels['player_code_end'],
        'prgBytes': len(prg), 'prgSha256': hashlib.sha256(prg).hexdigest(),
        'movieSha256': hashlib.sha256(movie).hexdigest(),
        'codeEnd': hex(labels['player_code_end']), 'assetsStart': hex(labels['raster_assets_start']),
        'endExclusive': hex(labels['animation_end']), 'frameRows': frame_rows,
    }
    baseline_report_path = HERE.parent / 'span-atlas/build/host-smoke.json'
    if baseline_report_path.exists():
        baseline_report = json.loads(baseline_report_path.read_text())
        before = baseline_report['first64RenderCycles']['mean']
        after = report['first64RenderCycles']['mean']
        report['baselineComparison'] = {
            'baselinePrgSha256': baseline_report['prgSha256'],
            'meanCyclesBefore': before, 'meanCyclesAfter': after,
            'meanCyclesSaved': before-after, 'renderReductionPercent': (before-after)*100/before,
            'instructionOnlySpeedup': before/after,
        }
    (BUILD / 'host-smoke.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'frameRows'}, indent=2))


if __name__ == '__main__':
    main()
