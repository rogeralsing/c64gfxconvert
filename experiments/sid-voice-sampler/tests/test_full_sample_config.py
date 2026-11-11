"""Public full-sample configuration, inactive prefixes and accepted defaults."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mod-hybrid"))
from full_sample_channel import prepare_full_samples
from full_score import pack_score
from full_sid_score import prepare_full_sid
import build_mod_hybrid as hybrid
from mod_reader import load_mod
from timeline import build_timeline


def fixture(states):
    samples = [{"length": 512, "data": bytes([64]) * 512,
                "loop_start": 0, "loop_length": 2} for _ in range(2)]
    mod = {"sha256": "configuration-fixture", "samples": samples, "channels": 4}
    empty = dict(playing_sample=0, period=0, volume=0, trigger=False, offset=0)
    ticks = []
    for index, state in enumerate(states):
        channels = [copy.deepcopy(empty) for _ in range(4)]
        channels[0].update(state)
        ticks.append(dict(time_s=index * .02, duration_s=.02, channels=channels))
    return mod, ticks


class FullSampleConfigurationTest(unittest.TestCase):
    def test_initial_silence_is_neutral_without_a_fake_note_or_cursor_step(self):
        mod, ticks = fixture([{}, {}, dict(playing_sample=1, period=1000, volume=41, trigger=True),
                              dict(playing_sample=1, period=1000, volume=41)])
        receipt = {"sha256": mod["sha256"], "title_slug": "configuration-fixture"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare_full_samples(mod, ticks, root / "out", channel=0,
                source_receipt=receipt, library_dir=root / "library", extra_decimation={1: 1},
                gain_quantum=1, allow_initial_silence=True)
            for step, trigger, variant in prepared["frames"][:2]:
                self.assertEqual((step, trigger), (0, 0))
                self.assertTrue(variant & 128)
                self.assertLess(variant & 127, len(prepared["banks"]))
            actual = (root / "out/expected-input.bin").read_bytes()
            self.assertEqual(actual[:313], bytes([128]) * 313)
            self.assertEqual(actual[313], 169)  # 128 + round(.5 * 127 * 41 / 64).
            self.assertEqual(prepared["metadata"]["triggers"], 1)
            self.assertEqual(prepared["metadata"]["initial_silent_ticks"], 2)
            with self.assertRaisesRegex(ValueError, "initial"):
                prepare_full_samples(mod, ticks, root / "strict", channel=0,
                    source_receipt=receipt, library_dir=root / "strict-library",
                    extra_decimation={1: 1}, gain_quantum=1)
            later_silence = ticks + [dict(time_s=.08, duration_s=.02,
                                         channels=copy.deepcopy(ticks[0]["channels"]))]
            with self.assertRaisesRegex(ValueError, "initial"):
                prepare_full_samples(mod, later_silence, root / "late", channel=0,
                    source_receipt=receipt, library_dir=root / "late-library",
                    extra_decimation={1: 1}, gain_quantum=1, allow_initial_silence=True)

    def test_gain_palette_is_explicit_and_existing_library_files_are_preserved(self):
        mod, ticks = fixture([dict(playing_sample=1, period=1000, volume=41, trigger=True),
                              dict(playing_sample=2, period=1000, volume=28, trigger=True)])
        receipt = {"sha256": mod["sha256"], "title_slug": "configuration-fixture"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = dict(channel=0, source_receipt=receipt, extra_decimation={1: 1, 2: 1})
            exact = prepare_full_samples(mod, ticks, root / "exact", library_dir=root / "exact-library",
                                         gain_quantum=1, **common)
            palette = prepare_full_samples(mod, ticks, root / "palette", library_dir=root / "palette-library",
                                           gain_quantum={1: 1, 2: 16}, **common)
            self.assertEqual({b["instrument"]: b["gain"] for b in exact["banks"]}, {1: 41, 2: 28})
            self.assertEqual({b["instrument"]: b["gain"] for b in palette["banks"]}, {1: 41, 2: 32})
            self.assertEqual([b["data"][0] for b in exact["banks"]], [169, 156])
            self.assertEqual([b["data"][0] for b in palette["banks"]], [169, 160])
            self.assertEqual(palette["metadata"]["gain_quantization_error_units"], [0, 4])
            files = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                     for path in (root / "palette-library").iterdir()}
            prepare_full_samples(mod, ticks, root / "repeat", library_dir=root / "palette-library",
                                 gain_quantum={1: 1, 2: 16}, **common)
            self.assertEqual(files, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files})
            first = next(path for path in files if path.suffix == ".asm")
            first.write_text("// Deliberate existing instrument edit.\n")
            with self.assertRaisesRegex(ValueError, "preserve"):
                prepare_full_samples(mod, ticks, root / "protected", library_dir=root / "palette-library",
                                     gain_quantum={1: 1, 2: 16}, **common)
            self.assertEqual(first.read_text(), "// Deliberate existing instrument edit.\n")
            for quantum in (0, {1: 1}):
                with self.subTest(quantum=quantum), self.assertRaisesRegex(ValueError, "gain_quantum"):
                    prepare_full_samples(mod, ticks, root / "invalid", library_dir=root / "invalid-library",
                                         gain_quantum=quantum, **common)

    def test_preferred_divisor_is_fixed_for_each_note_and_mute_keeps_its_cursor_scale(self):
        mod, ticks = fixture([
            dict(playing_sample=1, period=1000, volume=64, trigger=True),
            dict(playing_sample=1, period=800, volume=0),
            dict(playing_sample=1, period=800, volume=64),
            dict(playing_sample=1, period=100, volume=0, trigger=True),
            dict(playing_sample=1, period=1000, volume=41),
            dict(playing_sample=1, period=1000, volume=64, trigger=True),
            dict(playing_sample=1, period=800, volume=64),
        ])
        mod["samples"][0]["data"] = bytes(range(128)) * 4
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = prepare_full_samples(mod, ticks, root / "out", channel=0,
                source_receipt={"sha256": mod["sha256"], "title_slug": "configuration-fixture"},
                library_dir=root / "library", extra_decimation={1: 1}, gain_quantum=1,
                preferred_divisors={1: 1})
            banks = prepared["banks"]
            selected = [banks[variant & 127]["divisor"] for _, _, variant in prepared["frames"]]
            self.assertEqual(selected, [1, 1, 1, 5, 5, 1, 1])
            self.assertEqual([step for step, _, _ in prepared["frames"]], [116, 145, 145, 232, 23, 116, 145])
            self.assertTrue(prepared["frames"][3][2] & 128)
            self.assertEqual([trigger for _, trigger, _ in prepared["frames"]], [1, 0, 0, 1, 0, 1, 0])
            actual = (root / "out/expected-input.bin").read_bytes()
            self.assertEqual(actual[156:313], bytes([128]) * 157)
            # The muted tick advances phase: (156*116+157*145)>>8 =159,
            # source value31 maps to rounded eight-bit code159 at volume64.
            self.assertEqual(actual[313], 159)
            self.assertEqual(actual[782], 128)  # The next real trigger resets phase.

    @unittest.skipUnless((HERE.parent / "mod-hybrid/sources/hyperbased.mod").exists(),
                         "The pinned Hyperbased MOD source is required")
    def test_default_hyperbased_input_program_and_library_remain_byte_identical(self):
        mod = load_mod(HERE.parent / "mod-hybrid/sources/hyperbased.mod")
        ticks = build_timeline(mod)["ticks"]
        reference = HERE / "results/hyperbased-full"
        accepted = json.loads((reference / "verification.json").read_text())
        library = HERE / "instruments/hyperbased-full-samples"
        before = {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                  for path in library.iterdir() if path.is_file()}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            samples = prepare_full_samples(mod, ticks, out)
            self.assertEqual(json.loads(json.dumps(samples["metadata"])), accepted["pcm_input"])
            self.assertEqual(hashlib.sha256((out / "expected-input.bin").read_bytes()).hexdigest(),
                             accepted["pcm_input"]["expected_input_sha256"])
            synth = prepare_full_sid(mod, ticks, out)
            settings = [{"sustain": level, "pulse_width": width}
                        for level, width in zip(synth["voice_levels"], synth["voice_pulse_widths"])]
            pack_score(samples["frames"], synth["rows"], samples["banks"], out, len(ticks),
                       sid_settings=settings)
            compiled = hybrid.base.reference.assemble("full-song-player", out)
            self.assertEqual(compiled["program_sha256"], accepted["build"]["program_sha256"])
            self.assertEqual(Path(compiled["program"]).read_bytes(), (reference / "player.prg").read_bytes())
        self.assertEqual(before, {path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                                  for path in before})


if __name__ == "__main__":
    unittest.main()
