"""Preserve ordered HVSC-style voice programs through native SID playback."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from build_c64 import build, normalized, verify_raw_sid_trace
from run_vice import capture


class RawSIDBackendTest(unittest.TestCase):
    @unittest.skipUnless(Path('/opt/homebrew/bin/x64sc').is_file()
                         and (Path.home() / '.local/bin/kickass').is_file(),
                         'This integration check needs VICE and KickAssembler')
    def test_ordered_adsr_gate_and_repeated_writes_reach_sid_while_pcm_runs(self):
        # A single snapshot per tick cannot represent these repeated control
        # writes or a hard restart. Real bus events are the owning boundary.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / 'loop.bin'
            sample.write_bytes(bytes([0]) * 16 + bytes([15]) * 16)
            first = [[4, 0x20], [4, 0x20], [5, 0x09], [6, 0xc7],
                     [2, 0], [3, 8], [0, 0x34], [1, 0x11], [4, 0x21]]
            second = [[4, 0x40], [5, 0x03], [6, 0x94], [2, 0],
                      [3, 4], [0, 0x67], [1, 0x08], [4, 0x41]]
            ticks = []
            for index in range(16):
                writes = [copy.deepcopy(first), copy.deepcopy(second)] if index in (0, 9, 10) else [[], []]
                if index == 3:
                    writes[0] = [[2, 0x80], [3, 7], [0, 0x70]]
                if index == 6:
                    writes[1] = [[4, 0x40], [5, 0], [6, 0], [6, 0x94], [4, 0x41]]
                if index == 12:
                    writes = [[[4, 0x20]], [[4, 0x40]]]
                pcm = [dict(sample=1, step=step, volume=level, trigger=index == 0)
                       for step, level in ((128, 64), (64, 32))]
                ticks.append(dict(time_s=index * .02, duration_s=.02,
                                  order=index // 8, row=index // 2, tick=index % 2,
                                  sid=[{'writes': voice} for voice in writes], pcm=pcm))
            arrangement = dict(raw_sid=True, title='ordered SID regression',
                               duration_s=.32, pcm_rate_hz=985248 / 256,
                               mixing={'output_gain': 3.0},
                               pcm_bank=[dict(id=1, data_file=str(sample), loop_start=0, loop_length=32)],
                               ticks=ticks)
            path = root / 'arrangement.json'
            path.write_text(json.dumps(arrangement))
            compiled = build(path, root / 'c64')
            recorded = capture(root / 'c64/stardust.prg', root / 'c64/stardust.sym',
                               root / 'vice', .32, 'both')
            checked = verify_raw_sid_trace(path, root / 'vice/capture.json')
            self.assertEqual(checked['ordered_writes_checked'], 61)
            self.assertTrue(checked['passed'], checked)
            # Independently derived from the source loop and two cursor steps.
            # Fine sums18/74/48/104 become DAC0/10/5/15 at gain3. The initial
            # DAC8 is followed by one-sample-delayed computed output.
            clock, observed = 0, []
            with (root / 'vice/registers.txt').open() as stream:
                for line in stream:
                    delta, register, value = map(int, line.split())
                    clock += delta
                    if register & 31 == 24 and clock >= recorded['trace']['first_sample_cycle']:
                        observed.append(value)
            self.assertEqual([observed[index] for index in (0, 1, 33, 65, 97)],
                             [8, 0, 10, 5, 15])
            self.assertEqual(recorded['runtime']['audio'],
                             {'played_tick_count': 16, 'underrun_counter': 0})
            self.assertGreater(recorded['trace']['sample_writes'], 1200)
            self.assertGreater(recorded['audio']['raw_rms'], .001)
            self.assertTrue(compiled['raw_sid'])
            proof = HERE / 'results/rebuild/hvsc-hybrid/backend-proof'
            if proof.exists():
                shutil.rmtree(proof)
            shutil.copytree(root, proof)

    def test_raw_voice_contract_rejects_shared_or_linked_hardware(self):
        tick = dict(sid=[dict(writes=[]), dict(writes=[])],
                    pcm=[dict(sample=0, step=0, volume=0, trigger=False)] * 2)
        for writes in ([[24, 15]], [[7, 1]], [[4, 0x43]], [[4, 0x45]],
                       [[0, 256]], [[0, 0]] * 65):
            with self.subTest(writes=writes[:2], count=len(writes)):
                invalid = copy.deepcopy(tick)
                invalid['sid'][0]['writes'] = writes
                with self.assertRaises(ValueError):
                    normalized(invalid, raw_sid=True)


if __name__ == '__main__':
    unittest.main()
