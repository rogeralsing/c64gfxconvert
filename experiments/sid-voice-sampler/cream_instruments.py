"""Prepare Cream for the canonical native SID mixer.

The default source interval is 17.92..44.80 seconds, not the introduction.
The explicit full mode traverses all 241.92 seconds with a fractional Q8 cursor.
Original C2 uses reused samples, C3 a pulse voice and C4 quiet synthetic
percussion. The approved arrangement omits C1's chords explicitly.

PCM pitch banks compile the accepted unsigned 8-bit/Q8 cursor recipe into reused
instrument/pitch assets. They contain no mixed song audio or tick windows.
Every source trigger still starts a native C64 integer cursor at bank offset 0.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

import native_support as support
from sid_pitch import melody_pitch

HERE = Path(__file__).resolve().parent
LIBRARY = HERE / 'native_instruments/cream'
CLOCK, PERIOD, PAULA = support.CLOCK, support.PERIOD, support.PAULA
RATE = CLOCK / PERIOD
START_TICK, END_TICK = 896, 2240
START, END = START_TICK / 50, END_TICK / 50
APPROVED_PCM_SHA256 = '58b77dd50daa3f899e83d865cb7961bfa591a44a3c089ccac3c2700cc0b7482e'
APPROVED_SID_ROWS_SHA256 = '66c15ba0a9a1f7e01d8707efcb328557070f15a83d8fe942bab178702b57fa50'


def _recipes(*, full: bool = False) -> dict[int, dict]:
    presets = {item['source_instrument']: item for path in sorted(LIBRARY.glob('*.json'))
               for item in [json.loads(path.read_text())]}
    if not full:
        presets = {identifier: item for identifier, item in presets.items() if identifier <= 10}
    wanted = set(range(1, 16)) | {17} if full else set(range(1, 11))
    if set(presets) != wanted:
        raise ValueError('Cream requires its explicit instrument recipes')
    if any(presets[i]['sustain'] != 1 or presets[i]['rest_control'] != 25
           for i in (*range(1, 7), 10)):
        raise ValueError('Cream continuous envelopes must retain sustain 1 and TEST/GATE rests')
    return presets


def _sid_rows(mod: dict, all_ticks: list, presets: dict) -> tuple[list, dict]:
    """Reproduce the accepted source-RMS gates and short SID drum programs."""
    pulse, rest = presets[10], presets[10]['rest_control']
    pitch = melody_pitch(mod, pulse)
    raw = {i: np.frombuffer(mod['samples'][i - 1]['data'], np.int8).astype(float) / 128
           for i in range(1, 11)}
    peaks = {i: max(float(np.sqrt(np.mean(data[j:j + 256] ** 2)))
                    for j in range(0, len(data), 128)) for i, data in raw.items()}
    onset, position, current = -100.0, 0.0, 0
    melody_position, melody_current = 0.0, 0
    rows, triggers = [], []
    for index, tick in enumerate(all_ticks[:END_TICK]):
        melody = tick['channels'][2]
        if melody['trigger']:
            melody_current, melody_position = melody['playing_sample'], float(melody.get('offset', 0))
        active = False
        if melody_current == 10 and melody['period']:
            advance = PAULA / melody['period'] * tick['duration_s']
            indices = (melody_position + np.arange(max(1, round(advance)))).astype(int)
            block = np.zeros(len(indices)); valid = indices < len(raw[10])
            block[valid] = raw[10][indices[valid]]
            active = melody['volume'] > 0 and float(np.sqrt(np.mean(block * block))) > peaks[10] * pulse['rms_gate_ratio']
            melody_position += advance
        drum = tick['channels'][3]
        if drum['trigger']:
            if drum['playing_sample'] not in range(1, 7) or drum.get('offset', 0):
                raise ValueError('Unexpected Cream percussion instrument or offset')
            onset, position, current = tick['time_s'], 0.0, drum['playing_sample']
        drum_frequency, drum_control = 0.0, rest
        if current and drum['period']:
            preset = presets[current]
            source_rate = PAULA / drum['period']
            advance = source_rate * tick['duration_s']
            indices = (position + np.arange(max(1, round(advance)))).astype(int)
            block = np.zeros(len(indices)); valid = indices < len(raw[current])
            block[valid] = raw[current][indices[valid]]
            age = tick['time_s'] - onset
            audible = (drum['volume'] > 0 and age < preset['duration_s'] - 1e-8
                       and (float(np.sqrt(np.mean(block * block))) > peaks[current] * preset['rms_gate_ratio']
                            or drum['trigger']))
            if audible:
                if (preset['program'] == 'triangle-sweep' or
                        preset['program'] == 'noise-then-triangle-sweep'
                        and not age < preset['noise_duration_s'] - 1e-8):
                    body = preset['base_hz'] * preset['reference_period'] / drum['period']
                    drum_frequency = body * (1 + preset['sweep_depth'] * math.exp(-age / preset['sweep_decay_s']))
                    drum_control = preset['triangle_control']
                else:
                    drum_frequency = source_rate / preset['noise_divisor']
                    drum_control = preset['noise_control']
            position += advance
        if index < START_TICK:
            continue
        if melody['volume'] and melody['playing_sample'] != 10:
            raise ValueError('Cream melody changes instrument inside the approved passage')
        melodic_hz = PAULA / melody['period'] * pitch['cycles_per_source_sample'] if melody['period'] and active else 0
        frequencies = [round(hz * 2**24 / CLOCK) for hz in (melodic_hz, drum_frequency)]
        if any(not 0 <= word <= 65535 for word in frequencies):
            raise ValueError('Cream SID frequency exceeds 16 bits')
        rows.append([frequencies[0] & 255, frequencies[0] >> 8, pulse['control'] if melodic_hz else rest,
                     frequencies[1] & 255, frequencies[1] >> 8, drum_control])
        triggers.append(bool(drum['trigger']))
    # Preserve the approved one-tick TEST rest before every distinct drum hit.
    for index in range(1, len(rows)):
        if triggers[index] and not triggers[index - 1]:
            rows[index - 1][3:] = [0, 0, rest]
    encoded = bytes(value for row in rows for value in row)
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != APPROVED_SID_ROWS_SHA256:
        raise ValueError(f'Cream SID states differ from the approved PRG: {digest}')
    return rows, {'pitch': pitch, 'physical_frequency_control_sha256': digest,
                  'percussion_triggers': sum(triggers), 'continuous_gate': [True, True],
                  'AD': [0, 0], 'SR': [16, 16]}


def _emit_sid(out: Path, words: list[int]) -> Path:
    source = (HERE / 'cream_sid.asm').read_text()
    lines = [source, 'cream_frequency_low:', '.byte ' + ','.join(str(w & 255) for w in words),
             'cream_frequency_high:', '.byte ' + ','.join(str(w >> 8) for w in words),
             'sid_program_end:', '.assert "Cream SID programs must remain below vectors", * <= $ff00, true']
    path = out / 'sid-programs.asm'
    path.write_text('\n'.join(lines) + '\n')
    return path


def _emit_bank_asm(out: Path, asset: dict) -> Path:
    """Export one address-independent, reusable instrument/pitch bank."""
    directory = out / 'pcm-asm'
    directory.mkdir(exist_ok=True)
    identifier, period = asset['instrument'], asset['period']
    suffix = f'g{asset["gain"]:02d}' if asset.get('fractional_q8') else f'p{period:04d}'
    label = f'cream_i{identifier:02d}_{suffix}'
    pitch_note = (f'Exact accepted Q8 cursor step {asset["accepted_Q8_step"]}'
                  if not asset.get('fractional_q8') else 'Q8 cursor step supplied by the note score')
    center = 128 if asset.get('fractional_q8') else 113
    lines = [f'// Cream source instrument {identifier}, MOD period {period}.',
             f'// {pitch_note}; one-shot, no loop.',
             f'// Unsigned centre {center}; ' + ('native gain LUT follows the read.' if center == 128 else 'the native mixer adds its neutral triangle 15.'),
             f'// Includes {asset.get("guard_bytes", 156)} neutral guard bytes. The caller chooses the memory address.',
             f'{label}:']
    data = asset['data']
    for start in range(0, len(data), 32):
        lines.append('.byte ' + ','.join(str(value) for value in data[start:start + 32]))
    lines += [f'{label}_end:',
              f'.label {label}_logical_end = {label}+{asset["logical_bytes"]}',
              f'.label {label}_loop_offset = 0']
    path = directory / f'{identifier:02d}-{suffix}.asm'
    path.write_text('\n'.join(lines) + '\n')
    return path


def _full_sid_rows(mod: dict, ticks: list, presets: dict, *,
                   sid1_channels: list[int] | None = None) -> tuple[list, list, dict]:
    """Allocate full-song SID roles, retaining each original channel's cursor.

    The default keeps the preserved C3 arrangement and its approved-state
    guard. An explicit passage map is a new arrangement: it must not inherit
    that listening approval. Other voices still use their original routes.
    """
    if sid1_channels is not None and (len(sid1_channels) != len(ticks)
                                      or any(channel not in (0, 2) for channel in sid1_channels)):
        raise ValueError('Cream SID1 requires one explicit C1/C3 source per tick')
    raw = {s['id']: np.frombuffer(s['data'], np.int8).astype(float) / 128
           for s in mod['samples'] if s['length']}
    peaks = {i: max(float(np.sqrt(np.mean(data[j:j + 256] ** 2)))
                    for j in range(0, len(data), 128)) for i, data in raw.items()}
    roots = {i: melody_pitch(mod, presets[i])['source_period_samples'] for i in (10, 11, 12)}
    roots.update({i: presets[i]['source_period_samples'] for i in (13, 14, 15)})
    roots[9] = presets[9]['sid_role']['source_period_samples']
    positions, current, onsets, onset_ticks = [0.0] * 4, [0] * 4, [-100.0] * 4, [0] * 4
    rows, routes, percussion_hits = [], [], []
    for index, tick in enumerate(ticks):
        rms = [0.0] * 4
        for channel, state in enumerate(tick['channels']):
            if state['trigger']:
                current[channel], positions[channel] = state['playing_sample'], float(state.get('offset', 0))
                onsets[channel], onset_ticks[channel] = tick['time_s'], index
            identifier = current[channel]
            if not identifier or not state['period']:
                continue
            advance = PAULA / state['period'] * tick['duration_s']
            indices = (positions[channel] + np.arange(max(1, round(advance)))).astype(int)
            sample = mod['samples'][identifier - 1]
            if sample['loop_length'] > 2:
                end = sample['loop_start'] + sample['loop_length']
                indices = np.where(indices < end, indices,
                                   sample['loop_start'] + (indices - end) % sample['loop_length'])
            block = np.zeros(len(indices)); valid = indices < len(raw[identifier])
            block[valid] = raw[identifier][indices[valid]]
            rms[channel] = float(np.sqrt(np.mean(block * block)))
            positions[channel] += advance

        sid2_channel = (0 if index < 672 and not tick['channels'][3]['playing_sample']
                        and tick['channels'][0]['playing_sample'] == 10 else 3)
        sid1_channel = 2 if sid1_channels is None else sid1_channels[index]
        voices, voice_routes = [], [sid1_channel, sid2_channel]
        for channel in voice_routes:
            state = tick['channels'][channel]
            identifier = current[channel]
            control, frequency = 25, 0.0
            if identifier and state['period'] and state['volume']:
                if identifier not in presets:
                    raise ValueError(f'No full Cream SID recipe for instrument {identifier}')
                preset = presets[identifier]
                age = tick['time_s'] - onsets[channel]
                if identifier in range(1, 7):
                    audible = (age < preset['duration_s'] - 1e-8 and
                               (rms[channel] > peaks[identifier] * preset['rms_gate_ratio'] or state['trigger']))
                    if audible:
                        if (preset['program'] == 'triangle-sweep' or
                                preset['program'] == 'noise-then-triangle-sweep'
                                and not age < preset['noise_duration_s'] - 1e-8):
                            body = preset['base_hz'] * preset['reference_period'] / state['period']
                            frequency = body * (1 + preset['sweep_depth'] * math.exp(-age / preset['sweep_decay_s']))
                            control = preset['triangle_control']
                        else:
                            frequency = PAULA / state['period'] / preset['noise_divisor']
                            control = preset['noise_control']
                else:
                    recipe = preset['sid_role'] if identifier == 9 else preset
                    if rms[channel] > peaks[identifier] * recipe['rms_gate_ratio']:
                        if recipe['program'] == 'noise':
                            frequency = PAULA / state['period'] / recipe['noise_divisor']
                            control = recipe['noise_control']
                        else:
                            semitone = (recipe['semitones'][(index - onset_ticks[channel]) % len(recipe['semitones'])]
                                        if recipe['program'] == 'arpeggio' else 0)
                            frequency = PAULA / state['period'] / roots[identifier] * 2 ** (semitone / 12)
                            control = recipe['control']
            word = round(frequency * 2**24 / CLOCK)
            if not 0 <= word <= 65535:
                raise ValueError('Full Cream SID frequency exceeds 16 bits')
            voices += [word & 255, word >> 8, control]
        rows.append(voices)
        routes.append({'tick': index, 'time_s': tick['time_s'], 'sid1': sid1_channel + 1, 'sid2': sid2_channel + 1})
        drum = tick['channels'][sid2_channel]
        percussion_hits.append(sid2_channel == 3 and drum['trigger'] and drum['playing_sample'] in (*range(1, 7), 9, 17))
    for index in range(1, len(rows)):
        if percussion_hits[index] and not percussion_hits[index - 1]:
            rows[index - 1][3:] = [0, 0, 25]
    approved = bytes(value for row in rows[START_TICK:END_TICK] for value in row)
    if sid1_channels is None and hashlib.sha256(approved).hexdigest() != APPROVED_SID_ROWS_SHA256:
        raise ValueError('Full Cream changed approved passage frequency/control states')
    return rows, routes, {'roots_source_samples': roots,
                          'approved_frequency_control_sha256': (hashlib.sha256(approved).hexdigest()
                                                               if sid1_channels is None else None),
                          'selected_frequency_control_sha256': hashlib.sha256(approved).hexdigest(),
                          'new_sid1_passage_map': sid1_channels is not None,
                          'continuous_gate': [True, True], 'AD': [0, 0], 'SR': [16, 16],
                          'new_timbres': {'11': 'Measured complex tone approximated by pulse where not sampled.',
                                          '12': 'Measured monophonic polysynth root approximated by pulse.',
                                          '13/14/15': 'Measured major/minor/sus4 chords played as 50 Hz note arpeggios.',
                                          '17': 'Broadband noise approximation where not sampled.',
                                          '9_on_C4': 'Measured inharmonic tonal percussion approximated by triangle.'}}


def _emit_full_sid(out: Path) -> Path:
    """Decode full frequency bytes while retaining SID1's continuous flag."""
    source = '''// Full Cream SID1 descriptor packs frequency-high in bits1..7.
// Bit0 remains the shared runtime's continuous-envelope flag.
.label voice_record = $0620
.pc = $f800 "Full Cream native SID state program"
synth_sid_tick:
    lda tick_record
    sta voice_record
    lda tick_record+1
    lsr
    sta voice_record+1
    ldx #9
!copy:
    lda tick_record+2,x
    sta voice_record+2,x
    dex
    bpl !copy-
    rts
sid_program_end:
'''
    path = out / 'sid-programs.asm'
    path.write_text(source)
    return path


def _prepare_full(out: Path) -> dict:
    """Prepare all source ticks with reused fractional-cursor PCM banks."""
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    presets = _recipes(full=True)
    source = json.loads((HERE.parent / 'mod-hybrid/sources/cream-of-the-earth.source.json').read_text())
    mod = support.source_mod(source, out)
    ticks = support.build_timeline(mod)['ticks']
    if len(ticks) != 12096 or any(abs(t['duration_s'] - .02) > 1e-9 for t in ticks):
        raise ValueError('Expected the complete pinned 50 Hz Cream timeline')
    sid_rows, routes, sid_report = _full_sid_rows(mod, ticks, presets)
    cuts = [(i * CLOCK + PERIOD * 25) // (PERIOD * 50) for i in range(len(ticks) + 1)]
    counts = [high - low for low, high in zip(cuts, cuts[1:])]
    filtered = {i: resample_poly(np.frombuffer(mod['samples'][i - 1]['data'], np.int8).astype(float) / 128,
                                1, presets[i].get('decimation', presets[i].get('pcm_decimation')))
                for i in (7, 8, 9, 11, 17)}
    assets = [{'id': 0, 'instrument': 0, 'period': 0, 'gain': 0,
               'data': bytes([128] * 512), 'logical_bytes': 256, 'loop_offset': 0,
               'guard_bytes': 256, 'fractional_q8': True}]
    asset_ids, pages, page_ids = {}, [bytes(range(256))], {bytes(range(256)): 0}
    quantization = {}

    def bank(identifier: int, volume: int) -> tuple[int, int, int]:
        preset = presets[identifier]
        native_gain = identifier in (11, 17)
        key = identifier, 64 if native_gain else volume
        if key not in asset_ids:
            scale = preset['pcm_base_scale'] if native_gain else 127 * volume / 64
            values = np.clip(np.rint(128 + filtered[identifier] * scale), 0, 255).astype(np.uint8)
            values = np.pad(values, (0, (-len(values)) % 256), constant_values=128)
            if not native_gain and volume == preset['volume']:
                if len(values) != preset['bytes'] or hashlib.sha256(values.tobytes()).hexdigest() != preset['sha256']:
                    raise ValueError('Full Cream changed an approved reusable instrument bank')
            asset_id = len(assets)
            assets.append({'id': asset_id, 'instrument': identifier, 'period': 0, 'gain': key[1],
                           'data': values.tobytes() + bytes([128] * 256),
                           'logical_bytes': len(values), 'loop_offset': 0, 'guard_bytes': 256,
                           'fractional_q8': True, 'base_scale': scale,
                           'source_sha256': hashlib.sha256(mod['samples'][identifier - 1]['data']).hexdigest(),
                           'decimated_bank_sha256': hashlib.sha256(values.tobytes()).hexdigest(),
                           'kind': 'reused one-shot source bank; native fractional pitch and volume LUT'})
            asset_ids[key] = asset_id
        page = bytes(range(256))
        if native_gain:
            lut = np.clip(np.rint(128 + (np.arange(256) - 128) * 127 / preset['pcm_base_scale'] * volume / 64),
                          0, 255).astype(np.uint8)
            page = lut.tobytes()
            ideal = np.clip(np.rint(128 + filtered[identifier] * 127 * volume / 64), 0, 255).astype(np.int16)
            raw = np.frombuffer(assets[asset_ids[key]]['data'][:len(ideal)], np.uint8)
            delta = lut[raw].astype(np.int16) - ideal
            quantization[f'{identifier}:{volume}'] = {'peak_code_error': int(np.max(abs(delta))),
                                                     'rms_code_error': float(np.sqrt(np.mean(delta.astype(float) ** 2))),
                                                     'minimum_final_code': int(lut[raw].min()),
                                                     'maximum_final_code': int(lut[raw].max())}
        if page not in page_ids:
            page_ids[page] = len(pages); pages.append(page)
        return asset_ids[key], page_ids[page], preset.get('decimation', preset.get('pcm_decimation'))

    rows, descriptors, expected, omissions = [], [], bytearray(), []
    previous_channel, position = None, 0
    max_step, held_pitch_changes, last_step = 0, [], 0
    used = Counter()
    for index, (tick, sid, count, route) in enumerate(zip(ticks, sid_rows, counts, routes)):
        source_channel = (1 if tick['channels'][1]['playing_sample'] else
                          0 if index < START_TICK and tick['channels'][0]['playing_sample'] == 11 else None)
        if source_channel is None:
            asset_id, lut_id, step = 0, 0, 0
            reset = int(previous_channel is not None)
            position = 0
        else:
            state = tick['channels'][source_channel]
            identifier = state['playing_sample']
            if identifier not in (7, 8, 9, 11, 17) or not state['period']:
                raise ValueError('Unsupported full Cream sampled source role')
            if state.get('offset', 0) or state.get('loop_sample', identifier) not in (0, identifier):
                raise ValueError('Full Cream sampled offsets/loop changes require explicit support')
            if mod['samples'][identifier - 1]['loop_length'] > 2:
                raise ValueError('Full Cream PCM lane requires one-shot source banks')
            asset_id, lut_id, divisor = bank(identifier, state['volume'])
            step = round(PAULA / state['period'] / divisor / RATE * 256)
            if not 1 <= step <= 65535:
                raise ValueError('Full Cream fractional step exceeds 16 bits')
            if source_channel != previous_channel and not state['trigger']:
                raise ValueError('A Cream PCM handoff must coincide with the source note trigger')
            reset = int(state['trigger'])
            if reset:
                position = 0
            elif source_channel == previous_channel and step != last_step:
                held_pitch_changes.append(index)
            route['pcm'] = source_channel + 1
            used[(source_channel + 1, identifier)] += 1
        max_step = max(max_step, step)
        asset = assets[asset_id]
        # Independent logical Q8 cursor: source bytes are read before advance.
        # Gain changes leave position/fraction intact; held pitch changes only
        # change the increment. Ended one-shots return the neutral 128 value.
        indices = (position + np.arange(count, dtype=np.int64) * step) >> 8
        block = np.full(count, 128, dtype=np.uint8)
        valid = indices < asset['logical_bytes']
        values = np.frombuffer(asset['data'], np.uint8)
        lut = np.frombuffer(pages[lut_id], np.uint8)
        block[valid] = lut[values[indices[valid]]]
        expected.extend(block.tobytes()); position += count * step
        pulse_width = presets[10]['pulse_width']
        physical = [sid[0], sid[1], sid[2], pulse_width & 255, pulse_width >> 8, 1,
                    sid[3], sid[4], sid[5], pulse_width & 255 if sid[5] == 65 else 0,
                    pulse_width >> 8 if sid[5] == 65 else 8, 1]
        tail = [step & 255, step >> 8, lut_id, reset, asset_id, 0, 0, 0, 0, 0, reset, 0]
        rows.append(physical + tail)
        if sid[1] > 127:
            raise ValueError('Full Cream SID1 frequency exceeds its validated 15-bit descriptor')
        descriptors.append([sid[0], sid[1] << 1 | 1, sid[2], physical[3], physical[4], 16,
                            sid[3], sid[4], sid[5], physical[9], physical[10], 16] + tail)
        assigned = {route['sid1'], route['sid2']} | ({source_channel + 1} if source_channel is not None else set())
        missed = [ch for ch, state in enumerate(tick['channels'], 1)
                  if state['playing_sample'] and state['volume'] and ch not in assigned]
        if missed:
            omissions.append({'tick': index, 'channels': missed,
                              'instruments': [tick['channels'][ch - 1]['playing_sample'] for ch in missed]})
        previous_channel, last_step = source_channel, step
    if math.ceil(157 * max_step / 256) > 256:
        raise ValueError('Full Cream bank guards are shorter than the maximum sampled block advance')
    if len(pages) > 96:
        raise ValueError('Full Cream gain pages exhaust the low asset arena')
    expected = bytes(expected)
    sid_programs_asm = _emit_full_sid(out)
    for asset in assets:
        path = out / f'pcm-{asset["id"]:03d}.bin'
        path.write_bytes(asset['data']); asset['file'] = str(path)
        if asset['id']:
            asset['asm_file'] = str(_emit_bank_asm(out, asset))
    (out / 'expected-input.bin').write_bytes(expected)
    (out / 'semantic-rows.bin').write_bytes(bytes(value for row in rows for value in row))
    (out / 'score-rows.bin').write_bytes(bytes(value for row in descriptors for value in row))
    report = {'source_sha256': mod['sha256'], 'source_range_s': [0, len(ticks) / 50],
              'source_tick_range': [0, len(ticks)], 'ticks': len(ticks), 'duration_s': len(ticks) / 50,
              'original_source_ticks': len(ticks), 'native_rate_hz': RATE,
              'frame_sample_counts': dict(Counter(counts)), 'pcm_cursor_kind': 'fractional-q8',
              'pcm_bank_bytes_including_guards': sum(len(a['data']) for a in assets),
              'gain_LUT_pages': len(pages), 'gain_LUT_bytes': len(pages) * 256,
              'maximum_Q8_step': max_step, 'held_pitch_change_ticks': held_pitch_changes,
              'approved_PCM_banks_and_Q8_quantization_preserved': True,
              'approved_ordinary_states_preserved': True, 'sid': sid_report,
              'new_PCM_gain_LUT_quantization': quantization,
              'expected_input_sha256': hashlib.sha256(expected).hexdigest(),
              'source_routes': {'SID1': 'C3', 'SID2': 'C4, plus C1 pulse introduction while C4 is idle',
                                'SID3': 'C2, plus C1 geioilsound introduction while C2 is idle'},
              'omissions': 'C1 is omitted when no free physical voice remains; the introduction uses its prominent passages.',
              'approximations': ['SID1/SID2 use quiet native pulse/triangle/noise programs.',
                                 'Looped chords are 50 Hz major/minor/sus4 note arpeggios, not simultaneous partials.',
                                 'New 11/17 PCM gains use integer volume LUTs; measured code error is reported.'],
              'scope': 'Complete pinned source traversal; exact approved bank data and ordinary states are preserved. Global sample-clock phase differs from the isolated 26.88s preview. Perceived quality remains a listening decision.'}
    support.save(out / 'report.json', report)
    support.save(out / 'assets.json', {'assets': [{k: v for k, v in a.items() if k != 'data'} for a in assets]})
    support.save(out / 'routing.json', {'routes': routes, 'omissions': omissions})
    return {'rows': rows, 'score_rows': descriptors, 'sid_programs_asm': sid_programs_asm,
            'assets': assets, 'triangle_pages': pages, 'triangle_silence_index': 0,
            'ticks': ticks, 'frame_sample_counts_exact': counts, 'source': source,
            'report': report, 'expected_input': expected, 'pcm_cursor_kind': 'fractional-q8'}


def prepare(out: Path, *, full: bool = False) -> dict:
    """Return the shared 24-byte score contract with independent exact PCM proof."""
    if full:
        return _prepare_full(Path(out))
    out = Path(out).resolve(); out.mkdir(parents=True, exist_ok=True)
    presets = _recipes()
    source = json.loads((HERE.parent / 'mod-hybrid/sources/cream-of-the-earth.source.json').read_text())
    mod = support.source_mod(source, out)
    all_ticks = support.build_timeline(mod)['ticks']
    if len(all_ticks) != 12096 or any(abs(t['duration_s'] - .02) > 1e-9 for t in all_ticks):
        raise ValueError('Expected the pinned complete 50 Hz Cream timeline')
    ticks = all_ticks[START_TICK:END_TICK]
    if len(ticks) != 1344 or not ticks[0]['channels'][1]['trigger']:
        raise ValueError('Cream passage must start at the approved source note')
    sid_rows, sid_report = _sid_rows(mod, all_ticks, presets)
    counts = [(i * CLOCK + PERIOD * 25) // (PERIOD * 50) for i in range(len(ticks) + 1)]
    counts = [high - low for low, high in zip(counts, counts[1:])]

    # Recreate the accepted low-pass decimation/quantization before compiling
    # each fixed pitch. The hashes pin reusable instrument data, not a song WAV.
    originals = {}
    for identifier in (7, 8, 9):
        preset, sample = presets[identifier], mod['samples'][identifier - 1]
        if sample['loop_length'] > 2:
            raise ValueError('Cream approved PCM instruments must remain one-shots')
        raw = np.frombuffer(sample['data'], np.int8).astype(float) / 128
        filtered = resample_poly(raw, 1, preset['decimation'])
        values = np.clip(np.rint(128 + filtered * 127 * preset['volume'] / 64), 0, 255).astype(np.uint8)
        values = np.pad(values, (0, (-len(values)) % 256), constant_values=128)
        if len(values) != preset['bytes'] or hashlib.sha256(values.tobytes()).hexdigest() != preset['sha256']:
            raise ValueError(f'Cream instrument{identifier} differs from the approved reusable bank')
        originals[identifier] = values

    assets = [{'id': 0, 'instrument': 0, 'period': 0, 'gain': 0,
               'data': bytes([113] * 313), 'logical_bytes': 157, 'loop_offset': 0}]
    asset_ids = {}
    for tick in ticks:
        state = tick['channels'][1]
        identifier, period = state['playing_sample'], state['period']
        key = identifier, period
        if key in asset_ids:
            continue
        if identifier not in originals or not period:
            raise ValueError('Unexpected Cream sampled instrument or pitch')
        preset, original = presets[identifier], originals[identifier]
        step = round(PAULA / period / preset['decimation'] / RATE * 256)
        if not 1 <= step <= 255:
            raise ValueError('Cream Q8 pitch step exceeds the approved cursor range')
        length = math.ceil(len(original) * 256 / step)
        indices = np.arange(length, dtype=np.int64) * step >> 8
        fixed = original[indices].astype(np.int16) - 15
        if fixed.min() < 0 or fixed.max() + 15 > 255:
            raise ValueError('Cream PCM cannot fit neutral-triangle headroom without change')
        bank = fixed.astype(np.uint8).tobytes()
        asset_id = len(assets)
        assets.append({'id': asset_id, 'instrument': identifier, 'period': period,
                       'gain': preset['volume'], 'data': bank + bytes([113] * 156),
                       'logical_bytes': len(bank), 'loop_offset': 0,
                       'accepted_Q8_step': step,
                       'source_sha256': hashlib.sha256(mod['samples'][identifier - 1]['data']).hexdigest(),
                       'accepted_decimated_sha256': preset['sha256'],
                       'kind': 'reused one-shot instrument/pitch bank; exact accepted Q8 reads'})
        asset_ids[key] = asset_id

    # SID1 needs its second descriptor byte for the continuous-envelope flag.
    # SID2 stores direct frequencies, avoiding a dictionary bound for sweeps.
    words = sorted({row[0] | row[1] << 8 for row in sid_rows})
    if len(words) > 256:
        raise ValueError('Cream melody frequency dictionary exceeds 256 entries')
    dictionary = {word: index for index, word in enumerate(words)}
    rows, descriptors, expected = [], [], bytearray()
    previous = None; position = 0
    for tick, sid, count in zip(ticks, sid_rows, counts):
        state = tick['channels'][1]
        identifier, period = state['playing_sample'], state['period']
        key = identifier, period
        if state.get('offset', 0) or state.get('loop_sample', identifier) not in (0, identifier):
            raise ValueError('Cream approved sample lane has no offsets or loop-target changes')
        if state['volume'] != presets[identifier]['volume']:
            raise ValueError('Cream sample gain changed from its accepted constant value')
        if state['trigger']:
            position = 0
        elif previous != key:
            raise ValueError('Held Cream pitch changes need a phase-preserving native cursor')
        asset_id = asset_ids[key]
        asset = assets[asset_id]
        # Independent logical Q8 replay reads the original decimated bank.
        indices = (position + np.arange(count, dtype=np.int64)) * asset['accepted_Q8_step'] >> 8
        block = np.full(count, 128, dtype=np.uint8)
        valid = indices < len(originals[identifier])
        block[valid] = originals[identifier][indices[valid]]
        expected.extend(block.tobytes()); position += count
        pulse_width = presets[10]['pulse_width']
        physical = [sid[0], sid[1], sid[2], pulse_width & 255, pulse_width >> 8, 1,
                    sid[3], sid[4], sid[5], 0, 8, 1]
        tail = [0, 0, 0, 0, asset_id, 0, 0, 0, 0, 0, int(state['trigger']), 0]
        rows.append(physical + tail)
        sid1 = [dictionary[sid[0] | sid[1] << 8], 1, sid[2], pulse_width & 255, pulse_width >> 8, 16]
        sid2 = [sid[3], sid[4], sid[5], 0, 8, 16]
        descriptors.append(sid1 + sid2 + tail)
        previous = key

    expected = bytes(expected)
    if hashlib.sha256(expected).hexdigest() != APPROVED_PCM_SHA256:
        raise ValueError('Cream independent PCM replay differs from the accepted sample stream')
    # Exercise the actual integer-cursor bank contract independently of Q8.
    model = {'rows': rows, 'assets': assets, 'triangle_pages': [bytes([15] * 256)],
             'frame_sample_counts_exact': counts}
    from full_length_instruments import expected_input as native_model
    if native_model(model) != expected:
        raise ValueError('Cream fixed banks changed accepted Q8 playback values')
    sid_programs_asm = _emit_sid(out, words)
    for asset in assets:
        path = out / f'pcm-{asset["id"]:03d}.bin'
        path.write_bytes(asset['data']); asset['file'] = str(path)
        if asset['id']:
            asset['asm_file'] = str(_emit_bank_asm(out, asset))
    (out / 'expected-input.bin').write_bytes(expected)
    (out / 'semantic-rows.bin').write_bytes(bytes(value for row in rows for value in row))
    (out / 'score-rows.bin').write_bytes(bytes(value for row in descriptors for value in row))
    report = {'source_sha256': mod['sha256'], 'source_range_s': [START, END],
              'source_tick_range': [START_TICK, END_TICK], 'ticks': len(ticks),
              'duration_s': len(ticks) / 50, 'original_source_ticks': len(all_ticks),
              'native_rate_hz': RATE, 'frame_sample_counts': dict(Counter(counts)),
              'pcm_bank_bytes_including_guards': sum(len(a['data']) for a in assets),
              'reused_instrument_pitch_banks': len(asset_ids), 'melody_frequency_dictionary_entries': len(words),
              'source_channels': {'SID1': 3, 'SID2': 4, 'SID3_PCM': 2, 'omitted': [1]},
              'omissions': 'Original C1 chords omitted, matching the user-approved three-channel reference.',
              'approximations': ['C3 electronic guitar uses the accepted pulse program.',
                                 'C4 drums use the accepted triangle/noise programs.'],
              'sid': sid_report, 'expected_input_sha256': hashlib.sha256(expected).hexdigest(),
              'all_PCM_values_match_approved_reference': True,
              'all_ordinary_frequency_control_states_match_approved_reference': True,
              'scope': 'Native data correctness for the same approved source passage. Actual SID event phases differ from the old runtime; this does not claim bit-identical analogue audio.'}
    support.save(out / 'report.json', report)
    support.save(out / 'assets.json', {'assets': [{k: v for k, v in a.items() if k != 'data'} for a in assets]})
    support.save(out / 'routing.json', {'routes': [{'tick': i, 'time_s': i / 50, 'source_time_s': START + i / 50,
                                                  'sid1': 3, 'sid2': 4, 'pcm': 2} for i in range(len(ticks))],
                                      'omissions': [{'tick': i, 'channels': [1],
                                                     'instruments': [t['channels'][0]['playing_sample']]}
                                                    for i, t in enumerate(ticks) if t['channels'][0]['volume']]})
    return {'rows': rows, 'score_rows': descriptors, 'sid_programs_asm': sid_programs_asm,
            'assets': assets, 'triangle_pages': model['triangle_pages'],
            'triangle_silence_index': 0, 'ticks': ticks, 'frame_sample_counts_exact': counts,
            'source': source, 'report': report, 'expected_input': expected}


def expected_input(prepared: dict) -> bytes:
    """Return the independently validated logical Q8 source replay."""
    return prepared['expected_input']
