"""Optional lossless Q8 producer with reusable relative-index tables.

The fast path keeps the source cursor exact while indexing a 256-byte table
for the note's fixed Q8 step. Field 6 selects that table's page; field 7 is
the table's low-byte wrap threshold, or zero; field 8 selects the fast path.
Fields 9/10 can rebase the output index at a held pitch change without moving
the source cursor. The compiler must prove the new index has the correct
fractional phase. Field 11 marks a gain table whose every output is 128; that
producer skips source reads but advances the same cursor and implicit phase.
No instrument amplitudes or sample clocks change.

The caller reserves zero page $25..$2f. SID2 may use the untouched $0d00 page.
"""
from __future__ import annotations

import cream_fractional


def table(step: int) -> bytes:
    if not 0 <= step <= 511:
        raise ValueError("The relative-index producer supports Q8 steps 0..511")
    return bytes(((index * step) >> 8) & 255 for index in range(256))


def threshold(step: int) -> int:
    """Return the sole low-offset wrap inside one 256-output period."""
    if not 0 <= step <= 511:
        raise ValueError("The relative-index producer supports Q8 steps 0..511")
    crossing = (65536 + step - 1) // step if step > 256 else 256
    return crossing if crossing < 256 else 0


def initializer(address: int = 0xf820) -> str:
    """Build all relative-index pages before the music and interrupts begin.

    The data provider declares FAST_TABLE_COUNT and fast_table_commands, whose
    records contain step-low, step-high and destination-page bytes. Generated
    pages may occupy RAM excluded from the disk image. Steps are at most 511.
    """
    return f'''.pc=${address:04x} "Initialize reusable Q8 index tables"
.label fast_table_count=$2f
initialize_offset_tables:
    ldx #0
    lda #FAST_TABLE_COUNT
    sta fast_table_count
!command:
    lda fast_table_commands,x
    sta fast_table_add+1
    inx
    lda fast_table_commands,x
    beq !no_high+
    lda #$c8
    bne !high_opcode+
!no_high:
    lda #$ea
!high_opcode:
    sta fast_table_high
    inx
    lda fast_table_commands,x
    sta fast_table_store+2
    inx
    lda #0
    tay
    clc
!value:
fast_table_store:
    sty $1000
fast_table_add:
    adc #0
    bcc !same_byte+
    iny
    clc
!same_byte:
fast_table_high:
    nop
    inc fast_table_store+1
    bne !value-
    dec fast_table_count
    bne !command-
    rts
fast_table_initializer_end:
.assert "Index initializer exceeds its reserved space", * <= $f900, true
.assert "Index command count must fit its byte index", FAST_TABLE_COUNT > 0 && FAST_TABLE_COUNT <= 85, true
'''


def transform(source: str) -> str:
    source = cream_fractional.transform(source)
    source = cream_fractional._replace_once(source, "!bass_hold:\n",
        """!bass_hold:
    lda tick_record+22
    beq !maybe_fast_rebase+
    lda #0
    sta fast_elapsed
    beq !keep_fast_origin+
!maybe_fast_rebase:
    lda tick_record+10
    beq !keep_fast_origin+
    lda tick_record+9
    sta fast_elapsed
!keep_fast_origin:
""")
    old = """    ldx #0
    lda tick_record+14
    cmp #$10
    beq !gain_kernel_ready+
    inx
!gain_kernel_ready:
"""
    new = """    ldx #0
    lda tick_record+14
    cmp #$10
    beq !gain_kernel_ready+
    inx
!gain_kernel_ready:
    lda tick_record+8
    bne !producer_selected+
    inx
    inx
!producer_selected:
    lda tick_record+8
    beq !not_zero_gain+
    lda tick_record+11
    beq !not_zero_gain+
    ldx #5
!not_zero_gain:
    lda pcm_active
    bne !producer_live+
    ldx #4
!producer_live:
"""
    return cream_fractional._replace_once(source, old, new)


def _q8_kernel(name: str, address: int, gain: bool) -> list[str]:
    lines = [f'.pc = ${address:04x} "Fallback Q8 {name}"', f'mix_{name}:',
             'ldx pending_start_low', 'ldy pcm_cursor',
             'lda frame_count', 'and #1', f'beq mix_group_{name}']
    for index in range(3):
        if index == 1:
            lines += [f'mix_group_{name}:']
        lines += [f'sample_read_{name}{index}:', 'lda $ff00,y']
        if gain:
            lines += [f'sta gain_read_{name}{index}+1',
                      f'gain_read_{name}{index}:', 'lda $1000']
        lines += [f'destination_{name}{index}:', 'sta buffer_b,x',
                  'lda phase_low', f'step_low_{name}{index}:', 'adc #0',
                  'sta phase_low', 'tya', f'step_high_{name}{index}:', 'adc #0',
                  'tay', f'bcc !same_page{index}+', 'inc pcm_cursor+1', 'lda pcm_cursor+1']
        lines += [f'sta sample_read_{name}{slot}+2' for slot in range(3)]
        lines += ['clc', f'!same_page{index}:', 'inx']
    lines += [f'bne mix_group_{name}', 'sty pcm_cursor', f'mix_rts_{name}:', 'rts',
              f'.assert "Fallback {name} exceeds its page", * <= ${address + 256:04x}, true']
    return lines


def mixer() -> str:
    lines: list[str] = []
    for gain, name, address in ((False, 'full', 0x0c00), (True, 'gain', 0x0e00)):
        lines += [f'.pc = ${address:04x} "Table-indexed Q8 {name}"']
        if not gain:
            lines += ['mix_samples:']
        lines += [f'mix_{name}:', 'jmp fast_next_segment']
        for index in range(4):
            lines += [f'fast_{name}_{index}:', f'offset_{name}{index}:',
                      'ldy $1000,x', f'fast_source_{name}{index}:', 'lda $ffff,y']
            if gain:
                # Y is reloaded from the offset table for each output, so it
                # can index the aligned gain page without a self-modifying
                # operand store. X remains the output-period position.
                lines += ['tay', f'fast_gain_read{index}:', 'lda $1000,y']
            lines += [f'fast_destination_{name}{index}:', 'sta buffer_b,x', 'inx']
        lines += [f'fast_stop_{name}:', 'cpx #0']
        if not gain:
            lines += ['mix_end_count:']
        lines += [f'bne fast_{name}_0', 'jmp fast_segment_done',
                  f'.assert "Fast {name} exceeds its page", * <= ${address + 256:04x}, true']
    lines += _q8_kernel('q8full', 0xf900, False)
    lines += _q8_kernel('q8gain', 0xfa00, True)
    lines += ['.pc=$0f00 "Constant ended-sample fill"', 'mix_silence:',
              'ldx pending_start_low', 'lda frame_count', 'and #1', 'beq !group+',
              'lda #128', 'silence_destination0:', 'sta buffer_b,x', 'inx',
              '!group:', 'lda #128', '!values:']
    for index in range(1, 5):
        lines += [f'silence_destination{index}:', 'sta buffer_b,x', 'inx']
    lines += ['bne !values-', 'mix_rts_silence:', 'rts',
              '.assert "Silence producer exceeds its page", * <= $1000, true']
    lines += ['.pc=$0f40 "Zero-gain Q8 cursor producer"', 'mix_zero:',
              'jmp fast_next_segment']
    for index in range(4):
        lines += [f'fast_zero_{index}:', 'lda #128',
                  f'fast_destination_zero{index}:', 'sta buffer_b,x', 'inx']
    lines += ['fast_stop_zero:', 'cpx #0', 'bne fast_zero_0', 'jmp fast_segment_done',
              '.assert "Zero-gain producer exceeds its reserved range", * <= $0f80, true']
    lines += ['.label mix_half = mix_gain', '.label mix_quarter = mix_gain',
              '.label mix_mute = mix_gain', '.label mix_rts = fast_return',
              '.label mix_end = fast_return+1']
    # Only the selected producer will run. Updating the other destinations
    # wastes cycles during the active gain ramps that leave little time for
    # the independent SID2 ring producer.
    lines += ['.pc=$0f80 "Advance only the active output destination"',
              'fast_wrap_destination:', 'lda fast_mode', 'beq !full+',
              'cmp #2', 'beq !zero+']
    for name in ('gain', 'full', 'zero'):
        if name != 'gain':
            lines += [f'!{name}:']
        lines += [f'inc fast_destination_{name}{index}+2' for index in range(4)]
        lines += ['rts']
    lines += ['.assert "Selected destination helper exceeds main RAM", * <= $1000, true']
    lines += ['.pc=$f870 "Update only the selected absolute source operands"',
              'fast_patch_source:', 'lda fast_mode', 'sta fast_patched_mode',
              'beq !full_source+']
    for name in ('gain', 'full'):
        if name == 'full':
            lines += ['!full_source:']
        for operand, source in ((1, 'fast_source'), (2, 'fast_source+1')):
            lines += [f'lda {source}', f'sta fast_patched_source+{operand - 1}']
            lines += [f'sta fast_source_{name}{index}+{operand}' for index in range(4)]
        lines += ['rts']
    lines += ['.assert "Absolute source updater overlaps fallback kernel", * <= $f900, true']
    return '\n'.join(lines) + '\n'


def patchers() -> str:
    lines = ['.label fast_elapsed=$25', '.label fast_remaining=$26',
             '.label fast_mode=$27', '.label fast_source=$28',
             '.label fast_destination=$2a', '.label fast_patched_source=$2a',
             '.label fast_segment_count=$2c', '.label fast_threshold=$2d',
             '.label fast_patched_mode=$2e',
             '.pc=$7900 "Patch only the selected Q8 producer"']
    for mode, name in enumerate(('full', 'gain', 'zero')):
        lines += [f'patch_{name}:', f'lda #{mode}', 'sta fast_mode']
        if name != 'zero':
            lines += ['lda tick_record+6']
            lines += [f'sta offset_{name}{index}+2' for index in range(4)]
        if name == 'gain':
            lines += ['lda tick_record+14']
            lines += [f'sta fast_gain_read{index}+2' for index in range(4)]
        lines += ['lda pending_start_low', 'sec', 'sbc fast_elapsed']
        lines += [f'sta fast_destination_{name}{index}+1' for index in range(4)]
        lines += ['lda target_buffer', 'sbc #0']
        lines += [f'sta fast_destination_{name}{index}+2' for index in range(4)]
        lines += ['jmp fast_patch']
    lines += ['fast_patch:',
             'lda frame_count', 'sta fast_remaining', 'lda tick_record+7', 'sta fast_threshold',
             'lda tick_record+6', 'sta fast_offset_subtract+2', 'sta fast_offset_finish+2']
    lines += ['ldx fast_elapsed', 'lda pcm_cursor', 'sec', 'fast_offset_subtract:',
              'sbc $1000,x', 'sta fast_source', 'lda pcm_cursor+1', 'sbc #0',
              'sta fast_source+1',
              'lda fast_mode', 'cmp #2', 'beq !source_ready+',
              'cmp fast_patched_mode', 'bne !source_changed+',
              'lda fast_source', 'cmp fast_patched_source', 'bne !source_changed+',
              'lda fast_source+1', 'cmp fast_patched_source+1', 'beq !source_ready+',
              '!source_changed:', 'jsr fast_patch_source', '!source_ready:']
    lines += ['lda tick_record+12', 'sta fast_advance_low+1',
              'lda tick_record+13', 'ldy fast_threshold', 'beq !high_ready+',
              'lda #0', '!high_ready:', 'sta fast_advance_high+1', 'rts']
    for gain, name in ((False, 'q8full'), (True, 'q8gain')):
        lines += [f'patch_{name}:', 'lda target_buffer']
        lines += [f'sta destination_{name}{index}+2' for index in range(3)]
        if gain:
            lines += ['lda tick_record+14']
            lines += [f'sta gain_read_{name}{index}+2' for index in range(3)]
        lines += ['lda pcm_cursor+1']
        lines += [f'sta sample_read_{name}{index}+2' for index in range(3)]
        for byte, field in (('low', 12), ('high', 13)):
            lines += ['lda pcm_active', f'bne !active_{name}_{byte}+', 'lda #0',
                      f'beq !step_{name}_{byte}+', f'!active_{name}_{byte}:',
                      f'lda tick_record+{field}', f'!step_{name}_{byte}:']
            lines += [f'sta step_{byte}_{name}{index}+1' for index in range(3)]
        lines += ['rts']
    lines += ['.assert "Fast patchers exceed the two assigned pages", * <= $7b00, true',
              '.pc=$7c00 "Split table-indexed output at cursor wraps"',
              'fast_next_segment:', 'lda fast_remaining', 'sta fast_segment_count',
              'lda #0', 'sec', 'sbc fast_elapsed', 'beq !output_wrap_far+',
              'cmp fast_segment_count', 'bcs !output_wrap_far+', 'sta fast_segment_count',
              '!output_wrap_far:', 'lda fast_threshold', 'beq !threshold_far+',
              'sec', 'sbc fast_elapsed', 'bcc !threshold_far+', 'beq !threshold_far+',
              'cmp fast_segment_count', 'bcs !threshold_far+', 'sta fast_segment_count',
              '!threshold_far:', 'lda fast_remaining', 'sec', 'sbc fast_segment_count',
              'sta fast_remaining', 'lda fast_segment_count', 'clc', 'adc fast_elapsed',
              'sta fast_stop_full+1', 'sta fast_stop_gain+1', 'sta fast_stop_zero+1',
              'lda fast_segment_count', 'and #3', 'tay', 'lda fast_mode',
              'beq !full_entry+', 'cmp #2', 'beq !zero_entry+',
              'lda fast_gain_entries,y', 'ldy #>fast_gain_0',
              'bne !entry_ready+', '!full_entry:', 'lda fast_full_entries,y',
              'ldy #>fast_full_0', 'bne !entry_ready+', '!zero_entry:',
              'lda fast_zero_entries,y', 'ldy #>fast_zero_0',
              '!entry_ready:', 'sta fast_jump+1', 'sty fast_jump+2',
              'ldx fast_elapsed', 'fast_jump:', 'jmp fast_full_0',
              'fast_segment_done:', 'stx fast_elapsed', 'cpx #0', 'bne !not_output_wrap+']
    lines += ['jsr fast_wrap_destination',
              'clc', 'lda fast_source', 'fast_advance_low:', 'adc #0', 'sta fast_source',
              'lda fast_source+1', 'fast_advance_high:', 'adc #0', 'sta fast_source+1',
              'jmp !source_changed_after_wrap+', '!not_output_wrap:', 'cpx fast_threshold',
              'bne !cursor_ready+', 'inc fast_source+1', '!source_changed_after_wrap:',
              'lda fast_mode', 'cmp #2', 'beq !cursor_ready+', 'jsr fast_patch_source',
              '!cursor_ready:',
              'lda fast_remaining', 'beq !frame_finished+', 'jmp fast_next_segment',
              '!frame_finished:', 'ldx fast_elapsed',
              'fast_offset_finish:', 'lda $1000,x', 'clc', 'adc fast_source',
              'sta pcm_cursor', 'lda fast_source+1', 'adc #0', 'sta pcm_cursor+1',
              'fast_return:', 'rts',
              'fast_full_entries:', '.byte <fast_full_0,<fast_full_3,<fast_full_2,<fast_full_1',
              'fast_gain_entries:', '.byte <fast_gain_0,<fast_gain_3,<fast_gain_2,<fast_gain_1',
              'fast_zero_entries:', '.byte <fast_zero_0,<fast_zero_3,<fast_zero_2,<fast_zero_1',
              'patch_silence:', 'lda target_buffer']
    lines += [f'sta silence_destination{index}+2' for index in range(5)]
    lines += ['rts',
              'patch_low:', '.byte <patch_full,<patch_gain,<patch_q8full,<patch_q8gain,<patch_silence,<patch_zero',
              'patch_high:', '.byte >patch_full,>patch_gain,>patch_q8full,>patch_q8gain,>patch_silence,>patch_zero',
              'kernel_low:', '.byte <mix_full,<mix_gain,<mix_q8full,<mix_q8gain,<mix_silence,<mix_zero',
              'kernel_high:', '.byte >mix_full,>mix_gain,>mix_q8full,>mix_q8gain,>mix_silence,>mix_zero',
              '.assert "Fast segment manager exceeds its assigned page", * <= $7d00, true']
    return '\n'.join(lines) + '\n'
