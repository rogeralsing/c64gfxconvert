"""Source-backed pitch and recipe-preservation contracts for audition proposals."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mod-hybrid"))
from audition_instruments import recipe_for_instrument
from build_auditions import drum_substitution
from mod_reader import load_mod


class AuditionInstrumentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sources = HERE.parent / "mod-hybrid/sources"
        cls.cream = load_mod(sources / "cream-of-the-earth.mod")
        cls.hyper = load_mod(sources / "hyperbased.mod")

    def test_accepted_tonal_recipes_and_calibrated_roots_are_preserved(self):
        cases = [(self.cream, 10, "cream-of-the-earth/10-pulse-melody.json", 32.38197),
                 (self.hyper, 7, "hyperbased/07-pulse-lead.json", 40.0193),
                 (self.cream, 1, "cream-of-the-earth/01-kick.json", None),
                 (self.cream, 7, "cream-of-the-earth/07-bass.json", None)]
        for source, identifier, name, measured in cases:
            with self.subTest(instrument=name):
                path = HERE / "instruments" / name
                before = path.read_bytes()
                expected = json.loads(before)
                result = recipe_for_instrument(source, identifier)
                self.assertEqual(result["recipe"], expected)
                if measured is not None:
                    self.assertAlmostEqual(result["analysis"]["root_period_samples"], measured, delta=.05)
                self.assertEqual(result["analysis"]["decision"], "preserved_approved")
                result["recipe"]["control"] = 0
                self.assertEqual(recipe_for_instrument(source, identifier)["recipe"], expected)
                self.assertEqual(path.read_bytes(), before)
        chord_path = HERE / "instruments/hyperbased-full-sid/13-sid.json"
        chord = recipe_for_instrument(self.hyper, 13)
        self.assertEqual(chord["recipe"], json.loads(chord_path.read_text()))
        self.assertAlmostEqual(chord["analysis"]["root_period_samples"], 63.27907454)

    def test_measured_triads_use_audible_roots_instead_of_common_repeat_periods(self):
        for identifier, intervals in [(13, [0, 4, 7]), (14, [0, 3, 7]), (15, [0, 5, 7])]:
            with self.subTest(instrument=identifier):
                result = recipe_for_instrument(self.cream, identifier, preserve_approved=False)
                self.assertEqual(result["analysis"]["classification"], "chord")
                self.assertEqual(result["recipe"]["program"], "arpeggio")
                self.assertEqual(result["recipe"]["semitones"], intervals)
                self.assertTrue(31.5 < result["recipe"]["source_period_samples"] < 33)

    def test_monophonic_harmonics_do_not_become_a_false_triad(self):
        result = recipe_for_instrument(self.hyper, 7, preserve_approved=False)
        self.assertEqual(result["analysis"]["classification"], "tonal")
        self.assertEqual(result["recipe"]["program"], "pulse")
        self.assertAlmostEqual(result["analysis"]["root_period_samples"], 40.0193, delta=.1)

    def test_broadband_clap_uses_noise_and_ambiguous_octave_stays_sampled(self):
        clap = recipe_for_instrument(self.cream, 17, reference_period=214)
        self.assertEqual(clap["analysis"]["classification"], "noise")
        self.assertEqual(clap["recipe"]["program"], "noise")
        self.assertAlmostEqual(clap["recipe"]["duration_s"], .52)
        ambiguous = recipe_for_instrument(self.cream, 11)
        self.assertIsNone(ambiguous["recipe"])
        self.assertEqual(ambiguous["analysis"]["confidence"], "low")
        self.assertEqual(ambiguous["analysis"]["recommendation"], "sample")
        silent = recipe_for_instrument(self.cream, 16)
        self.assertEqual(silent["analysis"]["classification"], "silence")
        self.assertIsNone(silent["recipe"])

    def test_noisy_inharmonic_percussion_does_not_become_a_coincidental_triad(self):
        elysium = load_mod(HERE.parent / "mod-hybrid/sources/elysium.mod")
        result = recipe_for_instrument(elysium, 22)
        self.assertIn(result["analysis"]["classification"], ("noise", "complex"))
        self.assertNotIn("root_period_samples", result["analysis"])
        if result["recipe"] is not None:
            self.assertEqual(result["recipe"]["program"], "noise")

    def test_rejected_pitched_sources_do_not_become_kicks_from_spectral_classification(self):
        for slug, identifier in [("global-trash", 9), ("stardust-memories", 5)]:
            with self.subTest(source=slug, instrument=identifier):
                source = load_mod(HERE.parent / f"mod-hybrid/sources/{slug}.mod")
                analysis = recipe_for_instrument(source, identifier)["analysis"]
                self.assertIsNone(drum_substitution(source, identifier, analysis, {identifier: ""}))
        self.assertIsNone(drum_substitution(self.cream, 11, {}, {11: "string"}))


if __name__ == "__main__":
    unittest.main()
