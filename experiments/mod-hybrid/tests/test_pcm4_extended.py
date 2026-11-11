"""Regress the score-to-SID boundary for tempo, offsets and loop-pointer changes."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from pcm4_build import build
from pcm4_reference import expected_dac, verify_trace
from run_vice import capture


class ExtendedScoreTest(unittest.TestCase):
    @unittest.skipUnless(Path('/opt/homebrew/bin/x64sc').exists()
                         and (Path.home()/'.local/bin/kickass').exists(),
                         'This integration check needs VICE and KickAssembler')
    def test_finished_one_shot_can_enter_and_later_resume_a_replaced_loop(self):
        # Elysium has this outside its first50seconds. One voice already has
        # its next loop set when its one-shot ends; the other ends first and
        # receives its loop later, with no note retrigger in either case.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, loop = root/'one-shot.bin', root/'loop.bin'
            first.write_bytes(bytes([4])*32)
            loop.write_bytes(bytes([0])*16 + bytes([15])*16)
            bank = [{'id':1,'data_file':str(first),'loop_start':0,'loop_length':0},
                    {'id':2,'data_file':str(loop),'loop_start':0,'loop_length':32}]
            states = [dict(sample=1, step=255, volume=64, trigger=True, loop_sample=target)
                      for target in (2,0)]
            states += [dict(sample=0, step=0, volume=0, trigger=False, loop_sample=0)
                       for _ in range(2)]
            ticks = []
            for index in range(12):
                if index:
                    states = [dict(state, trigger=False) for state in states]
                if index == 2:
                    states[1]['loop_sample'] = 2
                if index == 3:
                    states[0]['volume'] = 0
                ticks.append(dict(time_s=index*.02, duration_s=.02, order=0, row=index,
                                  tick=0, pcm=copy.deepcopy(states)))
            arrangement = dict(pcm_rate_hz=985248/256, duration_s=.24, pcm_bank=bank,
                               ticks=ticks, mixing={'mode':'nearest'})
            source = root/'arrangement.json'
            source.write_text(json.dumps(arrangement))
            compiled = build(source, root/'c64', score_codec='dictionary8')
            actual = capture(Path(compiled['program']), Path(compiled['symbols']),
                             root/'vice', .24, 'registers')
            model, reference = expected_dac(arrangement)
            self.assertEqual(int(model[55]),10)
            # The resumed second voice alternates pure DAC6/10 after the first
            # voice is muted. A permanently inactive model would output8.
            self.assertEqual(set(map(int,model[250:300])),{6,10})
            checked = verify_trace(model, root/'vice/registers.txt', actual['trace']['first_sample_cycle'])
            self.assertTrue(checked['all_dac_bytes_match'],checked['examples'])
            self.assertEqual(actual['runtime']['registers'],
                             {'played_tick_count':12,'underrun_counter':0})
            proof = HERE/'results/rebuild/backend-edge-proof/shared-regression'
            if proof.exists():
                shutil.rmtree(proof)
            shutil.copytree(root,proof)
            (proof/'proof.json').write_text(json.dumps({'build':compiled,'reference':reference,
                'capture':actual,'dac_comparison':checked},indent=2)+'\n')

    @unittest.skipUnless(Path('/opt/homebrew/bin/x64sc').exists()
                         and (Path.home()/'.local/bin/kickass').exists(),
                         'This integration check needs VICE and KickAssembler')
    def test_variable_tempo_offsets_and_next_loop_reach_the_sid(self):
        # This contract was not covered by the original fixed-50-Hz/zero-offset
        # release checks. A missing offset, early loop switch, duplicate trigger
        # at a long-tick split, or changed sample clock changes actual SID bytes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = (bytes([0])*256 + bytes([4])*256 + bytes([15])*256 + bytes([8])*256,
                       bytes([0, 15]), bytes([15])*256)
            bank = []
            for index, values in enumerate(samples, 1):
                path = root/f'sample-{index}.bin'
                path.write_bytes(values)
                bank.append({'id': index, 'data_file': str(path), 'base_divisor': 1,
                             'loop_start': 256 if index == 1 else 0,
                             'loop_length': 512 if index == 1 else 256 if index == 3 else 0})
            bank[1]['loop_target_id'] = 1
            durations = [0.02, 0.01, 0.078125, 0.0125, 0.02, 0.02, 0.015, 0.01, 0.02, 0.02]
            states = [dict(sample=1, step=step, volume=volume, trigger=True,
                           offset=offset, offset_fraction=0, loop_sample=1)
                      for step, volume, offset in ((0,64,0),(128,48,512),(64,32,256),(255,16,640))]
            ticks, clock = [], 0.0
            for index, duration in enumerate(durations):
                if index:
                    states = [dict(state, trigger=False, offset=0, offset_fraction=0) for state in states]
                if index == 1:
                    states[0].update(trigger=True, offset=255, offset_fraction=128, step=128)
                if index == 2:
                    states[3]['loop_sample'] = 3
                if index == 3:
                    states[0].update(trigger=True, offset=0, step=0)
                if index == 4:
                    states[0].update(trigger=True, offset=256)
                if index == 5:
                    states[0].update(sample=2, trigger=True, offset=0, step=255)
                if index == 6:
                    states[3]['loop_sample'] = 1
                if index == 7:
                    states[1]['loop_sample'] = 3
                ticks.append(dict(time_s=clock, duration_s=duration, order=0, row=index,
                                  tick=0, pcm=copy.deepcopy(states)))
                clock += duration
            arrangement = dict(pcm_rate_hz=985248/256, duration_s=clock, pcm_bank=bank,
                               ticks=ticks, mixing={'mode':'nearest'})
            source = root/'arrangement.json'
            source.write_text(json.dumps(arrangement))
            try:
                compiled = build(source, root/'c64', score_codec='dictionary8')
            except RuntimeError:
                print((root/'c64/build.log').read_text())
                raise
            # 0.078125 s requires 301 DAC slots, split into two held records.
            self.assertEqual(compiled['ticks'], 11)
            actual = capture(Path(compiled['program']), Path(compiled['symbols']),
                             root/'vice', clock, 'both')
            self.assertEqual(actual['runtime']['registers'],
                             {'played_tick_count':11, 'underrun_counter':0})
            model, reference = expected_dac(arrangement)
            # Hand-derived waveform landmarks: the opening sum is 116 -> DAC7;
            # the half-byte cursor at source255.5 crosses into value4 one output
            # after the extended staggered retrigger, at DAC index71.
            np.testing.assert_array_equal(model[:32], np.r_[8, np.full(31,7)])
            self.assertEqual(int(model[70]),7)
            self.assertEqual(int(model[71]),8)
            checked = verify_trace(model, root/'vice/registers.txt', actual['trace']['first_sample_cycle'])
            self.assertTrue(checked['all_dac_bytes_match'], checked['examples'])
            self.assertEqual(checked['bytes_compared'], round(clock*985248/256))
            self.assertEqual(actual['audio']['frames'],round(clock*22050))
            proof = HERE/'results/rebuild/backend-extension-proof/synthetic'
            if proof.exists():
                shutil.rmtree(proof)
            shutil.copytree(root,proof)
            (proof/'proof.json').write_text(json.dumps({'build':compiled,'reference':reference,
                'capture':actual,'dac_comparison':checked},indent=2)+'\n')


if __name__ == '__main__':
    unittest.main()
