"""Keep SID accompaniment quiet enough for the unchanged sampled tracks."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from channel_resid import ARCHIVE, make_digiboost_sid
from hvsc_hybrid import arrangement, sid_program, target
from vice_profile import PAL_CLOCK, RATE


RESULTS = HERE / "results/rebuild/hvsc-hybrid"
INPUTS = (HERE / "sources/guitar-slinger.mod",
          RESULTS / "pcm/arrangement.json", RESULTS / "hybrid/arrangement.json", ARCHIVE)


def render_two_voices(programs: list) -> np.ndarray:
    """Measure native envelopes with the shared master volume held fixed."""
    chip = make_digiboost_sid(RATE)
    chip.write(24, 8)
    chip.clock(round(.1 * PAL_CLOCK))
    blocks, previous = [], 0
    for index, voices in enumerate(zip(*programs)):
        for voice, writes in enumerate(voices):
            for register, value in writes:
                chip.write(7 * voice + register, value)
        boundary = round((index + 1) * PAL_CLOCK / 50)
        blocks.append(np.asarray(chip.clock(boundary - previous), dtype=np.float64))
        previous = boundary
    return np.concatenate(blocks)


class HybridBalanceTest(unittest.TestCase):
    @unittest.skipUnless(all(path.is_file() for path in INPUTS)
                         and shutil.which("clang++"),
                         "This integration check needs the local hybrid inputs and VICE reSID source")
    def test_combined_phrase_lowers_sid_without_rewriting_samples_or_melody(self):
        _, ticks, cycles, _ = target()
        previous = json.loads((RESULTS / "hybrid/arrangement.json").read_text())
        patch = previous["donor_patch"]
        pcm = json.loads((RESULTS / "pcm/arrangement.json").read_text())
        original_banks = {bank["id"]: bank for bank in pcm["pcm_bank"]}
        unscaled = [sid_program(patch, ticks, channel, cycles) for channel in (0, 2)]

        with tempfile.TemporaryDirectory() as directory:
            # Offset preparation writes a reusable suffix beside its bank.
            # Keep that real production path inside the test's temporary tree.
            local_pcm = copy.deepcopy(pcm)
            for bank in local_pcm["pcm_bank"]:
                destination = Path(directory) / Path(bank["data_file"]).name
                shutil.copyfile(bank["data_file"], destination)
                bank["data_file"] = str(destination)
            mixed = arrangement(patch, ticks, cycles, local_pcm, False)
            solo = arrangement(patch, ticks, cycles, local_pcm, True)
            balanced = [[tick["sid"][voice]["writes"] for tick in mixed["ticks"]]
                        for voice in range(2)]

            # This balance control must not change the standalone audition or
            # the pitch, pulse, gate and hard-restart events in either voice.
            self.assertEqual([tick["sid"][0]["writes"] for tick in solo["ticks"]], unscaled[0])
            for voice in range(2):
                before_sr = after_sr = 0
                for index, (before, after) in enumerate(zip(unscaled[voice], balanced[voice])):
                    with self.subTest(voice=voice, tick=index):
                        self.assertEqual([write for write in before if write[0] != 6],
                                         [write for write in after if write[0] != 6])
                        for register, value in before:
                            if register == 6:
                                before_sr = value
                        for register, value in after:
                            if register == 6:
                                after_sr = value
                        self.assertEqual(before_sr & 15, after_sr & 15, "Donor release must stay unchanged")

            # Compare PCM playback with its actual preparation input. The
            # 9xx chord suffix may change the sample ID, but not the bytes,
            # cursor step, note trigger or track level delivered to the mixer.
            source_ticks = [tick for tick in pcm["ticks"]
                            if 5.5 - 1e-7 <= tick["time_s"] < 14.46 - 1e-7]
            banks = {bank["id"]: bank for bank in mixed["pcm_bank"]}
            self.assertEqual(len(mixed["ticks"]), len(source_ticks))
            for output, source in zip(mixed["ticks"], source_ticks):
                for voice, channel in enumerate((1, 3)):
                    actual, expected = output["pcm"][voice], source["pcm"][channel]
                    self.assertEqual({key: actual[key] for key in ("step", "volume", "trigger")},
                                     {key: expected[key] for key in ("step", "volume", "trigger")})
                    expected_bytes = Path(original_banks[expected["sample"]]["data_file"]).read_bytes()
                    expected_bytes = expected_bytes[expected.get("offset", 0):]
                    self.assertEqual(Path(banks[actual["sample"]]["data_file"]).read_bytes(), expected_bytes)

            # Register equality alone previously admitted a mix dominated by
            # SID. Measure the complete phrase using real reSID envelopes,
            # including the attack/decay that sustain scaling cannot multiply.
            before = render_two_voices(unscaled)[round(.2 * RATE):]
            after = render_two_voices(balanced)[round(.2 * RATE):]
            ratio = float(np.std(after) / np.std(before))
            self.assertLess(ratio, .55, f"SID phrase remains too loud relative to unchanged PCM: {ratio:.4f}")


if __name__ == "__main__":
    unittest.main()
