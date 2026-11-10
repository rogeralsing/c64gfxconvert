"""Exercise optional palette snapping through the multicolor extractor CLI."""

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "extract-multicolor.py"
COLORS = [
    (0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0),
    (0, 0, 255), (0, 255, 255), (255, 0, 255), (255, 255, 0),
    (32, 32, 32), (64, 64, 64), (96, 96, 96), (128, 128, 128),
    (160, 160, 160), (192, 192, 192), (255, 128, 0), (0, 128, 128),
]


class C64PaletteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_extractor(self, source, output, palette):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(source), "--output-dir", str(output),
             "--cell", "2x1", "--palette", str(palette)],
            capture_output=True, text=True, timeout=20,
        )

    def palette_lines(self):
        return [" ".join(f"{channel:02X}" for channel in color) for color in COLORS]

    def test_nearest_palette_preserves_pairs_dimensions_and_alpha_without_dithering(self):
        palette = self.root / "test.vpl"
        lines = self.palette_lines()
        lines = [line + (" 0F" if index % 2 else "") for index, line in enumerate(lines)]
        palette.write_text("# Independent test palette\n\n" + "\n".join(lines) + "\n")
        samples = [(254, 1, 1), (1, 254, 1), (1, 1, 254), (254, 254, 254),
                   (1, 1, 1), (127, 127, 127), (250, 125, 2), (3, 126, 130), (16, 16, 16)]
        # The final sample is equally far from black and gray 32: first palette
        # entry wins. Channel extremes also catch unsigned-distance overflow.
        expected_colors = [COLORS[index] for index in (2, 3, 4, 1, 0, 11, 14, 15, 0)]
        alpha = [0, 1, 17, 63, 127, 128, 191, 254, 255]

        for mode in ("RGB", "RGBA"):
            with self.subTest(mode=mode):
                source = self.root / f"source-{mode}.png"
                image = Image.new(mode, (6, 3))
                pixels = [color + ((alpha[index],) if mode == "RGBA" else ())
                          for index, color in enumerate(samples)]
                image.putdata([pixel for pixel in pixels for _ in range(2)])
                image.save(source)
                original = source.read_bytes()
                output = self.root / f"out-{mode}"

                result = self.run_extractor(source, output, palette)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                expected = Image.new(mode, (6, 3))
                pixels = [color + ((alpha[index],) if mode == "RGBA" else ())
                          for index, color in enumerate(expected_colors)]
                expected.putdata([pixel for pixel in pixels for _ in range(2)])
                with Image.open(output / source.name) as actual:
                    self.assertEqual(actual.size, (6, 3))
                    self.assertEqual(actual.mode, mode)
                    self.assertEqual(actual.tobytes(), expected.tobytes())
                self.assertEqual(source.read_bytes(), original)

                record = json.loads((output / "manifest.json").read_text())["images"][0]["palette"]
                self.assertEqual(record["source_unique_rgb"], 9)
                self.assertEqual(record["output_unique_rgb"], 8)
                usage = [4, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 2, 0, 0, 2, 2]
                self.assertEqual(record["palette_usage"], usage)
                self.assertAlmostEqual(record["mean_rgb_distance"],
                                       (6 * math.sqrt(3) + math.sqrt(38) + math.sqrt(17)
                                        + math.sqrt(768)) / 9)
                self.assertAlmostEqual(record["p95_rgb_distance"], math.sqrt(768))
                self.assertAlmostEqual(record["max_rgb_distance"], math.sqrt(768))

    def test_invalid_palette_fails_before_writing_output(self):
        source = self.root / "source.png"
        Image.new("RGB", (6, 3), (240, 80, 20)).save(source)
        original = source.read_bytes()
        lines = self.palette_lines()
        cases = {
            "too-few": lines[:-1],
            "too-many": lines + ["12 34 56"],
            "duplicate": lines[:-1] + [lines[0]],
            "out-of-range": ["100 00 00"] + lines[1:],
            "invalid-hex": ["GG 00 00"] + lines[1:],
            "too-few-columns": ["00 00"] + lines[1:],
            "too-many-columns": ["00 00 00 00 00"] + lines[1:],
            "invalid-fourth-column": ["00 00 00 GG"] + lines[1:],
        }
        for name, entries in cases.items():
            with self.subTest(case=name):
                palette = self.root / f"{name}.vpl"
                palette.write_text("\n".join(entries) + "\n")
                output = self.root / f"out-{name}"

                result = self.run_extractor(source, output, palette)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("palette", (result.stdout + result.stderr).lower())
                self.assertFalse(output.exists())
                self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
