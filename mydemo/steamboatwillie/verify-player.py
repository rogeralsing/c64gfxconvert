#!/usr/bin/env python3
"""Check every movie frame and the loop boundary at actual PAL VIC-II output.

This protects screen-only deltas, double-buffer history, PAL timing and
the contract that black ColorRAM is initialized once and never written again.
The font is fixed across the entire 256-glyph normal-hires movie.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess

from PIL import Image, ImageChops, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_BUILD = HERE / 'build'
FIELD_CYCLES = 19656
PAL_CLOCK = 985248


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def decode(screen, font):
    """Literal black-on-white text decoding, independent of the encoder."""
    assert len(screen) == 1000 and len(font) == 2048
    result = Image.new('RGB', (320, 200), (255, 255, 255))
    pixels = result.load()
    for cell, glyph in enumerate(screen):
        left, top = (cell % 40) * 8, (cell // 40) * 8
        for row in range(8):
            bits = font[glyph * 8 + row]
            for column in range(8):
                if bits & (128 >> column):
                    pixels[left + column, top + row] = (0, 0, 0)
    return result


def verify(build, output):
    build, output = build.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / 'build.json').read_text())
    assert manifest['passed']
    data = Path(manifest['sourceData'])
    source = json.loads((data / 'manifest.json').read_text())
    source_hashes = {name:sha((data / name).read_bytes()) for name in manifest['sourceHashes']}
    assert source_hashes == manifest['sourceHashes']
    frame_count = manifest['frameCount']
    program = build / 'player.prg'
    program_hash = sha(program.read_bytes())
    assert program_hash == manifest['programSha256']
    labels = json.loads((build / 'labels.json').read_text())
    events = ('presented','prepare_start','prepared','commit_start','commit_end','field_complete')
    assert len({labels[event] for event in events}) == len(events)
    font = (data / 'font.bin').read_bytes()
    assert len(font) == 2048 and font[:8] == bytes(8)
    assert source['hardwareMode'] == 'hires' and source['globalBackgroundC64Index'] == 1
    assert source['monochrome'] and source['fixedForegroundC64'] == 0
    raw_screen = (data / 'screen.frames').read_bytes()
    palette_path = REPO / 'palettes/colodore.vpl'
    palette = [tuple(int(channel,16) for channel in line.split()[:3]) for line in palette_path.read_text().splitlines()
               if line.strip() and not line.startswith('#')]
    expected = [decode(raw_screen[frame*1000:(frame+1)*1000], font)
                for frame in range(frame_count)]
    assert [sha(image.convert('RGBA').tobytes()) for image in expected] == source['expectedDecodedRGBAHashes']
    native = module(HERE / 'vice_monitor.py', 'willie_native_monitor')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port = reservation.getsockname()[1]
    command = ['/opt/homebrew/bin/x64sc','-default','+saveres','-minimized','-pal','-speed','100',
               '+warp','+autostart-warp','+confirmonexit','-sounddev','dummy','+refreshonbreak','+binarymonitor',
               '-initbreak','reset','-autostartprgmode','1','-autostart',str(program),'-VICIIfilter','0',
               '-VICIIextpal','-VICIIpalette',str(palette_path),'-VICIIsaturation','1000','-VICIIcontrast','1000',
               '-VICIIbrightness','1000','-VICIIgamma','1000','-remotemonitor','-remotemonitoraddress',f'ip4://127.0.0.1:{port}']
    report = dict(passed=False,programSha256=program_hash,fontSha256=sha(font),frameCount=frame_count,
                  targetFPS=manifest['fps'],sourceFPS=source['fps'],playbackBenchmark=manifest.get('playbackBenchmark',False),
                  holdFields=manifest['holdFields'],command=command,fields=[],commits=[],stages=[],
                  sourceData=str(data),scope='Every selected frame and first frame after loop wrap at actual completed PAL fields; natural timing, no source-time injection.')
    process = connection = monitor = None
    front_watch = color_watch = None
    active = 0
    pending = None
    initial = True
    prepare_clock = commit_clock = None
    preparation_cycles = 0
    last_counter = last_clock = None
    screenshots = {}
    state_first = labels['film_frame']
    state_last = labels['positions_left']

    def state():
        monitor.run('bank ram')
        raw = monitor.dump(output/'state.bin',state_first,state_last)
        monitor.run('bank cpu')
        return lambda key: raw[labels[key]-state_first]

    def word(read, key):
        at = labels[key]-state_first
        monitor.run('bank ram')
        raw = monitor.dump(output/'word.bin',labels[key],labels[key]+1)
        monitor.run('bank cpu')
        return int.from_bytes(raw,'little')

    def color_ram():
        monitor.run('bank io')
        raw = monitor.dump(output/'colors.bin',0xd800,0xdbff)
        monitor.run('bank cpu')
        return bytes(value&15 for value in raw)

    def matrix(address):
        monitor.run('bank ram')
        raw = monitor.dump(output/'screen.bin',address,address+999)
        monitor.run('bank cpu')
        return raw

    def resume():
        response = monitor.run('x')
        if color_watch is not None:
            assert not re.search(rf'#{color_watch}\s+\(Stop on ', response), 'A per-frame ColorRAM write executed'
        return response

    try:
        with (output/'vice.log').open('w') as log:
            process = subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            report['ownedPid'] = process.pid
            connection = native.connect(process,port)
            monitor = native.Monitor(connection)
            monitor.run('sidefx off')
            for event in events:
                monitor.checkpoint(labels[event])
            resume()
            for _ in range(frame_count * manifest['holdFields'] * 12 + 500):
                registers = monitor.registers()
                event = next((name for name in events if labels[name] == registers['pc']),None)
                assert event is not None, ('Unexpected protected memory write',registers)
                report['stages'].append(dict(event=event,**registers))
                read = state()
                if event != 'commit_end':
                    assert read('film_frame') == active
                if event == 'presented':
                    if initial:
                        initial = False
                        assert active == 0
                        monitor.run('bank ram')
                        assert monitor.dump(output/'loaded-font.bin',0x2000,0x27ff) == font
                        assert monitor.dump(output/'loaded-movie.bin',manifest['movieStart'],manifest['movieEnd']-1) == (build/'movie.bin').read_bytes()
                        monitor.run('bank io')
                        video = monitor.dump(output/'initial-video-registers.bin',0xd011,0xd024)
                        assert video[0] & 0x60 == 0, 'ECM and bitmap mode must be disabled'
                        assert video[5] & 0x10 == 0, 'Multicolor text must be disabled'
                        assert video[7] & 0x0e == 8, 'The 2 KB font must start at $2000'
                        assert video[16] & 15 == 1, 'The global background must be white'
                        monitor.run('bank cpu')
                        monitor.run(f"break store 1800 {manifest['movieEnd']-1:04x}")
                        assert color_ram() == bytes(1024)
                        result = monitor.run('break store d800 dbff')
                        color_watch = int(re.search(r'(?:BREAK|WATCH):\s*(\d+)', result)[1])
                    front = read('front_screen_hi') << 8
                    result = monitor.run(f'break store {front:04x} {front+1023:04x}')
                    front_watch = int(re.search(r'(?:BREAK|WATCH):\s*(\d+)',result)[1])
                elif event == 'prepare_start':
                    prepare_clock = registers['clock']
                elif event == 'prepared':
                    preparation_cycles = registers['clock'] - prepare_clock
                    pending = read('next_frame')
                    assert pending == (active + 1) % frame_count
                    back = read('back_screen_hi') << 8
                    prepared = decode(matrix(back),font)
                    assert ImageChops.difference(prepared,expected[pending]).getbbox() is None
                elif event == 'commit_start':
                    assert pending is not None
                    commit_clock = registers['clock']
                    for checkpoint in (front_watch,):
                        if checkpoint is not None:
                            monitor.run(f'delete {checkpoint}')
                    front_watch = None
                elif event == 'commit_end':
                    active = pending
                    assert read('film_frame') == active
                    front = read('front_screen_hi') << 8
                    published = decode(matrix(front),font)
                    assert ImageChops.difference(published,expected[active]).getbbox() is None
                    assert color_ram() == bytes(1024)
                    field = word(read,'field_counter')
                    if report['commits']:
                        assert field - report['commits'][-1]['field'] == manifest['holdFields']
                    else:
                        assert field == manifest['holdFields']
                    report['commits'].append(dict(frame=active,field=field,clock=commit_clock,
                        preparationWallCycles=preparation_cycles,commitWallCycles=registers['clock']-commit_clock))
                    pending = None
                elif event == 'field_complete':
                    counter = word(read,'field_counter')
                    if last_counter is not None:
                        assert counter == last_counter + 1
                        assert abs(registers['clock']-last_clock-FIELD_CYCLES) <= 126
                    last_counter,last_clock = counter,registers['clock']
                    picture = output/f'field-{counter:04d}-frame-{active:03d}.png'
                    monitor.run(f'scrsh "{picture}" 2')
                    actual = Image.open(picture).convert('RGB').crop((32,35,352,235))
                    difference = ImageChops.difference(actual,expected[active])
                    if difference.getbbox():
                        difference.save(output/'difference.png')
                        expected[active].save(output/'expected.png')
                        raise AssertionError(('Completed PAL field differs',counter,active))
                    screenshots.setdefault(active,picture)
                    report['fields'].append(dict(counter=counter,frame=active,clock=registers['clock'],screenshot=picture.name,differentPixels=0))
                    if len(report['commits']) >= frame_count + 1 and len(screenshots) == frame_count:
                        break
                resume()
            else:
                raise AssertionError('Bounded native proof did not finish')
            clocks = [b['clock']-a['clock'] for a,b in zip(report['commits'],report['commits'][1:])]
            assert all(abs(interval-manifest['holdFields']*FIELD_CYCLES) <= 126 for interval in clocks)
            selected = sorted(set((0,frame_count//4,frame_count//2,3*frame_count//4,frame_count-1)))
            contact = Image.new('RGB',(300*len(selected),225),(20,22,18))
            draw = ImageDraw.Draw(contact)
            for column,frame in enumerate(selected):
                image = Image.open(screenshots[frame]).convert('RGB').crop((32,35,352,235)).resize((300,200),Image.Resampling.NEAREST)
                contact.paste(image,(column*300,25))
                draw.text((column*300+6,5),f'Frame {frame}',fill=(225,230,213))
            contact.save(output/'contact.png')
            assert source_hashes == {name:sha((data/name).read_bytes()) for name in source_hashes}
            assert sha(program.read_bytes()) == program_hash
            report.update(passed=True,actualFramesVerified=len(screenshots),completedPALFields=len(report['fields']),
                comparedPixels=len(report['fields'])*64000,loopWrapAndFollowingFrameVerified=True,
                presentationFieldsPerFrame=manifest['holdFields'],fpsActualPAL=PAL_CLOCK/statistics.mean(clocks),
                preparationMaxWallCycles=max(record['preparationWallCycles'] for record in report['commits']),
                colorRAMFixedBlack=True,perFrameColorWrites=0,colorRAMStoreWatchAlwaysActive=True,
                frontProtectedDuringPreparation=True,sourceDataUnchanged=True,
                contact='contact.png',hardwareMode='hires',globalBackgroundC64Index=1,fixedForegroundC64=0,fontBytes=2048,colorBytesInMovie=0)
    finally:
        if monitor:
            (output/'monitor.log').write_text('\n'.join(monitor.transcript))
        if connection:
            try:
                connection.sendall(b'quit\n')
            except OSError:
                pass
            connection.close()
        if process and process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        report['ownedProcessExitCode'] = process.returncode if process else None
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    if data == (HERE/'generated').resolve() and build == DEFAULT_BUILD.resolve():
        metadata = dict(ready=True,program='build/player.prg',
                        programSha256=program_hash,frameCount=frame_count,fpsActualPAL=report['fpsActualPAL'],
                        sourceExpectedDecodedRGBAHashes=source['expectedDecodedRGBAHashes'],
                        movieBytes=manifest['movieBytes'],proof='build/native-check/verification.json',
                        hardwareMode='hires',fontSha256=sha(font),fontBytes=2048,monochrome=True,
                        fixedForegroundC64=0,colorBytesInMovie=0)
        (HERE/'native.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('fields','commits','stages','command')},indent=2),flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,default=DEFAULT_BUILD)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    verify(args.build,args.output or args.build/'native-check')
