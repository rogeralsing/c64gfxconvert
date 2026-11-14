"""Cream's Q8 source cursor for the shared native player.

Only the optional fractional build uses these emitted sections. The normal
triangle/fixed-pitch mixer and its assembly bytes remain unchanged. Raw PCM and
gain tables use unsigned centre 128. The C64 reads a reused bank, applies its
selected gain table and advances a persistent 16-bit-byte plus 8-bit-fraction
cursor. No song waveform or per-note resampled bank is required.
"""
from __future__ import annotations


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Unexpected shared runtime section: {old[:80]!r}")
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    """Keep the shared NMI and SID writes; replace only PCM scheduling work."""
    source = _replace_once(source, 'lda #113\n    sta neutral_pcm,x',
                           'lda #128\n    sta neutral_pcm,x')
    old = '''    lda pending_flags
    and #12
    lsr
    lsr
    tax
'''
    new = '''    // Page $10 is the exact identity gain table. Every other table uses
    // the gain kernel; the producer workload is identical in all mute builds.
    ldx #0
    lda tick_record+14
    cmp #$10
    beq !gain_kernel_ready+
    inx
!gain_kernel_ready:
'''
    source = _replace_once(source, old, new)
    begin = source.index('// Guards supply a contiguous crossing tick.')
    end = source.index('\ncommit_sid1:', begin)
    source = source[:begin] + '''// The Q8 kernel already advances pcm_cursor. Guards cover the crossing
// block; stop one-shots afterwards. No second integer-frame advance occurs.
advance_pcm:
    lda pcm_active
    beq !done+
    lda pcm_cursor+1
    cmp pcm_end+1
    bcc !done+
    bne !ended+
    lda pcm_cursor
    cmp pcm_end
    bcc !done+
!ended:
    jmp pcm_off
!done:
    rts
''' + source[end:]
    return source


def mixer() -> str:
    """Two-way unrolled identity/gain kernels; source banks may be unaligned."""
    lines: list[str] = []
    for gain, name, address in ((False, 'full', 0x0c00), (True, 'gain', 0x0e00)):
        lines += [f'.pc = ${address:04x} "Native Q8 {name} PCM cursor"']
        if not gain:
            lines += ['mix_samples:']
        lines += [f'mix_{name}:', 'ldx pending_start_low', 'ldy pcm_cursor']
        lines += ['lda frame_count', 'and #1', f'beq mix_group_{name}']

        def value(index: int) -> list[str]:
            body = [f'sample_read_{name}{index}:', 'lda $ff00,y']
            if gain:
                # Addressing the gain page directly leaves both index
                # registers live: Y is source position, X is output position.
                body += [f'sta gain_read_{name}{index}+1',
                         f'gain_read_{name}{index}:', 'lda $1000']
            body += [f'destination_{name}{index}:', 'sta buffer_b,x',
                     # Caller clears carry. Source high-byte ADC clears it
                     # again except on a page carry, handled below. Loads,
                     # stores, index increments and NMI/RTI preserve it.
                     'lda phase_low', f'step_low_{name}{index}:', 'adc #0',
                     'sta phase_low', 'tya',
                     f'step_high_{name}{index}:', 'adc #0',
                     'tay', f'bcc !same_page{index}+',
                     'inc pcm_cursor+1', 'lda pcm_cursor+1']
            body += [f'sta sample_read_{name}{slot}+2' for slot in range(3)]
            body += ['clc']
            body += [f'!same_page{index}:', 'inx']
            return body

        lines += value(0)
        lines += [f'mix_group_{name}:']
        lines += value(1) + value(2)
        lines += [f'mix_end_count_{name}:', f'bne mix_group_{name}']
        lines += ['sty pcm_cursor']
        lines += [f'mix_rts_{name}:', 'rts', f'mix_end_{name}:',
                  f'.assert "Q8 {name} kernel must remain in its page", * <= ${address + 256:04x}, true']
    lines += ['.label mix_half = mix_gain', '.label mix_quarter = mix_gain',
              '.label mix_mute = mix_gain', '.label mix_rts = mix_rts_full',
              '.label mix_end = mix_end_full', '.label mix_end_count = mix_end_count_full']
    return '\n'.join(lines) + '\n'


def patchers() -> str:
    lines: list[str] = []
    for gain, name, address in ((False, 'full', 0x7900), (True, 'gain', 0x7a00)):
        lines += [f'.pc = ${address:04x} "Patch Q8 {name} cursor"', f'patch_{name}:']
        fields = [('target_buffer', 'destination', 2),
                  ('tick_record+14', 'gain_read', 2)] if gain else [('target_buffer', 'destination', 2)]
        fields += [('pcm_cursor+1', 'sample_read', 2)]
        for load, label, operand in fields:
            lines += [f'lda {load}']
            lines += [f'sta {label}_{name}{index}+{operand}' for index in range(3)]
        # Ended/initially silent voices read the stable neutral page without
        # walking beyond it. Live one-shots keep every source Q8 pitch bit.
        lines += ['lda pcm_active', f'bne !active_{name}+', 'lda #0',
                  f'beq !step_low_{name}+', f'!active_{name}:', 'lda tick_record+12',
                  f'!step_low_{name}:']
        lines += [f'sta step_low_{name}{index}+1' for index in range(3)]
        lines += ['lda pcm_active', f'bne !active_high_{name}+', 'lda #0',
                  f'beq !step_high_{name}+', f'!active_high_{name}:', 'lda tick_record+13',
                  f'!step_high_{name}:']
        lines += [f'sta step_high_{name}{index}+1' for index in range(3)]
        lines += ['rts', f'.assert "Q8 {name} patcher must remain in its page", * <= ${address + 256:04x}, true']
    lines += ['.pc=$7ce0 "Q8 kernel dispatch tables"',
              'patch_low:', '.byte <patch_full,<patch_gain,<patch_gain,<patch_gain',
              'patch_high:', '.byte >patch_full,>patch_gain,>patch_gain,>patch_gain',
              'kernel_low:', '.byte <mix_full,<mix_gain,<mix_gain,<mix_gain',
              'kernel_high:', '.byte >mix_full,>mix_gain,>mix_gain,>mix_gain']
    return '\n'.join(lines) + '\n'
