"""Exercise optional packing searches without changing decoded score bytes."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from pcm4_build import build, decode, normalize, pack, render_ticks
from pcm4_reference import expected_dac
from score_dictionary import decode_blocks, encode_blocks


class ScoreSearchTest(unittest.TestCase):
    def test_shortest_parse_can_reuse_overlapping_raw_phrases(self):
        # Sequential replacement commits an avoidable literal boundary near
        # the end. Reusing the same three raw phrases saves one encoded byte.
        blocks = [b"AADDADDAADDAADDAAAAADCCBAADCCBAADCCBAAAAAADCCBADDAAAAAAA"]
        old = encode_blocks(blocks, maximum=4, one_byte=True)
        optimal = encode_blocks(blocks, maximum=4, one_byte=True, optimal_parse=True)
        self.assertEqual(decode_blocks(old), blocks)
        self.assertEqual(decode_blocks(optimal), blocks)
        self.assertEqual(old["bytes"], 42)
        self.assertEqual(optimal["bytes"], 41)
        self.assertEqual(optimal["phrases"], old["phrases"])
        for one_byte in (False, True):
            escaped = [blocks[0] + bytes([0xC0, 0xFE, 0xFF]) * 16 + blocks[0]]
            packed = encode_blocks(escaped, one_byte=one_byte, optimal_parse=True)
            self.assertEqual(decode_blocks(packed), escaped)

    def test_aligned_rows_preserve_all_voices_offsets_loops_and_tick_lengths(self):
        ticks = []
        rows = (0, 1, 2, 3, 2, 3, 4, 5)
        for order in range(2):
            for index, row in enumerate(rows):
                states = [dict(sample=voice + 1, step=32 + index * 7 + voice,
                               volume=64 - voice * 8, trigger=index % 2 == 0,
                               offset=index * 3, offset_fraction=voice * 64,
                               loop_sample=4 - voice) for voice in range(4)]
                ticks.append(dict(order=order, row=row, duration_s=(.01, .02, .078125)[index % 3],
                                  pcm=states))
        rendered, variable = render_ticks(ticks)
        self.assertTrue(variable)
        expected = [(normalize(tick, True, True), tick["sample_count"]) for tick in rendered]
        for continuous in (False, True):
            for grouping in ("row", "rows:2", "rows:4", "12", "24", "32", "64"):
                raw = pack(rendered, grouping, True, True, True, continuous)
                compressed = encode_blocks(raw["blocks"], one_byte=True, optimal_parse=True)
                restored = dict(raw, blocks=decode_blocks(compressed))
                self.assertEqual(decode(restored, with_timing=True), expected)

    @unittest.skipUnless((Path.home() / ".local/bin/kickass").exists(),
                         "This build check needs KickAssembler")
    def test_builder_opt_in_search_keeps_decoder_and_complete_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = root / "source.bin"
            bank.write_bytes(bytes(range(16)) * 16)
            states = [dict(sample=1, step=64 + voice, volume=48, trigger=True,
                           offset=voice, offset_fraction=128, loop_sample=1)
                      for voice in range(4)]
            ticks = []
            for index in range(12):
                ticks.append(dict(order=0, row=index // 2, duration_s=.01,
                                  pcm=[dict(state, trigger=index % 2 == 0) for state in states]))
            source = root / "arrangement.json"
            arrangement = dict(duration_s=.12, pcm_rate_hz=985248/256, ticks=copy.deepcopy(ticks),
                               pcm_bank=[dict(id=1, data_file=str(bank), loop_start=16, loop_length=16)])
            source.write_text(json.dumps(arrangement))
            with self.assertRaisesRegex(ValueError, "independent loop-target timing"):
                build(source, root / "unsafe", "dictionary8", minimum_loop_span=64)
            receipt = build(source, root / "c64", "dictionary8", ("rows:2", "12"), True,
                            continuous_blocks=True)
            self.assertEqual(receipt["pcm_channels"], 4)
            self.assertEqual(receipt["ticks"], len(ticks))
            self.assertEqual(receipt["sample_timer_cycles"], 256)
            self.assertTrue(receipt["quantized_timeline_roundtrip_verified"])
            self.assertTrue(receipt["compression"]["dictionary_byte_roundtrip_verified"])
            self.assertTrue(receipt["compression"]["optimal_dictionary_parse"])
            self.assertTrue(receipt["compression"]["continuous_blocks"])
            self.assertTrue({"rows:2", "12"} <= receipt["compression"]["dictionary_alternatives"].keys())
            self.assertEqual(receipt["extended_score"], dict(sample_offsets=True, variable_ticks=True,
                             loop_targets=True, source_ticks=12, runtime_ticks=12))
            self.assertEqual(json.loads(source.read_text()), arrangement)

    @unittest.skipUnless((Path.home() / ".local/bin/kickass").exists(),
                         "This build check needs KickAssembler")
    def test_short_loop_span_repeats_same_period_and_guards_alias_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = root / "source.bin"
            bank.write_bytes(bytes(range(7)))
            ticks = [dict(order=0, row=index, duration_s=.02,
                          pcm=[dict(sample=1, step=255, volume=48, trigger=index == 0)
                               for _ in range(4)]) for index in range(12)]
            arrangement = dict(duration_s=.24, pcm_rate_hz=985248/256, ticks=ticks,
                               pcm_bank=[dict(id=1, data_file=str(bank), loop_start=0, loop_length=7)])
            source = root / "arrangement.json"
            source.write_text(json.dumps(arrangement))
            normal = build(source, root / "normal")
            shorter = build(source, root / "shorter", minimum_loop_span=64)
            self.assertEqual(normal["pcm_bank"]["stored_sample_bytes"], 259)
            self.assertEqual(shorter["pcm_bank"]["stored_sample_bytes"], 70)
            self.assertEqual(normal["program_end"] - shorter["program_end"], 189)
            streams = []
            for name, size in (("normal", 259), ("shorter", 70)):
                prepared = dict(arrangement, pcm_bank=[dict(id=1,
                    data_file=str(root / name / "sample-01.bin"), loop_start=0, loop_length=size)])
                streams.append(expected_dac(prepared)[0].tobytes())
            self.assertEqual(streams[0], streams[1])
            arrangement["pcm_bank"][0]["loop_target_id"] = 1
            source.write_text(json.dumps(arrangement))
            with self.assertRaisesRegex(ValueError, "independent loop-target timing"):
                build(source, root / "unsafe-alias", minimum_loop_span=64)


if __name__ == "__main__":
    unittest.main()
