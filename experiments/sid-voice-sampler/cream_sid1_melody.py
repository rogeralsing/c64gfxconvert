"""Prepare a narrowly scoped, explicitly unapproved Cream SID1 candidate.

The original C1 figure is restored only at 17.92..31.36 seconds. All other
passages retain C3. This module changes native SID1 descriptors only; it does
not rewrite either sampler's note stream, instruments, gain or clock.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import cream_instruments as cream

SOURCE_CUT_TICK = 9408
C1_START_TICK, C1_END_TICK = 896, 1568
RECIPE = Path(__file__).resolve().parent / 'native_instruments/cream_sid1/voice.json'


def profile() -> dict:
    """Read the separately reviewable native instrument program parameters."""
    selected = json.loads(RECIPE.read_text())['profile']
    selected['controls'] = {int(identifier): control for identifier, control in selected['controls'].items()}
    return selected


def _digest(rows: list, start: int, stop: int | None = None) -> str:
    return hashlib.sha256(bytes(value for row in rows for value in row[start:stop])).hexdigest()


def _check_rows(rows: list, name: str) -> None:
    if any(len(row) != 24 or any(type(value) is not int or not 0 <= value <= 255
                                for value in row) for row in rows):
        raise ValueError(f'{name} requires complete 24-byte native descriptors')


def _triggers(ticks: list, channel: int, first: int, last: int) -> list[dict]:
    result = []
    for index in range(first, last):
        state = ticks[index]['channels'][channel]
        if state['trigger']:
            result.append({'tick': index, 'time_s': ticks[index]['time_s'],
                           'instrument': state['playing_sample'],
                           'period': state['period'], 'volume': state['volume']})
    return result


def apply(mod: dict, ticks: list, semantic: list, score_rows: list, *,
          sustain: int, pulse_width: int,
          controls: dict[int, int] | None = None,
          articulation: bool = False, release: int = 0,
          pre_note_ticks: int = 1) -> dict:
    """Change only SID1's six fields and return the complete change receipt.

    ``ticks`` is the original full source timeline, not the drained selection.
    ``semantic`` stores plain frequency high and a sustain nibble; the score
    stores packed high/continuous-GATE and the physical SR byte. Parameters
    select a candidate, rather than asserting any listening approval.
    """
    if type(sustain) is not int or not 1 <= sustain <= 15:
        raise ValueError('The continuous SID1 candidate requires sustain 1..15')
    if type(pulse_width) is not int or not 1 <= pulse_width <= 4095:
        raise ValueError('SID1 pulse width must be 1..4095')
    if type(articulation) is not bool:
        raise ValueError('SID1 articulation must be a boolean')
    if type(release) is not int or not 0 <= release <= 15:
        raise ValueError('SID1 release must be a nibble 0..15')
    if type(pre_note_ticks) is not int or not 1 <= pre_note_ticks <= 2:
        raise ValueError('SID1 preparation requires one or two explicit ticks')
    if articulation and pre_note_ticks == 2 and release != 0:
        raise ValueError('The two-tick hard restart requires the fastest release')
    if len(semantic) != len(score_rows) or not semantic:
        raise ValueError('SID1 semantic and score rows must have equal nonzero lengths')
    _check_rows(semantic, 'Semantic rows')
    _check_rows(score_rows, 'Score rows')
    selected_ticks = min(len(semantic), SOURCE_CUT_TICK)
    if len(ticks) < selected_ticks:
        raise ValueError('Original source timeline is shorter than the selected notes')

    old_tails = {'semantic': _digest(semantic, 6), 'score': _digest(score_rows, 6)}
    old_sid1 = {'semantic': _digest(semantic, 0, 6), 'score': _digest(score_rows, 0, 6)}
    old_sampler_fields = [(row[6:].copy(), packed[6:].copy())
                          for row, packed in zip(semantic, score_rows)]
    presets = deepcopy(cream._recipes(full=True))
    for raw_identifier, control in (controls or {}).items():
        if type(raw_identifier) not in (int, str):
            raise ValueError('SID1 instrument identifiers must be integers or JSON integer keys')
        identifier = int(raw_identifier)
        if identifier not in presets or type(control) is not int or not 0 <= control <= 255:
            raise ValueError('SID1 control overrides require known instruments and byte values')
        if control & 9 != 1:
            raise ValueError('Active SID1 controls must retain GATE and clear TEST')
        recipe = presets[identifier].get('sid_role', presets[identifier])
        field = 'noise_control' if recipe['program'] == 'noise' else 'control'
        recipe[field] = control

    channels = [0 if C1_START_TICK <= index < C1_END_TICK else 2
                for index in range(len(ticks))]
    native, _, source_report = cream._full_sid_rows(
        mod, ticks, presets, sid1_channels=channels)
    partials = []
    for index in range(selected_ticks):
        low, high, control = native[index][:3]
        if high > 127:
            raise ValueError(f'SID1 pitch exceeds the packed 15-bit descriptor at tick {index}')
        partials.append([low, high, control])
    # The drained tail must not start the next pattern's poly note. It retains
    # the selected ending's existing TEST rest and the constant native envelope.
    if len(semantic) > SOURCE_CUT_TICK and partials[-1] != [0, 0, 25]:
        raise ValueError('The selected SID1 ending must already be a zero-frequency TEST rest')
    partials.extend([partials[-1].copy() for _ in range(len(semantic) - selected_ticks)])
    source_channels = [channel + 1 for channel in channels[:selected_ticks]]
    source_channels.extend([source_channels[-1]] * (len(semantic) - selected_ticks))
    gate_off_ticks = []
    gate_off_events = []
    rest_gate_off_count = 0
    if articulation:
        for partial in partials:
            if partial[2] == 25:
                partial[2] = 24
                rest_gate_off_count += 1
        for index in range(1, selected_ticks):
            state = ticks[index]['channels'][channels[index]]
            route_change = channels[index] != channels[index - 1]
            if not state['trigger'] and not route_change:
                continue
            for previous in range(max(0, index - pre_note_ticks), index):
                if ticks[previous]['channels'][channels[previous]]['trigger']:
                    raise ValueError('SID1 notes are too close for the declared hard restart')
                previous_control = partials[previous][2]
                if previous_control & 9 == 1:
                    # Keep pitch and waveform. Two ticks with release 0 also
                    # cover the SID's approximately 33 ms rate-counter wrap,
                    # followed by its fastest release, before the new attack.
                    partials[previous][2] &= 254
                    gate_off_ticks.append(previous)
                    gate_off_events.append({'gate_off_tick': previous,
                                            'note_tick': index,
                                            'source_trigger': bool(state['trigger']),
                                            'route_change': route_change})
    physical_sr = sustain << 4 | release
    for row, packed, (low, high, control) in zip(semantic, score_rows, partials):
        row[:6] = [low, high, control, pulse_width & 255, pulse_width >> 8, sustain]
        packed[:6] = [low, high << 1 | 1, control,
                      pulse_width & 255, pulse_width >> 8, physical_sr]

    if any(row[6:] != before_semantic or packed[6:] != before_score
           for row, packed, (before_semantic, before_score)
           in zip(semantic, score_rows, old_sampler_fields)):
        raise ValueError('The SID1 candidate changed another voice descriptor')
    new_tails = {'semantic': _digest(semantic, 6), 'score': _digest(score_rows, 6)}
    if new_tails != old_tails:
        raise ValueError('The SID1 candidate changed SID2/SID3 fields')

    first, last = min(C1_START_TICK, selected_ticks), min(C1_END_TICK, selected_ticks)
    restored = _triggers(ticks, 0, first, last)
    dropped = _triggers(ticks, 2, first, last)
    routes = []
    for index, channel in enumerate(channels[:selected_ticks]):
        if routes and routes[-1]['source_channel'] == channel + 1:
            routes[-1]['end_tick_exclusive'] = index + 1
            routes[-1]['end_s'] = (index + 1) / 50
        else:
            routes.append({'start_tick': index, 'end_tick_exclusive': index + 1,
                           'start_s': index / 50, 'end_s': (index + 1) / 50,
                           'source_channel': channel + 1})
    limitations = [
        'C1 instrument 11 has a prominent fifth component; a single native root waveform does not reproduce it.',
        'Restoring C1 at 17.92..31.36 omits C3 tonic/octave accents in that interval.',
        'Later C1 chords remain omitted; no break-chord reassignment is included.',
        'Nonzero MOD volume slides and recorded sample envelopes are not reproduced exactly.',
        'Digital descriptor preservation is not listening approval or physical SID verification.']
    if articulation:
        limitations.append(
            f'Each source trigger or route handoff may shorten the preceding gated note by {pre_note_ticks * 20} ms; hardware ADSR is an approximation, not the MOD sample envelope.')
    else:
        limitations.append('Nonzero source volume retains the earlier flat on/off policy.')
    return {'status': 'Unapproved SID1 arrangement and native-instrument candidate',
            'scope': 'Only the six native SID1 descriptor fields are changed.',
            'routes': routes, 'source_channels_per_tick': source_channels,
            'drain_ticks': len(semantic) - selected_ticks,
            'drain_admits_new_notes': False,
            'native_program': {'pulse_width': pulse_width, 'sustain': sustain,
                               'release': release, 'physical_SR': physical_sr,
                               'continuous_GATE': not articulation,
                               'controls': dict(controls or {})},
            'articulation': {'enabled': articulation,
                             'rest_control': 24 if articulation else 25,
                             'rest_gate_off_tick_count': rest_gate_off_count,
                             'pre_note_gate_off_ticks': gate_off_ticks,
                             'pre_note_gate_off_count': len(gate_off_ticks),
                             'pre_note_gate_off_events': gate_off_events,
                             'gate_off_duration_s': pre_note_ticks / 50 if articulation else 0,
                             'pre_note_ticks': pre_note_ticks if articulation else 0,
                             'rules': ('TEST rests clear GATE. Before each selected real source trigger or route change, '
                                       'clear only the preceding active control GATE, retaining its frequency and waveform. '
                                       'Volume changes alone do not insert an extra pre-note gate edge. '
                                       'The next natural GATE rise restarts hardware attack.'
                                       if articulation else 'Retain continuous GATE through TEST rests.')},
            'restored_C1_triggers': restored,
            'restored_C1_trigger_count': len(restored),
            'restored_C1_instruments': dict(Counter(item['instrument'] for item in restored)),
            'omitted_C3_triggers': dropped,
            'omitted_C3_trigger_count': len(dropped),
            'omitted_C3_instruments': dict(Counter(item['instrument'] for item in dropped)),
            'old_SID1_fields_sha256': old_sid1,
            'new_SID1_fields_sha256': {'semantic': _digest(semantic, 0, 6),
                                      'score': _digest(score_rows, 0, 6)},
            'new_frequency_control_sha256': hashlib.sha256(
                bytes(value for row in partials for value in row)).hexdigest(),
            'non_SID1_fields_sha256_before': old_tails,
            'non_SID1_fields_sha256_after': new_tails,
            'non_SID1_fields_byte_identical': True,
            'pitch_roots_source_samples': source_report['roots_source_samples'],
            'limitations': limitations}
