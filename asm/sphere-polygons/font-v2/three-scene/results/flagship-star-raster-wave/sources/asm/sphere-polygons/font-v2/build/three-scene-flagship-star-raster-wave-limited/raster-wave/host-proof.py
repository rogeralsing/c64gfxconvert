import hashlib, json, math, pathlib, statistics, sys
sys.path.insert(0, '/tmp/disco-sid-analysis-py65')
from py65.devices.mpu6502 import MPU

root = pathlib.Path(sys.argv[1])
build = json.loads((root / 'build.json').read_text())
labels = json.loads((root / 'labels.json').read_text())
program = (root / 'player.prg').read_bytes()
reference = (root / 'reference.frames').read_bytes()
font = (root / 'font.bin').read_bytes()
movie = (root / 'movie.bin').read_bytes()
edges = json.loads((root / 'literal-index.json').read_text())
memory = [0xa5] * 65536
load = int.from_bytes(program[:2], 'little')
memory[load:load + len(program) - 2] = program[2:]
screens = build['addresses']['screens']
for screen in screens:
    memory[screen:screen + 1024] = bytes(1024)
cpu = MPU(memory=memory)
irq_cycles = 0
irq_calls = 0
memory[labels['irq_index']] = 0
memory[labels['field_counter']] = 0
memory[labels['field_counter']+1] = 0
memory[0xfffe] = labels['raster_irq'] & 255
memory[0xffff] = labels['raster_irq'] >> 8

# Inject real IRQ entries while the copy/decoder use their live registers,
# including carry and zero-page jump pointers. Real RTI must restore them.
def inject_irq():
    global irq_cycles, irq_calls
    if cpu.p & cpu.INTERRUPT:
        return
    state = (cpu.pc, cpu.a, cpu.x, cpu.y, cpu.p, cpu.sp)
    started = cpu.processorCycles
    cpu.irq()
    for _ in range(1000):
        if cpu.pc == state[0]:
            break
        cpu.step()
    else:
        raise AssertionError('IRQ did not return')
    assert (cpu.a, cpu.x, cpu.y, cpu.sp) == (state[1], state[2], state[3], state[5]), ('IRQ registers', state)
    assert (cpu.p & 0xcf) == (state[4] & 0xcf), ('IRQ status', state, cpu.p)
    irq_cycles += cpu.processorCycles - started
    irq_calls += 1

def run_to(label, inject=False, limit=100000):
    endpoint = labels[label] if isinstance(label, str) else label
    start = cpu.processorCycles
    irq_before = irq_cycles
    for step in range(limit):
        if cpu.pc == endpoint:
            return cpu.processorCycles - start - (irq_cycles - irq_before)
        if inject and step % 97 == 96:
            inject_irq()
        cpu.step()
    raise AssertionError('Did not reach ' + str(label) + ', pc=' + hex(cpu.pc))

def call(label):
    cpu.pc = labels[label]
    cpu.sp = 0xfd
    memory[0x1fe] = 0xff
    memory[0x1ff] = 0xfe
    return run_to(0xff00)

def check_map(newest, phase):
    wave = build['rasterWave']
    first, count = wave['startRow'], wave['rowCount']
    ages = []
    for row in range(25):
        if first <= row < first + count:
            fraction = 0 if count == 1 else (row - first) / (count - 1)
            value = 4.5 + 4.5 * math.sin(2 * math.pi * (fraction + phase / 96))
            expected = math.floor(value + .5)
        else:
            value, expected = 0, 0
        actual = memory[labels['row_age_table'] + row]
        assert actual == expected or abs(value - (math.floor(value) + .5)) < 1e-12, ('wave age', row, phase, expected, actual)
        assert 0 <= actual < 10
        slot = (newest - actual) % 11
        assert slot != (newest + 1) % 11
        assert memory[labels['row_d018_active'] + row] == 0x20 + slot * 16
        ages.append(actual)
    for split, row in enumerate(wave['splitRows']):
        assert memory[labels['irq_d018_active'] + split] == memory[labels['row_d018_active'] + row]
        assert memory[labels['irq_line_table'] + split] == 50 + row * 8
        assert memory[labels['irq_row_table'] + split] == row
    return ages

memory[labels['front_index']] = 0
memory[labels['front_screen_hi']] = 0x48
memory[labels['phase']] = 0
cpu.p |= cpu.INTERRUPT
call('build_row_map')
cpu.p &= ~cpu.INTERRUPT
check_map(0, 0)
records = []
front, phase = 0, 0
slot_frames = [0] * 11
sequence = [edges[0]] + edges[1:] * 3
for serial, edge in enumerate(sequence):
    source, target = edge['fromPose'], edge['targetPose']
    memory[labels['frame_index']] = source
    memory[labels['next_frame']] = target
    assert slot_frames[front] == source
    assert bytes(memory[screens[front]:screens[front] + 1000]) == reference[source * 1000:(source + 1) * 1000]
    call('choose_next_buffer')
    back = memory[labels['back_index']]
    assert back == (front + 1) % 11
    old_map = bytes(memory[labels['row_age_table']:labels['row_age_table'] + 25])
    old_d018 = bytes(memory[labels['row_d018_active']:labels['row_d018_active'] + 25])
    before = [bytes(memory[screen:screen + 1024]) for screen in screens]
    cpu.pc = labels['copy_start']
    copied = run_to('copy_end', inject=True)
    assert bytes(memory[screens[back]:screens[back] + 1024]) == before[front]
    run_to('render_start')
    rendered = run_to('render_end', inject=True)
    actual = bytes(memory[screens[back]:screens[back] + 1024])
    assert actual[:1000] == reference[target * 1000:(target + 1) * 1000], ('delta', serial, source, target)
    assert actual[1000:] == bytes(24)
    for slot, screen in enumerate(screens):
        if slot != back:
            assert bytes(memory[screen:screen + 1024]) == before[slot], ('history changed', serial, slot)
    assert bytes(memory[labels['row_age_table']:labels['row_age_table']+25]) == old_map
    assert bytes(memory[labels['row_d018_active']:labels['row_d018_active']+25]) == old_d018
    assert memory[labels['front_index']] == front
    assert memory[labels['phase']] == phase
    assert bytes(memory[0x4000:0x4800]) == font
    assert bytes(memory[0x8000:0x8000+len(movie)]) == movie
    cpu.pc = labels['map_publish_start']
    run_to('map_publish_end')
    phase = (phase + 1) % 96
    assert memory[labels['front_index']] == back
    assert memory[labels['frame_index']] == target
    assert memory[labels['phase']] == phase
    slot_frames[back] = target
    ages = check_map(back, phase)
    for age in range(10):
        slot = (back - age) % 11
        assert bytes(memory[screens[slot]:screens[slot]+1000]) == reference[slot_frames[slot]*1000:(slot_frames[slot]+1)*1000]
    run_to('presented')
    records.append(dict(serial=serial, fromPose=source, targetPose=target, newestIndex=back,
                        phase=phase, ages=ages, historyFrames=[slot_frames[(back-age)%11] for age in range(10)],
                        copyCpuCycles=copied, renderCpuCycles=rendered))
    front = back

def stats(values):
    return dict(min=min(values), mean=statistics.mean(values), max=max(values))
result = dict(passed=True, scope='Assembled 6502 hidden copy/delta, frozen ten-screen histories, mathematical row maps and IRQ preservation; no VIC timing claims.',
              transitionsVerified=len(records), uniqueTransitionsVerified=len(edges),
              closingTransitionsVerified=sum(r['fromPose'] == 96 for r in records),
              bufferCount=11, historyCount=10, allSlotsVisited=sorted(set(r['newestIndex'] for r in records)),
              injectedIrqs=irq_calls, irqRegistersAndStatusPreserved=True, frozenHistoriesUnchangedDuringRender=True,
              copyBytesPerFrame=1024, sourceAndFontUnchanged=True,
              copyCpuCycles=stats([r['copyCpuCycles'] for r in records]),
              renderCpuCycles=stats([r['renderCpuCycles'] for r in records]),
              programSha256=hashlib.sha256(program).hexdigest(), records=records)
(root / 'host-proof.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k:v for k,v in result.items() if k != 'records'}, indent=2))
