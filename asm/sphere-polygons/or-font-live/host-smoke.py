#!/usr/bin/env python3
"""Execute live 6502 geometry and polygon rasterization at varied checker poses.

References come from the existing integer native model, not prerecorded frames.
The write audit catches transient front-buffer, old-workspace and asset writes.
Instruction cycles exclude VIC stalls and raster waiting; they are not PAL FPS.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import statistics
import subprocess

from PIL import Image
from py65.devices.mpu6502 import MPU

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = HERE / 'build'
SPEC = importlib.util.spec_from_file_location('baseline_verify', ROOT / 'verify-c64.py')
BASELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASELINE)


class AuditedMemory(list):
    def __init__(self):
        super().__init__([0xa5] * 65536)
        self.immutable = []
        self.front = None
        self.guard_workspace = False
        self.write_count = 0

    def __setitem__(self, address, value):
        if isinstance(address, int):
            assert not any(first <= address < end for first, end in self.immutable), ('immutable write', hex(address))
            assert self.front is None or not self.front <= address < self.front + 1024, ('front write', hex(address))
            assert not self.guard_workspace or not 0x1000 <= address < 0x1400, ('separate coverage write', hex(address))
            self.write_count += 1
        super().__setitem__(address, value)


def poses():
    values = [(0, 0, 0), (64, 0, 0), (128, 0, 0), (192, 0, 0),
              (0, 64, 0), (0, 128, 0), (0, 0, 64), (0, 0, 128)]
    values.extend(((11 + i * 37) & 255, (24 + i * 19) & 255, (7 + i * 53) & 255) for i in range(24))
    return values


def references(samples):
    source = """
const path=require('node:path');
const model=require(path.join(process.argv[1],'native-model.cjs')).createModel();
const poses=JSON.parse(process.argv[2]);
console.log(JSON.stringify(poses.map(([yaw,pitch,roll])=>{
 const f=model.frame('checker',yaw,pitch,roll),g=f.geometry;
 return {yaw,pitch,roll,coverage:Array.from(f.coverage),screen:Array.from(f.screen),
  projectedX:Array.from(g.projectedX),projectedY:Array.from(g.projectedY),
  faceDepths:Array.from(g.faceDepths),matrix:g.matrix};
})));
"""
    result = subprocess.run(['rtk', 'proxy', 'node', '-e', source, str(ROOT), json.dumps(samples)],
                            cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def expected_screen(coverage, compact, circle_map, records):
    screen = bytearray(coverage)
    for index in range(0, len(records), 4):
        cell = int.from_bytes(records[index:index + 2], 'little')
        offset = int.from_bytes(records[index + 2:index + 4], 'little')
        screen[cell] = circle_map[offset + compact[screen[cell]]]
    return bytes(screen)


def summarize(values):
    return dict(samples=len(values), min=min(values), mean=statistics.mean(values), max=max(values))


def main():
    (BUILD / 'host-smoke.json').unlink(missing_ok=True)
    labels = {name: int(value, 16) for name, value in re.findall(
        r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)', (BUILD / 'main.sym').read_text())}
    prg = (BUILD / 'player.prg').read_bytes()
    assets = BUILD / 'assets'
    font = (assets / 'font.bin').read_bytes()
    original_font = (ROOT / 'assets/font.bin').read_bytes()
    glyph_lut = (ROOT / 'assets/glyph-lut.bin').read_bytes()
    compact = (assets / 'coverage-compact.bin').read_bytes()
    circle_map = (assets / 'circle-map.bin').read_bytes()
    records = (assets / 'clip-records.bin').read_bytes()
    clipped = {int.from_bytes(records[i:i + 2], 'little') for i in range(0, len(records), 4)}
    assert len(font) == 2048
    for mask in range(256):
        assert font[mask * 8:mask * 8 + 8] == original_font[glyph_lut[mask] * 8:glyph_lut[mask] * 8 + 8]
    assert not any(assets.glob('*.sa64')), 'Live renderer must not contain a span movie'
    samples = poses()
    states = references(samples)
    memory = AuditedMemory()
    load = int.from_bytes(prg[:2], 'little')
    memory[load:load + len(prg) - 2] = prg[2:]
    memory[0xdc01] = 255  # No keyboard keys held in this instruction emulator.
    memory.guard_workspace = True
    assets_start = labels.get('assets_start', labels.get('raster_assets_start', 0x4000))
    assets_end = labels['assets_end']
    immutable = bytes(memory[assets_start:assets_end])
    unused_coverage = bytes(memory[0x1000:0x1400])
    memory.immutable = [(0x2000, 0x2800), (assets_start, assets_end)]
    assert bytes(memory[0x2000:0x2800]) == font
    cpu = MPU(memory=memory, pc=labels['start'])
    stages = {name: [] for name in ('geometry', 'raster', 'resolve', 'render')}
    for name in ('clear', 'face_edges', 'face_fill'):
        if name + '_start' in labels and name + '_end' in labels:
            stages[name] = []
    starts = {}
    rows = []
    frames = 0
    previous_front = None
    current_state = None
    visible_faces = {3: 0, 4: 0}
    worst_images = None
    worst_error = -1
    for instruction in range(40000000):
        if cpu.pc == labels['render_start']:
            current_state = states[frames]
            for axis in ('yaw', 'pitch', 'roll'):
                memory[labels['angle_' + axis]] = current_state[axis]
            memory[labels['model']] = 0
            memory[labels['paused']] = 1
            memory[labels['rotation_mode']] = 0
            front = memory[labels['front_screen_hi']] << 8
            assert front in (0x0400, 0x0c00)
            previous_front = bytes(memory[front:front + 1024])
            memory.front = front
        new_face = False
        for name in stages:
            if cpu.pc == labels[name + '_start']:
                # The zero-overhead edge-stage label shares the loop target,
                # so subsequent edges revisit it before the one stage ends.
                if name == 'face_edges' and name in starts:
                    pass
                else:
                    assert name not in starts, (name, 'duplicate start')
                    starts[name] = cpu.processorCycles
                    new_face = name == 'face_edges'
            if cpu.pc == labels[name + '_end']:
                assert name in starts, name
                stages[name].append(cpu.processorCycles - starts.pop(name))
        if new_face:
            count = memory[labels['raster_vertex_count']]
            assert count in (3, 4)
            visible_faces[count] += 1
        if cpu.pc == labels['geometry_end']:
            pose = samples[frames]
            BASELINE.assert_bytes(bytes(memory[0x1400:0x1440]), current_state['projectedX'], 'projected X', pose)
            BASELINE.assert_bytes(bytes(memory[0x1440:0x1480]), current_state['projectedY'], 'projected Y', pose)
            for key, value in current_state['matrix'].items():
                assert memory[labels['matrix_' + key]] == value & 255, ('rotation matrix', pose, key)
        if cpu.pc == labels['resolve_start']:
            back = memory[labels['back_screen_hi']] << 8
            BASELINE.assert_bytes(bytes(memory[back:back + 1000]), current_state['coverage'], 'direct OR coverage', samples[frames])
            assert not any(memory[back + 1000:back + 1024]), ('screen padding not cleared', samples[frames])
        if cpu.pc == labels['render_end']:
            front = memory[labels['front_screen_hi']] << 8
            assert bytes(memory[front:front + 1024]) == previous_front
            assert bytes(memory[0x1000:0x1400]) == unused_coverage
            memory.front = None
        if cpu.pc == labels['wait_raster']:
            low = memory[0x100 + ((cpu.sp + 1) & 255)]
            high = memory[0x100 + ((cpu.sp + 2) & 255)]
            cpu.sp = (cpu.sp + 2) & 255
            cpu.pc = ((low | (high << 8)) + 1) & 65535
            continue
        if cpu.pc == labels['frame_done']:
            pose = samples[frames]
            assert memory[labels['model']] == 0
            assert memory[labels['frame_counter']] | memory[labels['frame_counter'] + 1] << 8 == frames + 1
            front = memory[labels['front_screen_hi']] << 8
            output = bytes(memory[front:front + 1000])
            expected = expected_screen(current_state['coverage'], compact, circle_map, records)
            BASELINE.assert_bytes(output, expected, 'final OR character codes', pose)
            face_check = BASELINE.check_faces(memory, labels, current_state, 0)
            assert bytes(memory[0x2000:0x2800]) == font
            assert bytes(memory[assets_start:assets_end]) == immutable
            before = BASELINE.pixels_from_screen(current_state['screen'], original_font)
            after = BASELINE.pixels_from_screen(output, font)
            error = 0
            differing_tiles = 0
            for cell, (code, original_code) in enumerate(zip(output, current_state['screen'])):
                actual = font[code * 8:code * 8 + 8]
                original = original_font[original_code * 8:original_code * 8 + 8]
                tile_error = sum((a ^ b).bit_count() for a, b in zip(actual, original))
                if cell not in clipped:
                    assert tile_error == 0, ('interior differs', pose, cell, tile_error)
                error += tile_error
                differing_tiles += bool(tile_error)
            protruding = sum(1 for index, pixel in enumerate(after) if pixel and
                             (index % 320 - 160) ** 2 + (index // 320 - 100) ** 2 > 94 ** 2)
            assert protruding == 0, ('silhouette spill', pose, protruding)
            row = {'frame': frames, 'yaw': pose[0], 'pitch': pose[1], 'roll': pose[2],
                   'silhouettePixelDifference': error, 'silhouetteDifferingTiles': differing_tiles,
                   'frontWhiteFaces': face_check['front_white_faces'],
                   'cycles': {name: stages[name][-1] for name in ('geometry', 'raster', 'resolve', 'render')}}
            rows.append(row)
            if error > worst_error:
                worst_error, worst_images = error, (before, after, frames)
            frames += 1
            if frames == len(samples):
                break
        cpu.step()
    else:
        raise AssertionError('Live renderer did not complete all requested poses')
    assert not starts
    assert bytes(memory[0x1000:0x1400]) == unused_coverage
    if 'face_edges' in stages and 'face_fill' in stages:
        assert len(stages['face_edges']) == len(stages['face_fill']) == sum(visible_faces.values())
    before, after, worst_frame = worst_images
    diff = bytes(96 if a == b and a else 0 if a == b else 255 for a, b in zip(before, after))
    image = Image.new('L', (960, 200))
    for index, data in enumerate((before, after, diff)):
        image.paste(Image.frombytes('L', (320, 200), data), (index * 320, 0))
    image.save(BUILD / 'host-clip-diff.png')
    report = {
        'pass': True, 'model': 'checker', 'poses': frames,
        'reference': 'Existing integer native-model.cjs, dynamically projected and rasterized for each yaw/pitch/roll pose.',
        'runtimeStages': ['rotation matrix', 'vertex projection', 'backface culling', 'edge DDA', 'polygon span fill', 'circle correction'],
        'prerecordedFrames': False,
        'all256MaskGlyphsIdenticalBeforeClipping': True,
        'projectionMatrixAndFaceDepthsMatch': True,
        'all72FaceRecordsTraversedPerPose': True,
        'directCoverageBytesChecked': frames * 1000,
        'screenCodeBytesChecked': frames * 1000,
        'allUnclippedPixelsIdenticalToBaseline': True,
        'protrudingPixels': 0,
        'frontBufferWritesDuringRender': 0,
        'separateCoverageWorkspaceWrites': 0,
        'immutableFontAndAssetWrites': 0,
        'auditedMemoryWrites': memory.write_count,
        'visibleTriangleCalls': visible_faces[3], 'visibleQuadCalls': visible_faces[4],
        'measurement': 'Assembled NMOS6502 instruction cycles including live geometry and runtime edge DDA; excludes VIC stalls and raster waiting. Not PAL FPS.',
        'stages': {name: summarize(values) for name, values in stages.items()},
        'silhouettePixelDifference': summarize([row['silhouettePixelDifference'] for row in rows]),
        'silhouetteDifferingTiles': summarize([row['silhouetteDifferingTiles'] for row in rows]),
        'worstFrame': rows[worst_frame], 'visualDiff': 'host-clip-diff.png',
        'prgBytes': len(prg), 'prgSha256': hashlib.sha256(prg).hexdigest(),
        'fontSha256': hashlib.sha256(font).hexdigest(),
        'sourceSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'rows': rows,
    }
    (BUILD / 'host-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'rows'}, indent=2))


if __name__ == '__main__':
    main()
