"""Accept MOD source padding without admitting nonzero or truncated payloads."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mod-hybrid"))

from mod_reader import load_mod


def source_module() -> bytes:
    data = bytearray(1084 + 1024 + 4)
    data[42:44] = (2).to_bytes(2, "big")
    data[45] = 64
    data[950] = 1
    data[1080:1084] = b"M.K."
    data[1084:1088] = bytes([1, 0xAC, 0x10, 0])
    data[-4:] = bytes([127, 128, 64, 192])
    return bytes(data)


class SourcePaddingTest(unittest.TestCase):
    def test_zero_suffix_preserves_declared_samples_notes_and_source_identity(self):
        payload = source_module()
        padding = bytes(1804)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "padded.mod"
            path.write_bytes(payload + padding)
            mod = load_mod(path)
            self.assertEqual(mod["samples"][0]["data"], bytes([127, 128, 64, 192]))
            self.assertEqual(mod["orders"], [0])
            self.assertEqual(len(mod["patterns"]), 1)
            self.assertEqual(mod["patterns"][0][0][0],
                             {"sample": 1, "period": 428, "effect": 0, "param": 0})
            self.assertEqual(mod["layout"], {"declared_payload_bytes": len(payload),
                             "trailing_zero_padding_bytes": len(padding),
                             "trailing_zero_padding_sha256": hashlib.sha256(padding).hexdigest()})
            self.assertEqual(mod["sha256"], hashlib.sha256(payload + padding).hexdigest())

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


if __name__ == "__main__":
    unittest.main()
