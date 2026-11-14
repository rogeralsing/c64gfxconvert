"""Keep whole-score DAC bytes while removing only unread one-shot tails."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mod-complete"))
from lossless_banks import optimize
from pcm4_reference import expected_dac


def write_bank(root: Path, bank_id: int, values: bytes, **metadata) -> dict:
    path = root / f"source-{bank_id}.bin"
    path.write_bytes(values)
    return dict(id=bank_id, data_file=str(path), bytes=len(values),
                loop_start=0, loop_length=0, **metadata)


def silent_state() -> dict:
    return dict(sample=0, step=0, volume=0, trigger=False, loop_sample=0)


class LosslessBanksTest(unittest.TestCase):
    def test_read_extent_includes_muted_fractional_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = write_bank(root, 1, bytes(range(16)) * 16)
            state = dict(sample=1, step=128, volume=0, trigger=True, loop_sample=0)
            ticks = [dict(duration_s=duration, pcm=[dict(state, trigger=index == 0)] +
                          [silent_state() for _ in range(3)])
                     for index, duration in enumerate((.01, .02))]
            arrangement = dict(pcm_rate_hz=985248/256, pcm_bank=[bank], ticks=ticks)
            dac, receipt = expected_dac(arrangement)
            # 0.03 s rounds to115 DAC slots. At step128, the final read is
            # floor(114/2)=57 even though all samples contribute zero volume.
            self.assertEqual(len(dac), 115)
            self.assertEqual(receipt["valid_sample_reads_per_track"][0], 115)
            self.assertEqual(receipt["bank"][0]["maximum_sample_index_plus_one"], 58)
            self.assertEqual(set(map(int, dac)), {8})

    def test_variable_ticks_offsets_and_aliases_preserve_complete_dac(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            banks = [write_bank(root, 1, bytes(range(16)) * 128),
                     write_bank(root, 2, bytes(range(15, -1, -1)) * 64),
                     write_bank(root, 3, bytes([0, 15]) * 32),
                     write_bank(root, 4, bytes([4]) * 128),
                     write_bank(root, 5, bytes([15]) * 512),
                     write_bank(root, 6, bytes([0, 4]) * 16,
                                original_instrument=5, first_segment_source_offset=64,
                                loop_target_id=3),
                     write_bank(root, 7, bytes([0]) * 100)]
            banks[2].update(loop_start=8, loop_length=32)
            states = [dict(sample=1, step=127, volume=0, trigger=True, loop_sample=0),
                      dict(sample=2, step=64, volume=48, trigger=True,
                           offset=255, offset_fraction=128, loop_sample=0),
                      dict(sample=6, step=255, volume=32, trigger=True, loop_sample=3),
                      dict(sample=4, step=128, volume=16, trigger=True, loop_sample=3)]
            ticks = []
            for index, duration in enumerate((.02, .01, .078125, .0125, .02)):
                if index:
                    states = [dict(state, trigger=False, offset=0, offset_fraction=0)
                              for state in states]
                if index == 2:
                    states[0]["volume"] = 64
                ticks.append(dict(duration_s=duration, pcm=copy.deepcopy(states)))
            arrangement = dict(pcm_rate_hz=985248/256, pcm_bank=banks, ticks=ticks,
                               mixing={"mode": "nearest"})
            source = root / "input.json"
            source.write_text(json.dumps(arrangement))
            originals = {Path(entry["data_file"]): Path(entry["data_file"]).read_bytes()
                         for entry in banks}
            original_json = source.read_bytes()
            expected, before = expected_dac(arrangement)
            proof = optimize(source, root / "optimized")
            candidate = json.loads(Path(proof["arrangement"]).read_text())
            actual, after = expected_dac(candidate)
            np.testing.assert_array_equal(actual, expected)
            self.assertEqual(proof["samples_compared"], 541)
            self.assertEqual(proof["original_dac_sha256"], hashlib.sha256(expected.tobytes()).hexdigest())
            self.assertTrue(proof["all_dac_bytes_match"])
            self.assertEqual(candidate["ticks"], arrangement["ticks"])
            self.assertEqual([entry["id"] for entry in candidate["pcm_bank"]], list(range(1, 8)))
            sizes = {entry["id"]: entry["bytes"] for entry in candidate["pcm_bank"]}
            reach = {entry["id"]: entry["maximum_sample_index_plus_one"] for entry in before["bank"]}
            self.assertEqual(sizes[1], reach[1])
            self.assertLess(sizes[1], 2048)
            self.assertEqual(sizes[7], 1)
            self.assertEqual(Path(candidate["pcm_bank"][6]["data_file"]).read_bytes(), b"\x08")
            # Offset instrument, loop, first-DMA alias, alias source and its
            # independent loop target retain every original sample byte.
            for bank_id in (2, 3, 5, 6):
                entry = candidate["pcm_bank"][bank_id - 1]
                self.assertEqual(Path(entry["data_file"]).read_bytes(), originals[Path(banks[bank_id - 1]["data_file"])])
            self.assertGreater(reach[3], 8)  # Reached through another bank's DMA completion.
            self.assertEqual(after["triggers_per_track"], [1, 1, 1, 1])
            self.assertEqual(source.read_bytes(), original_json)
            for path, values in originals.items():
                self.assertEqual(path.read_bytes(), values)

    def test_output_cannot_overwrite_input_or_source_banks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = write_bank(root, 1, bytes([4]) * 16)
            arrangement = dict(pcm_rate_hz=985248/256, pcm_bank=[bank],
                               ticks=[dict(duration_s=.02, pcm=[silent_state() for _ in range(4)])])
            source = root / "arrangement.json"
            source.write_text(json.dumps(arrangement))
            with self.assertRaisesRegex(ValueError, "separate"):
                optimize(source, root)
            output = root / "candidate"
            (output / "bank").mkdir(parents=True)
            (output / "bank" / "sample-01.bin").symlink_to(bank["data_file"])
            with self.assertRaisesRegex(ValueError, "overwrite a source bank"):
                optimize(source, output)
            self.assertEqual(Path(bank["data_file"]).read_bytes(), bytes([4]) * 16)


if __name__ == "__main__":
    unittest.main()
