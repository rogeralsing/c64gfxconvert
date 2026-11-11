#!/usr/bin/env python3
"""Focused native colored PAL proof of fixed-crop zoom flashes and checker colors.

Authoring gate: actual colored scanout owns palette, idle-byte, crop and phase
publication behavior. Wrong source-step parity, timing, fixed crop, checker colors, object/LUT
selection or late color writes fail at that boundary. The preceding B/W proof
cannot catch these new risks. All12flashes run their full25real fields; only
base-phase timers are explicitly advanced. No production test flag is used.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import socket
import subprocess
from PIL import Image, ImageChops, ImageDraw

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location("flash_reference_helpers",HERE/"verify-span-star-ball-player.py")
previous=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(previous)
span,mirror,native=previous.span,previous.mirror,previous.native
RawFrames,expected_screen,pose=previous.RawFrames,previous.expected_screen,previous.pose
sha,stats=span.sha,span.stats
PAIRS=((15,11),(10,4),(13,5))
EVENTS=("presented","clear_start","clear_end","cache_start","cache_end","render_start","render_end","commit_start","commit_end","field_complete","crop_latch_start","crop_latch_end","flash_crop_entry_start","flash_crop_entry_end","color_fill_start","color_fill_end")

def mode_of(step):return 6 if step&1 else (step%12)//2

def read_palette(path):
    values=[]
    for line in path.read_text().splitlines():
        line=line.split("#",1)[0].strip()
        if line:values.append(tuple(int(part,16)for part in line.split()[:3]))
    if len(values)!=16:raise AssertionError("Expected the16Colodore RGB colors")
    return values

def color_cells(mode,fg):
    return bytes(4 if (((p%40)//4)^((p//40)//4))&1==0 else 5 for p in range(1024))if mode==2 else bytes([fg])*1024

def colored_image(screen,font,mode,bg,fg,colors):
    bits=mirror.shifted_pixels(screen,font)if mode in(3,5,6)else native.pixels_from_screen(screen,font)
    mask=Image.frombytes("L",(320,200),bits)
    foreground=Image.new("RGB",(320,200),colors[fg])
    if mode==2:
        draw=ImageDraw.Draw(foreground)
        for y in range(0,200,32):
            for x in range(0,320,32):draw.rectangle((x,y,x+31,y+31),fill=colors[4 if ((x//32)^(y//32))&1==0 else 5])
    return Image.composite(foreground,Image.new("RGB",(320,200),colors[bg]),mask)

def actual_color(path,expected,bg):
    actual=Image.open(path).convert("RGB")
    if ImageChops.difference(actual.crop((32,35,352,235)),expected).getbbox():
        raise AssertionError("Actual colored VIC scanout differs from independent font/Colodore reference: "+path.name)
    for box in[(0,35,32,235),(352,35,384,235)]:
        border=actual.crop(box)
        if ImageChops.difference(border,Image.new("RGB",border.size,bg)).getbbox():
            raise AssertionError("Visible side border differs from the current background color")
    return {"comparedMatrixPixels":64000,"differentPixels":0,"sideBordersMatchBackground":True}

def symbols(path):
    labels={name:int(value,16)for name,value in re.findall(r"\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)",path.read_text())}
    required=set(EVENTS)|{"object_id","next_object","step_index","next_step","mode","next_mode","film_serial","next_serial","film_frame","next_film_frame","phase","next_phase","field_counter","mode_started_field","mode_fields_left","mode_due","transition_margin","front_screen_hi","back_screen_hi","wave_ages","row_cache","cache_frame_ids","cache_table_count","zoom_x","zoom_y","latched_zoom_x","latched_zoom_y","active_zoom_x","active_zoom_y","flash_center_x","flash_center_y","flash_crop_x","flash_crop_y","copy_high_start","active_color_pattern","next_color_pattern","active_palette_index","next_palette_index","active_bg","active_fg","next_bg","next_fg"}
    if required-labels.keys()or len({labels[e]for e in EVENTS})!=len(EVENTS):raise AssertionError("Missing or aliased flash-player ABI: "+str(sorted(required-labels.keys())))
    return labels

def verify(build,vice,output,data_root):
    build, output, data_root = build.resolve(), output.resolve(), data_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((build / "build.json").read_text())
    labels = symbols(build / "main.sym")
    font = (build / "font.bin").read_bytes()
    horizontal, vertical = [(build / (name + "-lut.bin")).read_bytes() for name in ("h", "v")]
    accepted = HERE / "three-scene/results/flagship-star-span-mirror-texture"
    for name in ("font.bin", "h-lut.bin", "v-lut.bin"):
        if (build / name).read_bytes() != (accepted / name).read_bytes():
            raise AssertionError("Locked font or corrected mirror maps changed")
    if sha(font) != span.LOCKED_FONT:
        raise AssertionError("Original font was regenerated")
    full_references = [(HERE / "three-scene/results/flagship-star-ten-buffer/reference.frames").read_bytes(), (data_root / "cube-full-reference.frames").read_bytes()]
    objects = []
    for index, item in enumerate(manifest["objects"]):
        obj = dict(item)
        obj["reference"] = (build / obj["referenceFile"]).read_bytes()
        obj["lookup"] = (build / obj["zoomLutFile"]).read_bytes()
        rows, offsets = (build / obj["rowsFile"]).read_bytes(), (build / obj["frameOffsetsFile"]).read_bytes()
        obj["rows"] = rows
        obj["oracle"] = RawFrames(rows, offsets, obj["reference"])
        original = full_references[index]
        wanted = bytes(1000) + b"".join(original[frame * 1000:(frame + 1) * 1000] for frame in range(1, 97, 2))
        if obj["reference"] != wanted or obj["lookup"] != (data_root / obj["name"] / "learned.lut").read_bytes():
            raise AssertionError("Object input differs from independent odd-pose reference/matched lookup")
        if len(obj["lookup"]) != 1024 or obj["lookup"][:4] != bytes(4) or len(obj["frameAddresses"]) != 49:
            raise AssertionError("Object lookup, blank or physical frame index differs")
        for quadrant, name in enumerate(("tl", "tr", "bl", "br")):
            if (build / (obj["name"] + "-zoom-" + name + ".bin")).read_bytes() != obj["lookup"][quadrant::4]:
                raise AssertionError("Runtime object/quadrant page differs from the matched empirical lookup")
        for frame, address in enumerate(obj["frameAddresses"]):
            logical_start = obj["oracle"].offsets[frame]
            logical_end = obj["oracle"].offsets[frame + 1] if frame < 48 else len(rows)
            end = address + logical_end - logical_start
            if not (0x5000 <= address < end <= 0xd000 or 0xe000 <= address < end <= 0xfffa) or address <= 0x7fff < end:
                raise AssertionError("A physical source frame crosses I/O or the reserved interrupt vectors")
        objects.append(obj)
    if len(objects) != 2 or [obj["id"] for obj in objects] != [0, 1]:
        raise AssertionError("Expected star then gradient-dithered cube")
    regions = []
    for region in manifest["sourceRegions"]:
        content = (build / region["file"]).read_bytes()
        if len(content) != region["end"] - region["start"] or sha(content) != region["sha256"]:
            raise AssertionError("Immutable loaded region file/hash differs")
        if region["start"] < 0xe000 and region["end"] > 0xd000:
            raise AssertionError("Movie or lookup crosses the CPU I/O hole")
        regions.append({**region, "data": content})
    program = build / "player.prg"
    program_bytes = program.read_bytes()
    program_sha = sha(program_bytes)
    load_start = int.from_bytes(program_bytes[:2], "little")
    load_end = load_start + len(program_bytes) - 2
    if load_end > 0xd000:
        raise AssertionError("Hardware PRG load would enter the I/O gap; high movie must be staged below it")
    staged_regions = []
    for region in regions:
        if region["start"] >= 0xe000 and region["data"]:
            staging = region.get("loadStart")
            if staging is None or not load_start <= staging < staging + len(region["data"]) <= load_end or program_bytes[2 + staging - load_start:2 + staging - load_start + len(region["data"])] != region["data"]:
                raise AssertionError("High movie is not present in a hardware-loadable low staging region")
            staged_regions.append({"file": region["file"], "loadStart": staging, "runtimeStart": region["start"], "bytes": len(region["data"])})
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0)); port = reservation.getsockname()[1]
    palette = HERE.parent.parent.parent / "palettes/colodore.vpl"
    command = [str(vice), "-default", "+saveres", "-minimized", "-pal", "-speed", "100", "+warp", "+autostart-warp", "+confirmonexit", "-sounddev", "dummy", "+refreshonbreak", "+binarymonitor", "-initbreak", "reset", "-autostartprgmode", "1", "-autostart", str(program), "-VICIIfilter", "0", "-VICIIextpal", "-VICIIpalette", str(palette), "-VICIIsaturation", "1000", "-VICIIcontrast", "1000", "-VICIIbrightness", "1000", "-VICIIgamma", "1000", "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
    colors=read_palette(palette)
    budgets=manifest["preparationBudgets"]
    if len(budgets)!=2 or any(len(row)!=7 for row in budgets):raise AssertionError("Expected measured seven-mode budgets for each object")
    dx=[value-256 if value>127 else value for value in(build/"flash-dx.bin").read_bytes()]
    dy=[value-256 if value>127 else value for value in(build/"flash-dy.bin").read_bytes()]
    if dx!=[0,-3,2,-1,3,-2]*2 or dy!=[0,-2,0,2,-1,1]*2:raise AssertionError("Fixed per-flash offset table differs")
    empty_high=manifest["highStagingBytes"]==0
    report={"pass":False,"program_sha256":program_sha,"font_sha256":sha(font),"manifest":manifest,"command":command,"method":"Actual colored PAL scanouts with exact Colodore RGB mapping. All12flash phases retain25natural fields; only base timers are advanced through declared budget margins. Source time is never injected.","hardwareLoad":{"start":load_start,"endExclusive":load_end,"stagedHighRegions":staged_regions,"neverLoadsIoGap":True},"fields":[],"events":[],"commits":[],"stepStarts":[],"timerInjections":[],"centerPokes":[],"fills":[],"renders":[],"clears":[],"cropLatches":[],"flashEntries":[]}
    front,back=0x4800,0x4c00;contents={front:bytes(1024),back:bytes(1024)}
    step=obj_id=mode=serial=started=last_counter=field_count=step_ordinal=0
    active_crop=pending_crop=requested_center=(10,6)
    ages=active_image=pending=work=crop_start=entry_start=None
    phase_images={};base_poses=[set(),set()];injected=set();poked=set();centers={(0,0),(20,0),(0,13),(20,13)}
    seen_pairs=set();clamp_hits=set();last_clock=None;front_watch=None;flash_entries={}
    render_clock=clear_clock=commit_clock=fill_clock=None
    process=connection=monitor=None

    def word(ram,name):return int.from_bytes(ram[labels[name]:labels[name]+2],"little")
    def duration(selected):return 25 if selected&1 else 501
    def margin(selected):
        upcoming=(selected+1)%24
        return budgets[selected//12][mode_of(selected)]+budgets[upcoming//12][mode_of(upcoming)]-1
    def screen(state,crop):
        selected,t=state
        return expected_screen(objects[selected//12],t,mode_of(selected),crop,ages,horizontal,vertical)
    def image(character_screen,selected):
        bg,fg=PAIRS[selected%3]
        return colored_image(character_screen,font,mode_of(selected),bg,fg,colors)

    with(output/"vice.log").open("w")as log:
        try:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);report["owned_pid"]=process.pid
            connection=native.connect(process,port);monitor=native.Monitor(connection);monitor.run("sidefx off")
            for resource,value in(("MachineVideoStandard",1),("Speed",100),("InitialWarpMode",0),("AutostartWarp",0),("RefreshOnBreak",0)):
                if f"{resource}={value}"not in monitor.run(f'resourceget "{resource}"'):raise AssertionError("Unexpected VICE resource")
            if empty_high:
                boot=monitor.checkpoint(labels["copy_high_start"]);monitor.run("x")
                if monitor.registers()["pc"]!=labels["copy_high_start"]:raise AssertionError("Native boot did not reach zero-safe high-copy boundary")
                monitor.run(f"delete {boot}");span.store_checkpoint(monitor,0xe000,0xfffa)
                report["hardwareLoad"]["zeroHighCopyStoreGuardInstalled"]=True
            initial=monitor.checkpoint(labels["presented"]);monitor.run("x")
            if monitor.registers()["pc"]!=labels["presented"]:raise AssertionError("Initial normal star not reached or empty high copy wrote unused RAM")
            monitor.run(f"delete {initial}")
            for event in EVENTS:monitor.checkpoint(labels[event])
            span.store_checkpoint(monitor,0x4000,0x4800);span.store_checkpoint(monitor,0x7fff,0x8000)
            for region in regions:
                if region["end"]>region["start"]:span.store_checkpoint(monitor,region["start"],region["end"])

            def read_state():
                monitor.run("bank ram");ram=monitor.dump(output/"last-ram.bin",0,65535)
                monitor.run("bank io");vic=monitor.dump(output/"last-vic.bin",0xd000,0xd03f);cia=monitor.dump(output/"last-cia.bin",0xdd00,0xdd02);color=monitor.dump(output/"last-colors.bin",0xd800,0xdbff);monitor.run("bank cpu")
                if ram[0x4000:0x4800]!=font or any(ram[r["start"]:r["end"]]!=r["data"]for r in regions)or ram[0x7fff]:raise AssertionError("Font/source/LUT changed or colored idle byte is not zero")
                bg,fg=PAIRS[step%3];control=0x1f if mode in(3,5,6)else 0x1b
                if registers_now["cpu_port"]!=0x35 or cia[0]&3!=2 or cia[2]&3!=3 or vic[0x11]&0x7f!=control or vic[0x16]&0x1f!=8 or vic[0x15]or vic[0x18]&0xfe!=(0x20 if front==0x4800 else 0x30):raise AssertionError("VIC mode/front/font geometry differs")
                if vic[0x20]&15!=bg or vic[0x21]&15!=bg or bytes(c&15 for c in color)!=color_cells(mode,fg):raise AssertionError("Border/background or uniform/checker foreground ColorRAM differs")
                if(ram[labels["active_palette_index"]],ram[labels["active_bg"]],ram[labels["active_fg"]])!=(step%3,bg,fg):raise AssertionError("Published palette metadata differs from phase")
                if(ram[labels["step_index"]],ram[labels["object_id"]],ram[labels["mode"]],word(ram,"film_serial"))!=(step,obj_id,mode,serial)or ram[labels["film_frame"]]!=pose(serial)or ram[labels["phase"]]!=serial%48:raise AssertionError("Published phase/object/source metadata changed before commit")
                if word(ram,"mode_started_field")!=started or ram[labels["front_screen_hi"]]<<8!=front or ram[labels["back_screen_hi"]]<<8!=back:raise AssertionError("Active phase timer or front pointer changed")
                if (ram[labels["active_zoom_x"]],ram[labels["active_zoom_y"]])!=active_crop or ram[labels["active_color_pattern"]]!=(mode==2):raise AssertionError("Active crop/color pattern changed before commit")
                if mode==6 and (ram[labels["flash_crop_x"]],ram[labels["flash_crop_y"]])!=flash_entries[step]["crop"]:raise AssertionError("Current flash crop moved after entry")
                if ages is not None and ram[labels["wave_ages"]:labels["wave_ages"]+1200]!=ages:raise AssertionError("Wave table changed")
                for address in(0x4800,0x4c00):
                    if address==back and work:continue
                    if ram[address:address+1024]!=contents[address]:raise AssertionError("Output differs from independent raw source/lookup")
                return ram

            def check_pending(ram):
                target=ram[labels["next_step"]];newobj=target//12;newmode=mode_of(target)
                t=1 if newobj!=obj_id else serial+(2 if newmode==6 else 1)
                if target not in(step,(step+1)%24)or(ram[labels["next_object"]],ram[labels["next_mode"]],word(ram,"next_serial"),ram[labels["next_film_frame"]],ram[labels["next_phase"]])!=(newobj,newmode,t,pose(t),t%48):raise AssertionError("Pending step2flash or object source reset differs")
                if(ram[labels["next_palette_index"]],ram[labels["next_bg"]],ram[labels["next_fg"]])!=(target%3,*PAIRS[target%3])or ram[labels["transition_margin"]]!=margin(step):raise AssertionError("Pending palette or measured transition budget differs")
                if ram[labels["next_color_pattern"]]!=(newmode==2):raise AssertionError("Pending checker color pattern differs")
                return target,t

            def check_cache(ram):
                target,t=pending;o=target//12;m=mode_of(target)
                if m>2:return
                count=ram[labels["cache_table_count"]]
                if count!={0:1,1:10,2:2}[m]:raise AssertionError("Cache size differs")
                cached=set()
                for slot in range(count):
                    frame=ram[labels["cache_frame_ids"]+slot];cached.add(frame)
                    if frame>48:raise AssertionError("Cache frame exceeds source")
                    for row in range(25):
                        a=labels["row_cache"]+slot*50+row*2;pointer=int.from_bytes(ram[a:a+2],"little")
                        if pointer!=objects[o]["frameAddresses"][frame]+objects[o]["oracle"].row_offsets[frame][row]:raise AssertionError("Cache points into wrong object or physical source hole")
                needed={pose(t)}
                if m==1:needed={pose(max(0,t-ages[row*48+t%48]))for row in range(25)}
                elif m==2:needed.add(pose(max(0,t-24)))
                if not needed.issubset(cached):raise AssertionError("Cache omitted selected object history")

            first=True
            while True:
                if not first:monitor.run("x")
                first=False;registers_now=span.registers(monitor);event=next((e for e in EVENTS if labels[e]==registers_now["pc"]),None)
                if event is None:raise AssertionError("Unexpected front/source/idle-byte write")
                report["events"].append({"event":event,"step":step,"serial":serial,**registers_now})
                if event=="presented":
                    ram=read_state()
                    if ages is None:
                        ages=ram[labels["wave_ages"]:labels["wave_ages"]+1200]
                        for row in range(25):
                            for p in range(48):
                                if abs(ages[row*48+p]-(4.5+4.5*math.sin(2*math.pi*(row/24+p/48))))>.500000000001:raise AssertionError("Wave sinusoid differs")
                        for obj in objects:
                            for frame,address in enumerate(obj["frameAddresses"]):
                                start=obj["oracle"].offsets[frame];end=obj["oracle"].offsets[frame+1]if frame<48 else len(obj["rows"])
                                if ram[address:address+end-start]!=obj["rows"][start:end]:raise AssertionError("Native boot did not install physical low/high source frames")
                        report["hardwareLoad"]["all98FramesMatchAfterNativeBoot"]=True;report["hardwareLoad"]["idle7fffZero"]=True
                        active_image=image(screen((0,0),active_crop),0);report["stepStarts"].append({"step":0,"field":0,"counter":0,"serial":0,"object":0})
                    if front_watch is not None:monitor.run(f"delete {front_watch}")
                    front_watch=span.store_checkpoint(monitor,front,front+1024)
                    if step&1 and step not in poked:
                        centers_after_flash=[(0,0),(20,0),(0,13),(20,13),(10,6),(10,6)]
                        requested_center=centers_after_flash[(step%12)//2]
                        for name,value in zip(("zoom_x","zoom_y"),requested_center):monitor.run(f"> ${labels[name]:04x} ${value:02x}")
                        report["centerPokes"].append({"step":step,"field":field_count,"center":list(requested_center),"duringCurrentFlash":True,"appliesToNextFlash":True});poked.add(step)
                    ready=len(base_poses[obj_id])==48 if step in(0,12)else len(phase_images.get(step_ordinal,set()))>=3
                    if step_ordinal<24 and not step&1 and ready and step_ordinal not in injected:
                        counter=word(ram,"field_counter");remaining=margin(step);started=(counter-(501-remaining))&0xffff
                        for name,value in(("mode_fields_left",remaining),("mode_started_field",started)):monitor.run(f"> ${labels[name]:04x} ${value&255:02x} ${value>>8:02x}")
                        monitor.run(f"> ${labels['mode_due']:04x} $00");injected.add(step_ordinal)
                        report["timerInjections"].append({"step":step,"actualField":field_count,"remaining":remaining,"newStartedField":started,"baseOnly":True,"sourceClockUnmodified":True})
                elif event=="crop_latch_start":
                    ram=read_state();pending=check_pending(ram);center=(ram[labels["zoom_x"]],ram[labels["zoom_y"]])
                    if center!=requested_center:raise AssertionError("Unrequested manual center change")
                    crop_start={"center":center}
                elif event=="flash_crop_entry_start":
                    ram=read_state();pending=check_pending(ram)
                    if pending[0]==step or mode_of(pending[0])!=6:raise AssertionError("Fixed crop was relatched inside an existing flash")
                    entry_start=(ram[labels["zoom_x"]],ram[labels["zoom_y"]])
                elif event=="flash_crop_entry_end":
                    ram=read_state();index=pending[0]//2
                    entry_crop=(max(0,min(20,entry_start[0]+dx[index])),max(0,min(13,entry_start[1]+dy[index])))
                    if(ram[labels["flash_center_x"]],ram[labels["flash_center_y"]],ram[labels["flash_crop_x"]],ram[labels["flash_crop_y"]])!=(*entry_start,*entry_crop):raise AssertionError("Fixed entry center/offset/clamp differs")
                    flash_entries[pending[0]]={"center":entry_start,"crop":entry_crop}
                    report["flashEntries"].append({"step":pending[0],"center":list(entry_start),"crop":list(entry_crop)})
                elif event=="crop_latch_end":
                    ram=read_state();pending=check_pending(ram)
                    pending_crop=flash_entries[pending[0]]["crop"]if mode_of(pending[0])==6 else crop_start["center"]
                    if(ram[labels["latched_zoom_x"]],ram[labels["latched_zoom_y"]])!=pending_crop:raise AssertionError("Manual center changed a current flash instead of waiting for next entry")
                    if mode_of(pending[0])==6:
                        if pending_crop[0]in(0,20):clamp_hits.add(("x",pending_crop[0]))
                        if pending_crop[1]in(0,13):clamp_hits.add(("y",pending_crop[1]))
                    report["cropLatches"].append({"step":pending[0],"serial":pending[1],"crop":list(pending_crop),"manualCenter":list(crop_start["center"])})
                elif event in("clear_start","cache_start"):
                    ram=read_state();pending=check_pending(ram)
                    if event=="clear_start":clear_clock,work=registers_now["clock"],"clear"
                elif event=="clear_end":
                    contents[back]=bytes(1024);work=None;read_state();report["clears"].append({"wallCycles":registers_now["clock"]-clear_clock,"all1024Zero":True})
                elif event=="cache_end":check_cache(read_state())
                elif event=="render_start":read_state();render_clock,work=registers_now["clock"],"render"
                elif event=="render_end":
                    contents[back]=screen(pending,pending_crop)+bytes(24);work=None;read_state();report["renders"].append({"step":pending[0],"serial":pending[1],"wallCycles":registers_now["clock"]-render_clock})
                elif event=="field_complete":
                    ram=read_state();counter=word(ram,"field_counter")
                    if counter!=(last_counter+1)&0xffff or not 256<=registers_now["raster"]<=258:raise AssertionError("Missed native completed field")
                    if last_clock is not None and abs(registers_now["clock"]-last_clock-native.PAL_FRAME_CYCLES)>126:raise AssertionError("Scanouts are not consecutive")
                    field_count+=1;last_counter,last_clock=counter,registers_now["clock"];elapsed=(counter-started)&0xffff;total=duration(step)
                    if elapsed>total or word(ram,"mode_fields_left")!=max(0,total-elapsed)or bool(ram[labels["mode_due"]])!=(elapsed>=total):raise AssertionError("Phase timer missed its501/25-field deadline")
                    picture=output/f"field-{field_count:04d}-step-{step:02d}-serial-{serial:04d}.png";monitor.run(f'scrsh "{picture}" 2');bg,fg=PAIRS[step%3]
                    comparison=actual_color(picture,active_image,colors[bg]);seen_pairs.add((bg,fg))
                    if mode in(3,5,6):
                        for box in[(0,0,320,4),(0,196,320,200)]:
                            strip=active_image.crop(box)
                            if ImageChops.difference(strip,Image.new("RGB",strip.size,colors[bg])).getbbox():raise AssertionError("Y7margin is not background")
                    report["fields"].append({"field":field_count,"step":step,"ordinal":step_ordinal,"object":obj_id,"mode":mode,"serial":serial,"pose":pose(serial),"bg":bg,"fg":fg,"crop":list(active_crop),"screenshot":picture.name,"comparison":comparison,"clock":registers_now["clock"]})
                    phase_images.setdefault(step_ordinal,set()).add(serial)
                    if not step&1 and serial:base_poses[obj_id].add(pose(serial))
                    if field_count%100==0:print(json.dumps({"actualFields":field_count,"step":step,"object":obj_id,"basePoses":[len(p)for p in base_poses],"flashesCompleted":sum(s["step"]&1 for s in report["stepStarts"][1:])}),flush=True)
                    if step_ordinal==24 and len(phase_images[24])>=3:break
                    if field_count>1200:raise AssertionError("Bounded flash proof exceeded1200fields")
                elif event=="commit_start":
                    ram=read_state()
                    if work or contents[back]!=screen(pending,pending_crop)+bytes(24):raise AssertionError("Presenting unfinished hidden image")
                    if 50<=registers_now["raster"]<256:raise AssertionError("Commit begins during visible matrix")
                    if pending[0]!=step and((word(ram,"field_counter")-started)&0xffff)!=duration(step):raise AssertionError("Script phase publication missed exactdeadline")
                    commit_clock=registers_now["clock"]
                elif event=="color_fill_start":fill_clock=registers_now["clock"]
                elif event=="color_fill_end":
                    monitor.run("bank io");color=monitor.dump(output/"fill-colors.bin",0xd800,0xdbff);monitor.run("bank cpu")
                    if bytes(v&15 for v in color)!=color_cells(mode_of(pending[0]),PAIRS[pending[0]%3][1]):raise AssertionError("Phase fill did not set all1024uniform/checker ColorRAMcells")
                    report["fills"].append({"step":pending[0],"wallCycles":registers_now["clock"]-fill_clock,"all1024Match":True,"endRaster":registers_now["raster"],"checker":mode_of(pending[0])==2})
                elif event=="commit_end":
                    changed=pending[0]!=step;step,serial=pending;obj_id,mode=step//12,mode_of(step);front,back=back,front;active_crop=pending_crop
                    if changed:
                        step_ordinal+=1;started=last_counter
                        if step!=step_ordinal%24:raise AssertionError("Base/flash/object order differs")
                    read_state();active_image=image(contents[front][:1000],step)
                    if 51<=registers_now["raster"]<256:raise AssertionError("Palette/front publication completes after visible51")
                    if changed:report["stepStarts"].append({"step":step,"field":field_count,"counter":last_counter,"serial":serial,"object":obj_id})
                    report["commits"].append({"step":step,"serial":serial,"field":field_count,"wallCycles":registers_now["clock"]-commit_clock})
            if sha(program.read_bytes())!=program_sha:raise AssertionError("Frozen player changed during proof")
            starts=report["stepStarts"]
            if[s["step"]for s in starts]!=list(range(24))+[0]or base_poses!=[set(range(1,49)),set(range(1,49))]or seen_pairs!=set(PAIRS):raise AssertionError("Phase/pose/palette coverage incomplete")
            flash_crops={str(i):{tuple(f["crop"])for f in report["fields"]if f["step"]==i}for i in range(1,24,2)}
            if any(len(v)!=1 for v in flash_crops.values())or len({next(iter(v))for v in flash_crops.values()})<2:raise AssertionError("Crop moved inside a flash or did not vary across flashes")
            report["fixedFlashCrops"]={i:list(next(iter(v)))for i,v in flash_crops.items()}
            flash_durations=[starts[i+1]["field"]-starts[i]["field"]for i in range(1,24,2)]
            if flash_durations!=[25]*12 or any(i&1 for i in injected):raise AssertionError("A flash was shortened or clock-injected")
            if any(starts[i]["serial"]!=1 for i in(12,24)):raise AssertionError("Object reset did not publish source1")
            required_high={(o["id"],f)for o in objects for f,a in enumerate(o["frameAddresses"])if a>=0xe000};seen_high={(f["object"],f["pose"])for f in report["fields"]if objects[f["object"]]["frameAddresses"][f["pose"]]>=0xe000}
            if not required_high.issubset(seen_high)or clamp_hits!={("x",0),("x",20),("y",0),("y",13)}:raise AssertionError("High source or sinusoidal clamp coverage incomplete")
            residence={}
            for f in report["fields"]:key=(f["ordinal"],f["serial"]);residence[key]=residence.get(key,0)+1
            report.update({"pass":True,"actualVisibleFieldsVerified":field_count,"all12FlashDurationsFields":flash_durations,"allFlashFieldsNatural":True,"basePosesVerified":[sorted(p)for p in base_poses],"colorPairsVerified":[list(p)for p in sorted(seen_pairs)],"clampBoundsVerified":[list(v)for v in sorted(clamp_hits)],"highFramesRendered":[list(v)for v in sorted(seen_high)],"bothObjectResetsVerified":True,"frontFontSourceIdleAndLookupWrites":0,"forcedRefresh":False,"fillWallCycles":stats([f["wallCycles"]for f in report["fills"]]),"renderWallCycles":stats([f["wallCycles"]for f in report["renders"]]),"maximumImageHeldFields":max(residence.values()),"flashImageCounts":{str(i):len(phase_images[i])for i in range(1,24,2)},"fixedEntryCropsVerified":True,"manualCenterOnlyAffectsNextFlash":True,"zeroHighCopyNoWrites":empty_high,"scope":"All12fixed flashes naturally timed; base timers shortened after source coverage. Checker pixels and all1024ColorRAM cells are independent parity checks; other modes restore uniform foreground. Not a full126-second native run. Physicalkeyboard input remains outside this minimized proof."})
        except BaseException as error:report["error"]=repr(error);raise
        finally:
            if monitor:(output/"monitor.log").write_text("\n".join(monitor.transcript))
            if connection:
                try:connection.sendall(b"quit\n")
                except OSError:pass
                connection.close()
            if process and process.poll()is None:
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            (output/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items()if k not in("manifest","command","fields","events","commits","renders","clears","cropLatches")},indent=2),flush=True)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--build",type=Path,default=HERE/"build/three-scene-star-cube-fixed-flash");parser.add_argument("--data",type=Path,default=HERE/"build/three-scene-star-cube-data");parser.add_argument("--output",type=Path);parser.add_argument("--vice",type=Path,default=Path("/opt/homebrew/Cellar/vice/3.10/bin/x64sc"));args=parser.parse_args();verify(args.build,args.vice,args.output or args.build/"pal-proof",args.data)
if __name__=="__main__":main()
