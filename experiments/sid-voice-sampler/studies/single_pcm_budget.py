"""Bounded one-PCM CPU diagnostic, never an alternative musical port.

Original C3 is deliberately omitted. C1 triangle/C4 drums remain byte-exact;
SID1 retains C2 and SID2 exercises ordinary zero-frequency TEST commands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SID = HERE.parent
sys.path[:0] = [str(SID / "native_instruments"), str(SID)]
import baseline
import compact_s3
import native_support as support
from native_instruments.measure_music_budget import measure as measure_cpu

GOLD = "080852a5c0cf96f0e3b00ac856d594015c92a513435ccb5e08816d54cfa267a2"


def save(path: Path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def delay(cycles: int) -> str:
    """Exact cold delay including RTS, with every branch within one page."""
    for outer in range(1, 255):
        for inner in range(1, 256):
            extra = cycles - (8 + outer * 1281 + inner * 5)
            if 0 <= extra <= 12 and extra != 1:
                tail = ("bit $ea\n" if extra % 2 else "")
                tail += "nop\n" * ((extra - (3 if extra % 2 else 0)) // 2)
                return (f"ldy #{outer}\n!outer:\nldx #255\n!inner:\ndex\nbne !inner-\n"
                        f"dey\nbne !outer-\nldx #{inner}\n!tail:\ndex\nbne !tail-\n" + tail + "rts\n")
    for inner in range(1, 256):
        extra = cycles - (7 + inner * 5)
        if 0 <= extra <= 12 and extra != 1:
            tail = ("bit $ea\n" if extra % 2 else "")
            tail += "nop\n" * ((extra - (3 if extra % 2 else 0)) // 2)
            return f"ldx #{inner}\n!tail:\ndex\nbne !tail-\n" + tail + "rts\n"
    raise ValueError(f"Unsupported cold delay {cycles}")


def prepare(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    pcm, rows, prep = baseline.prepare(out / "base")
    assert support.digest(out / "base/expected-input.bin") == GOLD
    compact = compact_s3.prepare(out / "compact", arena_start=0x1600, original=out / "base")
    text = (out / "base/data.asm").read_text()
    triangle_files = re.findall(r'triangle_(\d+):\n.import binary "([^"]+)"', text)
    assert len(triangle_files) == 6
    records = [[int(item) for item in line[6:].split(",")]
               for line in text.split("score:\n", 1)[1].split("program_end:", 1)[0].splitlines()
               if line.startswith(".byte ")]
    logical_ids = {(asset["instrument"], asset["source_period"], asset["gain"]): asset["id"]
                   for asset in compact["assets"] if asset["id"]}
    score, virtual_low, virtual_high = [], [], []
    for asset in compact["assets"]:
        pointer = (asset["physical_min"] - asset["first_read_index"]) & 65535
        virtual_low.append(pointer & 255); virtual_high.append(pointer >> 8)
    for old, drum in zip(records, compact["frame_states"]):
        step = (-(old[0] + old[1] * 256)) & 65535
        identifier = 0 if drum["constant"] else logical_ids[drum["key"]]
        score.append([step & 255, step >> 8, old[2], identifier, int(drum["trigger"]),
                      old[4], old[5], *old[6:9], 0, 0, 25])
    lines = [".label FRAME_COUNT = 1000", ".pc = $1000 \"Six triangle volume tables\""]
    for index, path in triangle_files:
        lines += [f"triangle_{index}:", f'.import binary "{path}"']
    for asset in compact["assets"]:
        lines += [f'.pc = ${asset["physical_min"]:04x} "Independent C4 instrument window"',
                  f'.import binary "{asset["file"]}"']
    data_end = max(asset["physical_max"] for asset in compact["assets"]) + 1
    lines += [f'.pc = ${data_end:04x} "Native note-position tables"',
              'drum_virtual_low:', '.byte ' + ','.join(map(str, virtual_low)),
              'drum_virtual_high:', '.byte ' + ','.join(map(str, virtual_high)), 'score:']
    lines += ['.byte ' + ','.join(map(str, record)) for record in score]
    lines += ['instrument_end:', '.assert "Instrument data must leave dispatch free", instrument_end < $7000, true']
    (out / "data.asm").write_text("\n".join(lines) + "\n")
    pcm.update(frames=1000)
    return {"pcm": pcm, "rows": [row[:3] for row in rows], "drums": compact,
            "triangle_bytes": 1536, "score_bytes": 13000, "pointer_bytes": len(virtual_low) * 2,
            "instrument_data_bytes": 1536 + compact["asset_bytes"] + 13000 + len(virtual_low) * 2}


def mixer() -> str:
    lines = ['.pc = $7900 "Native phase and four-way mixing"', 'mix_samples:',
             'ldx phase_high', 'ldy #0', 'lda frame_count', 'and #1', 'beq mix_group']
    def value(index):
        return ['lda phase_low', f'step_low{index}:', 'adc #0', 'sta phase_low', 'txa',
                f'step_high{index}:', 'adc #0', 'tax', f'triangle_read{index}:',
                'lda triangle_0,x', 'clc', f'sample_read{index}:', 'adc $ffff,y',
                f'destination{index}:', 'sta buffer_b,y', 'iny']
    lines += value(0)
    lines += ['mix_group:']
    for index in range(1, 5): lines += value(index)
    lines += ['mix_end_count:', 'cpy #156', 'bne mix_group', 'stx phase_high',
              'mix_rts:', 'rts', 'mix_end:', '.assert "Mixer must leave delay page free", * < $7b00, true']
    return "\n".join(lines) + "\n"


def assemble(out: Path, prepared, *, audio_delay=44024, initial_delay=4867):
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.asm").write_text((Path(prepared["root"]) / "data.asm").read_text()
                                   + '.label SID1_SUSTAIN = 2\n')
    source = (HERE / "single-pcm-budget.asm").read_text()
    for name, offset, low in (("step_low", 1, 0), ("step_high", 1, 0),
                              ("triangle_read", 2, 0), ("sample_read", 1, 0),
                              ("sample_read", 2, 0), ("destination", 1, 0), ("destination", 2, 1)):
        pattern = rf'\.for \(var i={low}; i<5; i\+\+\) \{{ sta {name}\[i\]\+{offset} \}}'
        source, hits = re.subn(pattern, "\n".join(f"sta {name}{i}+{offset}" for i in range(low, 5)), source)
        assert hits == 1, (pattern, hits)
    (out / "single-pcm-budget.asm").write_text(source)
    (out / "mix.asm").write_text(mixer())
    (out / "delays.asm").write_text('.pc = $7b00 "Cold audio delay"\nstartup_audio_delay:\n'
        + delay(audio_delay) + 'startup_audio_delay_end:\n'
        + '.pc = $7c00 "Initial note spacing"\nstartup_initial_delay:\n'
        + delay(initial_delay) + 'startup_initial_delay_end:\n')
    command = ["rtk", "proxy", str(Path.home()/".local/bin/kickass"), str(out/"single-pcm-budget.asm"),
               "-o", str(out/"player.prg"), "-symbolfile"]
    run = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out/"build.log").write_text(run.stdout + run.stderr)
    if run.returncode: raise RuntimeError(run.stdout + run.stderr)
    labels = {key: int(value,16) for key,value in re.findall(r'\.label\s+(\w+)\s*=\s*\$([\da-fA-F]+)',
        (out/"single-pcm-budget.sym").read_text())}
    result = {"program": str(out/"player.prg"), "program_sha256": support.digest(out/"player.prg"),
              "symbols": labels, "bytes": (out/"player.prg").stat().st_size,
              "cold_audio_delay_cycles": audio_delay, "initial_spacing_delay_cycles": initial_delay,
              "source_sha256": support.digest(out/"single-pcm-budget.asm")}
    save(out/"build.json",result)
    return result


def verify(build, receipt, prepared, out):
    expected = (Path(prepared["root"])/"base/expected-input.bin").read_bytes()
    clock, enables, first = 0, 0, None
    seen3, seen1, seen2, master, startup1 = [], [], [], [], []
    startup_master = None
    for line in Path(receipt["media"]).open():
        fields=line.split()
        if len(fields)!=3: continue
        delta,register,value=map(int,fields);clock+=delta;register&=31
        if register==18 and value==17:
            enables+=1
            if enables==2:first=clock
        if first is None:
            if register in (0,1,4): startup1.append((clock,register,value))
            if register==24 and value==15: startup_master=clock
            continue
        event=(clock-first,register,value)
        if register in (15,18): seen3.append(event)
        elif register in (0,1,4):seen1.append(event)
        elif register in (7,8,11):seen2.append(event)
        elif register==24:master.append(event)
    wanted3=[]
    for i,value in enumerate(expected):
        wanted3 += [(i*126+t,r,v) for t,r,v in ((0,18,17),(6,18,1),(12,18,9),(20,15,value),(26,18,1))]
    last_latch=(len(expected)-1)*126
    assert seen3[-1]==(last_latch+84,18,0),seen3[-1]
    seen3.pop()
    assert seen3==wanted3, next(((a,b) for a,b in zip(seen3,wanted3) if a!=b), ('length',len(seen3),len(wanted3)))
    counts=prepared["pcm"]["frame_sample_counts_exact"]
    cuts=np.r_[0,np.cumsum(counts)].tolist()
    wanted1=[(cuts[frame]*126+t,r,prepared["rows"][frame][field])
             for frame in range(1,1000) for field,(t,r) in enumerate(((53,0),(60,1),(67,4)))]
    assert seen1[-1]==(last_latch+76,4,0),seen1[-1]
    seen1.pop()
    assert seen1==wanted1, next(((a,b) for a,b in zip(seen1,wanted1) if a!=b), ('SID1length',len(seen1),len(wanted1)))
    wanted_startup1=[(first+t,r,prepared["rows"][0][field])
                     for field,(t,r) in enumerate(((-254,0),(-247,1),(-240,4)))]
    assert startup1[-3:]==wanted_startup1,(startup1[-3:],wanted_startup1)
    # Equal native epochs preserve the recording resampler's phase. No host alignment.
    assert first==2246223 and startup_master==2199480,(first,startup_master)
    assert seen2[-1]==(last_latch+80,11,0),seen2[-1]
    seen2.pop()
    assert len(seen2)==999*3,len(seen2)
    offsets=[]
    for frame in range(1,1000):
        events=seen2[(frame-1)*3:frame*3]
        assert [(r,v) for _,r,v in events]==[(7,0),(8,0),(11,25)],events
        for time,_,_ in events:
            offset=time-cuts[frame]*126
            assert 67<offset<126*8,(frame,offset)
            offsets.append(offset)
    assert master==[(last_latch+88,24,0)],master
    stats=bytes.fromhex(receipt["stats_hex"])
    assert stats[6]==0 and int.from_bytes(stats[8:10],'little')==1000,stats.hex()
    report={"passed":True,"first_latch_cycle":first,"sid3_values":len(expected),
            "sid3_all_inputs_and_prefixes_exact":True,"sid3_period_cycles":126,
            "SID1_music_writes_exact":len(seen1)+3,"SID1_startup_offsets":[-254,-247,-240],
            "SID1_offsets":[53,60,67],"startup_master_cycle":startup_master,
            "accepted_reference_startup_epoch_exact":True,
            "master_volume_constant_during_stream":True,
            "shutdown_writes_exact":True,
            "SID2_ordinary_TEST_writes":len(seen2),"SID2_foreground_offset_range":[min(offsets),max(offsets)],
            "underruns":0,"frames":1000,"expected_sha256":hashlib.sha256(expected).hexdigest(),
            "program_sha256":build["program_sha256"],"trace_sha256":receipt["media_sha256"],
            "scope":"Mechanical one-PCM diagnostic only. Original C3 intentionally omitted; not a complete musical arrangement."}
    save(out/"player-check.json",report)
    return report


def memory_budget(build, prepared):
    labels=build["symbols"]
    payload=build["bytes"]-2
    return {
        "PRG_bytes_including_load_address":build["bytes"],
        "loaded_span":{"start":0x0801,"end_exclusive":0x0801+payload,"bytes":payload,
                       "includes_assembler_padding_and_unused_gaps":True},
        "resident_assets":{"triangle_volume_tables":1536,
                           "C4_fixed_pitch_gain_instrument_windows":prepared["drums"]["asset_bytes"],
                           "virtual_drum_pointer_tables":prepared["pointer_bytes"],
                           "temporary_uncompressed_1000_tick_score":prepared["score_bytes"],
                           "total_data":prepared["instrument_data_bytes"]},
        "runtime":{"bootstrap_and_retained_handler_templates":labels["runtime_end"]-0x0801,
                   "distributed_clock_slide_reserved_pages":9*256,
                   "native_phase_mix_kernel":labels["mix_end"]-labels["mix_samples"],
                   "cold_delay_routines":labels["startup_audio_delay_end"]-labels["startup_audio_delay"]
                       +labels["startup_initial_delay_end"]-labels["startup_initial_delay"]},
        "outside_loaded_span":{"zero_page_state_and_live_NMI_bytes":23+labels["nmi_end"]-labels["nmi_common"],
                               "two_buffer_reserved_pages":512,"two_handler_reserved_pages":512,
                               "reserved_stack_page":256,"NMI_vector_bytes":2},
        "unallocated_intervals_at_current_layout":[
            {"start":labels["instrument_end"],"end_exclusive":0x7000,
             "bytes":0x7000-labels["instrument_end"]},
            {"start":0x0801+payload,"end_exclusive":0xd000,"bytes":0xd000-(0x0801+payload)},
            {"start":0xe000,"end_exclusive":0xff00,"bytes":0xff00-0xe000,
             "upper_256_bytes_conservatively_reserved":True}],
        "limitations":"Diagnostic only: the score is intentionally uncompressed; C3 is absent. "
                      "C4 windows cover only the accepted first 20 seconds. This is not a full-song memory bound. "
                      "No bank-switched asset storage or external RAM is used. BASIC/KERNAL are mapped out "
                      "with $01=$35; I/O at D000-DFFF is mapped in."
    }


def run(out:Path, *, assemble_only=False, audio_delay=44024, initial_delay=4867):
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    protected={p.name:support.digest(p) for p in (SID/"work/hyperbased/linus-mix").glob('*') if p.suffix in ('.wav','.prg')}
    prepared=prepare(out/"data");prepared["root"]=str(out/"data")
    build=assemble(out/"all",prepared,audio_delay=audio_delay,initial_delay=initial_delay)
    save(out/"input.json",prepared["pcm"])
    result={"build":build,"input":prepared["pcm"],"triangle_bytes":1536,
            "drum_bytes":prepared["drums"]["asset_bytes"],"score_bytes":13000,
            "instrument_data_bytes":prepared["instrument_data_bytes"],"canonical_files_before":protected}
    result['study_sources']={path.name:support.digest(path)
                             for path in (Path(__file__),HERE/'single-pcm-budget.asm')}
    result['memory']=memory_budget(build,prepared)
    save(out/"preparation.json",{k:v for k,v in prepared.items() if k!='drums'})
    if assemble_only:save(out/"verification.json",result);return result
    captured=support.capture(build,out/"registers",prepared["pcm"]["duration_s"])
    proof=verify(build,captured,prepared,out)
    result["native"]=proof
    save(out/"verification.json",result)
    cpu=measure_cpu(Path(build["program"]),build["symbols"],prepared["pcm"]["frame_sample_counts_exact"],out/"budget")
    cpu={k:v for k,v in cpu.items() if not k.startswith('c3_')}
    cpu['scope']='One-PCM diagnostic; all native phase/mix fills and NMI intervals measured; no C3 producer exists. SID2 ordinary controller executes TEST states.'
    result['cpu']=cpu
    receipt=support.capture(build,out/"audio",prepared["pcm"]["duration_s"],audio=True)
    signal,rate=support.audio_signal(receipt,proof,prepared["pcm"])
    peak=float(np.max(np.abs(signal)))
    assert peak*8<1,peak
    sf.write(out/"diagnostic.wav",signal*8,rate,subtype='PCM_16')
    result['audio']={"file":"diagnostic.wav","sha256":support.digest(out/"diagnostic.wav"),"gain":8,
                     "processing":"Actual VICE; clock crop, DC removal and constant gain only.",
                     "frames":len(signal),"sample_rate":rate,"raw_peak":peak,
                     "underruns":0,"raw_capture_sha256":receipt['media_sha256'],
                     "profile":receipt['profile'],
                     "omission":"Original C3 absent. This is not a candidate listening port."}
    result['canonical_files_unchanged']=all(support.digest(SID/"work/hyperbased/linus-mix"/name)==value for name,value in protected.items())
    assert result['canonical_files_unchanged']
    save(out/"verification.json",result)
    (out/".gitignore").write_text('*\n!.gitignore\n!player.prg\n!diagnostic.wav\n!verification.json\n')
    shutil.copyfile(build['program'],out/'player.prg')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=SID/'work/hyperbased/full-length-budget/native-probe')
    parser.add_argument('--assemble-only',action='store_true')
    parser.add_argument('--audio-delay',type=int,default=44024)
    parser.add_argument('--initial-delay',type=int,default=4867)
    args=parser.parse_args()
    result=run(args.out,assemble_only=args.assemble_only,audio_delay=args.audio_delay,initial_delay=args.initial_delay)
    print(json.dumps({"PRG_bytes":result['build']['bytes'],"instrument_data_bytes":result['instrument_data_bytes'],
                      "native_passed":result.get('native',{}).get('passed'),"cpu_passed":result.get('cpu',{}).get('passed')},indent=2))
