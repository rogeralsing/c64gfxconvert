"""Source-layout contracts that must survive complete four-channel conversion."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mod_reader import load_mod
from pcm4_prepare import prepare


def source_module() -> bytes:
    data = bytearray(1084 + 1024 + 4)
    data[42:44] = (2).to_bytes(2, "big")
    data[45] = 64
    # Instrument 2 has no source data but can legitimately be selected with
    # positive volume. Its channel event must remain present and silent.
    data[75] = 64
    data[950] = 1
    data[1080:1084] = b"M.K."
    data[1084:1092] = bytes([1, 0xAC, 0x10, 0, 1, 0xAC, 0x20, 0])
    data[1114:1116] = bytes([0x0F, 0])  # Row 1, channel 4: F00.
    data[-4:] = bytes([127, 128, 64, 192])
    return bytes(data)


class ModLayoutTest(unittest.TestCase):
    def test_zero_suffix_is_padding_after_complete_declared_samples(self):
        payload = source_module()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "padded.mod"
            path.write_bytes(payload + bytes(1804))
            mod = load_mod(path)
            self.assertEqual(mod["samples"][0]["data"], bytes([127, 128, 64, 192]))
            self.assertEqual(mod["samples"][1]["data"], b"")
            self.assertEqual(mod["orders"], [0])
            self.assertEqual(len(mod["patterns"]), 1)
            self.assertEqual(mod["patterns"][0][0][0],
                             {"sample": 1, "period": 428, "effect": 0, "param": 0})
            self.assertEqual(mod["layout"]["declared_payload_bytes"], len(payload))
            self.assertEqual(mod["layout"]["trailing_zero_padding_bytes"], 1804)
            self.assertEqual(mod["layout"]["trailing_zero_padding_sha256"],
                             hashlib.sha256(bytes(1804)).hexdigest())
            self.assertEqual(mod["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_nonzero_suffix_and_truncated_sample_remain_invalid(self):
        payload = source_module()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.mod"
            for data, message in [(payload + b"\0\x01", "Unexpected data after samples"),
                                  (payload[:-1], "Invalid sample 1")]:
                with self.subTest(error=message):
                    path.write_bytes(data)
                    with self.assertRaisesRegex(ValueError, message):
                        load_mod(path)

    def test_empty_instrument_keeps_its_channel_event_with_a_neutral_bank(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "empty.mod"
            path.write_bytes(source_module())
            summary = prepare(path, root / "prepared", bank_scope="score", protracker_loops=True)
            arrangement = json.loads((root / "prepared/arrangement.json").read_text())
            empty = next(item for item in arrangement["pcm_bank"] if item["id"] == 2)
            self.assertEqual(empty["original_bytes"], 0)
            self.assertEqual(Path(empty["data_file"]).read_bytes(), bytes([8]))
            self.assertEqual(empty["loop_length"], 0)
            self.assertEqual(summary["triggers_per_track"], [1, 1, 0, 0])
            self.assertTrue(all(len(tick["pcm"]) == 4 for tick in arrangement["ticks"]))
            voice = arrangement["ticks"][0]["pcm"][1]
            self.assertEqual((voice["sample"], voice["volume"], voice["trigger"]), (2, 64, True))
            self.assertGreater(voice["step"], 0)
            self.assertEqual(path.read_bytes(), source_module())

    def test_memory_preparation_reduces_reusable_bank_without_removing_music(self):
        payload = bytearray(source_module()[:-4])
        payload[42:44] = (2048).to_bytes(2, "big")
        payload.extend(bytes(range(256)) * 16)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "memory.mod"
            path.write_bytes(payload)
            normal = prepare(path, root / "normal", bank_scope="score", protracker_loops=True)
            reduced = prepare(path, root / "reduced", bank_scope="score", protracker_loops=True,
                              divisor_scale=2)
            self.assertLess(reduced["sample_bank_bytes_before_loop_expansion"],
                            normal["sample_bank_bytes_before_loop_expansion"] * 0.51)
            self.assertEqual(reduced["triggers_per_track"], [1, 1, 0, 0])
            self.assertEqual(reduced["duration_s"], 0.14)
            self.assertLess(reduced["sample_preparation"]["maximum_cursor_pitch_error_cents"], 10)
            arranged = json.loads((root / "reduced/arrangement.json").read_text())
            first = arranged["ticks"][0]["pcm"]
            self.assertEqual([(v["sample"], v["volume"]) for v in first[:2]], [(1, 64), (2, 64)])
            self.assertTrue(all(len(tick["pcm"]) == 4 for tick in arranged["ticks"]))
            self.assertEqual(path.read_bytes(), payload)
            for scale in (0.9, float("nan"), float("inf")):
                with self.assertRaisesRegex(ValueError, "divisor_scale"):
                    prepare(path, root / "invalid", divisor_scale=scale)


if __name__ == "__main__":
    unittest.main()
