"""Resident gain banks must be rejected before their addresses can wrap."""
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from full_score import pack_score


class MelodyMemoryTest(unittest.TestCase):
    def test_oversized_gain_banks_cannot_emit_a_wrapped_resident_score(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            banks = [{"id": index, "data": bytes([128]) * 4096, "real_end": 4096,
                      "loop_start": None, "asm_path": out / f"bank-{index}.asm"}
                     for index in range(24)]
            with self.assertRaisesRegex(ValueError, "RAM"):
                pack_score([(128, 1, 0)] * 12, [[0, 0, 25, 0, 0, 25]] * 12,
                           banks, out, 12)
            self.assertFalse((out / "data.asm").exists())


if __name__ == "__main__":
    unittest.main()
