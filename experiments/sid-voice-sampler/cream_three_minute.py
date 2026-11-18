"""A stock-RAM Cream arrangement with two native oscillator sample lanes.

Notes stop at the phrase boundary at 188.16 seconds. Existing one-shots drain
until 188.42 seconds; no following pattern is started. The earlier players and
listening references are inputs for regression checks, never overwritten here.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

import cream_instruments as cream
import cream_playback
import full_length_playback as playback
import full_length_score as score
import native_support as support

HERE = Path(__file__).resolve().parent
CUT_TICK, FRAMES = 9408, 9421
HISTORY_BYTES = 512
COLD_DELAY_CYCLES = 95085
SID1_COLD_DELAY_CYCLES = 149808
MODES = {'all': (True, True, True), 'sid-1': (True, False, False),
         'sid-2': (False, True, False), 'sid-3': (False, False, True),
         'muted': (False, False, False)}


class Layout:
    """Allocate only RAM visible while SID I/O remains mapped."""

    def __init__(self, low: int):
        self.free = [[low, 0x7000], [0x8000, 0xc000]]
        self.segments = []

    def add(self, data: bytes, name: str, alignment: int = 1) -> int:
        for span in self.free:
            first = (span[0] + alignment - 1) // alignment * alignment
            if first + len(data) <= span[1]:
                self.segments.append((first, data, name))
                span[0] = first + len(data)
                return first
        raise ValueError(f"Stock C64 RAM cannot fit {name}: {len(data)} bytes; free={self.free}")


def _sid3_model(rows: list, counts: list, assets: list, gains: list) -> tuple[bytes, list]:
    """Independent logical Q8 replay, including the held pitch changes."""
    expected, fractions = bytearray(), []
    position = 0
    for row, count in zip(rows, counts):
        if row[22] or row[15]:
            position = 0
        fractions.append(position & 255)
        step = row[12] | row[13] << 8
        bank = assets[row[16]]
        indices = (position + np.arange(count, dtype=np.int64) * step) >> 8
        valid = indices < bank['logical_bytes']
        values = np.full(count, 128, dtype=np.uint8)
        lut = np.frombuffer(gains[row[14]], np.uint8)
        raw = np.frombuffer(bank['data'], np.uint8)
        values[valid] = lut[raw[indices[valid]]]
        expected.extend(values.tobytes())
        position += count * step
    return bytes(expected), fractions


def _sid2(mod: dict, ticks: list, cuts: list) -> dict:
    """Compile reusable source-instrument windows and a separate note track.

    Each bank is keyed by original instrument, period and gain. Its stored
    extent is the union of positions required across all uses, never mixed
    song audio. Gain changes retain the note's elapsed output position.
    """
    banks, extents, events, expected = {}, {}, [], bytearray()
    elapsed, previous_channel, generation = 0, None, 0
    used_channels = Counter()
    for index, tick in enumerate(ticks):
        channel = (0 if index < 672 and tick['channels'][0]['playing_sample'] == 10
                   and not tick['channels'][3]['playing_sample'] else 3)
        state = tick['channels'][channel]
        identifier, period, volume = (state[k] for k in ('playing_sample', 'period', 'volume'))
        if state['trigger'] or channel != previous_channel:
            elapsed = 0
            generation += 1
        first = max(4, (cuts[index] + 3) // 4 * 4)
        count = len(range(first, cuts[index + 1], 4))
        key = None
        valid = 0
        if identifier and period and volume:
            if state.get('offset', 0) or mod['samples'][identifier - 1]['loop_length'] > 2:
                raise ValueError('The selected SID2 track requires one-shot instruments without offsets')
            key = identifier, period, volume
            if key not in banks:
                sample = mod['samples'][identifier - 1]
                raw = np.frombuffer(sample['data'], np.int8).astype(float) / 128
                ratio = Fraction(support.CLOCK * period / (504 * support.PAULA)).limit_denominator(20000)
                filtered = resample_poly(raw, ratio.numerator, ratio.denominator)
                virtual = np.clip(np.rint(128 + filtered * 127 * volume / 64), 0, 255).astype(np.uint8)
                banks[key] = np.rint(virtual.astype(float) * 105 / 249).astype(np.uint8).tobytes()
            raw_bank = banks[key]
            valid = min(count, max(0, len(raw_bank) - elapsed))
            if valid:
                extents.setdefault(key, []).append((elapsed, elapsed + valid))
                expected.extend(raw_bank[elapsed:elapsed + valid])
                used_channels[channel + 1] += valid
            else:
                key = None
        expected.extend(bytes([54] * (count - valid)))
        # Keep complete source-note intervals together, including ended tails.
        if (events and events[-1]['key'] == key and
                (key is None or events[-1]['generation'] == generation
                 and events[-1]['start'] + events[-1]['count'] == elapsed)):
            events[-1]['count'] += count
        else:
            events.append({'key': key, 'start': elapsed, 'count': count, 'generation': generation})
        elapsed += count
        previous_channel = channel

    # Coalesce overlapping source-position ranges, but do not store unused gaps.
    windows = []
    for key, intervals in extents.items():
        merged = []
        for first, last in sorted(intervals):
            if merged and first <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], last)
            else:
                merged.append([first, last])
        for first, last in merged:
            windows.append({'key': key, 'first': first, 'last': last,
                            'data': banks[key][first:last]})
    return {'windows': windows, 'events': events, 'expected': bytes(expected),
            'source_channel_values': dict(used_channels)}


def _score(rows: list, out: Path, address: int) -> dict:
    """Keep the existing score format with a smaller, exact native history."""
    old_size = score.HISTORY_BYTES
    try:
        score.HISTORY_BYTES = HISTORY_BYTES
        packed = score.prepare(rows, out, address)
    finally:
        score.HISTORY_BYTES = old_size
    native = (HERE / 'full-length-score.asm').read_text()
    pattern = 'and #$0f\n    ora #$e0'
    if native.count(pattern) != 5:
        raise ValueError('Unexpected native history-wrap sites')
    native = native.replace(pattern, 'and #$01\n    ora #$e0')
    target = out / 'score-decoder.asm'
    target.write_text(native)
    wrapper = Path(packed['score_asm'])
    wrapper.write_text(wrapper.read_text().replace(str(HERE / 'full-length-score.asm'), str(target)))
    packed.update(history_bytes=HISTORY_BYTES, history_range=[0xe000, 0xe200],
                  native_code_source=str(target), native_code_sha256=support.digest(target))
    support.save(out / 'score.json', packed)
    return packed


def prepare(out: Path, *, sid1_profile: dict | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    original = cream.prepare(out / 'source-model', full=True)
    mod = support.source_mod(original['source'], out)
    ticks = original['ticks'][:CUT_TICK]
    # Drain existing one-shots; no event from the next pattern is admitted.
    for index in range(CUT_TICK, FRAMES):
        previous = ticks[-1]
        ticks.append({**previous, 'time_s': index / 50,
                      'channels': [{**c, 'trigger': False} for c in previous['channels']]})
    cuts = [(i * support.CLOCK + support.PERIOD * 25) // (support.PERIOD * 50)
            for i in range(FRAMES + 1)]
    counts = [high - low for low, high in zip(cuts, cuts[1:])]
    rows = [r.copy() for r in original['score_rows'][:CUT_TICK]]
    semantic = [r.copy() for r in original['rows'][:CUT_TICK]]
    if semantic[-1][2] != 25:
        raise ValueError('The chosen ending must already rest the approved SID1 melody')
    for _ in range(CUT_TICK, FRAMES):
        for destination in (rows, semantic):
            row = destination[-1].copy()
            row[15] = row[22] = row[23] = 0
            destination.append(row)
    sid1_arrangement = None
    if sid1_profile is not None:
        from cream_sid1_melody import apply
        sid1_arrangement = apply(mod, original['ticks'], semantic, rows,
                                 **{key: value for key, value in sid1_profile.items()
                                    if key != 'attack_decay'})
    expected3, fractions = _sid3_model(semantic, counts, original['assets'], original['triangle_pages'])
    if expected3[:cuts[CUT_TICK]] != original['expected_input'][:cuts[CUT_TICK]]:
        raise ValueError('The three-minute selection changed existing SID3 samples')
    if sid1_profile is not None and hashlib.sha256(expected3).hexdigest() != '82c8fc0e92cea621b53ab4ff0725c92705b640637b29b3577f7f65f67f105e88':
        raise ValueError('The SID1 repair changed the frozen complete SID3 input')
    steps = sorted({r[12] | r[13] << 8 for r in rows})
    gains = sorted({r[14] for r in rows})
    if gains[0] != 0 or any(original['triangle_pages'][i][128] != 128 for i in gains):
        raise ValueError('The fast PCM backend requires identity page zero and neutral-preserving gains')
    layout = Layout(0x1000 + len(gains) * 256)
    for page, old in enumerate(gains):
        layout.segments.append((0x1000 + page * 256, original['triangle_pages'][old], f'gain-{old}'))
    gain_pages = {old: 0x10 + index for index, old in enumerate(gains)}
    table_pages = {}
    commands = bytearray()
    for index, step in enumerate(steps):
        page = 0xe2 + index if index < 14 else layout.add(bytes(256), f'offset-{step}', 256) >> 8
        table_pages[step] = page
        commands.extend((step & 255, step >> 8, page))
    assets, addresses = original['assets'], {}
    trimmed = {}
    for asset in sorted(assets, key=lambda a: -len(a['data'])):
        if asset['id'] == 0:
            logical, data = 256, bytes([128] * 256)
        else:
            recipe = cream._recipes(full=True)[asset['instrument']]
            divisor = recipe.get('decimation', recipe.get('pcm_decimation'))
            logical = math.ceil(mod['samples'][asset['instrument'] - 1]['length'] / divisor)
            if set(asset['data'][logical:]) - {128}:
                raise ValueError('Only neutral source-bank padding may be removed')
            data = asset['data'][:logical] + bytes([128] * 200)
        trimmed[asset['id']] = dict(asset, data=data, logical_bytes=logical)
        addresses[asset['id']] = layout.add(data, f'pcm-{asset["id"]}')

    sid2 = _sid2(mod, ticks, cuts)
    if sid1_profile is not None and hashlib.sha256(sid2['expected']).hexdigest() != '91b49e6b4f64f1b99b1a17b2c92564566e9482f7bc015a2d305aef7d9fa60e1c':
        raise ValueError('The SID1 repair changed the frozen complete SID2 input')
    for index, window in enumerate(sorted(sid2['windows'], key=lambda w: -len(w['data']))):
        window['address'] = layout.add(window['data'], f'sid2-{index}')
    descriptors, descriptor_ids, event_stream = [], {}, bytearray()
    for event in sid2['events']:
        if not event['count']:
            continue
        if event['key'] is None:
            pointer, end = 0, 0
        else:
            matches = [w for w in sid2['windows'] if w['key'] == event['key']
                       and w['first'] <= event['start'] < w['last']]
            if len(matches) != 1:
                raise ValueError(f'No unique reusable SID2 source extent for {event}')
            window = matches[0]
            pointer = window['address'] + event['start'] - window['first']
            end = window['address'] + len(window['data'])
        key = pointer, end
        if key not in descriptor_ids:
            descriptor_ids[key] = len(descriptors)
            descriptors.append(key)
        left = event['count']
        while left:
            count = min(left, 65535)
            event_stream.extend(count.to_bytes(2, 'little'))
            event_stream.append(descriptor_ids[key])
            left -= count
            if left and pointer < end:
                raise ValueError('A very long active SID2 event needs an explicit cursor continuation')
    event_stream.extend(b'\0\0')
    if len(descriptors) > 256:
        raise ValueError('The SID2 event dictionary exceeds 256 reusable descriptors')
    labels = {'sid2_events': layout.add(bytes(event_stream), 'sid2-events'),
              'fast_table_commands': layout.add(bytes(commands), 'offset-commands')}
    for label, field in (('sid2_bank_low', 0), ('sid2_bank_high', 0),
                         ('sid2_end_low', 1), ('sid2_end_high', 1)):
        shift = 8 if label.endswith('high') else 0
        labels[label] = layout.add(bytes((item[field] >> shift) & 255 for item in descriptors), label)

    rebases, previous_step = [], None
    physical = []
    for index, (row, logical) in enumerate(zip(rows, semantic)):
        sid1_aux = ([sid1_profile['pulse_width'] & 255, sid1_profile['pulse_width'] >> 8,
                     sid1_profile['sustain']] if sid1_profile is not None else [174, 7, 1])
        if logical[3:6] != sid1_aux:
            raise ValueError('The long runtime may omit auxiliary writes only for the frozen constant SID1 envelope')
        step = row[12] | row[13] << 8
        zero_gain = original['triangle_pages'][row[14]] == bytes([128] * 256)
        row[6:12] = [table_pages[step], math.ceil(65536 / step) if step > 256 else 0,
                     1, 0, 0, int(zero_gain)]
        if not row[22] and previous_step is not None and step != previous_step:
            solutions = [n for n in range(256) if n * step % 256 == fractions[index]]
            if not solutions:
                raise ValueError(f'No exact offset-table phase for held pitch at tick {index}')
            row[9:11] = [solutions[0], 1]
            rebases.append({'tick': index, 'step': step, 'fraction': fractions[index], 'table_index': solutions[0]})
        row[14] = gain_pages[row[14]]
        asset = trimmed[row[16]]
        first, end = addresses[asset['id']], addresses[asset['id']] + asset['logical_bytes']
        row[16:22] = [first & 255, first >> 8, end & 255, end >> 8, 0, 0]
        physical.append([logical[0], logical[1], logical[2], logical[3], logical[4], row[5]] + row[6:])
        previous_step = step
    # The original semantic rows and trimmed banks must still agree everywhere.
    check, _ = _sid3_model(semantic, counts, [trimmed[i] for i in range(len(assets))], original['triangle_pages'])
    if check != expected3:
        raise ValueError('Neutral-bank trimming changed an audible SID3 value')
    score_arena = max(layout.free, key=lambda span: span[1] - span[0])
    packed = _score(rows, out / 'score', score_arena[0])
    if packed['score_bytes'] > score_arena[1] - score_arena[0]:
        raise ValueError(f'Compressed note data needs {packed["score_bytes"]} bytes; score arena={score_arena}')
    score_arena[0] += packed['score_bytes']
    lines = [f'.label FAST_TABLE_COUNT = {len(steps)}']
    lines += [f'.label {label} = ${address:04x}' for label, address in labels.items()]
    for address, content, name in sorted(layout.segments):
        path = out / f'{address:04x}-{name}.bin'
        path.write_bytes(content)
        lines += [f'.pc = ${address:04x} "{name}"', f'.import binary "{path.resolve()}"']
    data = out / 'data.asm'
    data.write_text('\n'.join(lines) + '\n')
    sid_source = Path(original['sid_programs_asm']).read_text()
    if sid_source.count('    ldx #9\n!copy:') != 1:
        raise ValueError('Unexpected shared SID state-copy program')
    # SID2 is now a separate sampler. Its fields in voice_record are unused;
    # the fast SID3 producer reads its metadata directly from tick_record.
    sid_source = sid_source.replace('    ldx #9\n!copy:', '    ldx #3\n!copy:', 1)
    sid_programs = out / 'sid-programs.asm'
    sid_programs.write_text(sid_source)
    (out / 'expected-input.bin').write_bytes(expected3)
    (out / 'expected-high.bin').write_bytes(sid2['expected'])
    ledger = {'pcm_bytes': sum(len(a['data']) for a in trimmed.values()),
              'gain_bytes': len(gains) * 256, 'offset_table_runtime_bytes': len(steps) * 256,
              'offset_table_generated_high_bytes': min(14, len(steps)) * 256,
              'sid2_instrument_bytes': sum(len(w['data']) for w in sid2['windows']),
              'sid2_event_bytes': len(event_stream), 'sid2_descriptor_bytes': len(descriptors) * 4,
              'score_bytes': packed['score_bytes'], 'score_history_bytes': HISTORY_BYTES,
              'remaining_arenas': layout.free, 'loader_arena': [0xc400, 0xd000],
              'external_memory': False}
    result = {'rows': physical, 'score_rows': rows, 'data_asm': str(data),
              'score': packed, 'memory': ledger, 'source': original['source'],
              'source_ticks': original['ticks'], 'frames': FRAMES,
              'frame_sample_counts_exact': counts, 'input_codes': len(expected3),
              'duration_s': len(expected3) * support.PERIOD / support.CLOCK,
              'source_cut_s': CUT_TICK / 50, 'nominal_duration_s': FRAMES / 50,
              'sid_programs_asm': str(sid_programs),
              'sid_programs_sha256': support.digest(sid_programs),
              'sid1_profile': sid1_profile, 'sid1_arrangement': sid1_arrangement,
              'held_pitch_rebases': rebases, 'offset_steps': steps,
              'sid2_descriptor_count': len(descriptors),
              'sid2_instrument_windows': [{'key': w['key'], 'first': w['first'], 'last': w['last'],
                                           'address': w['address'], 'bytes': len(w['data'])}
                                          for w in sid2['windows']],
              'expected_input_sha256': hashlib.sha256(expected3).hexdigest(),
              'expected_high_sha256': hashlib.sha256(sid2['expected']).hexdigest()}
    support.save(out / 'preparation.json', result)
    return result


def _protected() -> dict:
    values = cream_playback.protected_hashes(full=True)
    for folder in ('full-linus-mix', 'sid2-repair'):
        for path in (HERE / 'work/cream' / folder).glob('*'):
            if path.suffix in ('.prg', '.wav'):
                values[str(path.relative_to(HERE))] = support.digest(path)
    return values


def _first_latch(receipt: dict) -> int:
    clock, seen = 0, 0
    for line in Path(receipt['media']).open():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            delta, register, value = map(int, fields)
        except ValueError:
            continue
        clock += delta
        if register & 31 == 18 and value == 17:
            seen += 1
            if seen == 2:
                return clock
    raise ValueError('Calibration capture contains no complete sample prefix')


def _build(out: Path, prepared: dict, mode: str, delay: int) -> dict:
    import cream_long_runtime as runtime
    return runtime.build(out, Path(prepared['data_asm']), Path(prepared['score']['score_asm']),
                         MODES[mode], loader_arena=(0xc400, 0xd000),
                         sid_programs_asm=Path(prepared['sid_programs_asm']),
                         startup_audio_delay=delay,
                         sid1_attack_decay=(prepared.get('sid1_profile') or {}).get('attack_decay', 0),
                         sid1_articulation=(prepared.get('sid1_profile') or {}).get('articulation', False))


def _verify(build: dict, receipt: dict, prepared: dict, out: Path, mode: str,
            expected_dir: Path) -> dict:
    from native_instruments.verify_music import verify
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(expected_dir / 'expected-input.bin', out / 'expected-input.bin')
    rows = [row[:3] if MODES[mode][0] else [0, 0, 24] for row in prepared['rows']]
    result = verify(build, receipt, prepared, rows, out, expected_dir / 'expected-high.bin',
                    directmeta={'hold_cycles': 249, 'reference_hold_cycles': 105,
                                'startup_neutral_values': 1, 'neutral_frequency_high': 54},
                    sid2_muted=not MODES[mode][1], baseline_first_latch_cycle=None)
    stats = bytes.fromhex(receipt['stats_hex'])
    if int.from_bytes(stats[6:8], 'little'):
        raise ValueError('The native sixteen-bit late-buffer counter is nonzero')
    if prepared.get('sid1_profile') is not None:
        initial, cycle = {}, 0
        with Path(receipt['media']).open() as stream:
            for line in stream:
                fields = line.split()
                if len(fields) != 3:
                    continue
                try:
                    delta, register, value = map(int, fields)
                except ValueError:
                    continue
                cycle += delta
                if cycle >= result['first_latch_cycle']:
                    break
                if (register & 31) in (2, 3, 5, 6):
                    initial[register & 31] = value
        profile = prepared['sid1_profile']
        expected_aux = {2: profile['pulse_width'] & 255, 3: profile['pulse_width'] >> 8,
                        5: profile.get('attack_decay', 0),
                        6: (profile['sustain'] << 4 | profile.get('release', 0)) if MODES[mode][0] else 0}
        result['sid1_native_envelope_startup'] = {'passed': initial == expected_aux,
                                                 'observed': initial, 'expected': expected_aux}
        if initial != expected_aux:
            raise ValueError(f'The actual SID1 envelope or pulse width differs: {initial}/{expected_aux}')
    return result


def _isolation(builds: dict, out: Path, *, sid1_sustain: int = 1) -> dict:
    """Require identical workloads, with only declared output immediates changed."""
    baseline = Path(builds['all']['startup_loader']['native_program']).read_bytes()
    load = int.from_bytes(baseline[:2], 'little')
    allowed_values = {(255, 0), (0, 24), (240, 0), (15, 143), (17, 25), (1, 9),
                      (sid1_sustain << 4, 0)}
    result = {}
    for name, build in builds.items():
        actual = Path(build['startup_loader']['native_program']).read_bytes()
        if len(actual) != len(baseline):
            raise ValueError('An output mute changed the native memory layout')
        changed = []
        for index, (old, new) in enumerate(zip(baseline, actual)):
            if old == new:
                continue
            address = load + index - 2
            if (not (0x0801 <= address < 0x0c00 or 0x7000 <= address < 0x8000)
                    or (old, new) not in allowed_values
                    or baseline[index - 1] not in (0x29, 0x09, 0xa9)):
                raise ValueError(f'Undeclared mute difference for {name} at ${address:04x}: {old}/{new}')
            changed.append(address)
        result[name] = {'passed': True, 'changed_immediate_addresses': changed,
                        'score_instruments_and_producer_workload_unchanged': True}
    support.save(out / 'isolation-check.json', result)
    return result


def _preserved_audio(captured: dict, prepared: dict, out: Path) -> dict:
    """Check actual unchanged musical parts on their fixed source clock."""
    from cream_reference import _metrics
    result = {}
    decisions = json.loads((HERE / 'work/cream/listening-decisions.json').read_text())
    names = ('sid-2', 'sid-3') if prepared.get('sid1_profile') is not None else ('sid-1', 'sid-3')
    for name in names:
        if name == 'sid-2':
            path = HERE / 'work/cream/three-minute-linus-mix/sid-2.wav'
            expected_digest = '4f9183d876bf1ebcd6307fbe77d3b446a28acddab13829e8c63ec09a7a21a6f9'
            reference_gain = 5.101806324304029
            high = np.frombuffer((out / 'instruments/expected-high.bin').read_bytes(), np.uint8)
            if hashlib.sha256(high.tobytes()).hexdigest() != '91b49e6b4f64f1b99b1a17b2c92564566e9482f7bc015a2d305aef7d9fa60e1c':
                raise ValueError('The SID1 repair changed the frozen SID2 inputs')
        else:
            path = HERE / 'work/cream/full-linus-mix' / f'{name}.wav'
            expected_digest = decisions['physical_voices'][name]['wav_sha256']
            reference_gain = 8
        if support.digest(path) != expected_digest:
            raise ValueError(f'The protected {name} listening reference changed')
        reference, rate = sf.read(path, dtype='float64')
        observed, new_rate, _ = captured[name]
        # The ending deliberately excludes the next source pattern. Compare
        # only the original interval, before the independently drained tails.
        count = round(CUT_TICK / 50 * rate)
        reference = reference[:count] / reference_gain
        actual = observed[:count]
        if rate != new_rate or len(reference) != len(actual):
            raise ValueError('Preserved parts have different source-clock axes')
        ratios, cosines, audible_cosines, failures = [], [], [], []
        rest_old_power, rest_new_power = None, None
        rest_windows = []
        rest_reference_bands = []
        window = round(.2 * rate)
        for start in range(0, count, window):
            old_rms, old_bands = _metrics(reference[start:start + window], rate)
            new_rms, new_bands = _metrics(actual[start:start + window], rate)
            if old_rms < .00001:
                if new_rms > .0001:
                    failures.append({'frame': start, 'kind': 'new sound in a reference rest'})
                continue
            ratio = new_rms / old_rms
            denominator = float(np.linalg.norm(old_bands) * np.linalg.norm(new_bands))
            cosine = float(np.dot(old_bands, new_bands) / denominator) if denominator else 0.
            ratios.append(ratio); cosines.append(cosine)
            first_tick = start * 50 // rate
            last_tick = min(CUT_TICK, (min(start + window, count) * 50 + rate - 1) // rate)
            declared_rest = (name == 'sid-1' and old_rms <= .0001
                             and all(row[:3] == [0, 0, 25]
                                     for row in prepared['rows'][first_tick:last_tick]))
            if name == 'sid-2' and old_rms <= .0001:
                first_code = max(0, math.floor(start * support.CLOCK / (rate * 504)) - 1)
                last_code = min(len(high), math.ceil(min(start + window, count) * support.CLOCK / (rate * 504)))
                declared_rest = bool(np.all(high[first_code:last_code] == 54))
            if declared_rest:
                # The approved recording's own independent rest windows fail
                # a per-window .99 spectral comparison (563/1081 reference
                # pairs). Their approximately 21-LSB floor is not an
                # instrument. Keep the level gate for EVERY window, and apply
                # the SAME .99 spectral bound to pooled rest-band power.
                # Classification uses the proven score and reference energy,
                # never candidate energy. No listening samples are changed.
                if rest_old_power is None:
                    rest_old_power = np.zeros_like(old_bands)
                    rest_new_power = np.zeros_like(new_bands)
                rest_old_power += old_bands ** 2
                rest_new_power += new_bands ** 2
                rest_windows.append(start)
                rest_reference_bands.append(old_bands)
            else:
                audible_cosines.append(cosine)
            if not .98 <= ratio <= 1.02 or (not declared_rest and cosine < .99):
                failures.append({'frame': start, 'RMS_ratio': ratio, 'spectral_cosine': cosine})
        rest_cosine = None
        reference_pairs = []
        if rest_windows:
            old = np.sqrt(rest_old_power); new = np.sqrt(rest_new_power)
            denominator = float(np.linalg.norm(old) * np.linalg.norm(new))
            rest_cosine = float(np.dot(old, new) / denominator) if denominator else 0.
            if rest_cosine < .99:
                failures.append({'kind': 'changed declared-rest noise spectrum', 'spectral_cosine': rest_cosine})
            for index, first in enumerate(rest_reference_bands):
                for second in rest_reference_bands[index + 1:]:
                    reference_pairs.append(float(np.dot(first, second) /
                                                 (np.linalg.norm(first) * np.linalg.norm(second))))
        result[name] = {'passed': not failures, 'reference_sha256': support.digest(path),
                        'fixed_source_interval_s': [0, CUT_TICK / 50],
                        'reference_gain_removed': reference_gain, 'window_seconds': .2,
                        'RMS_ratio_limits': [.98, 1.02], 'minimum_spectral_cosine_limit': .99,
                        'minimum_RMS_ratio': min(ratios), 'maximum_RMS_ratio': max(ratios),
                        'minimum_spectral_cosine': min(cosines),
                        'minimum_audible_spectral_cosine': min(audible_cosines),
                        'declared_rest_window_frames': rest_windows,
                        'pooled_rest_spectral_cosine': rest_cosine, 'failures': failures,
                        'reference_only_rest_control': {
                            'pairs': len(reference_pairs),
                            'pairs_below_per_window_limit': sum(x < .99 for x in reference_pairs),
                            'minimum_spectral_cosine': min(reference_pairs) if reference_pairs else None},
                        'scope': 'Actual native solo, fixed source clock; no fitted time or gain and no corrected listening audio. The new ending is outside the comparison.'}
    support.save(out / 'preserved-parts-check.json', result)
    if not all(item['passed'] for item in result.values()):
        raise ValueError('A frozen voice changed; inspect preserved-parts-check.json')
    return result


def finish_audio(out: Path, result: dict, builds: dict, captured: dict, prepared: dict) -> dict:
    """Publish only checked, unmodified native captures and the tested PRG."""
    result['preserved_parts'] = _preserved_audio(captured, prepared, out)
    peak = max(float(abs(value[0]).max()) for name, value in captured.items()
               if name not in ('muted', 'static-control'))
    gain = min(8., .92 / peak)
    muted = float(abs(captured['muted'][0] - captured['static-control'][0]).max()) * gain * 32768
    result['mute_control'] = {'passed': muted <= 1, 'maximum_PCM16_LSB_difference': muted}
    if not result['mute_control']['passed']:
        raise ValueError('The muted native producer differs from the independent static SID')
    result['audio'] = {}
    for name in ('all', 'sid-1', 'sid-2', 'sid-3'):
        signal, rate, receipt = captured[name]
        sf.write(out / f'{name}.wav', signal * gain, rate, subtype='PCM_16')
        result['audio'][name] = {'file': f'{name}.wav', 'sha256': support.digest(out / f'{name}.wav'),
                                'frames': len(signal), 'rate': rate, 'duration_s': len(signal) / rate,
                                'listening_gain': gain, 'raw_capture_sha256': receipt['media_sha256'],
                                'processing': 'Independent actual VICE recording, native-clock crop, DC removal and one common gain. No host mixing, EQ, alignment or dynamics.'}
    result['protected_unchanged'] = _protected() == result['protected_hashes']
    if not result['protected_unchanged']:
        raise ValueError('A preserved player or recording changed')
    shutil.copyfile(builds['all']['program'], out / 'player.prg')
    if result.get('sid1_profile') is not None:
        write_sid1_auditions(out, result)
    write_delivery(out, result, builds)
    support.save(out / 'verification.json', result)
    return result


def write_sid1_auditions(out: Path, result: dict) -> None:
    """Expose the reported lead phrase without changing its timing or sound."""
    from solo_original import load_library, render_track

    rate, start, end = 22050, 89.60, 107.52
    first, last = round(start * rate), round(end * rate)
    clips = {}
    for name in ('all', 'sid-1'):
        data, actual_rate = sf.read(out / f'{name}.wav', dtype='int16')
        if actual_rate != rate or len(data) < last:
            raise ValueError('The complete native recording does not cover the SID1 audition')
        path = out / f'{name}-89.60-107.52.wav'
        sf.write(path, data[first:last], rate, subtype='PCM_16')
        clips[name] = {'file': path.name, 'sha256': support.digest(path),
                       'processing': 'Exact frame slice of the independent full VICE recording; no further gain or processing.'}
    source = HERE.parent / 'mod-hybrid/sources/cream-of-the-earth.mod'
    if support.digest(source) != result['source']['sha256']:
        raise ValueError('The original melody audition is not the pinned Cream MOD')
    library, location = load_library()
    original, mute = render_track(library, source.read_bytes(), 2, rate, last)
    path = out / 'original-c3-89.60-107.52.wav'
    sf.write(path, original[first:last], rate, subtype='PCM_16')
    clips['original-C3'] = {'file': path.name, 'sha256': support.digest(path),
                            'decoder': location, 'mute_status': mute,
                            'processing': 'Independent original MOD decode from time zero, only C3 enabled; exact frame crop, no gain adjustment.'}
    result['audition'] = {'source_interval_s': [start, end], 'rate': rate,
                          'frames': last - first, 'clips': clips,
                          'scope': 'Compare original C3 with the same C3 phrase on SID1. This is a listening candidate, not an objective sound-quality pass.'}
    support.save(out / 'audition.json', result['audition'])


def write_delivery(out: Path, result: dict, builds: dict) -> None:
    """Keep the canonical result small, reproducible and clearly documented."""
    rebuild_file = out / 'rebuild-check.json'
    rebuild = json.loads(rebuild_file.read_text()) if rebuild_file.exists() else None
    if not (rebuild and rebuild.get('passed') and all(
            rebuild['variants'][name]['program_sha256'] == build['program_sha256']
            for name, build in builds.items())):
        checks = {}
        with tempfile.TemporaryDirectory(prefix='cream-stock-ram-') as folder:
            fresh = Path(folder)
            model = prepare(fresh / 'instruments', sid1_profile=result.get('sid1_profile'))
            delay = builds['all']['startup_audio_delay_cycles']
            for name, tested in builds.items():
                built = _build(fresh / 'programs' / name, model, name, delay)
                checks[name] = {
                    'program_sha256': built['program_sha256'],
                    'byte_identical': Path(built['program']).read_bytes() == Path(tested['program']).read_bytes(),
                    'native_byte_identical': Path(built['startup_loader']['native_program']).read_bytes()
                    == Path(tested['startup_loader']['native_program']).read_bytes()}
        if not all(c['byte_identical'] and c['native_byte_identical'] for c in checks.values()):
            raise ValueError('Clean native or packaged PRG rebuild changed bytes')
        rebuild = {'passed': True, 'cold_delay_cycles': delay, 'variants': checks,
                   'scope': 'All five native and packaged PRGs rebuilt from source in a fresh temporary directory.'}
        support.save(rebuild_file, rebuild)
    result['clean_rebuild'] = {'file': rebuild_file.name, 'sha256': support.digest(rebuild_file), 'passed': True}
    # These files own analysis and dispatch; the emitted native source and all
    # actual PRG hashes above independently pin the program that was measured.
    result['source_sha256']['cream_three_minute.py'] = support.digest(Path(__file__))
    result['source_sha256']['build_linus_mix.py'] = support.digest(HERE / 'build_linus_mix.py')
    if result.get('sid1_profile') is not None:
        result['source_sha256']['cream_sid1_melody.py'] = support.digest(HERE / 'cream_sid1_melody.py')
        result['source_sha256']['native_instruments/cream_sid1/voice.json'] = support.digest(
            HERE / 'native_instruments/cream_sid1/voice.json')
        result['limitations'] = result['sid1_arrangement']['limitations'] + [
            'SID2 has approximately 977 Hz audio bandwidth.',
            'Screen-on operation and physical SID have not been verified.']
        result['listening_status'] = 'SID1 candidate awaiting assessment; native proof is not listening approval.'
    routing = json.loads((out / 'instruments/source-model/routing.json').read_text())
    sid1_repair = result.get('sid1_profile') is not None
    if sid1_repair:
        # Recompute omissions from the selected channels. The source-model
        # report describes the preserved C3-only baseline, not this repair.
        source_channels = result['sid1_arrangement']['source_channels_per_tick']
        source_ticks = json.loads((out / 'instruments/preparation.json').read_text())['source_ticks']
        routing['omissions'] = []
        for index, route in enumerate(routing['routes'][:CUT_TICK]):
            assigned = {source_channels[index], route['sid2'], route.get('pcm')}
            states = source_ticks[index]['channels']
            missed = [channel for channel, state in enumerate(states, 1)
                      if state['playing_sample'] and state['volume'] and channel not in assigned]
            if missed:
                routing['omissions'].append({'tick': index, 'channels': missed,
                                            'instruments': [states[channel - 1]['playing_sample'] for channel in missed]})
    omissions = []
    for item in routing['omissions']:
        tick = item['tick']
        if tick >= CUT_TICK:
            continue
        if (omissions and omissions[-1]['end_tick'] == tick
                and omissions[-1]['channels'] == item['channels']
                and omissions[-1]['instruments'] == item['instruments']):
            omissions[-1]['end_tick'] = tick + 1
        else:
            omissions.append({'start_tick': tick, 'end_tick': tick + 1,
                              'channels': item['channels'], 'instruments': item['instruments']})
    coverage = {'source_interval_s': [0, CUT_TICK / 50], 'drain_end_s': FRAMES / 50,
                'source_channels': {'SID1': ('C3, except C1 at 17.92..31.36' if sid1_repair else 'C3'), 'SID2': 'C4, plus C1 instrument 10 introduction',
                                    'SID3': 'C2, plus C1 instrument 11 introduction'},
                'omitted_intervals': omissions,
                'scope': ('SID1 restores 12 C1 triggers at 17.92..31.36 and omits six sparse C3 triggers there. Later C1 chords remain omitted; no new pattern starts during the drain.'
                          if sid1_repair else 'C1 remains omitted outside its explicitly allocated introduction; no new following-pattern notes play during the drain.')}
    support.save(out / 'coverage.json', coverage)
    result['coverage'] = {'file': 'coverage.json', 'sha256': support.digest(out / 'coverage.json')}
    (out / '.gitignore').write_text(
        '*\n!.gitignore\n!README.md\n!player.prg\n!all.wav\n!sid-[1-3].wav\n'
        '!verification.json\n!phase-calibration.json\n!preserved-parts-check.json\n'
        '!isolation-check.json\n!coverage.json\n!rebuild-check.json\n!guard-controls.json\n'
        '!audition.json\n!*-89.60-107.52.wav\n')
    gain = result['audio']['all']['listening_gain']
    native_description = ('''SID1 is a listening candidate, not an approved replacement. Instrument 10
uses triangle+saw (`$31`), with AD `$18`, SR `$60` and real GATE attacks.
Other SID1 instruments retain their earlier waveform approximations under the
same hardware envelope. A real source note or route handoff may shorten the
preceding note by 40 ms to prepare GATE. This is not the original recorded
envelope or an exact MOD volume replay. C1's 12 linear-note triggers at
17.92..31.36 replace six sparse C3 tonic/octave triggers; C3 carries the later
lead. Later C1 chords remain omitted.'''
                          if sid1_repair else '''SID1 retains the earlier native pulse
and arpeggio programs. C1's instruments 10/11 are included in the introduction;
later C1 chords remain omitted.''')
    guard_description = ('''Actual SID2/SID3 music passes the same .98–1.02 window-level and .99
spectral bounds against its frozen recordings. Declared neutral SID2 windows
retain the per-window level check and use pooled band power for the .99
spectral check. Both complete sampler input streams and clocks remain exact.
The previous SID1 recording is intentionally not a sound target: the user
rejected its flat held-note character. Its files remain intact.'''
                         if sid1_repair else '''Actual SID1/SID3 music passes the unchanged .98–1.02 window-level and .99
spectral bounds against the previous full recording. Declared SID1 rests
retain the same per-window level check and use pooled band power for the .99
spectral check. The reference's own independent noise-floor windows fail a
per-200-ms spectral comparison, so they are not treated as instruments.''')
    (out / 'README.md').write_text(f'''# Cream of the Earth — selected 3:08.42 arrangement

This is the complete selected arrangement for an unexpanded 64 KiB C64.
New notes stop at the source pattern boundary at 188.16 seconds, where SID1
already rests. Existing bass and drums drain until 188.42 seconds.

- [All three voices](all.wav)
- [SID1: native melody programs](sid-1.wav)
- [SID2: original sampled percussion](sid-2.wav)
- [SID3: original sampled bass and other C2 instruments](sid-3.wav)
- [Runnable PRG](player.prg)
- [Full verification and CPU/memory measurements](verification.json)
- [Frozen voice audio checks](preserved-parts-check.json)
- [Explicit source-channel omissions](coverage.json)
- [Clean rebuild](rebuild-check.json)

SID2 uses the Linus-style oscillator method at 1,954.86 values/s; SID3 uses
the same principle at 7,819.43 values/s. {native_description}
SID2's limited bandwidth reduces hihat
brightness. The introduction on SID2 now uses actual instrument 10 samples.
This is not an exact four-channel Amiga replay.

No REU, GeoRAM, external streaming or flattened song recording is used.
Instrument samples are reused. Position tables are generated in ordinary C64
RAM before playback; the compressed main score uses 512 bytes of history.
Read [the implementation](../../../CREAM-THREE-MINUTE.md) for the memory layout
and lossless CPU optimizations. The PRG is {result['program']['bytes']:,} bytes.

All five output/mute variants pass every one of 1,473,337 SID3 inputs and
368,334 SID2 inputs, all global register phases and every SID1 note. All
9,421 buffers finish without a late buffer. Full ring-generation tracing has
no stale reads or overwrites; minimum write-to-read margin is
{result['ring']['minimum_write_to_read_margin_cycles']:,} cycles. Maximum NMI is
{result['cpu']['maximum_nmi_cycles']} cycles; minimum foreground margin is
{result['cpu']['minimum_deadline_slack_foreground_cycles']:,} cycles. This does not establish
capacity for another sample channel or a visible display.

Normal true-drive D64 autostart passes, including restored native RAM and the
complete musical trace. All five native and packaged PRGs rebuild byte for
byte in a fresh temporary directory. Original full/short Cream, the drum
audition, Hyperbased and protected references remain unchanged.

Each WAV is an independent actual VICE recording, mono 22,050 Hz and
4,154,662 frames. All use one common gain, {gain:.6f}. Only a native-clock crop,
DC removal and that constant gain are applied. No EQ, host mixing, fitted
alignment, dynamics or noise removal is used.

{guard_description}
No listening samples are changed by this analysis.

Use PAL, reSID, MOS8580 + digiboost and resampling method 2. Screen blanking
is intentional. Physical SID operation and screen-on playback remain unverified.

```sh
rtk proxy experiments/mod-hybrid/.venv/bin/python experiments/sid-voice-sampler/build_linus_mix.py --song cream --full
```
''')


def run(out: Path, *, assemble_only: bool = False, sid1_profile: dict | None = None) -> dict:
    """Build, prove and record the selected complete three-minute arrangement."""
    out = Path(out).resolve()
    if sid1_profile is not None and out == HERE / 'work/cream/three-minute-linus-mix':
        raise ValueError('Keep the rejected SID1 baseline intact; use a separate repair output')
    out.mkdir(parents=True, exist_ok=True)
    protected = _protected()
    prepared_dir = out / 'instruments'
    prepared = prepare(prepared_dir, sid1_profile=sid1_profile)
    print(f"Prepared {FRAMES} ticks; stock-RAM free arenas {prepared['memory']['remaining_arenas']}", flush=True)
    delay = SID1_COLD_DELAY_CYCLES if sid1_profile is not None else COLD_DELAY_CYCLES
    first_build = _build(out / 'calibration/program', prepared, 'all', delay)
    if not assemble_only:
        # Stop this unchanged PRG in its first wait loop. This diagnostic reads
        # the first native latch; it never captures or adjusts listening audio.
        short = dict(first_build, symbols=dict(first_build['symbols']))
        short['symbols']['done'] = short['symbols']['wait_start']
        initial = support.capture(short, out / 'calibration/initial', .2)
        first = _first_latch(initial)
        old = json.loads((HERE / 'work/cream/full-linus-mix/verification.json').read_text())
        origin = old['native']['all']['first_latch_cycle']
        period = 54736  # Exactly 1,225 recording frames; preserves resampling phase.
        target = origin + math.ceil((first - origin) / period) * period
        delay += target - first
        phase = {'initial_latch_cycle': first, 'target_latch_cycle': target,
                 'reference_latch_cycle': origin, 'phase_period_cycles': period,
                 'cold_delay_cycles': delay, 'audio_time_or_gain_fit': False}
        support.save(out / 'phase-calibration.json', phase)
        print(f"Native phase target {target}; cold delay {delay} cycles", flush=True)
    else:
        phase = None
    builds = {name: _build(out / 'programs' / name, prepared, name, delay) for name in MODES}
    isolation = _isolation(builds, out, sid1_sustain=(sid1_profile['sustain'] if sid1_profile else 1))
    result = {'scope': 'Complete selected Cream arrangement on an unexpanded 64 KiB C64, with two oscillator PCM lanes and one native SID program.',
              'full_song': False, 'complete_selected_arrangement': True,
              'source': prepared['source'], 'source_interval_s': [0, CUT_TICK / 50],
              'nominal_duration_s': FRAMES / 50, 'duration_s': prepared['duration_s'],
              'frames': FRAMES, 'program': {k: v for k, v in builds['all'].items() if k != 'symbols'},
              'sid1_profile': sid1_profile, 'sid1_arrangement': prepared['sid1_arrangement'],
              'memory': prepared['memory'], 'score': prepared['score'],
              'held_pitch_rebases': prepared['held_pitch_rebases'],
              'output_isolation': isolation,
              'phase_calibration': phase, 'protected_hashes': protected,
              'source_sha256': {str(p.relative_to(HERE)): support.digest(p) for p in
                  [Path(__file__).resolve(), HERE / 'cream_long_runtime.py', HERE / 'cream_q8_fast.py',
                   HERE / 'full_length_player.asm', HERE / 'linus-mix-player.asm',
                   HERE / 'full_length_score.py', HERE / 'full-length-score.asm',
                   HERE / 'prg_loader.py', HERE / 'cream_instruments.py', HERE / 'cream_sid.asm',
                   *sorted((HERE / 'native_instruments/cream').glob('*.json'))]},
              'limitations': ['Original C1 is included only in its existing introduction allocation; subsequent C1 chords remain omitted.',
                              'SID1 keeps the existing pulse and arpeggio approximations and on/off volume policy.',
                              'SID2 has approximately 977 Hz audio bandwidth; its C1 introduction now uses original sampled instrument data.',
                              'Screen-on operation and physical SID have not been verified.'],
              'native_rates_hz': {'SID3': support.CLOCK / 126, 'SID2': support.CLOCK / 504}}
    support.save(out / 'verification.json', result)
    if assemble_only:
        shutil.copyfile(builds['all']['program'], out / 'player.prg')
        return result

    def trace(item):
        name, build = item
        folder = out / 'programs' / name
        saved = folder / 'register-receipt.json'
        receipt = json.loads(saved.read_text()) if saved.exists() else None
        if not (receipt and receipt['program_sha256'] == build['program_sha256']
                and receipt['profile'] == support.profile().PROFILE
                and Path(receipt['media']).exists()
                and support.digest(Path(receipt['media'])) == receipt['media_sha256']):
            receipt = support.capture(build, folder / 'registers', prepared['duration_s'])
            support.save(saved, receipt)
        return name, _verify(build, receipt, prepared, folder / 'proof', name, prepared_dir)

    with ThreadPoolExecutor(max_workers=3) as pool:
        proofs = dict(pool.map(trace, builds.items()))
    print('All five complete native traces passed', flush=True)
    if {p['first_latch_cycle'] for p in proofs.values()} != {phase['target_latch_cycle']}:
        raise ValueError('Native variants do not share the fixed resampling phase')
    result['native'] = proofs
    support.save(out / 'verification.json', result)
    from native_instruments.measure_ring import measure as measure_ring
    from native_instruments.measure_music_budget import measure as measure_cpu
    result['ring'] = measure_ring(builds['all'], (prepared_dir / 'expected-high.bin').read_bytes(),
                                  out / 'ring', prepared['duration_s'])
    result['cpu'] = measure_cpu(Path(builds['all']['program']), builds['all']['symbols'],
                                prepared['frame_sample_counts_exact'], out / 'cpu')
    support.save(out / 'verification.json', result)
    if not result['ring']['passed'] or not result['cpu']['passed']:
        raise ValueError('The complete native CPU or ring deadline proof failed')
    print('Complete CPU and ring deadlines passed', flush=True)
    from verify_prg_startup import verify as autostart
    startup = autostart(builds['all'], Path(builds['all']['startup_loader']['native_program']),
                         out / 'autostart', mode=2, full=True)
    result['autostart'] = _verify(builds['all'], startup, prepared, out / 'autostart/proof', 'all', prepared_dir)
    result['autostart'].update(mode=2, restored_native_ram=startup['restored_native_ram'])
    print('Normal true-drive autostart and musical trace passed', flush=True)
    support.save(out / 'verification.json', result)
    audio_builds = dict(builds)
    audio_builds['static-control'] = playback.static_control(builds['muted'], out / 'static-control', FRAMES)

    def capture_audio(item):
        name, build = item
        epoch = proofs['all' if name == 'static-control' else name]['first_latch_cycle']
        folder = out / 'programs' / name / 'audio'
        saved = folder / 'receipt.json'
        receipt = json.loads(saved.read_text()) if saved.exists() else None
        if (receipt and receipt['program_sha256'] == build['program_sha256']
                and receipt['profile'] == support.profile().PROFILE
                and Path(receipt['media']).exists()
                and support.digest(Path(receipt['media'])) == receipt['media_sha256']):
            return name, playback.read_audio_capture(receipt, prepared['duration_s'], epoch, FRAMES)
        return name, playback.capture_audio(build, folder, prepared['duration_s'], epoch, FRAMES)

    with ThreadPoolExecutor(max_workers=6) as pool:
        captured = dict(pool.map(capture_audio, audio_builds.items()))
    print('Six independent actual VICE audio captures complete', flush=True)
    return finish_audio(out, result, builds, captured, prepared)
