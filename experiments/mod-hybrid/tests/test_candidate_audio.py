"""Keep quiet melody audible through the actual candidate build path."""
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

from build_release import build_candidate
from pcm4_reference import expected_dac, PCM_RATE


class CandidateAudioTest(unittest.TestCase):
    @unittest.skipUnless((HERE / "sources/guitar-slinger.mod").is_file()
                         and (Path.home() / ".local/bin/kickass").is_file(),
                         "This integration check needs the Guitar Slinger source and KickAssembler")
    def test_guitar_slinger_candidate_retains_quiet_melody(self):
        source = HERE / "sources/guitar-slinger.mod"
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         "584a8f11031f3c14695aa23325405e64f29c751f80e2607ce825d70ccc592406",
                         "The regression needs the verified, unmodified source MOD")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = build_candidate("guitar-slinger", root, 50.0, capture_audio=False)
            self.assertEqual(record["status"], "built", record)
            arrangement = json.loads((root / "guitar-slinger/arrangement.json").read_text())
            _, arithmetic = expected_dac(arrangement)
            loss = arithmetic["quantization"]
            with self.subTest(scope="complete 50-second mixture"):
                self.assertGreater(loss["snr_db"], 10.0, loss)
                self.assertLess(loss["musical_energy_erased_fraction"], 0.05, loss)

            # Exact native DAC agreement previously passed while final rounding
            # erased this quiet guitar phrase. Check actual output codes from
            # the delivered score, with other tracks muted, across the phrase.
            solo = copy.deepcopy(arrangement)
            for tick in solo["ticks"]:
                for channel, state in enumerate(tick["pcm"]):
                    if channel != 0:
                        state["volume"] = 0
            dac, _ = expected_dac(solo)
            for start in range(5, 30, 5):
                with self.subTest(phrase_start_s=start):
                    phrase = dac[round(start * PCM_RATE):round((start + 5) * PCM_RATE)]
                    self.assertGreater(float(np.mean(phrase != 8)), 0.25,
                                       "Quiet guitar phrase was rounded to neutral DAC output")


if __name__ == "__main__":
    unittest.main()
