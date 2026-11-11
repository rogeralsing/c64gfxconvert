"""Contracts for data-only previews on the unchanged accepted SID player."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mod-hybrid"))
from audition_samples import frame_ticks, prepare
from mod_reader import load_mod
from timeline import build_timeline


def tick(time, duration, *, trigger=False, volume=64):
    state = {"playing_sample": 1, "period": 678, "volume": volume, "trigger": trigger}
    return {"time_s": time, "duration_s": duration, "channels": [dict(state) for _ in range(4)]}


class AuditionSamplesTest(unittest.TestCase):
    def test_cream_reference_first_twenty_seconds_are_identical(self):
        source = HERE.parent / "mod-hybrid/sources/cream-of-the-earth.mod"
        reference = HERE / "results/mod-channel/expected-input.bin"
        if not source.exists() or not reference.exists():
            self.skipTest("Pinned source and accepted reference are required")
        mod = load_mod(source)
        selected = build_timeline(mod)["ticks"][896:1896]
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            result = prepare(mod, selected, 1, out)
            expected = reference.read_bytes()[:156389]
            self.assertEqual((out / "expected-input.bin").read_bytes(), expected)
            self.assertEqual(result["metadata"]["frames"], 1000)
            self.assertEqual(result["metadata"]["triggers"],
                             sum(t["channels"][1]["trigger"] for t in selected))

    def test_variable_ticks_keep_cumulative_clock_and_balanced_held_buffers(self):
        ticks = [tick(0, .02, trigger=True), tick(.02, .0125), tick(.0325, .04)]
        frames, counts = frame_ticks(ticks)
        self.assertEqual(counts, [156, 98, 156, 157])
        self.assertEqual([frame["channels"][0]["trigger"] for frame in frames],
                         [True, False, False, False])
        self.assertEqual(sum(counts), 567)

    def test_bounded_original_loop_retains_waveform_and_rejects_audible_gain_change(self):
        raw = bytes([0, 127, 0, 128] * 16)
        mod = {"samples": [{"data": raw, "length": 64, "loop_start": 16, "loop_length": 16}]}
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            result = prepare(mod, [tick(0, .04, trigger=True)], 0, out)
            actual = np.frombuffer((out / "expected-input.bin").read_bytes(), np.uint8)
            phase = np.arange(313) * 171 // 256
            codes = np.array([128, 254, 128, 1], np.uint8)
            np.testing.assert_array_equal(actual, codes[phase % 4])
            self.assertGreater(result["banks"][0]["unrolled_loop_copies"], 0)
            self.assertEqual(result["metadata"]["bank_bytes"], 256)
            with self.assertRaisesRegex(ValueError, "Audible gain changed"):
                prepare(mod, [tick(0, .02, trigger=True), tick(.02, .02, volume=32)], 0, out / "bad")


if __name__ == "__main__":
    unittest.main()
