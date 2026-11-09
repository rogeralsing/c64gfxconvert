#!/usr/bin/env python3
"""Check the assembled span-atlas player through all 64 frames and loop wrap."""
import hashlib
import json
from pathlib import Path
import re
import statistics
from py65.devices.mpu6502 import MPU

HERE=Path(__file__).resolve().parent
BUILD=HERE/'build'


def main():
    labels={name:int(value,16) for name,value in re.findall(r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)',(BUILD/'main.sym').read_text())}
    prg=(BUILD/'player.prg').read_bytes()
    assets=BUILD/'assets'
    reference=HERE.parent/'build/assets'
    screens=(reference/'reference.bin').read_bytes()
    coverages=(reference/'coverage-reference.bin').read_bytes()
    font=(assets/'font.bin').read_bytes()
    movie=(assets/'spans.sa64').read_bytes()
    memory=[0xa5]*65536
    load=int.from_bytes(prg[:2],'little')
    memory[load:load+len(prg)-2]=prg[2:]
    immutable=bytes(memory[labels['raster_assets_start']:labels['animation_end']])
    cpu=MPU(memory=memory,pc=labels['start'])
    stages={name:[] for name in ('decode','clear','face_edges','face_fill','resolve','render')}
    starts={}
    faces={3:0,4:0}
    frame=0
    previous_front=None
    frame_rows=[]
    for instruction in range(30000000):
        for name in stages:
            if cpu.pc==labels[name+'_start']:
                assert name not in starts,(name,'duplicate start')
                starts[name]=cpu.processorCycles
            if cpu.pc==labels[name+'_end']:
                assert name in starts,name
                stages[name].append(cpu.processorCycles-starts.pop(name))
        current=memory[labels['frame_index']]
        if cpu.pc==labels['render_start']:
            front=memory[labels['front_screen_hi']]<<8
            previous_front=bytes(memory[front:front+1024])
        if cpu.pc==labels['face_edges_start']:
            count=memory[labels['raster_vertex_count']]
            index=memory[labels['current_face_index']]
            assert count in (3,4)
            assert (memory[0x1580+(index>>3)]>>(index&7))&1
            faces[count]+=1
        if cpu.pc==labels['resolve_start']:
            assert bytes(memory[0x1000:0x13e8])==coverages[current*1000:(current+1)*1000],('coverage',current)
        if cpu.pc==labels['render_end']:
            front=memory[labels['front_screen_hi']]<<8
            assert bytes(memory[front:front+1024])==previous_front,('front modified',current)
        if cpu.pc==labels['wait_raster']:
            low=memory[0x100+((cpu.sp+1)&255)]
            high=memory[0x100+((cpu.sp+2)&255)]
            cpu.sp=(cpu.sp+2)&255
            cpu.pc=((low|(high<<8))+1)&65535
            continue
        if cpu.pc==labels['frame_done']:
            assert current==frame%64
            assert memory[labels['frame_counter']]|(memory[labels['frame_counter']+1]<<8)==frame+1
            front=memory[labels['front_screen_hi']]<<8
            assert bytes(memory[front:front+1000])==screens[current*1000:(current+1)*1000],('screen',current)
            assert bytes(memory[0x2000:0x2800])==font
            assert bytes(memory[labels['raster_assets_start']:labels['animation_end']])==immutable
            assert bytes(memory[labels['animation']:labels['animation_end']])==movie
            frame_rows.append({'frame':current,'renderCycles':stages['render'][-1]})
            frame+=1
            if frame==66:break
        cpu.step()
    else:raise AssertionError('Native player did not complete64+wrap frames')
    assert len(stages['face_edges'])==len(stages['face_fill'])==sum(faces.values())
    assert not starts
    summary=lambda values:dict(samples=len(values),min=min(values),mean=statistics.mean(values),max=max(values))
    manifest=json.loads((assets/'manifest.json').read_text())
    report={'pass':True,'frames':frame,'loopWraps':1,'screenBytesChecked':frame*1000,'coverageBytesChecked':frame*1000,
        'fontAndAllAssetsImmutable':True,'visibleTriangleCalls':faces[3],'visibleQuadCalls':faces[4],
        'measurement':'Assembled NMOS6502 instruction cycles; no VIC stalls, raster waiting, presentation, projection, or runtime edge DDA. Not native FPS.',
        'edgeStageMeaning':'Decode normalized per-face crossing samples into span_left/right arrays.',
        'stages':{name:summary(values) for name,values in stages.items()},'first64RenderCycles':summary([row['renderCycles'] for row in frame_rows[:64]]),
        'codeBytes':labels['player_code_end']-labels['start'],'sharedRasterTableBytes':manifest['sharedTableBytes']-2048,
        'fontBytes':2048,'movieBytes':len(movie),'assetAlignmentPaddingBytes':labels['raster_assets_start']-labels['player_code_end'],
        'prgBytes':len(prg),'prgSha256':hashlib.sha256(prg).hexdigest(),'movieSha256':hashlib.sha256(movie).hexdigest(),
        'codeEnd':hex(labels['player_code_end']),'assetsStart':hex(labels['raster_assets_start']),'endExclusive':hex(labels['animation_end']),
        'frameRows':frame_rows}
    (BUILD/'host-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='frameRows'},indent=2))


if __name__=='__main__':main()
