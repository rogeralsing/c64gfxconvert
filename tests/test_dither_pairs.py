"""Behavioral CLI checks for vertical dither pairs and their spatial neighbors."""

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "analyze-dither-pairs.py"
COLORS = [
    (0, 0, 0), (255, 255, 255), (120, 120, 120), (101, 101, 101),
    (100, 100, 100), (255, 0, 0), (0, 255, 0), (0, 0, 255),
    (255, 255, 0), (0, 255, 255), (255, 0, 255), (64, 0, 0),
    (0, 64, 0), (0, 0, 64), (128, 64, 0), (64, 0, 128),
]
ROWS = [[0, 1, 2], [1, 0, 2], [0, 2, 1], [1, 2, 0]]
PAIR_COUNTS = {"0-1": 5, "2-2": 2, "0-2": 1, "2-1": 1}
EDGE_COUNTS = {
    ("0-1", "2-2"): (3, 2, 5),
    ("0-1", "0-2"): (1, 0, 1),
    ("0-2", "2-1"): (1, 0, 1),
}
SELF_ADJACENCY = {"0-1": {"horizontal": 1, "vertical": 1, "count": 2}}


class DitherPairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.palette = self.root / "test.vpl"
        self.palette.write_text("# Test palette\n" + "\n".join(
            " ".join(f"{value:02X}" for value in color) for color in COLORS) + "\n")

    def indexed_image(self, name, rows):
        image = Image.new("P", (len(rows[0]) * 2, len(rows)))
        image.putpalette([value for color in COLORS for value in color] + [0] * (768 - 48))
        image.putdata([color for row in rows for color in row for _ in range(2)])
        source = self.root / name
        image.save(source)
        return source

    def run_analyzer(self, sources, output, min_count=1, min_edge_count=1):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, sources), "-o", str(output),
             "--palette", str(self.palette), "--min-count", str(min_count),
             "--min-edge-count", str(min_edge_count)],
            capture_output=True, text=True, timeout=20,
        )

    def analyze(self, sources, output, **thresholds):
        result = self.run_analyzer(sources, output, **thresholds)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((output / "analysis.json").read_text())

    def edge_counts(self, edges):
        counts = {tuple(sorted((edge["a"], edge["b"]))):
                  (edge["horizontal"], edge["vertical"], edge["count"]) for edge in edges}
        self.assertEqual(len(counts), len(edges), "Undirected edges must not appear twice.")
        return counts

    def test_all_vertical_phases_and_nonoverlapping_spatial_neighbors(self):
        source = self.indexed_image("pairs.png", ROWS)

        data = self.analyze([source], self.root / "out")

        self.assertEqual(len(data["images"]), 1)
        image = data["images"][0]
        self.assertEqual(image["pair_counts"], PAIR_COUNTS)
        self.assertEqual(image["phase_pair_counts"], [
            {"0-1": 4, "2-2": 2}, {"0-1": 1, "0-2": 1, "2-1": 1},
        ])
        self.assertEqual(image["orientation_counts"], {
            "0-1": {"canonical": 2, "reversed": 3},
            "2-2": {"canonical": 2, "reversed": 0},
            "0-2": {"canonical": 1, "reversed": 0},
            "2-1": {"canonical": 1, "reversed": 0},
        })
        # Two horizontal neighbors per pair row yield six contacts. Only y=0
        # can connect to y+2, yielding three additional, nonoverlapping contacts.
        self.assertEqual(self.edge_counts(image["edges"]), EDGE_COUNTS)
        self.assertEqual(image["self_adjacency"], SELF_ADJACENCY)
        aggregate = data["aggregate"]
        self.assertEqual(aggregate["pair_total"], 9)
        self.assertEqual(aggregate["mixed_pair_total"], 7)
        self.assertEqual(aggregate["solid_pair_total"], 2)
        pairs = {pair["id"]: pair for pair in aggregate["pairs"]}
        self.assertEqual({key: pair["count"] for key, pair in pairs.items()}, PAIR_COUNTS)
        self.assertEqual(pairs["2-1"]["colors"], [2, 1])
        self.assertEqual(pairs["0-1"]["canonical_count"], 2)
        self.assertEqual(pairs["0-1"]["reversed_count"], 3)
        self.assertFalse(pairs["2-2"]["mixed"])
        self.assertTrue(all(pair["image_count"] == 1 for pair in pairs.values()))
        self.assertEqual(self.edge_counts(aggregate["edges"]), EDGE_COUNTS)
        self.assertEqual(aggregate["self_adjacency"], SELF_ADJACENCY)

    def test_close_luminance_uses_index_order_and_decoded_duplicates_count_once(self):
        source = self.indexed_image("indexed.png", [[4, 3, 3], [3, 4, 3]])
        duplicate = self.root / "rgb.png"
        with Image.open(source) as image:
            image.convert("RGB").save(duplicate)
        self.assertNotEqual(source.read_bytes(), duplicate.read_bytes())

        data = self.analyze([source, duplicate], self.root / "out")

        self.assertEqual(len(data["images"]), 1)
        image = data["images"][0]
        self.assertEqual(image["aliases"], [{"id": 2, "source": str(duplicate.resolve())}])
        self.assertEqual(image["pair_counts"], {"3-4": 2, "3-3": 1})
        self.assertEqual(image["orientation_counts"]["3-4"], {"canonical": 1, "reversed": 1})
        aggregate = data["aggregate"]
        self.assertEqual(aggregate["pair_total"], 3)
        pairs = {pair["id"]: pair for pair in aggregate["pairs"]}
        self.assertEqual(pairs["3-4"]["colors"], [3, 4])
        self.assertEqual(pairs["3-4"]["count"], 2)
        self.assertEqual(pairs["3-4"]["image_count"], 1)
        self.assertEqual(self.edge_counts(aggregate["edges"]), {
            ("3-3", "3-4"): (1, 0, 1),
        })
        self.assertEqual(image["self_adjacency"], {
            "3-4": {"horizontal": 1, "vertical": 0, "count": 1},
        })
        self.assertEqual(aggregate["self_adjacency"], image["self_adjacency"])

    def test_virtual_colors_mix_linear_light_and_export_matching_csv_metadata(self):
        sources = [self.indexed_image("forward.png", [[0], [1]]),
                   self.indexed_image("reversed.png", [[1], [0]]),
                   self.indexed_image("solid.png", [[2], [2]])]
        output = self.root / "virtual-colors"

        data = self.analyze(sources, output)

        aggregate = data["aggregate"]
        self.assertEqual(aggregate["pair_total"], 3)
        self.assertEqual(aggregate["mixed_pair_total"], 2)
        self.assertEqual(aggregate["solid_pair_total"], 1)
        self.assertEqual([image["pair_counts"] for image in data["images"]],
                         [{"0-1": 1}, {"0-1": 1}, {"2-2": 1}])
        self.assertEqual(data["images"][0]["orientation_counts"]["0-1"],
                         {"canonical": 1, "reversed": 0})
        self.assertEqual(data["images"][1]["orientation_counts"]["0-1"],
                         {"canonical": 0, "reversed": 1})
        self.assertEqual(aggregate["edges"], [])
        self.assertEqual(aggregate["self_adjacency"], {})
        pairs = {pair["id"]: pair for pair in aggregate["pairs"]}
        self.assertEqual({key: pair["count"] for key, pair in pairs.items()}, {"0-1": 2, "2-2": 1})
        self.assertEqual(pairs["0-1"]["image_count"], 2)
        # Independent reference anchors: half black/white has Y=0.5. Gray 120
        # has Y=0.18782077230067777 under the standard sRGB transfer function.
        expected = {
            "0-1": ([188, 188, 188], "#BCBCBC", 0.5, 76.06926101415557),
            "2-2": ([120, 120, 120], "#787878", 0.18782077230067777, 50.43126613670571),
        }
        with (output / "pairs.csv").open(newline="") as stream:
            csv_pairs = {row["id"]: row for row in csv.DictReader(stream)}
        for key, (rgb, hex_color, luminance, lightness) in expected.items():
            with self.subTest(pair=key):
                self.assertEqual(pairs[key]["virtual_rgb"], rgb)
                self.assertEqual(pairs[key]["virtual_hex"], hex_color)
                self.assertAlmostEqual(pairs[key]["luminance"], luminance, places=12)
                self.assertAlmostEqual(pairs[key]["lightness"], lightness, places=10)
                self.assertEqual(csv_pairs[key]["virtual_hex"], hex_color)
                self.assertAlmostEqual(float(csv_pairs[key]["luminance"]), luminance, places=12)

    def test_thresholds_keep_raw_counts_and_never_bridge_rare_nodes(self):
        source = self.indexed_image("thresholds.png", ROWS)
        cases = [(2, 3, {"0-1", "2-2"}, {("0-1", "2-2")}), (6, 1, set(), set())]
        for min_count, min_edge_count, retained_pairs, retained_edges in cases:
            with self.subTest(min_count=min_count, min_edge_count=min_edge_count):
                data = self.analyze([source], self.root / f"out-{min_count}",
                                    min_count=min_count, min_edge_count=min_edge_count)

                aggregate = data["aggregate"]
                self.assertEqual({pair["id"]: pair["count"] for pair in aggregate["pairs"]},
                                 PAIR_COUNTS)
                self.assertEqual(self.edge_counts(aggregate["edges"]), EDGE_COUNTS)
                self.assertEqual(aggregate["self_adjacency"], SELF_ADJACENCY)
                self.assertEqual({pair["id"] for pair in aggregate["pairs"] if pair["retained"]},
                                 retained_pairs)
                self.assertEqual({tuple(sorted((edge["a"], edge["b"])))
                                  for edge in aggregate["edges"] if edge["retained"]}, retained_edges)

    def test_unknown_palette_colors_and_broken_double_pixels_fail_before_output(self):
        valid = self.indexed_image("valid.png", ROWS)
        with Image.open(valid) as image:
            rgb = image.convert("RGB")
        unknown = rgb.copy()
        unknown.putpixel((0, 0), (13, 37, 71))
        unknown.putpixel((1, 0), (13, 37, 71))
        broken = rgb.copy()
        broken.putpixel((1, 0), COLORS[1])
        for name, image in (("unknown", unknown), ("broken", broken)):
            with self.subTest(case=name):
                source = self.root / f"{name}.png"
                image.save(source)
                original = source.read_bytes()
                output = self.root / f"out-{name}"

                result = self.run_analyzer([source], output)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("palette" if name == "unknown" else "2x1", result.stderr.lower())
                self.assertFalse(output.exists())
                self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
