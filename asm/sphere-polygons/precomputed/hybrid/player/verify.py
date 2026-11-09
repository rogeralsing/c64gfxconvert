#!/usr/bin/env python3
"""Measure complete PAL playback and compare real screen RAM with all64 frames."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[2]
spec=importlib.util.spec_from_file_location('sphere_vice_verifier',BASE/'verify-c64.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
def sha(data):return hashlib.sha256(data).hexdigest()
def symbols(path):
    result={name:int(value,16) for name,value in re.findall(r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)',path.read_text())}
    for name in ['render_start','render_end','frame_done','frame_index','frame_counter','front_screen_hi','back_screen_hi']:
        if name not in result:raise ValueError('Missing playback label: '+name)
    return result
def verify(args):
    variant=args.variant.resolve();program=variant/'build/player.prg';labels=symbols(variant/'build/main.sym')
    output=variant/'build/verification';output.mkdir(parents=True,exist_ok=True)
    font=(HERE/'build/assets/font.bin').read_bytes();reference=(HERE/'build/reference/checker-64-screen.bin').read_bytes();assert len(reference)==64000
    asset=args.asset.resolve().read_bytes() if args.asset else None
    if asset is not None:
        assert 'animation' in labels and 'animation_end' in labels
        assert labels['animation_end']-labels['animation']==len(asset)
    assert args.frames>=66,'At least one full loop and two following images are required'
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    command=[str(args.vice),'-default','+saveres','-minimized','-pal','-speed','100','+warp','+autostart-warp','+confirmonexit','-sounddev','dummy','+refreshonbreak','+binarymonitor','-initbreak','reset','-autostartprgmode','1','-autostart',str(program),'-VICIIfilter','0','-VICIIextpal','-VICIIpalette',str(BASE.parents[1]/'palettes/colodore.vpl'),'-VICIIsaturation','1000','-VICIIcontrast','1000','-VICIIbrightness','1000','-VICIIgamma','1000','-remotemonitor','-remotemonitoraddress',f'ip4://127.0.0.1:{port}']
    report={'pass':False,'variant':variant.name,'motion':json.loads((HERE/'build/assets/data-layout.json').read_text()).get('motion'),'program_sha256':sha(program.read_bytes()),'font_sha256':sha(font),'reference_sha256':sha(reference),'pal_clock_hz':native.PAL_CLOCK,'pal_frame_cycles':native.PAL_FRAME_CYCLES,'speed_percent':100,'warp':False,'measurement':'Complete decoding and screen writes with VIC stalls; cadence includes raster wait. No music or IRQ workload.','samples':[],'command':command}
    if asset is not None:report.update({'movie_bytes':len(asset),'movie_sha256':sha(asset)})
    process=connection=monitor=None;pending=None
    with (output/'vice.log').open('w') as log:
      try:
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);report['pid']=process.pid
        connection=native.connect(process,port);monitor=native.Monitor(connection);monitor.run('sidefx off')
        for resource,expected in [('MachineVideoStandard',1),('Speed',100),('InitialWarpMode',0),('AutostartWarp',0)]:
            assert f'{resource}={expected}' in monitor.run(f'resourceget "{resource}"')
        for name in ['render_start','render_end','frame_done']:monitor.checkpoint(labels[name])
        for index in range(args.frames):
            stages={}
            for name in ['render_start','render_end','frame_done']:
                monitor.run('x');registers=monitor.registers();assert registers['pc']==labels[name],(name,registers)
                stages[name]=registers
            if pending:
                # Polling the raster wrap adds a few cycles of phase jitter.
                # A full visible scan must pass; exact screenshots verify it.
                previous,pixels=pending;assert stages['frame_done']['clock']-previous['clock']>=native.PAL_FRAME_CYCLES-63
                screenshot=output/f'frame-{previous["index"]:02d}-vice.png';monitor.run(f'scrsh "{screenshot}" 2')
                previous['screenshot']=screenshot.name;previous['screenshot_comparison']=native.screenshot_matches(screenshot,pixels);pending=None
            monitor.run('bank ram');ram=monitor.dump(output/'last-ram.bin',0,65535)
            monitor.run('bank io');vic=monitor.dump(output/'last-vic.bin',0xd000,0xd03f);colors=monitor.dump(output/'last-colors.bin',0xd800,0xdbe7);cia=monitor.dump(output/'last-cia.bin',0xdd00,0xdd00)[0];monitor.run('bank cpu')
            frame=ram[labels['frame_index']];assert frame==index%64,('Frame sequence',index,frame)
            counter=int.from_bytes(ram[labels['frame_counter']:labels['frame_counter']+2],'little');assert counter==index+1
            front=ram[labels['front_screen_hi']]<<8;assert front in (0x0400,0x0c00)
            assert (vic[0x18]>>4)*0x400==front and (vic[0x18]&14)*0x400==0x2000 and (cia&3)==3
            assert not(vic[0x11]&0x60) and not(vic[0x16]&0x10) and (vic[0x11]&0x18)==0x18 and (vic[0x16]&8)
            assert all(c&15==1 for c in colors)
            expected=reference[frame*1000:(frame+1)*1000];screen=ram[front:front+1000]
            assert screen==expected,('Screen mismatch',index,frame,next((i for i,(a,b) in enumerate(zip(screen,expected)) if a!=b),None))
            assert ram[0x2000:0x2800]==font
            if asset is not None:assert ram[labels['animation']:labels['animation_end']]==asset,'Encoded movie changed during playback'
            sample={'index':index,'frame':frame,'counter':counter,'front':front,'clock':stages['frame_done']['clock'],'render_cycles':stages['render_end']['clock']-stages['render_start']['clock'],'screen_match':True}
            if report['samples']:sample['presentation_cycles']=sample['clock']-report['samples'][-1]['clock']
            report['samples'].append(sample)
            if index in (0,31,63):pending=(sample,native.pixels_from_screen(screen,font))
        assert pending is None
        intervals=[s['presentation_cycles'] for s in report['samples'][1:]];renders=[s['render_cycles'] for s in report['samples']]
        report.update({'pass':True,'frames_verified':args.frames,'loop_wrap_verified':True,'loop_wraps_verified':(args.frames-1)//64,'screen_bytes_checked':args.frames*1000,'font_bytes_checked':args.frames*2048,'movie_immutable':asset is not None,'screenshots':sum('screenshot' in s for s in report['samples']),'render_cycles':{'min':min(renders),'mean':statistics.mean(renders),'max':max(renders)},'presentation_cycles':{'min':min(intervals),'mean':statistics.mean(intervals),'max':max(intervals)},'median_fps':native.PAL_CLOCK/statistics.median(intervals),'mean_fps':native.PAL_CLOCK/statistics.mean(intervals),'pal_fields_per_presentation':statistics.mean(intervals)/native.PAL_FRAME_CYCLES})
        assert sha(program.read_bytes())==report['program_sha256']
      except BaseException as error:
        report['error']=repr(error);raise
      finally:
        if monitor:(output/'monitor.log').write_text('\n'.join(monitor.transcript))
        if connection:
            try:connection.sendall(b'quit\n')
            except OSError:pass
            connection.close()
        if process and process.poll() is None:
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        report['owned_process_exit_code']=process.returncode if process else None
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('samples','command')},indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--variant',type=Path,required=True);parser.add_argument('--vice',type=Path,default=Path('/opt/homebrew/Cellar/vice/3.10/bin/x64sc'));parser.add_argument('--frames',type=int,default=66);parser.add_argument('--asset',type=Path);verify(parser.parse_args())
