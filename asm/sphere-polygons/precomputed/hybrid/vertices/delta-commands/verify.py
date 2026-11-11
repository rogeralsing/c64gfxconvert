#!/usr/bin/env python3
"""Prove queued future-geometry decoding and bounded single-front flushes."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import statistics
from py65.devices.mpu6502 import MPU

HERE=Path(__file__).resolve().parent
BUILD=HERE/'build'


class Memory(list):
    def __init__(self):
        super().__init__([0xa5]*65536);self.active=False;self.pending=[]
    def __setitem__(self,address,value):
        if self.active and isinstance(address,int):
            if 0x0400<=address<0x0800:self.pending.append((address,value))
            elif 0x0c00<=address<0x1000 or 0x2000<=address<0x2800 or address in (0xd011,0xd015,0xd018,0xdd00):raise AssertionError(('Protected display state',hex(address)))
        super().__setitem__(address,value)


def main():
    labels={name:int(value,16) for name,value in re.findall(r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)',(BUILD/'main.sym').read_text())}
    image=(BUILD/'player.prg').read_bytes()
    reference=(HERE/'../../player/build/reference/checker-64-screen.bin').read_bytes()
    coverage=(HERE/'../build/assets/coverage-reference.bin').read_bytes()
    font=(BUILD/'assets/font.bin').read_bytes()
    memory=Memory();load=int.from_bytes(image[:2],'little');memory[load:load+len(image)-2]=image[2:]
    immutable=bytes(memory[labels['glyph_lut']:labels['animation_end']])
    cpu=MPU(memory=memory,pc=labels['start'])
    frames=[];computes=[];flushes=[];writes=[]
    current_compute=None;current_flush=None;pending=None;last_wait_exit=None
    last_flush_end=None;compute_end_stamp=None;post_flush_drivers=[];pre_wait_drivers=[]
    for instruction in range(10000000):
        pc=cpu.pc
        if pc==labels['wait_boundary']:
            assert current_compute is None and current_flush is None
            if compute_end_stamp is not None:
                pre_wait_drivers.append(cpu.processorCycles-compute_end_stamp);compute_end_stamp=None
            low=memory[0x100+((cpu.sp+1)&255)];high=memory[0x100+((cpu.sp+2)&255)]
            cpu.sp=(cpu.sp+2)&255;cpu.pc=((low|(high<<8))+1)&65535;cpu.processorCycles+=6
            last_wait_exit=cpu.processorCycles
            continue
        if pc==labels['compute_start']:
            assert current_compute is None and current_flush is None
            if last_flush_end is not None:post_flush_drivers.append(cpu.processorCycles-last_flush_end)
            display=memory[labels['frame_index']];target=memory[labels['target_update_index']]
            assert display==len(frames)%64 and target==(display+1)%64
            assert bytes(memory[0x0400:0x07e8])==reference[display*1000:(display+1)*1000]
            current_compute={'sequence':len(frames),'frame':display,'target':target,'start':cpu.processorCycles,'front':bytes(memory[0x0400:0x0800])}
            memory.active=True
        if pc==labels['compute_end']:
            assert current_compute is not None
            compute_end_stamp=cpu.processorCycles
            target=current_compute['target']
            assert bytes(memory[0x1000:0x13e8])==coverage[target*1000:(target+1)*1000],('coverage',target)
            assert bytes(memory[0x0400:0x0800])==current_compute.pop('front'),'Compute wrote visible screen'
            count=memory[labels['queue_count']];assert count<=128
            addresses=[memory[0x1400+i]|(memory[0x1480+i]<<8) for i in range(count)]
            assert all(addresses[i]<addresses[i+1] for i in range(count-1))
            assert all(0x0400<=address<0x07e8 for address in addresses)
            for i,address in enumerate(addresses):assert memory[0x1500+i]==reference[target*1000+address-0x0400]
            current_compute['queueCount']=count;current_compute['cpuCycles']=cpu.processorCycles-current_compute.pop('start')
            pending=current_compute;computes.append(current_compute);current_compute=None
        if pc==labels['frame_done']:
            assert pending is not None and current_compute is None and current_flush is None
            display=memory[labels['frame_index']];assert display==len(frames)%64
            assert bytes(memory[0x0400:0x07e8])==reference[display*1000:(display+1)*1000]
            assert bytes(memory[0x2000:0x2800])==font
            assert bytes(memory[labels['glyph_lut']:labels['animation_end']])==immutable
            assert memory[0xd018]==0x18 and memory[0xd015]==0 and memory[0xd011]&0x7f==0x1b
            frames.append({'frame':display,'target':pending['target']})
        if pc==labels['flush_start']:
            assert pending is not None and last_wait_exit is not None
            driver=cpu.processorCycles-last_wait_exit;assert driver+15<=63
            current_flush={'sequence':len(frames)-1,'target':pending['target'],'start':cpu.processorCycles,'stores':0,'worstSlack':None,'postWaitDriverCycles':driver}
        if pc==labels['flush_end']:
            assert current_flush is not None
            last_flush_end=cpu.processorCycles
            target=current_flush['target']
            assert bytes(memory[0x0400:0x07e8])==reference[target*1000:(target+1)*1000],('flushed screen',target)
            assert current_flush['stores']==pending['queueCount']
            current_flush['cpuCycles']=cpu.processorCycles-current_flush.pop('start')
            flushes.append(current_flush);current_flush=None;pending=None
            if len(frames)==194:break
        opcode=memory[pc];assert opcode!=0,('BRK',hex(pc))
        memory.pending.clear();cpu.step()
        for address,value in memory.pending:
            assert current_flush is not None and pc==labels['screen_store'],'Visible write outside flush'
            row,column=divmod(address-0x0400,40);offset=cpu.processorCycles-current_flush['start'];deadline=(312-256+51+row*8)*63
            write={'sequence':current_flush['sequence'],'target':current_flush['target'],'address':address,'row':row,'column':column,'cpuCompleteOffset':offset,'deadline':deadline,'completionUpperBound':offset+1075+63,'slack':deadline-offset-1075-63}
            if writes and writes[-1]['sequence']==write['sequence']:assert writes[-1]['address']<address
            writes.append(write);current_flush['stores']+=1
            if current_flush['worstSlack'] is None or write['slack']<current_flush['worstSlack']:current_flush['worstSlack']=write['slack']
    else:raise AssertionError('Player did not complete194 presented frames and flushes')
    assert len(frames)==len(flushes)==194
    worst=min(writes,key=lambda write:write['slack'])
    stats=lambda values:dict(min=min(values),mean=statistics.mean(values),max=max(values))
    maximum_flush=max(item['cpuCycles'] for item in flushes)
    maximum_update=max(item['cpuCycles'] for item in computes)+maximum_flush
    driver_allowance=128
    measured_drivers=max(post_flush_drivers)+max(pre_wait_drivers)+max(item['postWaitDriverCycles'] for item in flushes)
    assert measured_drivers+5<=driver_allowance,'Driver allowance does not cover measured paths plus counter carry'
    bound=worst['slack']>0 and maximum_flush+1138<6741
    assert bound,'Queued flush is not proven before first next-field row'
    report={'pass':True,'blankingFlushBoundPass':bound,'scope':'Precomputed geometric probe-mask XOR deltas, future-target coverage and sparseglyphqueue; actual6502 CPU proof, not realPAL FPS.',
        'presentedFrames':194,'loopWraps':3,'coverageBytesCompared':194000,'screenBytesCompared':194000,'frontUnchangedDuringCompute':True,'allVisibleWritesOnlyInAscendingFlush':True,'fontAndAllAssetsImmutable':True,
        'computeCpuCycles':stats([item['cpuCycles'] for item in computes]),'flushCpuCycles':stats([item['cpuCycles'] for item in flushes]),'queueEntries':stats([item['queueCount'] for item in computes]),
        'maximumComputePlusFlushCpu':maximum_update,'driverCpuAllowance':driver_allowance,'measuredPostFlushToCompute':stats(post_flush_drivers),'measuredComputeEndToWait':stats(pre_wait_drivers),'measuredPostWaitRtsToFlush':stats([item['postWaitDriverCycles'] for item in flushes]),'twoFieldCpuBound':maximum_update+2150+63+driver_allowance,'twoFieldCpuBoundPass':maximum_update+2213+driver_allowance<39312,
        'stallBudgetPerField':1075,'startJitterBudget':63,'maximumFlushClockBound':maximum_flush+1138,'firstRowDeadline':6741,'worstPerRowSlack':worst['slack'],'worstWrite':worst,
        'codeBytes':labels['delta_code_end']-labels['start'],'fontBytes':2048,'fixedLookupBytes':labels['lookup_end']-labels['glyph_lut'],'fixedLookupInternalPaddingBytes':labels['clip_cell_classes']-labels['limb_remap']-8880,'codeToLookupPaddingBytes':labels['glyph_lut']-labels['delta_code_end'],'movieBytes':labels['animation_end']-labels['animation'],
        'geometryPlaneAllocatedBytes':1024,'sparseGlyphQueueBytes':384,'queueCapacity':128,'prgBytes':len(image),'endExclusive':hex(labels['animation_end']),
        'programSha256':hashlib.sha256(image).hexdigest(),'computes':computes,'flushes':flushes}
    (BUILD/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    with gzip.open(BUILD/'writes.jsonl.gz','wt') as handle:
        for write in writes:handle.write(json.dumps(write,separators=(',',':'))+'\n')
    print(json.dumps({key:value for key,value in report.items() if key not in ('computes','flushes')},indent=2))


if __name__=='__main__':main()
