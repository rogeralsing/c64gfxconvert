"""Assembly support for the native full-length player, without arranging notes.

``data.asm`` owns reusable assets. ``score.asm`` owns the native decoder and
defines score_init, score_next_tick, tick_record=$0600 and FRAME_COUNT.
``sid-programs.asm`` defines synth_sid_tick and voice_record=$0620, converting
the ordinary instruments' compact score fields to twelve actual SID register
values. It reads tick_record without changing it. A bounded one-tick prefetch
decodes the next score after completing the current buffer. fill_frame consumes
the prefetched record and calls synth_sid_tick exactly once; score_init only
initializes the decoder. The decoder's 24-byte record is described by TICK_FIELDS below. Transient reset
flags must clear on held ticks. The runtime computes the 156/157 output schedule.
Field23 contains ordinary SID retrigger bits0/1 and also clears on held ticks.
Its bits2/3 select PCM gain shifts0/1/2 or neutral/mute3 and are persistent,
unlike the trigger bits. The PCM cursor advances in every mode.

PCM data uses centre 113 and triangle tables use centre 15; every sum must be
0..255. A PCM bank has 156 readable guard values after its exclusive end: neutral
113 for a one-shot, or repeated loop values. Loops must be at least 157 values,
repeating a shorter periodic source loop in the reusable bank when necessary.
Held gain-bank changes must share lengths and loop offsets. Held pitch-bank
changes are not implemented; preserving an output offset does not preserve the
original instrument's source phase across a change of resampling ratio.
No per-tick waveform data is accepted or generated here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
TICK_FIELDS = {
    "sid1_base_frequency_low": 0, "sid1_continuous_envelope": 1,
    "sid1_instrument_and_active_bit": 2, "sid1_chord_table_index": 3,
    "sid1_reserved": 4, "sid1_sustain_level": 5,
    "sid2_base_frequency_low": 6, "sid2_base_frequency_high": 7,
    "sid2_instrument_and_active_bit": 8, "sid2_chord_table_index": 9,
    "sid2_reserved": 10, "sid2_sustain_level": 11,
    "triangle_negative_step_low": 12, "triangle_negative_step_high": 13,
    "triangle_table_page": 14, "triangle_reset": 15,
    "pcm_base_low": 16, "pcm_base_high": 17, "pcm_end_low": 18,
    "pcm_end_high": 19, "pcm_loop_low": 20, "pcm_loop_high": 21,
    "pcm_trigger": 22, "ordinary_retrigger_and_PCM_shift_bits": 23,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _delay(cycles: int) -> str:
    """Exact cold delay, including RTS. All branches remain in one page."""
    for outer in range(1, 255):
        for inner in range(1, 256):
            extra = cycles - (8 + outer * 1281 + inner * 5)
            if 0 <= extra <= 12 and extra != 1:
                tail = "bit $ea\n" if extra % 2 else ""
                tail += "nop\n" * ((extra - (3 if extra % 2 else 0)) // 2)
                return (f"ldy #{outer}\n!outer:\nldx #255\n!inner:\ndex\nbne !inner-\n"
                        f"dey\nbne !outer-\nldx #{inner}\n!tail:\ndex\nbne !tail-\n" + tail + "rts\n")
    for inner in range(1, 256):
        extra = cycles - (7 + inner * 5)
        if 0 <= extra <= 12 and extra != 1:
            tail = "bit $ea\n" if extra % 2 else ""
            tail += "nop\n" * ((extra - (3 if extra % 2 else 0)) // 2)
            return f"ldx #{inner}\n!tail:\ndex\nbne !tail-\n" + tail + "rts\n"
    raise ValueError(f"Unsupported cold delay: {cycles}")


def _mixer() -> str:
    lines = []
    for mode, name in enumerate(('full','half','quarter','mute')):
        lines += [f'.pc = ${0x0c00+mode*256:04x} "Native {name} PCM mixer"']
        if not mode: lines += ['mix_samples:']
        lines += [f'mix_{name}:','ldx phase_high','ldy #0','lda frame_count','and #1',
                  f'beq mix_group_{name}']

        def value(index: int):
            prefix = ['lda phase_low', f'step_low_{name}{index}:', 'adc #0', 'sta phase_low', 'txa',
                      f'step_high_{name}{index}:', 'adc #0', 'tax']
            if mode==3:
                prefix += [f'triangle_read_{name}{index}:','lda $1000,x','clc','adc #113']
            elif not mode:
                prefix += [f'triangle_read_{name}{index}:','lda $1000,x','clc',
                           f'sample_read_{name}{index}:','adc $ffff,y']
            else:
                prefix += [f'sample_read_{name}{index}:','lda $ffff,y'] + ['lsr']*mode
                # LSR carry rounds the scaled sample. The bias addition cannot
                # overflow, therefore triangle ADC and the next phase start C=0.
                prefix += [f'adc #{56 if mode==1 else 85}',
                           f'triangle_read_{name}{index}:','adc $1000,x']
            return prefix+[f'destination_{name}{index}:','sta buffer_b,y','iny']

        lines += value(0)
        lines += [f'mix_group_{name}:']
        for index in range(1, 5): lines += value(index)
        lines += [f'mix_end_count_{name}:','cpy #156',f'bne mix_group_{name}','stx phase_high',
                  f'mix_rts_{name}:','rts',f'mix_end_{name}:',
                  f'.assert "{name} mixer must remain in its page", * <= ${0x0d00+mode*256:04x}, true']
    lines += ['.label mix_rts = mix_rts_full','.label mix_end = mix_end_full',
              '.label mix_end_count = mix_end_count_full']
    return "\n".join(lines) + "\n"


def _patchers() -> str:
    lines=[]
    for address,name in zip((0x7900,0x7a00,0x7c40,0x7a90),('full','half','quarter','mute')):
        lines += [f'.pc = ${address:04x} "Patch active {name} mixer"',f'patch_{name}:']
        for load,label,operand in [('pending_start_low','destination',1),
                                   ('target_buffer','destination',2),
                                   ('tick_record+12','step_low',1),
                                   ('tick_record+13','step_high',1),
                                   ('tick_record+14','triangle_read',2),
                                   ('pcm_cursor','sample_read',1),
                                   ('pcm_cursor+1','sample_read',2)]:
            if name=='mute' and label=='sample_read': continue
            lines += [f'lda {load}']+[f'sta {label}_{name}{index}+{operand}' for index in range(5)]
        lines += ['lda frame_count',f'sta mix_end_count_{name}+1','rts']
    lines += ['.assert "Mute patcher must precede cold delay", * <= $7b00, true',
              '.pc=$7ce0 "Kernel dispatch tables"',
              'patch_low:','.byte <patch_full,<patch_half,<patch_quarter,<patch_mute',
              'patch_high:','.byte >patch_full,>patch_half,>patch_quarter,>patch_mute',
              'kernel_low:','.byte <mix_full,<mix_half,<mix_quarter,<mix_mute',
              'kernel_high:','.byte >mix_full,>mix_half,>mix_quarter,>mix_mute',
              '.assert "Quarter patcher must precede interrupt template", * <= $7d00, true']
    return '\n'.join(lines)+'\n'


def build(out: Path, data_asm: Path, score_asm: Path, enabled=(True, True, True), *,
          loader_arena: tuple[int, int], sid_programs_asm: Path | None = None, startup_audio_delay=44024,
          startup_initial_delay=4867, pcm_fractional: bool = False) -> dict:
    """Build one shared-workload program; enabled only changes mute constants.

    Main code occupies $0801..0fff, auxiliary code reserves $7000..7fff.
    Low RAM: buffers0200/0300, copied handlers0400/0500, tick_record0600,
    voice_record0620, neutral PCM0700. Runtime state is ZP02..2f, the NMI is ZP80..b7.
    Decoder owns ZP40..5f and optional E000..Efff history.
    """
    if len(enabled) != 3 or any(not isinstance(item, bool) for item in enabled):
        raise ValueError("enabled must contain three booleans")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    data_asm, score_asm = Path(data_asm).resolve(), Path(score_asm).resolve()
    sid_programs_asm = (Path(sid_programs_asm).resolve() if sid_programs_asm is not None
                        else data_asm.parent / 'sid-programs.asm')
    if not sid_programs_asm.is_file():
        raise ValueError(f'Native SID instrument programs are required: {sid_programs_asm}')
    config = []
    for voice in (1, 2):
        on = enabled[voice - 1]
        config += [f'.label SID{voice}_MASK = {255 if on else 0}',
                   f'.label SID{voice}_TEST = {0 if on else 24}']
    config += [f'.label SID3_SUSTAIN = {240 if enabled[2] else 0}',
               f'.label MASTER_VOLUME = {15 if enabled[2] else 143}']
    (out / 'config.asm').write_text('\n'.join(config) + '\n')
    # Import wrappers preserve paths within the supplied generated ASM files.
    for filename, original in (('data.asm', data_asm), ('score.asm', score_asm),
                               ('sid-programs.asm', sid_programs_asm)):
        wrapper = out / filename
        if wrapper.resolve() != original:
            wrapper.write_text(f'.import source "{original}"\n')
    source = (HERE / 'full_length_player.asm').read_text()
    if pcm_fractional:
        import cream_fractional
        source = cream_fractional.transform(source)
    target = out / 'full_length_player.asm'
    target.write_text(source)
    (out / 'mix.asm').write_text(cream_fractional.mixer() if pcm_fractional else _mixer())
    (out / 'patch.asm').write_text(cream_fractional.patchers() if pcm_fractional else _patchers())
    (out / 'delays.asm').write_text(
        '.pc = $7b00 "Cold audio delay"\nstartup_audio_delay:\n' + _delay(startup_audio_delay)
        + 'startup_audio_delay_end:\n.pc = $7c00 "Initial note spacing"\nstartup_initial_delay:\n'
        + _delay(startup_initial_delay) + 'startup_initial_delay_end:\n')
    program = out / 'player.prg'
    command = ['rtk', 'proxy', str(Path.home() / '.local/bin/kickass'), str(target),
               '-o', str(program), '-symbolfile']
    completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (out / 'build.log').write_text(completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    labels = {key: int(value, 16) for key, value in re.findall(
        r'\.label\s+(\w+)\s*=\s*\$([\da-fA-F]+)', target.with_suffix('.sym').read_text())}
    if labels.get('tick_record') != 0x600:
        raise ValueError('Decoder must define tick_record=$0600')
    if labels.get('voice_record') != 0x620:
        raise ValueError('SID programs must define voice_record=$0620')
    from prg_loader import package
    native = out / 'native.prg'
    program.replace(native)
    loader = package(native, program, entry=labels['start'], arena=loader_arena)
    labels.update(loader['symbols'])
    result = {'program': str(program), 'symbols': labels,
              'program_sha256': digest(program), 'bytes': program.stat().st_size,
              'source_sha256': digest(HERE / 'full_length_player.asm'),
              'runtime_helper_sha256': digest(Path(__file__)),
              'data_asm_sha256': digest(data_asm), 'score_asm_sha256': digest(score_asm),
              'sid_programs_asm_sha256': digest(sid_programs_asm),
              'enabled': list(enabled), 'tick_record_fields': TICK_FIELDS,
              'startup_loader': loader,
              'runtime_reserved_ranges': [
                  {'start': 0x0801, 'end_exclusive': 0x1000,
                   'purpose': 'bootstrap/main and four native mixing kernels'},
                  {'start': 0x7000, 'end_exclusive': 0x8000,
                   'purpose': 'clock slide, patchers, delays and interrupt templates'}],
              'shared_low_ram': {'buffers': [0x0200, 0x0300],
                                 'copied_handlers': [0x0400, 0x0500],
                                 'tick_record': 0x0600, 'voice_record': 0x0620,
                                 'neutral_PCM_page': 0x0700},
              'startup_audio_delay_cycles': startup_audio_delay,
              'startup_initial_delay_cycles': startup_initial_delay}
    if pcm_fractional:
        result['pcm_backend'] = {'kind': 'fractional Q8 source cursor with gain tables',
                                 'source_sha256': digest(HERE / 'cream_fractional.py')}
    (out / 'build.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
