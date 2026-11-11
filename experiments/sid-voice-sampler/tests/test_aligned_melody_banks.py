"""Loop rotation must preserve emitted bytes through gain and mute changes."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aligned_melody_banks import align


def signal(samples):
    """Independent oracle: an unbounded source position maps to a periodic wave."""
    banks = {bank["id"]: bank for bank in samples["banks"]}
    output, position = bytearray(), 0
    for (step, trigger, variant), count in zip(samples["frames"], samples["metadata"]["frame_sample_counts_exact"]):
        bank = banks[variant & 127]
        if trigger:
            position = 0
        for _ in range(count):
            index = position // 256
            if index >= bank["real_end"]:
                index = bank["loop_start"] + (index - bank["real_end"]) % (bank["real_end"] - bank["loop_start"])
            output.append(128 if variant & 128 else bank["data"][index])
            position += step
    return bytes(output)


def fixture(directory, waves, end, loop, frames, counts):
    sources = directory / "original"
    sources.mkdir()
    banks = []
    for identifier, values in enumerate(waves):
        path = sources / f"gain-{identifier}.asm"
        path.write_text("// Immutable original fixture bank.\n")
        banks.append(dict(id=identifier, data=values, sha256=hashlib.sha256(values).hexdigest(),
                          real_end=end, loop_start=loop, asm_path=path, instrument=1, divisor=1))
    samples = dict(frames=frames, banks=banks,
                   metadata=dict(frames=len(frames), frame_sample_counts_exact=counts,
                                 input_codes=sum(counts), sample_rate_hz=985248 / 126,
                                 sample_period_cycles=126))
    samples["metadata"]["expected_input_sha256"] = hashlib.sha256(signal(samples)).hexdigest()
    return samples


class AlignedMelodyBanksTest(unittest.TestCase):
    def test_short_period_rotation_preserves_fraction_gain_mute_and_retriggers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            waves = [bytes([11, 31, 51, 71, 91, 111, 131]) + bytes([128]) * 249,
                     bytes([20, 40, 60, 80, 100, 120, 140]) + bytes([128]) * 249]
            samples = fixture(root, waves, 7, 2,
                [(255, 1, 0), (127, 0, 1), (201, 0, 128),
                 (244, 0, 1), (99, 1, 0), (255, 0, 1)], [128] * 6)
            original = copy.deepcopy(samples)
            source_files = {bank["asm_path"]: bank["asm_path"].read_bytes() for bank in samples["banks"]}
            expected = signal(samples)
            result = align(samples, root / "candidate")
            self.assertEqual(signal(result), expected)
            self.assertEqual([(b["real_end"], b["loop_start"]) for b in result["banks"]], [(256, 251)] * 2)
            self.assertEqual(result["alignment_proof"]["samples_compared"], 768)
            self.assertEqual(samples, original)
            self.assertEqual(source_files, {path: path.read_bytes() for path in source_files})
            self.assertTrue(all(bank["asm_path"].is_relative_to(root.resolve() / "candidate/aligned-instruments")
                                for bank in result["banks"]))

    def test_trimmed_gain_prefix_is_not_required_to_contain_an_unread_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            full = bytes(64 + n % 127 for n in range(600)) + bytes([128]) * 168
            prefix = bytes(80 + n % 95 for n in range(256))
            samples = fixture(root, [full, prefix], 600, 500,
                [(255, 1, 1), (255, 0, 0), (255, 0, 0),
                 (128, 0, 129), (255, 0, 0), (255, 1, 1)], [100, 256, 256, 256, 256, 100])
            expected = signal(samples)
            result = align(samples, root / "candidate")
            self.assertEqual(signal(result), expected)
            self.assertEqual(len(result["banks"][1]["data"]), 256)
            self.assertEqual(result["banks"][1]["loop_start"], 668)
            self.assertEqual(result["banks"][1]["real_end"], 768)
            # A stale or corrupt claimed input cannot produce a successful proof.
            samples["metadata"]["expected_input_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "Independent replay differs"):
                align(samples, root / "invalid")
            self.assertFalse((root / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
