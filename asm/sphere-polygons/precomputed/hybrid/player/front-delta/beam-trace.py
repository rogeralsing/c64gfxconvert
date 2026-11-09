#!/usr/bin/env python3
"""Bound each real single-buffer STA against the next PAL matrix-row fetch.

This is an assembled NMOS6502 trace plus an intentionally pessimistic PAL
deadline bound, not a cycle-exact VIC emulator or a screenshot-based tear test.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import statistics
from py65.devices.mpu6502 import MPU

HERE=Path(__file__).resolve().parent
PAL_LINES=312
LINE_CYCLES=63
START_LINE=256
FIRST_BADLINE=51
BADLINE_STEP=8
MAX_BADLINE_STALL=43  # 40 phi2 matrix accesses plus up to 3 BA/RDY lead-in cycles.
STALL_BUDGET=25*MAX_BADLINE_STALL
FIELD_CYCLES=PAL_LINES*LINE_CYCLES
STA_OPCODES={0x81,0x85,0x8d,0x91,0x95,0x99,0x9d}


def digest(data):return hashlib.sha256(data).hexdigest()


class Memory(list):
    def __init__(self):
        super().__init__([0xa5]*65536)
        self.active=False
        self.pending=[]

    def __setitem__(self,address,value):
        if self.active and isinstance(address,int):
            if 0x0400<=address<0x07e8:
                self.pending.append((address,value))
            elif 0x2000<=address<0x2800 or 0x0c00<=address<0x1000 or address in (0xd011,0xd015,0xd018,0xdd00):
                raise AssertionError(f'Timed update changed protected display state ${address:04x}')
        super().__setitem__(address,value)


def summary(values):
    return dict(samples=len(values),min=min(values),mean=statistics.mean(values),max=max(values)) if values else dict(samples=0,min=None,mean=None,max=None)


def trace(args):
    program=HERE/'build/player.prg'
    symbols=HERE/'build/main.sym'
    labels={name:int(value,16) for name,value in re.findall(r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)',symbols.read_text())}
    for name in ('start','render_start','render_end','frame_done','frame_index','frame_counter','wait_boundary','literal_store','repeat_store','destination_ptr','animation','animation_end'):
        assert name in labels,name
    reference_path=HERE.parent/'build/reference/checker-64-screen.bin'
    font_path=HERE.parent/'build/assets/font.bin'
    reference=reference_path.read_bytes()
    font=font_path.read_bytes()
    assert len(reference)==64000 and len(font)==2048
    image=program.read_bytes()
    memory=Memory()
    load=int.from_bytes(image[:2],'little')
    memory[load:load+len(image)-2]=image[2:]
    immutable=bytes(memory[labels['animation']:labels['animation_end']])
    cpu=MPU(memory=memory,pc=labels['start'])
    frames=[]
    all_writes=[]
    rows=[{'row':row,'nextBadline':FIRST_BADLINE+BADLINE_STEP*row,
           'deadlineFromLine256':(PAL_LINES-START_LINE+FIRST_BADLINE+BADLINE_STEP*row)*LINE_CYCLES,
           'stores':0,'worstSlack':None,'worstWrite':None} for row in range(25)]
    active=None
    completed=None
    last_wait_exit=None
    for instruction in range(10000000):
        pc=cpu.pc
        if pc==labels['wait_boundary']:
            assert active is None,'Raster wait entered inside timed render'
            low=memory[0x100+((cpu.sp+1)&255)]
            high=memory[0x100+((cpu.sp+2)&255)]
            cpu.sp=(cpu.sp+2)&255
            cpu.pc=((low|(high<<8))+1)&65535
            cpu.processorCycles+=6  # Retain the RTS cost, omit only polling/wait.
            last_wait_exit=cpu.processorCycles
            continue
        if pc==labels['render_start']:
            assert active is None and last_wait_exit is not None
            assert memory[0xd011]&0x7f==0x1b and memory[0xd015]==0
            assert memory[0xd018]==0x18 and memory[0xdd00]&3==3
            current=memory[labels['frame_index']]
            assert current==len(frames)%64,('frame order',len(frames),current)
            prior=(current-1)%64 if frames else 0
            assert bytes(memory[0x0400:0x07e8])==reference[prior*1000:(prior+1)*1000],('prior screen',current)
            driver=cpu.processorCycles-last_wait_exit
            # A BIT/branch polling period is 7 clocks. Reserve 15 including
            # overshoot, final branch and RTS, then the measured post-RTS driver.
            assert driver+15<=args.start_jitter_cycles,('start jitter budget too small',driver)
            active={'sequence':len(frames),'frame':current,'startCpu':cpu.processorCycles,
                    'driverAfterWaitRtsCycles':driver,'writes':[]}
            memory.active=True
        if pc==labels['render_end']:
            assert active is not None
            memory.active=False
            writes=active.pop('writes')
            elapsed=cpu.processorCycles-active.pop('startCpu')
            assert elapsed+STALL_BUDGET+args.start_jitter_cycles<FIELD_CYCLES,'Update may span more than one PAL field'
            current=active['frame']
            assert bytes(memory[0x0400:0x07e8])==reference[current*1000:(current+1)*1000],('decoded screen',current)
            assert all(writes[i]['address']<writes[i+1]['address'] for i in range(len(writes)-1)),('nonascending writes',current)
            if not frames:assert not writes,'Startup frame zero must be the DEN-off decoded key'
            active.update({'cpuCycles':elapsed,'storeCount':len(writes),'ascending':True,
                           'wholeUpdateClockUpperBound':elapsed+STALL_BUDGET+args.start_jitter_cycles,
                           'worstSlack':min((write['slack'] for write in writes),default=None),
                           'lastStoreCpuOffset':writes[-1]['cpuCompleteOffset'] if writes else None})
            completed=active
            active=None
        if pc==labels['frame_done']:
            assert active is None and completed is not None
            current=memory[labels['frame_index']]
            assert current==len(frames)%64 and current==completed['frame']
            counter=memory[labels['frame_counter']]|(memory[labels['frame_counter']+1]<<8)
            assert counter==len(frames)+1
            assert bytes(memory[0x0400:0x07e8])==reference[current*1000:(current+1)*1000]
            assert bytes(memory[0x2000:0x2800])==font
            assert bytes(memory[labels['animation']:labels['animation_end']])==immutable
            frames.append(completed)
            completed=None
            if len(frames)==args.frames:break
        opcode=memory[pc]
        assert opcode!=0,('BRK trap',hex(pc))
        memory.pending.clear()
        cpu.step()
        if memory.pending:
            assert active is not None and opcode in STA_OPCODES,('Non-STA screen write',hex(pc))
            assert pc in (labels['literal_store'],labels['repeat_store']),('Unexpected screen store PC',hex(pc))
            for address,value in memory.pending:
                row,column=divmod(address-0x0400,40)
                offset=cpu.processorCycles-active['startCpu']
                deadline=rows[row]['deadlineFromLine256']
                # Charge the entire field's worst-case stall budget even to
                # early writes. No exact VIC phase or column timing is assumed.
                upper=offset+STALL_BUDGET+args.start_jitter_cycles
                write={'sequence':active['sequence'],'frame':active['frame'],'address':address,'pc':pc,
                       'row':row,'column':column,'value':value,'cpuCompleteOffset':offset,
                       'clockCompletionUpperBound':upper,'rowStartDeadline':deadline,'slack':deadline-upper}
                assert write['slack']>0,('Matrix fetch deadline not proven',write)
                active['writes'].append(write)
                all_writes.append(write)
                rows[row]['stores']+=1
                if rows[row]['worstSlack'] is None or write['slack']<rows[row]['worstSlack']:
                    rows[row]['worstSlack']=write['slack']
                    rows[row]['worstWrite']=write
    else:raise AssertionError('Trace did not complete requested frame count')
    assert len(frames)>=194 and sum(frame['frame']==0 for frame in frames)>=4
    worst=min(all_writes,key=lambda write:write['slack'])
    output=HERE/'build'
    trace_path=output/'beam-writes.jsonl.gz'
    with gzip.open(trace_path,'wt',encoding='utf8') as handle:
        for write in all_writes:handle.write(json.dumps(write,separators=(',',':'))+'\n')
    report={'pass':True,'scope':'Assembled NMOS6502 per-store trace plus conservative PAL row-deadline bound; not cycle-exact VIC simulation. Independent PAL scanout verification is separate.',
        'frames':len(frames),'loopWraps':(len(frames)-1)//64,'screenBytesCompared':len(frames)*1000,
        'programSha256':digest(image),'referenceSha256':digest(reference),'fontSha256':digest(font),
        'storesTraced':len(all_writes),'allTimedStoreAddressesStrictlyAscendingPerFrame':True,
        'fontAndMovieImmutable':True,'noTimedFontBankControlOrBackBufferWrites':True,
        'timing':{'palLines':PAL_LINES,'clocksPerLine':LINE_CYCLES,'startLine':START_LINE,'yScroll':3,
                  'matrixBadlines':'51 + 8*r, r=0..24; final row is line243',
                  'deadline':'Start of next row badline, before its first matrix-fetch clock',
                  'startJitterClocksReserved':args.start_jitter_cycles,'maximumPostWaitRtsDriverCycles':max(frame['driverAfterWaitRtsCycles'] for frame in frames),
                  'wholeFieldStallClocksReserved':STALL_BUDGET,'stallDerivation':'25*(40 matrix-access clocks + up to3 BA/RDY lead-in clocks)',
                  'sprites':False,'interruptWork':False,'fontAndDisplayRegistersStaticDuringUpdates':True},
        'startupKeyScope':'Initial key is decoded with DEN off before the traced frame0 no-op. Every later frame0 is the actual63-to0 closing delta.',
        'cpuRenderCycles':summary([frame['cpuCycles'] for frame in frames]),
        'wholeUpdateClockUpperBounds':summary([frame['wholeUpdateClockUpperBound'] for frame in frames]),
        'worstStoreSlackClocks':worst['slack'],'worstStoreSlackMilliseconds':worst['slack']*1000/985248,'worstWrite':worst,
        'rows':rows,'framesDetail':frames,'fullWriteTrace':trace_path.name,'fullWriteTraceSha256':digest(trace_path.read_bytes()),
        'timingSources':[{'title':'Christian Bauer: The MOS6567/6569 video controller, sections2.4.3,3.5,3.6 and3.7','url':'https://www.cebix.net/VIC-Article.txt'},
                         {'title':'Linus Akesson: VIC6569/8565 Timing Chart','url':'https://www.linusakesson.net/programming/vic-timing/victiming.pdf'}]}
    (output/'beam-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('rows','framesDetail','timingSources')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames',type=int,default=194)
    parser.add_argument('--start-jitter-cycles',type=int,default=63)
    trace(parser.parse_args())
