"""Preferred banks retain independent Paula loops and short initial DMA reads."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextual_banks import combine
from pcm4_prepare import prepare
from pcm4_reference import expected_dac


def loop_module(late_loop: bool) -> bytes:
    data = bytearray(1084 + 1024)
    for instrument in range(2):
        header = 20 + 30 * instrument
        data[header + 22:header + 24] = (256).to_bytes(2, "big")
        data[header + 25] = 64
        data[header + 26:header + 28] = (128).to_bytes(2, "big")
        data[header + 28:header + 30] = (128).to_bytes(2, "big")
    data[950] = 1
    data[1080:1084] = b"M.K."

    def note(row, voice, sample=0, period=0, effect=0, value=0):
        offset = 1084 + row * 16 + voice * 4
        data[offset:offset + 4] = bytes([(sample & 0xF0) | (period >> 8), period & 255,
                                       (sample << 4 & 0xF0) | effect, value])

    note(0, 0, 1, 856, 9, 255)  # Out-of-range 9xx: two-byte first DMA segment.
    note(0, 1, 1, 856)
    if late_loop:
        note(1, 0, 1, 856)
        note(1, 1, 1, 856)
        note(2, 0, 2)  # Loop replacement occurs after the preferred excerpt.
        note(3, 0, 1, 113)
        note(4, 3, effect=15)
    else:
        note(1, 0, 2)  # Change next loop without retriggering the current DMA.
        note(2, 0, 1, 113)
        note(3, 3, effect=15)
    data.extend(bytes(range(256)) * 2)
    data.extend(bytes(reversed(range(256))) * 2)
    return bytes(data)


class ContextualBankTest(unittest.TestCase):
    def test_preferred_notes_keep_loop_targets_aliases_and_matching_irq_cadence(self):
        # The same boundary owns both failures: a full score may add loop
        # descriptors and use a coarser bank than its accepted short opening.
        for late_loop, seconds in ((False, .24), (True, .12)):
            with self.subTest(late_loop=late_loop), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "loops.mod"
                source.write_bytes(loop_module(late_loop))
                prepare(source, root / "full", bank_scope="score", protracker_loops=True)
                prepare(source, root / "preferred", seconds=seconds, bank_scope="score",
                        protracker_loops=True)
                preferred = json.loads((root / "preferred/arrangement.json").read_text())
                baseline = json.loads((root / "full/arrangement.json").read_text())
                receipt = combine(root / "full/arrangement.json",
                                  root / "preferred/arrangement.json", root / "combined")
                combined = json.loads((root / "combined/arrangement.json").read_text())
                banks = {entry["id"]: entry for entry in combined["pcm_bank"]}
                alias = banks[combined["ticks"][0]["pcm"][0]["sample"]]
                self.assertEqual(alias["original_instrument"], 1)
                self.assertEqual(alias["base_divisor"], 2)
                self.assertEqual(banks[alias["loop_target_id"]]["base_divisor"], 2)
                replacement = combined["ticks"][12 if late_loop else 6]["pcm"][0]
                self.assertFalse(replacement["trigger"])
                target = banks[replacement["loop_sample"]]
                self.assertEqual(target.get("original_sample", target["id"]), 2)
                for before, after in zip(baseline["ticks"], combined["ticks"]):
                    self.assertEqual(len(after["pcm"]), 4)
                    self.assertEqual([(v["volume"], v["trigger"]) for v in before["pcm"]],
                                     [(v["volume"], v["trigger"]) for v in after["pcm"]])
                # Explicitly initialize an already silent loop descriptor so
                # both references use the full score's eight-slot commit lead.
                expected = copy.deepcopy(preferred)
                expected["ticks"][0]["pcm"][3]["loop_sample"] = 0
                prefix, _ = expected_dac(expected)
                actual, _ = expected_dac(combined)
                np.testing.assert_array_equal(actual[:len(prefix) - 7], prefix[:-7])
                self.assertEqual(receipt["preferred_prefix_dac_mismatches"], 0)
                self.assertEqual(receipt["preferred_prefix_eof_slots_excluded"], 7)


if __name__ == "__main__":
    unittest.main()
