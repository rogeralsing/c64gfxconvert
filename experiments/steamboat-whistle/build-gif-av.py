#!/usr/bin/env python3
"""Build the isolated exact approved six-second MickeyGIF/native-SID integration."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
FILM_SOURCE = HERE / 'assets/approved'
AUDIO_SOURCE = HERE / 'assets/whistle-gif-6s.wav'
FONT = FILM_SOURCE / 'font.bin'
FONT_SHA = '7fa677802cbea962c5530f0596bfe1e60dffccd6d3739ddd4cb0ff36aa06d5e6'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def module(path, name):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def build(output, loop=True):
    output.mkdir(parents=True, exist_ok=True)
    audio = output / 'audio'
    audio.mkdir(parents=True,exist_ok=True)
    assert sha(AUDIO_SOURCE.read_bytes()) == 'a8b1b7c7d359ada8e3119ed0f74838de57ce764552915b594d769855248a9554'
    component = module(HERE/'build.py','gif_av_audio_component')
    component.prepare(AUDIO_SOURCE,audio)
    prep = json.loads((audio / 'preparation.json').read_text())
    packed = (audio / 'packed.bin').read_bytes()
    expected_audio = (audio / 'expected-input.bin').read_bytes()
    assert (prep['sampleCount'], len(packed), prep['period']) == (46917, 23552, 126)
    assert sha(expected_audio) == prep['inputSha256'] and sha(packed) == prep['packedSha256']
    assert prep['sourceSha256'] == 'a8b1b7c7d359ada8e3119ed0f74838de57ce764552915b594d769855248a9554'
    font = FONT.read_bytes()
    assert len(font) == 2048 and sha(font) == FONT_SHA
    original_manifest = (FILM_SOURCE/'manifest.json').read_bytes()
    source_manifest = json.loads(original_manifest)
    assert sha(original_manifest) == 'e013c164956dfdaeeba64371119ad911b85d354b21fbb7e0a8fa28d5ab1f4449'
    assert (source_manifest['frameCount'],source_manifest['fps'],source_manifest['durationSeconds']) == (60,10,6)
    # Exact approved character IDs: no bitmap rendering, threshold, crop or
    # font rematching is permitted in this integration.
    raw_screens = (FILM_SOURCE/'screen.frames').read_bytes()
    assert sha(raw_screens) == '631fa988e77cf2713fc5ac38e8a4b54a5c69f2a4f89b035b27f4ef89344092aa'
    screens = np.frombuffer(raw_screens,np.uint8).reshape(60,1000)
    mono = module(HERE / 'screen_codec.py', 'av_mono_encoder')
    packets = [mono.encode_screen(screens[i - 1], screens[i])[0] for i in range(60)]
    movie = b''.join(packets)
    assert len(movie) == 28010
    assert sha(movie) == '2d8d79f8fbd757aeaf4106924186afb90665a846a1362317837763df271a6a6b'
    keyframe = mono.encode_screen(np.zeros(1000, np.uint8), screens[0])[0]
    assert len(keyframe) == 649 and np.array_equal(mono.decode_screen(keyframe, np.zeros(1000,np.uint8)), screens[0])
    for frame, packet in enumerate(packets):
        assert np.array_equal(mono.decode_screen(packet, screens[frame - 1]), screens[frame])
    movie_chunks = [dict(address=0x2800, offset=0, bytes=0x7000-0x2800),
                    dict(address=0x7900, offset=0x7000-0x2800, bytes=len(movie)-(0x7000-0x2800))]
    movie_end = movie_chunks[-1]['address'] + movie_chunks[-1]['bytes']
    assert movie_end == 0x9e6a
    offsets, cursor = [], 0
    for packet in packets:
        offsets.append(cursor)
        cursor += len(packet)

    def movie_address(offset):
        return 0x2800 + offset if offset < 0x4800 else 0x7900 + offset - 0x4800

    pointers = b''.join(movie_address(offset).to_bytes(2,'little') for offset in offsets)
    deadlines = [round(frame * prep['sampleCount'] / 60) for frame in range(60)]
    ranges = [(0x0c00,0x1000),(0x1b00,0x1c00),(0x1e00,0x2000)]
    jitter = []
    for page in range(0x70,0x79):
        delta = page - 0x70
        head = 5 + (delta + 1)//2
        jitter.append(dict(page=page, address=page*256, bytes=head, delta=delta))
        ranges.append((page*256+head,(page+1)*256))
    ranges.extend(((movie_end,0xd000),(0xe000,0xfffa)))
    pcm_chunks, cursor = [], 0
    for first,end in ranges:
        count = min(end-first,len(packed)-cursor)
        if count:
            pcm_chunks.append(dict(address=first,offset=cursor,bytes=count))
            cursor += count
        if cursor == len(packed):
            break
    assert cursor == len(packed), 'No PCM was dropped; address ranges are insufficient'
    for file, raw in [('packed.bin',packed),('expected-input.bin',expected_audio),('font.bin',font),
                      ('movie.bin',movie),('keyframe.bin',keyframe),('expected-screen.frames',raw_screens),
                      ('frame-pointers.bin',pointers),('frame-deadlines.bin',b''.join(x.to_bytes(2,'little') for x in deadlines))]:
        (output / file).write_bytes(raw)
    for file in ('high-lookup.bin','low-lookup.bin','target-input.bin'):
        shutil.copyfile(audio / file, output / file)
    shutil.copyfile(HERE / 'gif-av-player.asm', output / 'gif-av-player.asm')
    config = dict(PACKED_START=pcm_chunks[0]['address'],SAMPLE_COUNT=prep['sampleCount'],
                  PAGE_COUNT=prep['pageCount'],FULL_PAGES=prep['fullPages'],FINAL_VALUES=prep['finalValues'],
                  FRAME_COUNT=60,LOOP=int(loop))
    (output / 'config.asm').write_text('\n'.join(f'.const {k}={v}' for k,v in config.items())+'\n')
    transitions = ['advance_source_page:','lda packed_read+2']
    for before,after in zip(pcm_chunks,pcm_chunks[1:]):
        natural = before['address'] + before['bytes']
        assert natural & 255 == 0
        if after['address'] != natural:
            transitions += [f'cmp #{natural>>8}','bne !next+',f'lda #{after["address"]&255}',
                            'sta packed_read+1',f'lda #{after["address"]>>8}','sta packed_read+2','rts','!next:']
    transitions += ['rts']
    (output / 'source-transitions.asm').write_text('\n'.join(transitions)+'\n')
    data = ['.pc=$1800 "Encoded frame zero"','keyframe_data:','.import binary "keyframe.bin"',
            'keyframe_end:','.assert "Keyframe below PCM page",keyframe_end<=$1b00,true',
            '.pc=$1c00 "Nibble lookup high"','high_lookup:','.import binary "high-lookup.bin"',
            '.pc=$1d00 "Nibble lookup low"','low_lookup:','.import binary "low-lookup.bin"',
            '.pc=$2000 "Fixed movie font"','font:','.import binary "font.bin"',
            'font_end:','.assert "Font bank exact",font_end==$2800,true']
    for chunk in movie_chunks:
        data += [f'.pc=${chunk["address"]:04x} "Movie delta segment"',
                 f'.import binary "movie.bin",{chunk["offset"]},{chunk["bytes"]}']
    for entry in jitter:
        delta=entry['delta']
        data += [f'.pc=${entry["address"]:04x} "Original distributed jitter entry"',f'.fill {delta//2},$ea']
        data += ['.byte $85,<(restore_a+1)'] if delta%2==0 else ['.byte $8d,<(restore_a+1),>(restore_a+1)']
        data += ['jmp nmi_common']
    for chunk in pcm_chunks:
        data += [f'.pc=${chunk["address"]:04x} "Packed whistle segment"',
                 f'.import binary "packed.bin",{chunk["offset"]},{chunk["bytes"]}']
    (output / 'data.asm').write_text('\n'.join(data)+'\n')
    (output / 'main.asm').write_text('.var framePointers=LoadBinary("frame-pointers.bin")\n.var frameDeadlines=LoadBinary("frame-deadlines.bin")\n.import source "gif-av-player.asm"\n')
    command = ['rtk','proxy',str(Path.home()/'.local/bin/kickass'),'main.asm','-odir',str(output),
               '-o',str(output/'native-image.prg'),'-symbolfile']
    assembled = subprocess.run(command,cwd=output,text=True,capture_output=True,timeout=60)
    (output/'build.log').write_text(assembled.stdout+assembled.stderr)
    assert assembled.returncode==0,assembled.stdout+assembled.stderr
    labels = {k:int(v,16) for k,v in re.findall(r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)',(output/'main.sym').read_text())}
    save(output/'labels.json',labels)
    native = (output/'native-image.prg').read_bytes()
    load = int.from_bytes(native[:2],'little')
    regions = [dict(name='runtime',address=0x1000,bytes=labels['player_code_end']-0x1000),
               dict(name='keyframe',address=0x1800,bytes=len(keyframe)),dict(name='lookup-high',address=0x1c00,bytes=256),
               dict(name='lookup-low',address=0x1d00,bytes=256),dict(name='font',address=0x2000,bytes=2048)]
    regions += [dict(name='movie',**c) for c in movie_chunks]+[dict(name='packed',**c) for c in pcm_chunks]
    regions += [dict(name='jitter',address=j['address'],bytes=j['bytes']) for j in jitter]
    ordered = sorted(regions,key=lambda r:r['address'])
    for before,after in zip(ordered,ordered[1:]):
        assert before['address']+before['bytes']<=after['address'],(before,after)
    assert load==0x0801 and load+len(native)-2<=0xfffa
    for chunk in pcm_chunks:
        assert native[2+chunk['address']-load:2+chunk['address']-load+chunk['bytes']] == packed[chunk['offset']:chunk['offset']+chunk['bytes']]
    for chunk in movie_chunks:
        assert native[2+chunk['address']-load:2+chunk['address']-load+chunk['bytes']] == movie[chunk['offset']:chunk['offset']+chunk['bytes']]
    packer = module(HERE/'pack.py','whistle_cold_pack')
    package = packer.package(output/'native-image.prg',output/'player.prg',entry=labels['start'])
    program=(output/'player.prg').read_bytes()
    expected_pixels = [mono.rgba_hash(mono.decode_pixels(screen,font)) for screen in screens]
    assert expected_pixels == source_manifest['expectedDecodedRGBAHashes'], 'Approved GIF pixels must remain exact'
    result = dict(program=str((output/'player.prg').resolve()),program_sha256=sha(program),
                  native_program=str((output/'native-image.prg').resolve()),native_sha256=sha(native),
                  source_sha256=sha((HERE/'gif-av-player.asm').read_bytes()),symbols=labels,preparation=prep,
                  packedChunks=pcm_chunks,movieChunks=movie_chunks,regions=regions,package=package,
                  stateAddresses=dict(boundary_count=2,boundary_before=3,generated_pages=4,underruns=5,finished=6,next_buffer=7),
                  film=dict(frameCount=60,sourceFPS=10,durationSeconds=6,frontBufferRendering=True,source='Exact approved mono/darker GIF',
                            sourceManifestSha256=sha(original_manifest),sourceScreenSha256=sha(raw_screens),
                            monoDerivation='EXACT approved screen.frames/font copied; no re-render, threshold, crop or rematch',
                            expectedScreenFile='expected-screen.frames',expectedRGBAHashes=expected_pixels,
                            fontAddress=0x2000,fontSha256=FONT_SHA,fontBytes=2048,movieBytes=len(movie),keyframeBytes=len(keyframe),
                            frameAddresses=[movie_address(o) for o in offsets],sampleDeadlines=deadlines,
                            synchronization='Direct front-buffer delta begins at each100ms consumed-sample deadline; completion recorded separately',
                            backgroundC64=1,foregroundC64=0,colorBytes=0),
                  audioComponentSha256=sha((HERE/'player.asm').read_bytes()),screenOn=True,loop=loop,
                  entry=labels['start'],nativeEndExclusive=load+len(native)-2,codeBytes=labels['player_code_end']-0x1000,
                  sourceRegions=regions,nativePlaybackVerified=False)
    save(output/'build.json',result)
    print(json.dumps(dict(program=result['program'],programSha256=result['program_sha256'],nativeEnd=result['nativeEndExclusive'],
                          codeBytes=result['codeBytes'],movieBytes=len(movie),keyframeBytes=len(keyframe),audioBytes=len(packed),loop=loop)),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'work/mickey-gif-av')
    parser.add_argument('--no-loop',action='store_true')
    args=parser.parse_args()
    build(args.output.resolve(),not args.no_loop)

if __name__=='__main__':main()
