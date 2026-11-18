"""Native dual-sampler runtime for the longer Cream arrangement.

The main compressed score retains the existing SID1 and fractional SID3
contracts. SID2 reads independent three-byte note events: a little-endian
504-cycle output count and a descriptor ID. Four parallel tables supply each
descriptor's cursor and exclusive end. A zero count ends the stream. Its
asynchronous producer preserves a bounded lead over the ring
reader. No event contains mixed audio or a score-timed waveform window.

This module only emits optional generated assembly. The preserved players and
their shared assembly source remain untouched.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

import full_length_runtime as shared

HERE = Path(__file__).resolve().parent


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Unexpected shared runtime section: {old[:90]!r}")
    return source.replace(old, new, 1)


def _interrupts() -> str:
    """Reuse the measured four-phase interrupt, including pending SID1 slots."""
    original = (HERE / "linus-mix-player.asm").read_text()
    begin = original.index("sid2_image:\n")
    end = original.index("\nruntime_end:", begin)
    body = original[begin:end]
    body = body.replace("sid2_image:\n", '.pc = $7d00 "SID2 normal interrupt template"\nsid2_image:\n', 1)
    body = body.replace("sid2_pending_image:\n", '.pc = $7e00 "SID2 pending interrupt template"\nsid2_pending_image:\n', 1)
    body = body.replace(".align $100\nnmi_image:\n", '.pc = $7f00 "Shared sample interrupt template"\nnmi_image:\n', 1)
    body = body.replace('.label nmi_rti = $dd0c\n', '')
    return body + '''
.label normal_image = sid2_image
.label pending_image = sid2_pending_image
.label normal_handler = sid2_phase0
.label pending_handler = sid2_pending_phase0
.label sid_dispatch = sid2_dispatch
.assert "Interrupt templates must remain below 8000", * <= $8000, true
'''


def _producer() -> str:
    """Emit a small native note cursor and bounded unrolled COPY32 producer."""
    lines = ['.pc = $c000 "SID2 independent note cursor"', '''c3_initialize:
    lda #0
    sta c3_remaining
    sta c3_remaining+1
    sta c3_done
    lda #32
    sta c3_chunk_limit
    lda #1
    sta c3_ring_write
    lda #54
    sta sid2_high_buffer
    lda #<sid2_events
    sta c3_event_pointer
    lda #>sid2_events
    sta c3_event_pointer+1
    rts

c3_pump:
    lda c3_done
    beq !live+
    rts
!live:
    lda c3_remaining
    ora c3_remaining+1
    bne !have_event+
    ldy #0
    lda (c3_event_pointer),y
    sta c3_remaining
    iny
    lda (c3_event_pointer),y
    sta c3_remaining+1
    ora c3_remaining
    bne !record+
    inc c3_done
    rts
!record:
    iny
    lda (c3_event_pointer),y
    tax
    lda sid2_bank_low,x
    sta c3_source_pointer
    lda sid2_bank_high,x
    sta c3_source_pointer+1
    lda sid2_end_low,x
    sta c3_source_end
    lda sid2_end_high,x
    sta c3_source_end+1
    clc
    lda c3_event_pointer
    adc #3
    sta c3_event_pointer
    bcc !have_event+
    inc c3_event_pointer+1
!have_event:
    lda c3_chunk_limit
    ldx c3_remaining+1
    bne !block+
    cmp c3_remaining
    bcc !block+
    lda c3_remaining
!block:
    sta c3_block_count
    sec
    lda c3_remaining
    sbc c3_block_count
    sta c3_remaining
    lda c3_remaining+1
    sbc #0
    sta c3_remaining+1
    // Clamp the active prefix at the exclusive one-shot end. The rest of
    // this event remains neutral; a subsequent record alone changes bank.
    sec
    lda c3_source_end
    sbc c3_source_pointer
    sta c3_active_count
    lda c3_source_end+1
    sbc c3_source_pointer+1
    bcc !empty+
    bne !whole+
    lda c3_active_count
    cmp c3_block_count
    bcc !prefix+
!whole:
    lda c3_block_count
!prefix:
    sta c3_active_count
    // CMP can leave Z clear even when the selected prefix in A is zero.
    ora #0
    beq !silent+
    jsr c3_copy_block
    clc
    lda c3_source_pointer
    adc c3_active_count
    sta c3_source_pointer
    bcc !silent+
    inc c3_source_pointer+1
    jmp !silent+
!empty:
    lda #0
    sta c3_active_count
!silent:
    lda c3_block_count
    sec
    sbc c3_active_count
    beq !done+
    sta c3_neutral_count
    tax
    lda c3_neutral_target_low,x
    sta c3_neutral_jump+1
    lda c3_neutral_target_high,x
    sta c3_neutral_jump+2
    ldx c3_ring_write
    lda #54
c3_neutral_jump:
    jmp c3_neutral_values
!done:
    rts

c3_copy_block:
    ldx c3_active_count
    lda c3_copy_target_low,x
    sta c3_copy_jump+1
    lda c3_copy_target_high,x
    sta c3_copy_jump+2
    ldx c3_ring_write
    ldy #0
c3_copy_jump:
    jmp c3_copy_values
c3_copy_values:
''']
    for index in range(32):
        lines += ['    lda (c3_source_pointer),y', f'c3_ring_store_copy_{index:02d}:',
                  '    sta sid2_high_buffer,x', '    iny', '    inx']
    lines += ['''c3_copy_values_end:
    stx c3_ring_write
c3_copy_block_rts:
    rts
c3_copy_target_low:
.for (var count=0; count<=32; count++) {
    .byte <(c3_copy_values_end-count*7)
}
c3_copy_target_high:
.for (var count=0; count<=32; count++) {
    .byte >(c3_copy_values_end-count*7)
}
''']
    lines += ['c3_neutral_values:']
    for index in range(32):
        lines += [f'c3_ring_store_neutral_{index:02d}:', '    sta sid2_high_buffer,x', '    inx']
    lines += ['''c3_neutral_values_end:
    stx c3_ring_write
c3_ended_block_copy_rts:
    rts
c3_neutral_target_low:
.for (var count=0; count<=32; count++) {
    .byte <(c3_neutral_values_end-count*4)
}
c3_neutral_target_high:
.for (var count=0; count<=32; count++) {
    .byte >(c3_neutral_values_end-count*4)
}
c3_producer_end:
''']
    return '\n'.join(lines) + '\n'


def transform(source: str) -> str:
    """Add the independent SID2 producer to an otherwise prepared runtime."""
    source = '''.label sid2_high_buffer = $0d00
.label C3_RING_BYTES = 256
.label c3_event_pointer = $30
.label c3_source_pointer = $32
.label c3_source_end = $34
.label c3_remaining = $36
.label c3_ring_write = $38
.label c3_done = $39
.label c3_block_count = $3a
.label c3_active_count = $3b
.label c3_neutral_count = $3c
.label c3_chunk_limit = $3d
''' + source
    source = _replace(source, '    jsr synth_sid_tick\n', '')
    source = _replace(source, '    jsr score_init\n', '''    jsr c3_initialize
!prefill:
    jsr c3_pump
    lda c3_done
    bne !prefilled+
    lda c3_ring_write
    cmp #209
    bcc !prefill-
!prefilled:
    jsr score_init
''')
    source = _replace(source, '''    sta $d406
    lda voice_record+11
    and #SID2_MASK
    sta $d40d
''', '''    sta $d406
    lda #SID2_SUSTAIN
    sta $d40d
''')
    source = _replace(source, '''    lda #0
    sta $d40f
    ldy #32
''', '''    lda #0
    sta $d40f
    // Prepare the same neutral held level as the measured dual sampler.
    lda #54
    sta $d408
    lda #9
    sta $d40b
    lda #SID2_RELEASE_CONTROL
    sta $d40b
    .fill 119, $ea
    lda #SID2_LATCH_CONTROL
    sta $d40b
    lda #9
    sta $d40b
    ldy #32
''')
    source = _replace(source, '''    jsr commit_extra_sid
    jsr commit_sid1
    bit $ea
    .fill 8, $ea
    .fill 3, $ea
    bit $ea
    .fill 3, $ea
''', '''    jsr commit_extra_sid
    lda #54
    sta $d408
    jsr commit_sid1
    bit $ea
    .fill 8, $ea
    lda #SID2_RELEASE_CONTROL
sid2_startup_release:
    sta $d40b
    bit $ea
    .fill 3, $ea
''')
    background = '''background_begin:
    lda c3_done
    bne background_done
    lda c3_ring_write
    sec
    sbc sid2_read_high+1
    cmp #209
    bcs background_done
background_chunk:
    // Amortize note-cursor dispatch over complete early blocks. A bounded
    // late block may straddle activation; prefetch is already complete.
    lda buffer_read+1
    cmp #236
    lda #32
    bcc !chunk_ready+
    lda #16
!chunk_ready:
    sta c3_chunk_limit
    // Check the generation after observing the pointer. Otherwise an NMI
    // between these reads can make the new buffer look like early idle time.
    lda boundary_count
    cmp boundary_before
    bne background_done
    jsr c3_pump
    jmp background_begin
background_done:
'''
    source = _replace(source, '!already_final:\nwait_start:\n',
                      '!already_final:\n' + background + 'wait_start:\n')
    source = _replace(source, '''    bne !sid1_committed-
    jsr commit_extra_sid
    lda next_buffer
''', '''    bne !sid1_committed-
    // Pulse width and sustain are constant in this Cream arrangement. The
    // startup writes already establish them; repeated writes add no edge.
    lda next_buffer
''')
    begin = source.index('    // Retain the playing control before preparing the next one.')
    end = source.index('    jsr prepare_pcm\n', begin)
    source = source[:begin] + '''    // Cream holds GATE continuously. The pending interrupt commits the
    // three musical SID1 fields; a duplicate boundary write adds no edge.
    lda tick_record
    and #SID1_MASK
    sta pending_sid
    lda tick_record+1
    lsr
    and #SID1_MASK
    sta pending_sid+1
    lda tick_record+2
    and #SID1_MASK
    ora #SID1_TEST
    sta pending_sid+2
''' + source[end:]
    # The score stores SID1's physical fields directly. Its packed frequency
    # high byte is decoded above; pulse width and sustain are constant, so the
    # startup can read them even after the next record has been prefetched.
    for field in (3, 4, 5):
        source = source.replace(f'lda voice_record+{field}\n', f'lda tick_record+{field}\n')
    source = _replace(source, '''    lda pcm_active
    beq pcm_off
    sec
    lda pcm_cursor
''', '''    lda pcm_active
    beq pcm_off
    // End and loop metadata above always refresh. A held bank with the same
    // base already has the correct native cursor, including gain-LUT changes.
    lda pcm_base
    cmp pcm_old_base
    bne !base_changed+
    lda pcm_base+1
    cmp pcm_old_base+1
    bne !base_changed+
    rts
!base_changed:
    sec
    lda pcm_cursor
''')
    begin = source.index('    lda voice_record+8\n', source.index('commit_extra_sid:'))
    end = source.index('\nfinished:', begin)
    source = source[:begin] + '    rts\n' + source[end:]
    source = _replace(source, '''.assert "Main runtime must stay below asset data", runtime_end <= $1000, true''',
                      '''.assert "Main runtime must stay below PCM kernels", runtime_end <= $0c00, true''')
    # Keep the expanded bootstrap away from the fixed kernel pages. Calls keep
    # the same six-cycle JSR cost; this code uses ordinary RAM with ROM banked out.
    begin = source.index('// A base change preserves elapsed position')
    end = source.index('// The Q8 kernel already advances pcm_cursor', begin)
    prepare_pcm = source[begin:end]
    source = source[:begin] + source[end:]
    begin = source.index('.pc = $7d00 "Normal interrupt template"')
    source = (source[:begin] + _interrupts() + '\n' + _producer() + '\n' + prepare_pcm
              + 'cream_manager_end:\n.assert "Cream manager must leave loader arena free", * <= $c400, true\n')
    return source


def build(out: Path, data_asm: Path, score_asm: Path,
          enabled=(True, True, True), *, loader_arena: tuple[int, int],
          sid_programs_asm: Path, startup_audio_delay: int = 44024,
          startup_initial_delay: int = 4867, fast_pcm: bool = True,
          sid1_attack_decay: int = 0, sid1_articulation: bool = False) -> dict:
    """Assemble and package one full-workload dual-sampler output variant."""
    if len(enabled) != 3 or any(type(item) is not bool for item in enabled):
        raise ValueError('enabled must contain exactly three booleans')
    if type(sid1_attack_decay) is not int or not 0 <= sid1_attack_decay <= 255:
        raise ValueError('SID1 attack/decay must be an explicit byte')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    config = [f'.label SID1_MASK = {255 if enabled[0] else 0}',
              f'.label SID1_TEST = {0 if enabled[0] else 24}',
              f'.label SID2_MASK = {255 if enabled[1] else 0}',
              f'.label SID2_TEST = {0 if enabled[1] else 24}',
              f'.label SID2_SUSTAIN = {240 if enabled[1] else 0}',
              f'.label SID2_LATCH_CONTROL = {17 if enabled[1] else 25}',
              f'.label SID2_RELEASE_CONTROL = {1 if enabled[1] else 9}',
              f'.label SID3_SUSTAIN = {240 if enabled[2] else 0}',
              f'.label MASTER_VOLUME = {15 if enabled[2] else 143}']
    (out / 'config.asm').write_text('\n'.join(config) + '\n')
    for filename, original in (('data.asm', data_asm), ('score.asm', score_asm),
                               ('sid-programs.asm', sid_programs_asm)):
        original = Path(original).resolve()
        if original != out / filename:
            (out / filename).write_text(f'.import source "{original}"\n')
    if fast_pcm:
        import cream_q8_fast as backend
    else:
        import cream_fractional as backend
    source = transform(backend.transform((HERE / 'full_length_player.asm').read_text()))
    if sid1_articulation:
        source = source.replace('''    // Cream holds GATE continuously. The pending interrupt commits the
    // three musical SID1 fields; a duplicate boundary write adds no edge.
''', '''    // This candidate carries its explicit note GATE edges in CONTROL.
    // The pending interrupt commits the same three musical SID1 fields.
''')
        # Reproduce the earlier muted SID1 warmup: AD00, SR00, GATE+TEST.
        # Its attack/decay settles at zero before music. Omitting that attack
        # changed the mixer's initial DC transient in the SID2-only capture.
        # Preserve its cycle count and both sampler initializations.
        source = _replace(source, '''    sta $d40c
    lda tick_record+5
    and #SID1_MASK
    sta $d406
''', '''    sta $d40c
    lda #0
    sta $d406
    nop
    nop
''')
        # commit_extra_sid has installed the selected SR and pulse width.
        # Raising sustain cannot restart a zero envelope; this explicit GATE
        # fall, followed by commit_sid1's rise, starts the first real attack.
        source = _replace(source, '''    jsr commit_extra_sid
    lda #54
    sta $d408
    jsr commit_sid1
''', f'''    jsr commit_extra_sid
    lda #54
    sta $d408
    lda #24
    sta $d404
    jsr commit_sid1
    lda #{sid1_attack_decay}
    sta $d405
''')
    elif sid1_attack_decay:
        raise ValueError('A changing SID1 ADSR requires the explicit articulated program')
    if fast_pcm:
        source = _replace(source, '    jsr c3_initialize\n',
                          '    jsr initialize_offset_tables\n    jsr c3_initialize\n')
        source += '\n' + backend.initializer()
    target = out / 'full_length_player.asm'
    target.write_text(source)
    (out / 'mix.asm').write_text(backend.mixer())
    (out / 'patch.asm').write_text(backend.patchers())
    (out / 'delays.asm').write_text(
        '.pc = $7b00 "Cold audio delay"\nstartup_audio_delay:\n'
        + shared._delay(startup_audio_delay)
        + 'startup_audio_delay_end:\n.assert "Cold delay must precede initial delay", * <= $7b80, true\n'
        + '.pc = $7b80 "Initial note spacing"\nstartup_initial_delay:\n'
        + shared._delay(startup_initial_delay)
        + 'startup_initial_delay_end:\n.assert "Initial delay must precede fast manager", * <= $7c00, true\n')
    program = out / 'player.prg'
    command = ['rtk', 'proxy', str(Path.home() / '.local/bin/kickass'), str(target),
               '-o', str(program), '-symbolfile']
    assembled = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out / 'build.log').write_text(assembled.stdout + assembled.stderr)
    if assembled.returncode:
        raise RuntimeError(assembled.stdout + assembled.stderr)
    labels = {name: int(value, 16) for name, value in re.findall(
        r'\.label\s+(\w+)\s*=\s*\$([0-9a-fA-F]+)', target.with_suffix('.sym').read_text())}
    for name, wanted in {'tick_record': 0x600, 'voice_record': 0x620,
                         'sid2_high_buffer': 0xd00}.items():
        if labels.get(name) != wanted:
            raise ValueError(f'Unexpected {name} address: {labels.get(name)}')
    from prg_loader import package
    native = out / 'native.prg'
    program.replace(native)
    loader = package(native, program, entry=labels['start'], arena=loader_arena)
    labels.update(loader['symbols'])
    result = {'program': str(program), 'program_sha256': shared.digest(program),
              'bytes': program.stat().st_size, 'symbols': labels,
              'enabled': list(enabled), 'startup_loader': loader,
              'source_sha256': shared.digest(Path(__file__)),
              'generated_source_sha256': shared.digest(target),
              'pcm_backend_sha256': shared.digest(Path(backend.__file__)),
              'runtime_reserved_ranges': [[0x0801, 0x1000], [0x7000, 0x8000],
                                          [0xc000, 0xc400]],
              'SID2_event_format': 'Three-byte little-endian count and descriptor ID; zero count terminates. Four parallel tables supply cursor/end addresses.',
              'SID2_ring': {'start': 0xd00, 'bytes': 256, 'ZP': [0x30, 0x3d]},
              'startup_audio_delay_cycles': startup_audio_delay,
              'startup_initial_delay_cycles': startup_initial_delay,
              'SID1_attack_decay': sid1_attack_decay,
              'SID1_articulation': sid1_articulation}
    (out / 'build.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
